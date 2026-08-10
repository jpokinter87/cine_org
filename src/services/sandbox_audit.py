"""
Audit des fichiers présents dans le sandbox.

Détermine, pour chaque fichier isolé, s'il existe bien un remplaçant légitime
dans la vidéothèque (fiche en base dont le fichier est physiquement présent).
Sans cette vérification, une purge pourrait effacer la seule copie d'un média.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger

from src.utils.constants import VIDEO_EXTENSIONS
from src.utils.helpers import normalize_accents

# Statuts d'audit
REPLACED = "replaced"  # remplaçant confirmé dans la vidéothèque → purge sûre
MISSING = "missing"  # aucun remplaçant → le sandbox détient la seule copie
UNKNOWN = "unknown"  # impossible de trancher (nommage hors schéma, non-vidéo)


@dataclass(frozen=True)
class SandboxAudit:
    """Résultat de l'audit d'un fichier sandboxé.

    Attributs:
        status: REPLACED, MISSING ou UNKNOWN
        replacement_path: Chemin du fichier vivant qui remplace celui-ci
        shares_inode: True si le fichier partage son inode (hardlink) — le
            supprimer ne libère alors aucun espace disque
        reclaimable_bytes: Espace réellement récupérable par la suppression
    """

    status: str
    replacement_path: Optional[Path] = None
    shares_inode: bool = False
    reclaimable_bytes: int = 0


def _normalize_title(title: str) -> str:
    """Normalise un titre pour la comparaison (accents, année, ponctuation)."""
    text = normalize_accents(title or "")
    text = re.sub(r"\(\d{4}\)", "", text)
    return re.sub(r"[^a-z0-9]+", "", text.lower())


class SandboxAuditor:
    """Confronte les fichiers du sandbox au contenu réel de la vidéothèque.

    L'index est construit une seule fois par instance : auditer 700 fichiers
    ne doit pas déclencher 700 requêtes.

    Args:
        session: Session SQLModel ouverte sur la base
        sandbox_dir: Racine du sandbox (sert à exclure les fiches qui
            pointeraient elles-mêmes vers le sandbox)
    """

    def __init__(self, session, sandbox_dir: Path) -> None:
        self._session = session
        self._sandbox_dir = Path(sandbox_dir)
        self._episodes: Optional[dict] = None
        self._movies: Optional[dict] = None

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------

    def prime(self) -> "SandboxAuditor":
        """Construit l'index tout de suite.

        Permet à l'appelant de refermer sa session juste après : les audits
        suivants n'interrogent plus la base.
        """
        if self._episodes is None or self._movies is None:
            self._build_index()
        return self

    def _build_index(self) -> None:
        """Construit les index séries/films depuis la base."""
        from sqlmodel import select

        from src.infrastructure.persistence.models import (
            EpisodeModel,
            MovieModel,
            SeriesModel,
        )

        episodes: dict[str, list[tuple[int, int, int, str]]] = {}
        titles = {s.id: s.title for s in self._session.exec(select(SeriesModel)).all()}
        for ep in self._session.exec(select(EpisodeModel)).all():
            if not ep.file_path:
                continue
            title = titles.get(ep.series_id)
            if not title:
                continue
            end = ep.episode_end or ep.episode_number
            episodes.setdefault(_normalize_title(title), []).append(
                (ep.season_number, ep.episode_number, end, ep.file_path)
            )

        movies: dict[str, list[tuple[Optional[int], str]]] = {}
        for movie in self._session.exec(select(MovieModel)).all():
            if not movie.file_path:
                continue
            movies.setdefault(_normalize_title(movie.title), []).append(
                (movie.year, movie.file_path)
            )

        self._episodes = episodes
        self._movies = movies

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def audit(self, path: Path) -> SandboxAudit:
        """Audite un fichier du sandbox.

        Args:
            path: Chemin du fichier sandboxé

        Returns:
            SandboxAudit décrivant si le fichier peut être purgé sans perte
        """
        if self._episodes is None or self._movies is None:
            self._build_index()

        shares, reclaimable = self._disk_facts(path)

        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            return SandboxAudit(UNKNOWN, None, shares, 0)

        replacement = self._find_replacement(path)
        if replacement is None:
            identified = self._identify(path) is not None
            status = MISSING if identified else UNKNOWN
            return SandboxAudit(status, None, shares, reclaimable)

        return SandboxAudit(REPLACED, replacement, shares, reclaimable)

    def _disk_facts(self, path: Path) -> tuple[bool, int]:
        """Retourne (partage d'inode, octets réellement récupérables)."""
        try:
            st = path.lstat()
        except OSError:
            return False, 0
        shares = st.st_nlink > 1
        return shares, 0 if shares else st.st_size

    # ------------------------------------------------------------------
    # Identification et recherche du remplaçant
    # ------------------------------------------------------------------

    def _identify(self, path: Path) -> Optional[tuple]:
        """Extrait ('series', titre, saison, ep_debut, ep_fin) ou ('movie', titre, année)."""
        from guessit import guessit

        info = guessit(path.name)
        season = info.get("season")
        episode = info.get("episode")

        if isinstance(season, int) and episode is not None:
            numbers = episode if isinstance(episode, list) else [episode]
            numbers = [n for n in numbers if isinstance(n, int)]
            if numbers:
                title = self._series_title(path) or str(info.get("title") or "")
                if title:
                    return ("series", title, season, min(numbers), max(numbers))

        # Films : exiger l'année. Le sandbox reçoit des fichiers issus du
        # storage, donc nommés « Titre (Année) … » ; sans année, le fichier
        # n'est pas au format canonique et ne doit pas être déclaré « seule
        # copie d'un média » — il relève de l'examen manuel.
        title = info.get("title")
        year = info.get("year")
        if title and info.get("type") == "movie" and isinstance(year, int):
            return ("movie", str(title), year)

        return None

    def _series_title(self, path: Path) -> str:
        """Déduit le titre de la série depuis l'arborescence du sandbox.

        Le sandbox reproduit l'arborescence du storage : le dossier précédant
        « Saison XX » porte le titre de la série, plus fiable que le seul nom
        de fichier (releases abrégées, titres tronqués).
        """
        try:
            parts = path.relative_to(self._sandbox_dir).parts
        except ValueError:
            return ""
        for i, segment in enumerate(parts):
            if i and segment.lower().startswith(("saison", "season")):
                return parts[i - 1]
        return parts[-2] if len(parts) >= 2 else ""

    def _find_replacement(self, path: Path) -> Optional[Path]:
        """Cherche un fichier vivant qui remplace le fichier sandboxé."""
        identified = self._identify(path)
        if identified is None:
            return None

        if identified[0] == "series":
            _, title, season, first, last = identified
            candidates = (self._episodes or {}).get(_normalize_title(title), [])
            for ep_season, ep_first, ep_last, file_path in candidates:
                if ep_season != season:
                    continue
                if ep_first <= first and ep_last >= last:
                    resolved = self._living_file(file_path)
                    if resolved is not None:
                        return resolved
            return None

        _, title, year = identified
        candidates = (self._movies or {}).get(_normalize_title(title), [])
        for movie_year, file_path in candidates:
            if year is not None and movie_year is not None and movie_year != year:
                continue
            resolved = self._living_file(file_path)
            if resolved is not None:
                return resolved
        return None

    def _living_file(self, file_path: str) -> Optional[Path]:
        """Retourne le chemin s'il désigne un fichier vivant hors sandbox."""
        candidate = Path(file_path)
        try:
            candidate.relative_to(self._sandbox_dir)
            return None  # la fiche pointe dans le sandbox : pas un remplaçant
        except ValueError:
            pass
        if not candidate.exists():
            logger.debug("Remplaçant déclaré mais absent du disque : {}", candidate)
            return None
        return candidate
