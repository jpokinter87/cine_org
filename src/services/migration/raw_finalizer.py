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
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.adapters.api.tmdb_client import TMDBClient
from src.adapters.api.tvdb_client import TVDBClient
from src.core.entities.media import Episode, Movie, Series
from src.core.ports.api_clients import MediaDetails
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
from src.services.migration.dataclasses import MigrationItem
from src.services.organizer import OrganizerService
from src.services.renamer import RenamerService


@dataclass
class _CachedMovie:
    """Bundle Movie + symlink_path canonique pour le finalize idempotent."""

    movie: Movie
    symlink_path: Path


@dataclass
class _CachedSeries:
    """Bundle Series + Episode synthétique + symlink_path pour finalize idempotent."""

    series: Series
    episode: Episode
    symlink_path: Path


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
        tvdb_client: Optional[TVDBClient] = None,
        series_repo: Optional[SQLModelSeriesRepository] = None,
        episode_repo: Optional[SQLModelEpisodeRepository] = None,
        parser: Optional[IFilenameParser] = None,
    ) -> None:
        self._tmdb = tmdb_client
        self._movie_repo = movie_repo
        self._organizer = organizer
        self._renamer = renamer
        self._storage_dir = Path(storage_dir)
        self._video_dir = Path(video_dir)
        self._tvdb = tvdb_client
        self._series_repo = series_repo
        self._episode_repo = episode_repo
        self._parser = parser
        # Cache local item_id → bundle pour idempotence prepare → finalize.
        self._movie_cache: dict[str, _CachedMovie] = {}
        self._series_cache: dict[str, _CachedSeries] = {}

    # ---- RawItemFinalizer Protocol ---------------------------------------

    def prepare(self, item: MigrationItem) -> Optional[Path]:
        """Calcule le chemin de destination canonique (insert DB si nécessaire)."""
        if self._is_series_item(item):
            return self._prepare_series(item)
        if item.match.tmdb_id is not None:
            return self._prepare_movie(item)
        return None

    def finalize(self, item: MigrationItem, destination: Path) -> None:
        """Persiste les paths en DB, crée le symlink dans video/, supprime la source.

        Idempotent : un appel répété sur un item déjà finalisé est silencieux
        (les paths sont déjà à jour, le symlink existe, la source est absente).
        Doit être appelé après que rsync + verify hash ont réussi.
        """
        if item.item_id in self._movie_cache:
            self._finalize_movie(item, destination, self._movie_cache[item.item_id])
        elif item.item_id in self._series_cache:
            self._finalize_series(
                item, destination, self._series_cache[item.item_id]
            )
        else:
            raise RuntimeError(
                f"prepare() doit être appelé avant finalize() pour {item.item_id}"
            )

    # ---- Films : finalize -------------------------------------------------

    def _finalize_movie(
        self,
        item: MigrationItem,
        destination: Path,
        cached: _CachedMovie,
    ) -> None:
        if cached.movie.id is not None:
            self._update_movie_paths(
                int(cached.movie.id),
                file_path=str(destination),
                symlink_path=str(cached.symlink_path),
            )
        _create_symlink(cached.symlink_path, destination)
        _delete_source(item.source_path)

    def _update_movie_paths(
        self, movie_id: int, *, file_path: str, symlink_path: str
    ) -> None:
        """Met à jour file_path et symlink_path sur MovieModel via la session.

        Pattern repris de workflow.transfer_step._update_file_paths : l'entité
        domaine Movie n'expose pas symlink_path, on passe par le SQLModel.
        """
        from src.infrastructure.persistence.models import MovieModel

        session = self._movie_repo._session
        model = session.get(MovieModel, movie_id)
        if model is None:
            return
        model.file_path = file_path
        model.symlink_path = symlink_path
        session.add(model)
        session.commit()

    # ---- Séries : finalize ------------------------------------------------

    def _finalize_series(
        self,
        item: MigrationItem,
        destination: Path,
        cached: _CachedSeries,
    ) -> None:
        if self._episode_repo is None:
            raise RuntimeError(
                "Le mode séries finalize requiert episode_repo sur MigrationRawFinalizer"
            )
        # 1. Insert/update Episode (synthétique en mémoire jusqu'ici).
        saved_episode = self._upsert_episode_for_series(cached.episode)
        # 2. Mettre à jour les paths (équivalent transfer_step._update_file_paths).
        if saved_episode.id is not None:
            self._update_episode_paths(
                int(saved_episode.id),
                file_path=str(destination),
                symlink_path=str(cached.symlink_path),
            )
        _create_symlink(cached.symlink_path, destination)
        _delete_source(item.source_path)

    def _upsert_episode_for_series(self, episode: Episode) -> Episode:
        """Cherche l'épisode existant en DB, sinon le crée (idempotent)."""
        assert self._episode_repo is not None  # type narrow
        if episode.series_id is None:
            return self._episode_repo.save(episode)
        existing = self._episode_repo.get_by_series(
            str(episode.series_id),
            episode.season_number,
            episode.episode_number,
        )
        if existing:
            return existing[0]
        return self._episode_repo.save(episode)

    def _update_episode_paths(
        self, episode_id: int, *, file_path: str, symlink_path: str
    ) -> None:
        from src.infrastructure.persistence.models import EpisodeModel

        session = self._episode_repo._session  # type: ignore[union-attr]
        model = session.get(EpisodeModel, episode_id)
        if model is None:
            return
        model.file_path = file_path
        model.symlink_path = symlink_path
        session.add(model)
        session.commit()

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

        extension = item.source_path.suffix or ""
        directory = self._organizer.get_movie_destination(
            movie, self._storage_dir, self._video_dir
        )
        filename = self._renamer.generate_movie_filename(
            movie=movie, media_info=None, extension=extension
        )
        # Symlink path canonique côté video/.
        video_dir = self._organizer.get_movie_video_destination(
            movie, self._video_dir
        )
        symlink_path = video_dir / filename

        self._movie_cache[item.item_id] = _CachedMovie(
            movie=movie, symlink_path=symlink_path
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

    # ---- Séries -----------------------------------------------------------

    def _is_series_item(self, item: MigrationItem) -> bool:
        """Vrai si l'item doit etre traite comme une serie (tvdb_id ou heuristique)."""
        if item.match.tvdb_id is not None:
            return True
        media_root = (item.media_root or "").lower()
        return (
            media_root.startswith("seri")
            or media_root.startswith("séri")
            or media_root.startswith("anim")
        )

    def _prepare_series(self, item: MigrationItem) -> Optional[Path]:
        if self._series_repo is None or self._parser is None:
            raise RuntimeError(
                "Le mode séries requiert series_repo et parser sur MigrationRawFinalizer"
            )
        if item.source_path is None:
            return None

        parsed = self._parser.parse(item.source_path.name)
        if parsed.season is None or parsed.episode is None:
            return None  # Sans saison/épisode, pas de chemin canonique possible.

        series = self._lookup_or_fetch_series(item)
        if series is None:
            return None

        episode = self._synthetic_episode(series, parsed)

        extension = item.source_path.suffix or ""
        directory = self._organizer.get_series_destination(
            series, parsed.season, self._storage_dir, self._video_dir
        )
        filename = self._renamer.generate_series_filename(
            series=series,
            episode=episode,
            media_info=None,
            extension=extension,
        )
        video_dir = self._organizer.get_series_video_destination(
            series, parsed.season, self._video_dir
        )
        symlink_path = video_dir / filename

        self._series_cache[item.item_id] = _CachedSeries(
            series=series, episode=episode, symlink_path=symlink_path
        )
        return directory / filename

    def _lookup_or_fetch_series(
        self, item: MigrationItem
    ) -> Optional[Series]:
        """Lookup Series en DB par tmdb_id/tvdb_id ; sinon fetch + save."""
        assert self._series_repo is not None  # type narrow

        tvdb_id = item.match.tvdb_id
        tmdb_id = item.match.tmdb_id

        if tvdb_id is not None:
            existing = self._series_repo.get_by_tvdb_id(tvdb_id)
            if existing is not None:
                return existing
        if tmdb_id is not None:
            existing = self._series_repo.get_by_tmdb_id(tmdb_id)
            if existing is not None:
                return existing

        details = self._fetch_series_details(item)
        if details is None:
            return None

        series = self._build_series_from_details(
            details, tmdb_id=tmdb_id, tvdb_id=tvdb_id
        )
        return self._series_repo.save(series)

    def _fetch_series_details(
        self, item: MigrationItem
    ) -> Optional[MediaDetails]:
        """Fetch via TMDB (search_tv) ou TVDB selon source du match."""
        # Préférer TVDB quand l'id TVDB est connu (catalogue plus exhaustif
        # pour les séries anciennes), sinon retomber sur TMDB.
        if item.match.tvdb_id is not None and self._tvdb is not None:
            return asyncio.run(
                self._tvdb.get_details(str(item.match.tvdb_id))
            )
        if item.match.tmdb_id is not None:
            return asyncio.run(
                self._tmdb.get_tv_details(str(item.match.tmdb_id))
            )
        return None

    @staticmethod
    def _build_series_from_details(
        details: MediaDetails,
        *,
        tmdb_id: Optional[int],
        tvdb_id: Optional[int],
    ) -> Series:
        return Series(
            tmdb_id=tmdb_id,
            tvdb_id=tvdb_id,
            title=details.title,
            original_title=details.original_title,
            year=details.year,
            genres=tuple(details.genres),
            overview=details.overview,
            poster_path=details.poster_url,
            vote_average=details.vote_average,
            vote_count=details.vote_count,
            director=details.director,
            cast=tuple(details.cast),
        )

    @staticmethod
    def _synthetic_episode(
        series: Series, parsed: ParsedFilename
    ) -> Episode:
        """Episode synthétique en mémoire (pas inseré DB).

        Pattern réutilisé de destination_planner._synthetic_episode : pour la
        migration on n'enrichit pas le titre des épisodes (déféré à
        `enrich-episode-titles` post-transfert).
        """
        return Episode(
            series_id=series.id,
            season_number=parsed.season or 0,
            episode_number=parsed.episode or 0,
            title=parsed.episode_title or "",
        )


# ---- Helpers module-level (réutilisables) --------------------------------


def _create_symlink(symlink_path: Path, target: Path) -> None:
    """Crée (ou remplace) le symlink pointant vers target.

    Pattern aligné sur transferer._create_symlink_at : symlink absolu vers
    `target.resolve()`. Idempotent : si un symlink existe déjà au même
    emplacement, il est remplacé.
    """
    import os

    symlink_path.parent.mkdir(parents=True, exist_ok=True)
    if symlink_path.exists() or symlink_path.is_symlink():
        symlink_path.unlink()
    os.symlink(target.resolve(), symlink_path)


def _delete_source(source: Optional[Path]) -> None:
    """Supprime le fichier source physique. Idempotent (FileNotFoundError ignoré)."""
    if source is None:
        return
    try:
        source.unlink()
    except FileNotFoundError:
        # Reprise après crash : la source a déjà été supprimée — silencieux.
        pass
