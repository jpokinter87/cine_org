"""
Planificateur de destination pour la migration NAS.

Pour chaque MigrationCandidate (issu du scanner) et sa RatingDecision (issue
du resolver), calcule le chemin de destination final sur le nouveau NAS.

Stratégie :

* Symlink brisé, déjà sur la destination, ou sans cible résolue → pas de
  destination (None).
* Œuvre identifiée en DB (movie_id_in_db ou series_id_in_db) → chemin
  canonique CineOrg via OrganizerService + RenamerService. Cela ré-aligne
  les fichiers historiques sur la convention courante (genre, lettre,
  saison, nom standardisé). Pour les séries dont l'épisode n'est pas en DB,
  on construit un Episode synthétique à partir de la saison/épisode parsés
  et on conserve le titre d'épisode du nom de fichier d'origine.
* Œuvre absente de la DB → fallback : on conserve l'arborescence relative
  depuis `source_root` sous `destination_storage_dir`. C'est volontairement
  préservatif : pas de réorganisation hasardeuse pour des fichiers qu'on
  ne peut pas typer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlmodel import Session

from src.core.entities.media import Episode, Series
from src.core.ports.parser import IFilenameParser
from src.core.value_objects.parsed_info import ParsedFilename
from src.infrastructure.persistence.repositories.episode_repository import (
    SQLModelEpisodeRepository,
)
from src.infrastructure.persistence.repositories.movie_repository import (
    SQLModelMovieRepository,
)
from src.infrastructure.persistence.repositories.series_repository import (
    SQLModelSeriesRepository,
)
from src.services.migration.dataclasses import MigrationCandidate, RatingDecision
from src.services.organizer import OrganizerService
from src.services.renamer import RenamerService


class MigrationDestinationPlanner:
    """
    Calcule le chemin de destination d'un candidat de migration.

    Args:
        session: Session SQLModel ouverte sur la base CineOrg (lecture seule).
        parser: Parser de noms de fichiers (guessit) — fournit saison/épisode
            pour les séries.
        organizer: Service de calcul de chemin canonique CineOrg.
        renamer: Service de génération de nom de fichier canonique.
        destination_storage_dir: Racine physique sur le nouveau NAS (cible
            réelle des fichiers).
        destination_video_dir: Racine des symlinks sur le nouveau NAS (sert
            de référence à l'organizer pour naviguer dans l'arborescence
            existante).
        source_root: Racine de l'arborescence source (sert au fallback
            relatif quand l'œuvre n'est pas en DB).
    """

    def __init__(
        self,
        session: Session,
        parser: IFilenameParser,
        organizer: OrganizerService,
        renamer: RenamerService,
        destination_storage_dir: Path,
        destination_video_dir: Path,
        source_root: Path,
    ) -> None:
        self._session = session
        self._parser = parser
        self._organizer = organizer
        self._renamer = renamer
        self._storage_dir = Path(destination_storage_dir)
        self._video_dir = Path(destination_video_dir)
        self._source_root = Path(source_root)
        self._movie_repo = SQLModelMovieRepository(session)
        self._series_repo = SQLModelSeriesRepository(session)
        self._episode_repo = SQLModelEpisodeRepository(session)

    def plan(
        self, candidate: MigrationCandidate, decision: RatingDecision
    ) -> Optional[Path]:
        """Retourne le chemin de destination ou None si non applicable."""
        if candidate.is_broken or candidate.target_path is None:
            return None
        if candidate.already_on_destination:
            return None

        parsed = self._parser.parse(candidate.symlink_path.name)
        extension = candidate.symlink_path.suffix or ""

        if decision.movie_id_in_db is not None:
            return self._plan_movie(decision.movie_id_in_db, extension)

        if decision.series_id_in_db is not None:
            destination = self._plan_series(
                decision.series_id_in_db, parsed, extension
            )
            if destination is not None:
                return destination
            # Saison/épisode introuvables → on retombe sur le chemin relatif

        return self._fallback_relative(candidate)

    def _plan_movie(self, movie_id: int, extension: str) -> Optional[Path]:
        movie = self._movie_repo.get_by_id(str(movie_id))
        if movie is None:
            return None
        directory = self._organizer.get_movie_destination(
            movie, self._storage_dir, self._video_dir
        )
        filename = self._renamer.generate_movie_filename(
            movie, media_info=None, extension=extension
        )
        return directory / filename

    def _plan_series(
        self, series_id: int, parsed: ParsedFilename, extension: str
    ) -> Optional[Path]:
        if parsed.season is None or parsed.episode is None:
            return None
        series = self._series_repo.get_by_id(str(series_id))
        if series is None:
            return None
        episode = self._find_or_synthesize_episode(series, parsed)
        directory = self._organizer.get_series_destination(
            series, parsed.season, self._storage_dir, self._video_dir
        )
        filename = self._renamer.generate_series_filename(
            series, episode, media_info=None, extension=extension
        )
        return directory / filename

    def _find_or_synthesize_episode(
        self, series: Series, parsed: ParsedFilename
    ) -> Episode:
        """Cherche l'épisode en DB ; sinon en construit un avec le titre
        extrait du nom de fichier (peut être vide)."""
        if series.id is None:
            return self._synthetic_episode(parsed)
        existing = self._episode_repo.get_by_series(
            series.id, parsed.season, parsed.episode
        )
        if existing:
            return existing[0]
        return self._synthetic_episode(parsed)

    @staticmethod
    def _synthetic_episode(parsed: ParsedFilename) -> Episode:
        return Episode(
            season_number=parsed.season or 0,
            episode_number=parsed.episode or 0,
            title=parsed.episode_title or "",
        )

    def _fallback_relative(
        self, candidate: MigrationCandidate
    ) -> Optional[Path]:
        try:
            relative = candidate.symlink_path.relative_to(self._source_root)
        except ValueError:
            return None
        return self._storage_dir / relative
