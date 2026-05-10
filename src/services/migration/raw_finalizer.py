"""
Finalizer concret pour les items raw du package migration.

Implementation du Protocol `RawItemFinalizer` (defini dans transfer_executor) :

* `prepare(item)` :
  1. Recupere le Movie/Series depuis la DB (par tmdb_id/tvdb_id) ou fetch
     TMDB/TVDB pour creer une nouvelle entree en base.
  2. Calcule le chemin de destination canonique via OrganizerService +
     RenamerService.
  3. Met l'entite en cache local (pour idempotence dans `finalize`).

* `finalize(item, destination)` (etape 4b3) :
  1. Insert VideoFileModel lie a l'entite Movie/Episode.
  2. Cree le symlink dans video/ canonique.
  3. Supprime la source physique apres verify hash.

Approche film/serie :
- Films (item.match.tmdb_id) : reutilise OrganizerService.get_movie_destination
  + RenamerService.generate_movie_filename, idem au workflow standard.
- Series (livre en etape 4b2) : nécessite saison/épisode parsés depuis le
  filename + Episode synthétique pour le renamer.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from src.adapters.api.tmdb_client import TMDBClient
from src.core.entities.media import Movie
from src.core.ports.api_clients import MediaDetails
from src.infrastructure.persistence.repositories.movie_repository import (
    SQLModelMovieRepository,
)
from src.services.migration.dataclasses import MigrationItem
from src.services.organizer import OrganizerService
from src.services.renamer import RenamerService


class MigrationRawFinalizer:
    """
    Finalizer concret pour les fichiers physiques (mode raw migration).

    Args:
        tmdb_client: Client TMDB (films + séries via get_tv_details). Utilise
            asynchroniquement via `asyncio.run` à l'intérieur de prepare()
            (rare appel batch, overhead acceptable).
        movie_repo: Repository pour upsert Movie via tmdb_id.
        organizer: OrganizerService pour le chemin canonique storage.
        renamer: RenamerService pour le nom canonique.
        storage_dir: Racine storage du nouveau NAS.
        video_dir: Racine video/ du nouveau NAS.
    """

    def __init__(
        self,
        *,
        tmdb_client: TMDBClient,
        movie_repo: SQLModelMovieRepository,
        organizer: OrganizerService,
        renamer: RenamerService,
        storage_dir: Path,
        video_dir: Path,
    ) -> None:
        self._tmdb = tmdb_client
        self._movie_repo = movie_repo
        self._organizer = organizer
        self._renamer = renamer
        self._storage_dir = Path(storage_dir)
        self._video_dir = Path(video_dir)
        # Cache local item_id → Movie pour idempotence prepare → finalize.
        self._movie_cache: dict[str, Movie] = {}

    # ---- RawItemFinalizer Protocol ---------------------------------------

    def prepare(self, item: MigrationItem) -> Optional[Path]:
        """Calcule le chemin de destination canonique (insert DB si nécessaire)."""
        if item.match.tmdb_id is not None and item.match.tvdb_id is None:
            return self._prepare_movie(item)
        # Series support en 4b2.
        if item.match.tvdb_id is not None or self._looks_like_series(item):
            raise NotImplementedError(
                "MigrationRawFinalizer.prepare ne supporte pas encore les séries (étape 4b2)"
            )
        return None

    def finalize(self, item: MigrationItem, destination: Path) -> None:
        """Insert VideoFile + create symlink + delete source. Étape 4b3."""
        raise NotImplementedError(
            "MigrationRawFinalizer.finalize sera livré en étape 4b3"
        )

    # ---- Films ------------------------------------------------------------

    def _prepare_movie(self, item: MigrationItem) -> Optional[Path]:
        tmdb_id = item.match.tmdb_id
        if tmdb_id is None or item.source_path is None:
            return None

        movie = self._movie_repo.get_by_tmdb_id(tmdb_id)
        if movie is None:
            details = self._fetch_movie_details(tmdb_id)
            if details is None:
                return None
            movie = self._build_movie_from_details(details)
            movie = self._movie_repo.save(movie)

        # Cache pour finalize() (4b3) sans relookup.
        self._movie_cache[item.item_id] = movie

        extension = item.source_path.suffix or ""
        directory = self._organizer.get_movie_destination(
            movie, self._storage_dir, self._video_dir
        )
        filename = self._renamer.generate_movie_filename(
            movie=movie, media_info=None, extension=extension
        )
        return directory / filename

    def _fetch_movie_details(self, tmdb_id: int) -> Optional[MediaDetails]:
        """Récupère les détails TMDB (synchrone via asyncio.run)."""
        return asyncio.run(self._tmdb.get_details(str(tmdb_id)))

    @staticmethod
    def _build_movie_from_details(details: MediaDetails) -> Movie:
        """Construit un Movie minimal depuis les details TMDB.

        Les champs techniques (résolution, codecs, languages, file_size_bytes)
        ne sont PAS remplis ici : ils relèvent de l'enrichissement post-transfert
        (commande `enrich-tech`).
        """
        return Movie(
            tmdb_id=int(details.id) if details.id else None,
            title=details.title,
            original_title=details.original_title,
            year=details.year,
            genres=tuple(details.genres),
            duration_seconds=details.duration_seconds,
            overview=details.overview,
            poster_path=details.poster_url,
            vote_average=details.vote_average,
            vote_count=details.vote_count,
            director=details.director,
            cast=tuple(details.cast),
            collection_id=details.collection_id,
            collection_name=details.collection_name,
        )

    @staticmethod
    def _looks_like_series(item: MigrationItem) -> bool:
        media_root = (item.media_root or "").lower()
        return media_root.startswith("seri") or media_root.startswith(
            "séri"
        ) or media_root.startswith("anim")
