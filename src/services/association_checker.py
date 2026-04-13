"""
Service de détection automatique d'associations TMDB potentiellement erronées.

Analyse les films et séries en comparant les métadonnées TMDB (titre, année,
durée) avec les informations extraites des noms de fichiers via guessit.
Chaque entité reçoit un score de confiance (0-100). Score < 60 = suspect.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger
from sqlmodel import Session, select

from src.adapters.parsing.guessit_parser import GuessitFilenameParser
from src.infrastructure.persistence.models import (
    ConfirmedAssociationModel,
    EpisodeModel,
    MovieModel,
    SeriesModel,
)
from src.services.matcher import _calculate_title_score


@dataclass
class SuspiciousAssociation:
    """Résultat de détection d'une association suspecte."""

    entity_type: str  # "movie" | "series"
    entity_id: int
    title_tmdb: str
    title_parsed: str | None
    year_tmdb: int | None
    year_parsed: int | None
    confidence_score: int  # 0 = très suspect, 100 = OK
    reasons: list[str] = field(default_factory=list)
    poster_path: str | None = None


# Seuil en dessous duquel une association est considérée suspecte
SUSPECT_THRESHOLD = 60

# Callback de progression : (current, total, label)
ProgressCallback = Callable[[int, int, str], None]

_parser = GuessitFilenameParser()

# Pattern scene-release : nom court tout lowercase avec tirets
# Ex: hidef-btbl, nemo-madso, fhd-dmw, air-laod, mgl-mb1080p
_SCENE_RELEASE_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)+$")

# Mono-token lowercase : brian, morse, moonacre, loveactually1080p
# (guessit tronque parfois les releases type "fhd-brian" au 2e token)
_LOWERCASE_SINGLE_RE = re.compile(r"^[a-z][a-z0-9]{3,}$")

# Dossiers de structure du storage (à ne pas utiliser comme fallback titre) :
# lettres seules (A, B), subdivisions alpha (A-D, F-G, Ma-Mi, Mab-Man, Da-De),
# Saison XX, ou dossiers racine (Films, Series). Case-insensitive.
_STRUCTURE_DIR_RE = re.compile(
    r"^[a-z]$|^[a-z]{1,4}-[a-z]{1,4}$|"
    r"^(saison|season|s)\s*\d+$|"
    r"^(films?|séries?|series?)(\s+tv)?$",
    re.IGNORECASE,
)

# Mots-clés indiquant une version étendue/longue d'un film.
# Déclenche des seuils de tolérance durée plus larges.
# Les abréviations DC/EC/UC/TC sont case-sensitive pour éviter les faux
# positifs (ex: "dc" dans un titre lowercase).
_EXTENDED_CUT_RE = re.compile(
    r"\b(extended|director'?s?[\s._-]?cut|ultimate|uncut|unrated|"
    r"remastered|theatrical|final[\s._-]?cut|special[\s._-]?edition|"
    r"longue[\s._-]?version|version[\s._-]?longue)\b",
    re.IGNORECASE,
)
_EXTENDED_ABBREV_RE = re.compile(r"\b(DC|EC|UC|TC)\b")


def _is_extended_cut(filename: str) -> bool:
    """Détecte les marqueurs de version étendue (mots-clés ou abréviations)."""
    return bool(_EXTENDED_CUT_RE.search(filename)) or bool(
        _EXTENDED_ABBREV_RE.search(filename)
    )


# Suffixes de format 3D mal nettoyés par guessit (surtout quand le titre est
# en majuscules). Ex: "LE MONDE DE NEMO 3D Side By Side PublicHD Mixed" →
# garder uniquement "LE MONDE DE NEMO".
_3D_SUFFIX_RE = re.compile(r"\s+3D\b.*$", re.IGNORECASE)


def _strip_3d_suffix(title: str | None) -> str | None:
    """Retire le suffixe 3D et ses descripteurs (Side By Side, Top-Bottom, etc.)."""
    if not title:
        return title
    return _3D_SUFFIX_RE.sub("", title).strip() or title


def _is_suspicious_title(title: str | None) -> bool:
    """Détecte un titre extrait probablement inexploitable (scene-release,
    trop court, lowercase mono-token). Déclenche le fallback dossier parent."""
    if not title:
        return True
    stripped = title.strip()
    if len(stripped) < 6:
        return True
    # Scene-release : tout lowercase avec tirets (accepte chiffres)
    if _SCENE_RELEASE_RE.match(stripped.replace(" ", "")):
        return True
    # Mono-token lowercase (brian, morse, moonacre, loveactually1080p)
    if _LOWERCASE_SINGLE_RE.match(stripped):
        return True
    return False


def _best_title_score(
    title_parsed: str, title: str, original_title: str | None
) -> float:
    """Retourne le meilleur score entre titre local et titre original."""
    score = _calculate_title_score(title_parsed, title)
    if original_title and original_title != title:
        score = max(score, _calculate_title_score(title_parsed, original_title))
    return score


class AssociationChecker:
    """Détecte les associations TMDB potentiellement erronées."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def scan_suspicious(
        self,
        on_progress: ProgressCallback | None = None,
        limit: int | None = None,
    ) -> list[SuspiciousAssociation]:
        """Scanne films et séries et retourne les associations suspectes."""
        results: list[SuspiciousAssociation] = []

        # Charger les associations déjà confirmées
        confirmed = self._session.exec(
            select(ConfirmedAssociationModel)
        ).all()
        confirmed_set = {
            (c.entity_type, c.entity_id) for c in confirmed
        }

        # --- Comptage préalable ---
        movie_query = select(MovieModel).where(
            MovieModel.tmdb_id.is_not(None),  # type: ignore[union-attr]
            MovieModel.file_path.is_not(None),  # type: ignore[union-attr]
        )
        series_query = select(SeriesModel).where(
            SeriesModel.tmdb_id.is_not(None),  # type: ignore[union-attr]
        )
        if limit is not None:
            movie_query = movie_query.limit(limit)
            series_query = series_query.limit(limit)

        movies = self._session.exec(movie_query).all()
        all_series = self._session.exec(series_query).all()

        total = len(movies) + len(all_series)

        # --- Films ---
        logger.info(f"Scan de {len(movies)} films pour associations suspectes")
        for i, movie in enumerate(movies):
            if on_progress and i % 50 == 0:
                on_progress(i, total, f"Analyse film {i + 1}/{len(movies)}")
            if ("movie", movie.id) in confirmed_set:
                continue
            result = self._check_movie(movie)
            if result is not None and result.confidence_score < SUSPECT_THRESHOLD:
                results.append(result)

        # --- Séries ---
        logger.info(f"Scan de {len(all_series)} séries pour associations suspectes")
        offset = len(movies)
        for i, series in enumerate(all_series):
            if on_progress and i % 20 == 0:
                on_progress(
                    offset + i, total, f"Analyse série {i + 1}/{len(all_series)}"
                )
            if ("series", series.id) in confirmed_set:
                continue
            result = self._check_series(series)
            if result is not None and result.confidence_score < SUSPECT_THRESHOLD:
                results.append(result)

        # Signal de fin
        if on_progress:
            on_progress(total, total, "Analyse terminée")

        # Trier par score croissant (les plus suspects en premier)
        results.sort(key=lambda r: r.confidence_score)
        logger.info(f"{len(results)} associations suspectes détectées")
        return results

    # ------------------------------------------------------------------
    # Heuristiques Films
    # ------------------------------------------------------------------

    def _check_movie(self, movie: MovieModel) -> SuspiciousAssociation | None:
        """Évalue la confiance d'une association film."""
        if not movie.file_path:
            return None

        title_parsed, year_parsed = self._parse_filename(movie.file_path)
        if title_parsed is None:
            return None

        score = 100
        reasons: list[str] = []

        # Pré-calcul année et durée pour l'heuristique titre
        year_match_solid = (
            year_parsed is not None
            and movie.year is not None
            and abs(year_parsed - movie.year) <= 1
        )
        file_duration = self._get_file_duration(movie.file_path)
        duration_match_solid = (
            file_duration is not None
            and movie.duration_seconds is not None
            and movie.duration_seconds > 0
            and abs(file_duration - movie.duration_seconds) / movie.duration_seconds
            <= 0.15
        )

        # Heuristique 1 : Titre (compare avec titre FR et titre original).
        # Suppression de la pénalité si année ET durée concordent : signal
        # "traduction FR libre" plutôt que "mauvais match" (ex: The 400 Blows
        # → Les Quatre Cents Coups, Star Wars → La Guerre des étoiles).
        title_sim = _best_title_score(title_parsed, movie.title, movie.original_title)
        title_override = year_match_solid and duration_match_solid
        if not title_override:
            if title_sim < 60:
                score -= 45
                reasons.append(
                    f"Titre très différent : « {title_parsed} » vs « {movie.title} » "
                    f"(similarité {title_sim:.0f}%)"
                )
            elif title_sim < 75:
                score -= 15
                reasons.append(
                    f"Titre peu similaire : « {title_parsed} » vs « {movie.title} » "
                    f"(similarité {title_sim:.0f}%)"
                )

        # Heuristique 2 : Année
        if year_parsed is not None and movie.year is not None:
            year_diff = abs(year_parsed - movie.year)
            if year_diff >= 3:
                score -= 25
                reasons.append(
                    f"Écart d'année significatif : {year_parsed} (fichier) "
                    f"vs {movie.year} (TMDB) — {year_diff} ans"
                )
            elif year_diff == 2:
                score -= 10
                reasons.append(
                    f"Écart d'année : {year_parsed} (fichier) "
                    f"vs {movie.year} (TMDB) — 2 ans"
                )

        # Heuristique 3 : Durée (en pourcentage, cohérent avec le matcher).
        # Assouplie si version étendue détectée (Extended, Director's Cut, etc.).
        if file_duration and movie.duration_seconds and movie.duration_seconds > 0:
            diff_pct = abs(file_duration - movie.duration_seconds) / movie.duration_seconds * 100
            file_min = file_duration // 60
            tmdb_min = movie.duration_seconds // 60
            is_extended = _is_extended_cut(Path(movie.file_path).name)
            # Seuils relâchés pour versions étendues (jusqu'à +60% est normal)
            threshold_high = 70 if is_extended else 30
            threshold_low = 40 if is_extended else 15
            if diff_pct >= threshold_high:
                score -= 45
                reasons.append(
                    f"Écart de durée important : {file_min}min (fichier) "
                    f"vs {tmdb_min}min (TMDB) — {diff_pct:.0f}% d'écart"
                )
            elif diff_pct >= threshold_low:
                score -= 15
                reasons.append(
                    f"Écart de durée : {file_min}min (fichier) "
                    f"vs {tmdb_min}min (TMDB) — {diff_pct:.0f}% d'écart"
                )

        score = max(0, score)

        if not reasons:
            return None

        return SuspiciousAssociation(
            entity_type="movie",
            entity_id=movie.id,  # type: ignore[arg-type]
            title_tmdb=movie.title,
            title_parsed=title_parsed,
            year_tmdb=movie.year,
            year_parsed=year_parsed,
            confidence_score=score,
            reasons=reasons,
            poster_path=movie.poster_path,
        )

    # ------------------------------------------------------------------
    # Heuristiques Séries
    # ------------------------------------------------------------------

    def _check_series(self, series: SeriesModel) -> SuspiciousAssociation | None:
        """Évalue la confiance d'une association série."""
        episode = self._get_first_episode(series)
        if episode is None or not episode.file_path:
            return None

        title_parsed, year_parsed = self._parse_filename(episode.file_path)

        # Extraire aussi le titre depuis le répertoire parent (au-dessus de Saison X)
        dir_title = self._extract_series_dir_title(episode.file_path)

        # Garder le meilleur candidat entre fichier et dossier
        if title_parsed is None and dir_title is None:
            return None

        score = 100
        reasons: list[str] = []

        # Heuristique : Titre — meilleur score entre fichier et dossier parent
        best_sim = 0.0
        best_parsed = title_parsed or dir_title
        for candidate in [title_parsed, dir_title]:
            if candidate is None:
                continue
            sim = _best_title_score(candidate, series.title, series.original_title)
            if sim > best_sim:
                best_sim = sim
                best_parsed = candidate
        title_parsed = best_parsed
        title_sim = best_sim
        if title_sim < 60:
            score -= 45
            reasons.append(
                f"Titre très différent : « {title_parsed} » vs « {series.title} » "
                f"(similarité {title_sim:.0f}%)"
            )
        elif title_sim < 75:
            score -= 15
            reasons.append(
                f"Titre peu similaire : « {title_parsed} » vs « {series.title} » "
                f"(similarité {title_sim:.0f}%)"
            )

        # Heuristique : Année (si disponible)
        if year_parsed is not None and series.year is not None:
            year_diff = abs(year_parsed - series.year)
            if year_diff >= 3:
                score -= 25
                reasons.append(
                    f"Écart d'année significatif : {year_parsed} (fichier) "
                    f"vs {series.year} (TMDB) — {year_diff} ans"
                )

        score = max(0, score)

        if not reasons:
            return None

        return SuspiciousAssociation(
            entity_type="series",
            entity_id=series.id,  # type: ignore[arg-type]
            title_tmdb=series.title,
            title_parsed=title_parsed,
            year_tmdb=series.year,
            year_parsed=year_parsed,
            confidence_score=score,
            reasons=reasons,
            poster_path=series.poster_path,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_series_dir_title(file_path: str) -> str | None:
        """Extrait le titre de série depuis la hiérarchie des répertoires.

        Remonte depuis le fichier en sautant les dossiers « Saison X ».
        Ex: /storage/Séries/A/Au coeur du temps/Saison 1/ep.mkv → "Au coeur du temps"
        """
        import re

        path = Path(file_path)
        for parent in path.parents:
            name = parent.name
            if not name:
                break
            # Sauter les dossiers « Saison XX » / « Season XX »
            if re.match(r"(?i)^saison\s+\d+|^season\s+\d+|^s\d+$", name):
                continue
            # Sauter les lettres seules (subdivision alphabétique A, B, etc.)
            if len(name) <= 2:
                continue
            # Sauter les dossiers racines connus
            if name.lower() in {"séries", "series", "séries tv", "series tv"}:
                break
            return name
        return None

    def _get_first_episode(self, series: SeriesModel) -> EpisodeModel | None:
        """Récupère le premier épisode d'une série ayant un file_path."""
        return self._session.exec(
            select(EpisodeModel)
            .where(
                EpisodeModel.series_id == series.id,
                EpisodeModel.file_path.is_not(None),  # type: ignore[union-attr]
            )
            .order_by(EpisodeModel.season_number, EpisodeModel.episode_number)
            .limit(1)
        ).first()

    def _parse_filename(self, file_path: str) -> tuple[str | None, int | None]:
        """Extrait titre et année. Fallback sur le dossier parent si le parse
        du fichier est suspect (nom de scene-release, titre très court)."""
        try:
            path = Path(file_path)
            basename = path.stem
            parsed = _parser.parse(basename)
            title = parsed.title if parsed.title != "Unknown" else None
            # Nettoyer les suffixes 3D que guessit n'enlève pas toujours
            # (surtout sur les titres en majuscules).
            title = _strip_3d_suffix(title)
            year = parsed.year
            if isinstance(year, list):
                year = year[0] if year else None

            # Si le titre extrait est suspect, essayer le dossier parent.
            # Cas typiques : scene-release (hidef-btbl, nemo-madso), titres
            # très courts (tp, dmw), ou préfixes (Yves Angelo - Film).
            if _is_suspicious_title(title):
                parent_name = path.parent.name
                if parent_name and not _STRUCTURE_DIR_RE.match(parent_name):
                    parent_parsed = _parser.parse(parent_name)
                    parent_title = (
                        parent_parsed.title
                        if parent_parsed.title != "Unknown"
                        else None
                    )
                    # Accepter le parent même si jugé court : il reste
                    # plus fiable qu'un scene-release, à condition d'être
                    # au moins aussi long que le titre parsé du fichier.
                    if parent_title and (
                        not _is_suspicious_title(parent_title)
                        or (title and len(parent_title) > len(title))
                        or not title
                    ):
                        title = parent_title
                        if not year and parent_parsed.year:
                            y = parent_parsed.year
                            year = y[0] if isinstance(y, list) else y
            return title, year
        except Exception:
            logger.debug(f"Impossible de parser : {file_path}")
            return None, None

    def _get_file_duration(self, file_path: str) -> int | None:
        """Extrait la durée du fichier via mediainfo (résolution symlink)."""
        try:
            path = Path(file_path)
            # Résoudre le symlink si nécessaire
            if path.is_symlink():
                path = path.resolve()
            if not path.exists():
                return None

            from pymediainfo import MediaInfo

            media_info = MediaInfo.parse(str(path))
            for track in media_info.tracks:
                if track.track_type == "Video" and track.duration:
                    return int(float(track.duration) / 1000)  # ms → secondes
            return None
        except Exception:
            return None
