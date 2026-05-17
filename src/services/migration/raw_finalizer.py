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

Architecture interne (post-refactor A#8) :
- `_MoviePreparer` : encapsule la phase `prepare` films (lookup DB,
  fetch TMDB, build paths). Stateless, instancié à chaque appel.
- `_SeriesPreparer` : idem pour les séries (TMDB+TVDB, parse saison/épisode).
- `MigrationRawFinalizer` : dispatcher public — détient les repos, caches,
  méthodes de finalize (update_paths, symlink, delete source). Ses
  preparers délèguent vers `_MoviePreparer`/`_SeriesPreparer` à chaque
  appel pour respecter les modifs runtime d'attributs (tests qui
  mutent `_episode_repo`/`_parser` après construction).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from sqlmodel import Session

from src.adapters.api.tmdb_client import TMDBClient
from src.adapters.api.tvdb_client import TVDBClient
from src.adapters.imdb.dataset_importer import IMDbDatasetImporter
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
from src.services.migration._helpers import is_series_like
from src.services.migration.dataclasses import MigrationItem
from src.services.organizer import OrganizerService
from src.services.renamer import RenamerService


@dataclass
class _RatingBundle:
    """Notes externes récupérées pendant le fetch (TMDB external_ids + cache IMDb).

    Utilisé par les preparers pour transporter les valeurs entre le fetch et
    le builder d'entité (Movie/Series). Toutes les valeurs sont optionnelles —
    un fetch raté laisse l'entité sans note (comportement résilient).
    """

    imdb_id: Optional[str] = None
    imdb_rating: Optional[float] = None
    imdb_votes: Optional[int] = None


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


# ============================================================================
# _MoviePreparer : phase `prepare` pour les films
# ============================================================================


class _MoviePreparer:
    """Sous-finalizer dédié à la phase `prepare` des items film.

    Stateless : prend ses dépendances (TMDB, repo, organizer, renamer,
    storage/video dirs) en arguments, retourne soit `(destination, _CachedMovie)`
    soit `None`. Le cache et l'écriture en DB sont gérés par le dispatcher
    `MigrationRawFinalizer`.
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
        imdb_importer: Optional[IMDbDatasetImporter] = None,
    ) -> None:
        self._tmdb = tmdb_client
        self._movie_repo = movie_repo
        self._organizer = organizer
        self._renamer = renamer
        self._storage_dir = storage_dir
        self._video_dir = video_dir
        self._imdb_importer = imdb_importer

    def prepare(self, item: MigrationItem) -> Optional[tuple[Path, _CachedMovie]]:
        tmdb_id = item.match.tmdb_id
        if tmdb_id is None or item.source_path is None:
            return None

        movie = self._lookup_or_create(tmdb_id)
        if movie is None:
            return None

        extension = item.source_path.suffix or ""
        directory = self._organizer.get_movie_destination(
            movie, self._storage_dir, self._video_dir
        )
        filename = self._renamer.generate_movie_filename(
            movie=movie, media_info=None, extension=extension
        )
        video_dir = self._organizer.get_movie_video_destination(movie, self._video_dir)
        symlink_path = video_dir / filename

        return directory / filename, _CachedMovie(
            movie=movie, symlink_path=symlink_path
        )

    def _lookup_or_create(self, tmdb_id: int) -> Optional[Movie]:
        movie = self._movie_repo.get_by_tmdb_id(tmdb_id)
        if movie is None:
            bundle = _fetch_movie_details_with_ratings(
                self._tmdb, tmdb_id, self._imdb_importer
            )
            if bundle is None:
                return None
            details, ratings = bundle
            movie = _build_movie_from_details(details, ratings=ratings)
            return self._movie_repo.save(movie)
        if movie.file_path and Path(movie.file_path).exists():
            # Garde-fou anti-écrasement : un Movie déjà associé à un fichier
            # existant ne doit pas être ré-utilisé comme destination — sinon
            # rsync --inplace écraserait silencieusement la bibliothèque.
            # Cas typiques : multi-parts (4 fichiers source → même tmdb_id),
            # doublon non détecté par LibraryPresenceChecker, ou Movie créé
            # par un item antérieur du même plan.
            raise FileExistsError(
                f"Movie tmdb_id={tmdb_id} ({movie.title}) déjà présent en DB "
                f"avec file_path={movie.file_path} — écrasement bloqué."
            )
        return movie


# ============================================================================
# _SeriesPreparer : phase `prepare` pour les séries
# ============================================================================


class _SeriesPreparer:
    """Sous-finalizer dédié à la phase `prepare` des items série.

    Requiert series_repo + parser pour la phase prepare (lookup par
    tvdb/tmdb_id + parse saison/épisode du filename). Le tvdb_client est
    optionnel — si absent et que l'item a un tvdb_id mais pas de tmdb_id,
    `_fetch_series_details` retourne None et `prepare` renvoie None.
    """

    def __init__(
        self,
        *,
        tmdb_client: TMDBClient,
        tvdb_client: Optional[TVDBClient],
        series_repo: SQLModelSeriesRepository,
        parser: IFilenameParser,
        organizer: OrganizerService,
        renamer: RenamerService,
        storage_dir: Path,
        video_dir: Path,
        imdb_importer: Optional[IMDbDatasetImporter] = None,
    ) -> None:
        self._tmdb = tmdb_client
        self._tvdb = tvdb_client
        self._series_repo = series_repo
        self._parser = parser
        self._organizer = organizer
        self._renamer = renamer
        self._storage_dir = storage_dir
        self._video_dir = video_dir
        self._imdb_importer = imdb_importer

    def prepare(self, item: MigrationItem) -> Optional[tuple[Path, _CachedSeries]]:
        if item.source_path is None:
            return None

        parsed = self._parser.parse(item.source_path.name)
        if parsed.season is None or parsed.episode is None:
            return None  # Sans saison/épisode, pas de chemin canonique possible.

        series = self._lookup_or_fetch(item)
        if series is None:
            return None

        episode = _synthetic_episode(series, parsed)

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

        return directory / filename, _CachedSeries(
            series=series, episode=episode, symlink_path=symlink_path
        )

    def _lookup_or_fetch(self, item: MigrationItem) -> Optional[Series]:
        """Lookup Series en DB par tmdb_id/tvdb_id ; sinon fetch + save."""
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

        bundle = self._fetch_details_with_ratings(item)
        if bundle is None:
            return None
        details, ratings, resolved_tmdb_id = bundle

        # Quand on bridge depuis TVDB, on récupère aussi le tmdb_id côté TMDB
        # (utile pour les enrichissements futurs et pour rester aligné avec
        # le workflow principal). Si on était déjà arrivé via TMDB, on garde
        # l'id d'origine.
        final_tmdb_id = tmdb_id if tmdb_id is not None else resolved_tmdb_id

        series = _build_series_from_details(
            details,
            tmdb_id=final_tmdb_id,
            tvdb_id=tvdb_id,
            ratings=ratings,
        )
        return self._series_repo.save(series)

    def _fetch_details_with_ratings(
        self, item: MigrationItem
    ) -> Optional[tuple[MediaDetails, _RatingBundle, Optional[int]]]:
        """Fetch détails + external_ids + IMDb rating en une seule run async.

        Stratégie séries (alignée sur DefaultDetailsFetcher.fetch en matching) :

        * Si tvdb_id présent : on bridge via `tmdb.find_by_tvdb_id` pour
          récupérer `vote_average` (TVDB v3 ne l'expose pas) + `imdb_id` via
          `get_tv_external_ids`. Si TMDB ignore le tvdb_id, on retombe sur
          `tvdb.get_details` (legacy, série sans note).
        * Sinon (tmdb_id présent) : `tmdb.get_tv_details` + `get_tv_external_ids`.

        L'IMDb rating est ensuite lu depuis le cache local (importer optionnel —
        si absent, l'entité reste sans imdb_rating mais le transfert continue).

        Returns:
            Tuple `(details, ratings, tmdb_id_resolved)` ou None si rien trouvé.
            `tmdb_id_resolved` = id TMDB inféré depuis `details.id` quand on a
            bridgé depuis TVDB (sert à peupler `series.tmdb_id`).
        """
        tvdb_id = item.match.tvdb_id
        tmdb_id = item.match.tmdb_id

        if tvdb_id is not None:
            return self._fetch_via_tvdb_bridge(tvdb_id)
        if tmdb_id is not None:
            return self._fetch_via_tmdb(tmdb_id)
        return None

    def _fetch_via_tvdb_bridge(
        self, tvdb_id: int
    ) -> Optional[tuple[MediaDetails, _RatingBundle, Optional[int]]]:
        tvdb_id_str = str(tvdb_id)

        async def _bundle() -> tuple[
            Optional[MediaDetails], Optional[str], Optional[int]
        ]:
            details = await self._tmdb.find_by_tvdb_id(tvdb_id_str)
            if details is None:
                return None, None, None
            tmdb_id_resolved: Optional[int] = None
            try:
                tmdb_id_resolved = int(details.id) if details.id else None
            except (TypeError, ValueError):
                tmdb_id_resolved = None
            imdb_id: Optional[str] = None
            if details.id:
                ext = await self._tmdb.get_tv_external_ids(str(details.id))
                if ext:
                    imdb_id = ext.get("imdb_id") or None
            return details, imdb_id, tmdb_id_resolved

        details, imdb_id, tmdb_id_resolved = _run_async_isolated(_bundle, self._tmdb)

        if details is None:
            # Fallback legacy : TMDB ignore ce tvdb_id, on prend TVDB brut
            # (sans note — comportement préservé pour ne rien dégrader).
            if self._tvdb is None:
                return None
            tvdb_details = _run_async_isolated(
                lambda: self._tvdb.get_details(tvdb_id_str),
                self._tvdb,
            )
            if tvdb_details is None:
                return None
            return tvdb_details, _RatingBundle(), None

        ratings = _resolve_imdb_rating(imdb_id, self._imdb_importer)
        return details, ratings, tmdb_id_resolved

    def _fetch_via_tmdb(
        self, tmdb_id: int
    ) -> Optional[tuple[MediaDetails, _RatingBundle, Optional[int]]]:
        tmdb_id_str = str(tmdb_id)

        async def _bundle() -> tuple[Optional[MediaDetails], Optional[str]]:
            details = await self._tmdb.get_tv_details(tmdb_id_str)
            if details is None:
                return None, None
            imdb_id: Optional[str] = None
            ext = await self._tmdb.get_tv_external_ids(tmdb_id_str)
            if ext:
                imdb_id = ext.get("imdb_id") or None
            return details, imdb_id

        details, imdb_id = _run_async_isolated(_bundle, self._tmdb)
        if details is None:
            return None
        ratings = _resolve_imdb_rating(imdb_id, self._imdb_importer)
        return details, ratings, None


# ============================================================================
# MigrationRawFinalizer : dispatcher public + état + phase `finalize`
# ============================================================================


class MigrationRawFinalizer:
    """
    Finalizer concret pour les fichiers physiques (mode raw migration).

    Détient les repos, le cache, et la phase `finalize` (qui touche la DB
    via update_paths, crée le symlink, supprime la source). La phase
    `prepare` est déléguée à `_MoviePreparer` / `_SeriesPreparer` instanciés
    à chaque appel pour refléter d'éventuelles modifs runtime d'attributs.

    Args:
        tmdb_client: Client TMDB (films + séries via get_tv_details). Utilise
            asynchroniquement via `asyncio.run` à l'intérieur de prepare()
            (rare appel batch, overhead acceptable).
        movie_repo: Repository pour upsert Movie via tmdb_id.
        organizer: OrganizerService pour le chemin canonique storage.
        renamer: RenamerService pour le nom canonique.
        storage_dir: Racine storage du nouveau NAS.
        video_dir: Racine video/ du nouveau NAS.
        session: Session SQLModel pour la mise à jour des paths (file_path,
            symlink_path) sur MovieModel/EpisodeModel — colonnes absentes des
            entités domaine. Doit être la même que celle utilisée par les
            repos passés en arguments. Si None (rétrocompat), tombe en
            fallback sur l'attribut privé `_session` du repo concerné.
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
        session: Optional[Session] = None,
        imdb_importer: Optional[IMDbDatasetImporter] = None,
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
        self._session = session
        self._imdb_importer = imdb_importer
        # Cache local item_id → bundle pour idempotence prepare → finalize.
        self._movie_cache: dict[str, _CachedMovie] = {}
        self._series_cache: dict[str, _CachedSeries] = {}

    def _get_session(self, repo: object) -> Session:
        """Retourne la session injectée si dispo, sinon celle du repo (legacy)."""
        if self._session is not None:
            return self._session
        # Rétrocompat : avant l'injection explicite, on tapait dans `_session`
        # du repo. Conservé pour ne pas casser les tests existants qui
        # construisent le finalizer sans session. Les nouveaux call sites
        # devraient toujours passer `session=`.
        return repo._session  # type: ignore[attr-defined]

    # ---- RawItemFinalizer Protocol : prepare (délégation) ----------------

    def prepare(self, item: MigrationItem) -> Optional[Path]:
        """Calcule le chemin de destination canonique (insert DB si nécessaire).

        Délègue à `_MoviePreparer`/`_SeriesPreparer` selon le type d'item, puis
        stocke le bundle retourné dans le cache local pour `finalize`.

        Fallback film : si la route série échoue, on retombe sur la route
        film UNIQUEMENT pour les items `Animations/` (films courts mal
        classés par l'heuristique série). Pour `Séries/` pur, le fallback
        est désactivé — sinon une saison entière sans épisode (ex:
        `Les Shadoks - S3.mkv`) bascule en film via le tmdb_id, qui peut
        être un homonyme côté `/movie/{id}` (collision d'ID entre les
        namespaces TMDB film et TV → catastrophe silencieuse observée).
        """
        if self._is_series_item(item):
            result = self._dispatch_series_prepare(item)
            if result is not None:
                return result
            if (
                self._is_animation_item(item)
                and item.match.tmdb_id is not None
            ):
                return self._dispatch_movie_prepare(item)
            return None
        if item.match.tmdb_id is not None:
            return self._dispatch_movie_prepare(item)
        return None

    def _is_animation_item(self, item: MigrationItem) -> bool:
        """Vrai si l'item est sous Animation(s) — déclencheur du fallback film.

        Couvre `media_root` direct (`Animation`, `Animations`) et le cas
        NAS nested (segment `Animation/Animations` au milieu du chemin).
        """
        media_root = (item.media_root or "").lower()
        if media_root.startswith("anim"):
            return True
        for p in (item.source_path, item.symlink_path):
            if p is None:
                continue
            path_lower = str(p).lower()
            if "/animation/" in path_lower or "/animations/" in path_lower:
                return True
        return False

    def _dispatch_movie_prepare(self, item: MigrationItem) -> Optional[Path]:
        preparer = _MoviePreparer(
            tmdb_client=self._tmdb,
            movie_repo=self._movie_repo,
            organizer=self._organizer,
            renamer=self._renamer,
            storage_dir=self._storage_dir,
            video_dir=self._video_dir,
            imdb_importer=self._imdb_importer,
        )
        result = preparer.prepare(item)
        if result is None:
            return None
        destination, cached = result
        self._movie_cache[item.item_id] = cached
        return destination

    def _dispatch_series_prepare(self, item: MigrationItem) -> Optional[Path]:
        if self._series_repo is None or self._parser is None:
            raise RuntimeError(
                "Le mode séries requiert series_repo et parser sur MigrationRawFinalizer"
            )
        preparer = _SeriesPreparer(
            tmdb_client=self._tmdb,
            tvdb_client=self._tvdb,
            series_repo=self._series_repo,
            parser=self._parser,
            organizer=self._organizer,
            renamer=self._renamer,
            storage_dir=self._storage_dir,
            video_dir=self._video_dir,
            imdb_importer=self._imdb_importer,
        )
        result = preparer.prepare(item)
        if result is None:
            return None
        destination, cached = result
        self._series_cache[item.item_id] = cached
        return destination

    # ---- RawItemFinalizer Protocol : finalize ----------------------------

    def finalize(self, item: MigrationItem, destination: Path) -> None:
        """Persiste les paths en DB, crée le symlink dans video/, supprime la source.

        Idempotent : un appel répété sur un item déjà finalisé est silencieux
        (les paths sont déjà à jour, le symlink existe, la source est absente).
        Doit être appelé après que rsync + verify hash ont réussi.
        """
        if item.item_id in self._movie_cache:
            self._finalize_movie(item, destination, self._movie_cache[item.item_id])
        elif item.item_id in self._series_cache:
            self._finalize_series(item, destination, self._series_cache[item.item_id])
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

        L'entité domaine Movie n'expose pas symlink_path : on passe par le
        SQLModel directement. Session injectée si disponible, sinon fallback
        sur celle du repo (cf. _get_session).
        """
        from src.infrastructure.persistence.models import MovieModel

        session = self._get_session(self._movie_repo)
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

        assert self._episode_repo is not None
        session = self._get_session(self._episode_repo)
        model = session.get(EpisodeModel, episode_id)
        if model is None:
            return
        model.file_path = file_path
        model.symlink_path = symlink_path
        session.add(model)
        session.commit()

    # ---- Helpers de routing ----------------------------------------------

    def _is_series_item(self, item: MigrationItem) -> bool:
        """Vrai si l'item doit etre traite comme une serie (tvdb_id ou heuristique).

        Heuristique chemin : inclut `source_path` ET `symlink_path` car le
        scanner peut produire un `media_root` non-catégoriel quand `source_root`
        pointe au-dessus de Séries/Films/Animations (cas NAS nested).
        """
        if item.match.tvdb_id is not None:
            return True
        return is_series_like(item.media_root, item.source_path, item.symlink_path)


# ============================================================================
# Helpers module-level (réutilisables — pures fonctions de fetch & build)
# ============================================================================


def _fetch_movie_details(
    tmdb_client: TMDBClient, tmdb_id: int
) -> Optional[MediaDetails]:
    """Récupère les détails TMDB film (synchrone via asyncio.run isolé).

    Conservé pour rétrocompat des tests qui importent directement cette
    fonction. Le code de production passe par
    `_fetch_movie_details_with_ratings` pour aussi récupérer imdb_*.
    """
    tmdb_id_str = str(tmdb_id)
    return _run_async_isolated(
        lambda: tmdb_client.get_details(tmdb_id_str),
        tmdb_client,
    )


def _fetch_movie_details_with_ratings(
    tmdb_client: TMDBClient,
    tmdb_id: int,
    imdb_importer: Optional[IMDbDatasetImporter],
) -> Optional[tuple[MediaDetails, _RatingBundle]]:
    """Fetch détails TMDB + external_ids (imdb_id) + IMDb rating.

    Bundle les 2 appels TMDB dans un seul asyncio.run pour amortir le coût
    d'init du client httpx (cf. `_run_async_isolated`). Le rating IMDb est
    résolu en synchrone après — la lookup DB locale est très rapide.
    """
    tmdb_id_str = str(tmdb_id)

    async def _bundle() -> tuple[Optional[MediaDetails], Optional[str]]:
        details = await tmdb_client.get_details(tmdb_id_str)
        if details is None:
            return None, None
        imdb_id: Optional[str] = None
        ext = await tmdb_client.get_external_ids(tmdb_id_str)
        if ext:
            imdb_id = ext.get("imdb_id") or None
        return details, imdb_id

    details, imdb_id = _run_async_isolated(_bundle, tmdb_client)
    if details is None:
        return None
    ratings = _resolve_imdb_rating(imdb_id, imdb_importer)
    return details, ratings


def _resolve_imdb_rating(
    imdb_id: Optional[str], imdb_importer: Optional[IMDbDatasetImporter]
) -> _RatingBundle:
    """Lookup `imdb_rating`/`imdb_votes` dans le cache local IMDb.

    Renvoie un bundle avec uniquement `imdb_id` (sans rating) si le cache
    est absent ou ne connaît pas cet imdb_id — l'entité reste utilisable,
    le transfert n'est pas bloqué.
    """
    bundle = _RatingBundle(imdb_id=imdb_id)
    if imdb_id is None or imdb_importer is None:
        return bundle
    try:
        rating_data = imdb_importer.get_rating(imdb_id)
    except Exception:
        return bundle
    if rating_data:
        bundle.imdb_rating, bundle.imdb_votes = rating_data
    return bundle


def _run_async_isolated(
    coro_factory: Callable[[], Awaitable[Any]],
    *clients: Any,
) -> Any:
    """Lance `coro_factory()` dans asyncio.run() en isolant les clients httpx.

    Pourquoi : un `httpx.AsyncClient` singleton (Container) garde des
    références internes (connection pool, transports) à la 1ère event loop
    dans laquelle il a été utilisé. Chaque `asyncio.run()` crée une loop
    éphémère puis la ferme. Au 2e `asyncio.run()`, httpx tente de réutiliser
    une connexion du pool dont les ressources internes pointent vers la
    loop fermée → `RuntimeError: Event loop is closed`.

    Solution : avant `asyncio.run()`, reset `_client = None` sur chaque
    client passé (force la recréation paresseuse dans la nouvelle loop) ;
    après, `aclose()` proprement et reset à nouveau pour le prochain appel.
    """
    for c in clients:
        c._client = None

    async def _wrap() -> Any:
        try:
            return await coro_factory()
        finally:
            for c in clients:
                client = getattr(c, "_client", None)
                if client is not None and not getattr(client, "is_closed", False):
                    await client.aclose()
                c._client = None

    return asyncio.run(_wrap())


def _build_movie_from_details(
    details: MediaDetails, *, ratings: Optional[_RatingBundle] = None
) -> Movie:
    """Construit un Movie minimal depuis les details TMDB.

    Les champs techniques (résolution, codecs, languages, file_size_bytes)
    ne sont PAS remplis ici : ils relèvent de l'enrichissement post-transfert
    (commande `enrich-tech`).
    """
    ratings = ratings or _RatingBundle()
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
        imdb_id=ratings.imdb_id,
        imdb_rating=ratings.imdb_rating,
        imdb_votes=ratings.imdb_votes,
        director=details.director,
        cast=tuple(details.cast),
        collection_id=details.collection_id,
        collection_name=details.collection_name,
    )


def _build_series_from_details(
    details: MediaDetails,
    *,
    tmdb_id: Optional[int],
    tvdb_id: Optional[int],
    ratings: Optional[_RatingBundle] = None,
) -> Series:
    ratings = ratings or _RatingBundle()
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
        imdb_id=ratings.imdb_id,
        imdb_rating=ratings.imdb_rating,
        imdb_votes=ratings.imdb_votes,
        director=details.director,
        cast=tuple(details.cast),
    )


def _synthetic_episode(series: Series, parsed: ParsedFilename) -> Episode:
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
