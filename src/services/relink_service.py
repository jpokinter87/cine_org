"""
Service de ré-association des fiches films sans fichier (file_path NULL).

Certaines fiches en base n'ont pas de file_path/symlink_path renseigné alors
que le fichier existe sur le disque (import d'une vidéothèque, matching
incomplet…). Ce service retrouve le fichier et renseigne la base :

- Tier 1 : un symlink formaté existe déjà dans video/ → réutilisé tel quel.
- Tier 2 : fichier brut trouvé dans storage/ → un symlink au nom canonique est
  créé à la destination calculée par l'OrganizerService.

Le fichier physique dans storage/ n'est pas renommé (cf. CanonicalRenamerService
pour cela) : seul le symlink video/ porte le nom canonique.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger
from sqlmodel import Session

from src.core.entities.media import Movie
from src.infrastructure.persistence.models import MovieModel
from src.services.matcher import calculate_movie_score
from src.services.organizer import get_movie_video_destination
from src.services.renamer import generate_movie_filename


@dataclass
class FoundFile:
    """Résultat d'une recherche de fichier pour une fiche."""

    storage_path: Path
    existing_symlink: Optional[Path] = None
    media_info: Optional[object] = None  # MediaInfo extrait (tier 2), réutilisable


@dataclass
class ScoredCandidate:
    """Candidat storage scoré (titre/année/durée) pour les suggestions."""

    storage_path: Path
    score: float
    media_info: Optional[object] = None


def _normalize(s: str) -> str:
    """Retire ponctuation/accents légers pour comparaison de titres."""
    return "".join(c.lower() for c in s if c.isalnum() or c == " ").strip()


class TmdbAltTitleProvider:
    """Fournit les titres alternatifs (AKA + titre en-US) d'un film via TMDB.

    Les AKA sont préchargés en un seul event loop (prefetch) pour éviter de
    créer/fermer un client httpx par appel. Le provider lui-même est synchrone
    (lookup dict), donc utilisable dans le finder sync.
    """

    def __init__(self, tmdb_client) -> None:
        self._tmdb = tmdb_client
        self._cache: dict[int, list[str]] = {}

    def prefetch(self, tmdb_ids: list[int]) -> None:
        """Précharge les AKA pour une liste d'ID TMDB (best-effort)."""
        todo = [tid for tid in tmdb_ids if tid and tid not in self._cache]
        if not todo:
            return
        try:
            asyncio.run(self._prefetch_async(todo))
        except Exception as e:  # pragma: no cover - réseau/API
            logger.debug(f"Préchargement AKA TMDB échoué : {e}")

    async def _prefetch_async(self, tmdb_ids: list[int]) -> None:
        results = await asyncio.gather(
            *(self._fetch_one(tid) for tid in tmdb_ids), return_exceptions=True
        )
        for tid, res in zip(tmdb_ids, results):
            self._cache[tid] = res if isinstance(res, list) else []

    async def _fetch_one(self, tmdb_id: int) -> list[str]:
        client = self._tmdb._get_client()
        titles: list[str] = []
        try:
            resp = await client.get(f"/movie/{tmdb_id}/alternative_titles")
            if resp.status_code == 200:
                for t in resp.json().get("titles", []):
                    if t.get("title"):
                        titles.append(t["title"])
        except Exception:  # pragma: no cover - best-effort
            pass
        try:
            resp = await client.get(f"/movie/{tmdb_id}", params={"language": "en-US"})
            if resp.status_code == 200 and resp.json().get("title"):
                titles.append(resp.json()["title"])
        except Exception:  # pragma: no cover - best-effort
            pass
        # Dédupliquer en préservant l'ordre
        seen: set[str] = set()
        out: list[str] = []
        for t in titles:
            k = t.lower()
            if k not in seen:
                seen.add(k)
                out.append(t)
        return out

    def __call__(self, movie: Movie) -> list[str]:
        if not movie.tmdb_id:
            return []
        return self._cache.get(int(movie.tmdb_id), [])


def _title_before_year(filename: str, year: Optional[int]) -> Optional[str]:
    """Extrait le titre situé avant « (année) » dans un nom canonique.

    « Dragons 3 - Le monde caché (2019) MULTi x265 1080p.mkv » → « Dragons 3 -
    Le monde caché ». Retourne None si « (année) » est absent.
    """
    if not year:
        return None
    marker = f"({year})"
    idx = filename.find(marker)
    if idx <= 0:
        return None
    title = filename[:idx].strip()
    return title or None


class MovieFileFinder:
    """Recherche le fichier d'une fiche : tier 1 video_dir, tier 2 storage.

    Tier 2 réutilise le scoring canonique du workflow `process`
    (titre 50 % + année 25 % + durée 25 %) et n'accepte qu'au-dessus du seuil
    d'auto-validation. La durée écarte featurettes et mauvais films de même année.
    """

    def __init__(
        self,
        video_dir: Path,
        repair_service,
        parser,
        media_info_extractor,
        min_score: float = 85.0,
        top_k: int = 5,
        alt_title_provider=None,
    ) -> None:
        self._video_dir = Path(video_dir)
        self._repair = repair_service
        self._parser = parser
        self._extractor = media_info_extractor
        self._min_score = min_score
        self._top_k = top_k
        self._alt_title_provider = alt_title_provider

    def find(self, movie: Movie) -> Optional[FoundFile]:
        # Tier 1 : symlink formaté déjà présent dans video_dir (cible valide)
        link = self._find_in_video_dir(movie)
        if link is not None:
            target = link.resolve()
            if target.exists():
                return FoundFile(storage_path=target, existing_symlink=link)

        # Tier 2 : recherche floue dans storage + scoring canonique
        result = self._find_in_storage(movie)
        if result is not None:
            storage, media_info = result
            return FoundFile(
                storage_path=storage, existing_symlink=None, media_info=media_info
            )

        return None

    def _find_in_video_dir(self, movie: Movie) -> Optional[Path]:
        """Glob video/Films par titre + année (nom de symlink normalisé)."""
        if not movie.year:
            return None
        films_dir = self._video_dir / "Films"
        root = films_dir if films_dir.exists() else self._video_dir
        if not root.exists():
            return None

        wanted = {_normalize(movie.title)}
        if movie.original_title:
            wanted.add(_normalize(movie.original_title))
        year_str = f"({movie.year})"

        for f in root.rglob(f"*{year_str}*"):
            if not f.is_file():  # ignore les symlinks cassés (cible absente)
                continue
            idx = f.name.find(year_str)
            if idx <= 0:
                continue
            file_title = f.name[:idx].strip()
            if _normalize(file_title) in wanted:
                return f
        return None

    def suggest(self, movie: Movie, floor: float = 60.0) -> list[ScoredCandidate]:
        """Candidats de la bande litigieuse (floor ≤ score < seuil), triés."""
        return [
            c
            for c in self._scored_candidates(movie)
            if floor <= c.score < self._min_score
        ]

    def search_manual(
        self, title: str, year: Optional[int] = None, limit: int = 10
    ) -> list[ScoredCandidate]:
        """Recherche storage par titre libre, sans garde-fou année/durée.

        Pour la validation manuelle : classe par similarité de titre (score brut
        du RepairService) et renvoie tous les candidats, à valider à l'œil/mpv.
        """
        suffix = f" ({year})" if year else ""
        synthetic = self._video_dir / "Films" / f"{title}{suffix}.mkv"
        candidates = self._repair.find_possible_targets(synthetic, min_score=0.0)

        results: list[ScoredCandidate] = []
        for path, raw in candidates[:limit]:
            p = Path(path)
            media_info = None
            try:
                media_info = self._extractor.extract(p)
            except Exception:  # pragma: no cover - best-effort
                media_info = None
            results.append(
                ScoredCandidate(storage_path=p, score=raw, media_info=media_info)
            )
        return results

    def _find_in_storage(self, movie: Movie):
        """Meilleur candidat storage au-dessus du seuil.

        Returns un tuple (Path, MediaInfo) si un candidat dépasse le seuil,
        sinon None.
        """
        scored = self._scored_candidates(movie)
        if scored and scored[0].score >= self._min_score:
            best = scored[0]
            return best.storage_path, best.media_info
        return None

    def _candidate_titles(self, movie: Movie) -> list[str]:
        """Titres de recherche/scoring : localisé + original + AKA (TMDB)."""
        titles: list[str] = [movie.title]
        if movie.original_title and movie.original_title != movie.title:
            titles.append(movie.original_title)
        if self._alt_title_provider is not None:
            try:
                for alt in self._alt_title_provider(movie):
                    if alt and alt not in titles:
                        titles.append(alt)
            except Exception:  # pragma: no cover - best-effort (réseau/API)
                pass
        return titles

    def _scored_candidates(
        self, movie: Movie, search_titles: Optional[list[str]] = None
    ) -> list[ScoredCandidate]:
        """Score les candidats storage par titre/année/durée (tri décroissant).

        Cherche storage pour chaque variante de titre (localisé + original +
        AKA) et score chaque candidat contre l'ensemble de ces titres.
        """
        if not movie.year:
            return []

        titles = (
            search_titles
            if search_titles is not None
            else self._candidate_titles(movie)
        )

        # Recherche storage pour chaque variante de titre, fusion par chemin
        merged: dict[str, tuple[Path, float]] = {}
        for title in titles:
            synthetic = self._video_dir / "Films" / f"{title} ({movie.year}).mkv"
            for path, raw in self._repair.find_possible_targets(
                synthetic, min_score=0.0, alternative_names=titles
            ):
                key = str(path)
                if key not in merged or raw > merged[key][1]:
                    merged[key] = (Path(path), raw)

        # Garder les meilleurs candidats bruts avant le scoring fin (coûteux)
        ranked = sorted(merged.values(), key=lambda pr: pr[1], reverse=True)

        scored: list[ScoredCandidate] = []
        for p, _raw_score in ranked[: self._top_k]:
            parsed = self._parser.parse(p.name)
            media_info = None
            try:
                media_info = self._extractor.extract(p)
            except Exception:  # pragma: no cover - extraction best-effort
                media_info = None
            file_duration = media_info.duration_seconds if media_info else None

            # Titres requête : guessit + titre canonique avant « (année) ».
            # guessit tronque au séparateur « - » (« Dragons 3 - Le monde caché »
            # → « Dragons 3 ») ; le titre avant « (année) » récupère le complet.
            query_titles = {parsed.title or ""}
            for year in (movie.year, parsed.year):
                canonical = _title_before_year(p.name, year)
                if canonical:
                    query_titles.add(canonical)

            # Meilleur score sur le produit (titres requête) × (titres candidats)
            score = max(
                calculate_movie_score(
                    query_title=qt,
                    query_year=parsed.year,
                    query_duration=file_duration,
                    candidate_title=ct,
                    candidate_year=movie.year,
                    candidate_duration=movie.duration_seconds,
                )
                for qt in query_titles
                for ct in titles
            )
            scored.append(
                ScoredCandidate(storage_path=p, score=score, media_info=media_info)
            )

        scored.sort(key=lambda c: c.score, reverse=True)
        return scored


@dataclass
class RelinkOutcome:
    """Résultat d'une tentative de ré-association."""

    movie_id: int
    status: str  # "linked_existing" | "linked_created" | "unresolved" | "already_linked" | "error"
    storage_path: Optional[Path] = None
    symlink_path: Optional[Path] = None
    reason: Optional[str] = None


def _to_entity(model: MovieModel) -> Movie:
    """Construit un Movie entity (avec genres) pour renamer + organizer."""
    import json

    genres = tuple(json.loads(model.genres_json)) if model.genres_json else ()
    return Movie(
        id=str(model.id) if model.id is not None else None,
        tmdb_id=model.tmdb_id,
        title=model.title,
        original_title=model.original_title,
        year=model.year,
        genres=genres,
        duration_seconds=model.duration_seconds,
    )


class MovieRelinkService:
    """Retrouve et renseigne file_path/symlink_path pour les fiches sans fichier."""

    def __init__(
        self,
        session: Session,
        media_info_extractor,
        finder,
        video_dir: Path,
    ) -> None:
        self._session = session
        self._extractor = media_info_extractor
        self._finder = finder
        self._video_dir = Path(video_dir)

    def relink_unlinked(self, dry_run: bool = True) -> list[RelinkOutcome]:
        """Ré-associe toutes les fiches films sans file_path."""
        from sqlmodel import select

        ids = self._session.exec(
            select(MovieModel.id).where(MovieModel.file_path.is_(None))
        ).all()
        return [self.relink_movie(mid, dry_run=dry_run) for mid in ids]

    def relink_movie(self, movie_id: int, dry_run: bool = True) -> RelinkOutcome:
        """Tente de ré-associer une fiche. Dry-run par défaut."""
        movie = self._session.get(MovieModel, movie_id)
        if movie is None:
            return RelinkOutcome(movie_id, status="error", reason="movie_not_found")

        if movie.file_path:
            return RelinkOutcome(movie_id, status="already_linked")

        entity = _to_entity(movie)
        found = self._finder.find(entity)
        if found is None:
            return RelinkOutcome(movie_id, status="unresolved")

        storage = Path(found.storage_path)

        # Tier 1 : un symlink formaté existe déjà → le réutiliser tel quel
        if found.existing_symlink is not None:
            symlink = Path(found.existing_symlink)
            if not dry_run:
                movie.file_path = str(storage)
                movie.symlink_path = str(symlink)
                self._session.add(movie)
                self._session.commit()
            return RelinkOutcome(
                movie_id,
                status="linked_existing",
                storage_path=storage,
                symlink_path=symlink,
            )

        # Tier 2 : créer un symlink canonique vers le fichier storage brut.
        return self._apply_created(movie, storage, found.media_info, dry_run)

    def collect_suggestions(
        self, movie_id: int, floor: float = 60.0
    ) -> list[ScoredCandidate]:
        """Candidats litigieux (bande floor-seuil) pour une fiche non liée."""
        movie = self._session.get(MovieModel, movie_id)
        if movie is None or movie.file_path:
            return []
        return self._finder.suggest(_to_entity(movie), floor=floor)

    def manual_search(
        self, movie_id: int, title: str, limit: int = 10
    ) -> list[ScoredCandidate]:
        """Recherche storage par titre libre (gardes-fous relâchés) pour une fiche."""
        movie = self._session.get(MovieModel, movie_id)
        year = movie.year if movie else None
        return self._finder.search_manual(title, year=year, limit=limit)

    def link_chosen(
        self,
        movie_id: int,
        storage_path: Path,
        media_info=None,
        dry_run: bool = False,
    ) -> RelinkOutcome:
        """Lie une fiche au fichier explicitement choisi par l'utilisateur."""
        movie = self._session.get(MovieModel, movie_id)
        if movie is None:
            return RelinkOutcome(movie_id, status="error", reason="movie_not_found")
        return self._apply_created(movie, Path(storage_path), media_info, dry_run)

    def _apply_created(
        self, movie: MovieModel, storage: Path, media_info, dry_run: bool
    ) -> RelinkOutcome:
        """Crée le symlink canonique vers `storage` et met à jour la fiche."""
        movie_id = movie.id
        entity = _to_entity(movie)

        # Réutiliser le MediaInfo déjà extrait si disponible, sinon l'extraire
        if media_info is None:
            try:
                media_info = self._extractor.extract(storage)
            except Exception as e:  # pragma: no cover - fallback silencieux
                logger.debug(f"MediaInfo échoue pour {storage} : {e}")

        canonical_name = generate_movie_filename(entity, media_info, storage.suffix)
        dest_dir = get_movie_video_destination(entity, self._video_dir)
        symlink = dest_dir / canonical_name

        if dry_run:
            return RelinkOutcome(
                movie_id,
                status="linked_created",
                storage_path=storage,
                symlink_path=symlink,
            )

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            if symlink.is_symlink() or symlink.exists():
                symlink.unlink()
            symlink.symlink_to(storage)
            movie.file_path = str(storage)
            movie.symlink_path = str(symlink)
            self._session.add(movie)
            self._session.commit()
        except Exception as e:
            logger.error(f"Ré-association échouée pour movie {movie_id} : {e}")
            return RelinkOutcome(
                movie_id, status="error", storage_path=storage, reason=str(e)
            )

        return RelinkOutcome(
            movie_id,
            status="linked_created",
            storage_path=storage,
            symlink_path=symlink,
        )
