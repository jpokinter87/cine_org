"""
Service de détection automatique d'associations TMDB potentiellement erronées.

Analyse les films et séries en comparant les métadonnées TMDB (titre, année,
durée) avec les informations extraites des noms de fichiers via guessit.
Chaque entité reçoit un score de confiance (0-100). Score < 60 = suspect.
"""

from __future__ import annotations

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

        # Heuristique 1 : Titre (compare avec titre FR et titre original)
        title_sim = _best_title_score(title_parsed, movie.title, movie.original_title)
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

        # Heuristique 3 : Durée (en pourcentage, cohérent avec le matcher)
        file_duration = self._get_file_duration(movie.file_path)
        if file_duration and movie.duration_seconds and movie.duration_seconds > 0:
            diff_pct = abs(file_duration - movie.duration_seconds) / movie.duration_seconds * 100
            file_min = file_duration // 60
            tmdb_min = movie.duration_seconds // 60
            if diff_pct >= 30:
                score -= 45
                reasons.append(
                    f"Écart de durée important : {file_min}min (fichier) "
                    f"vs {tmdb_min}min (TMDB) — {diff_pct:.0f}% d'écart"
                )
            elif diff_pct >= 15:
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
        """Extrait titre et année du nom de fichier via guessit."""
        try:
            basename = Path(file_path).stem
            parsed = _parser.parse(basename)
            title = parsed.title if parsed.title != "Unknown" else None
            year = parsed.year
            # guessit peut retourner une liste d'années
            if isinstance(year, list):
                year = year[0] if year else None
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
