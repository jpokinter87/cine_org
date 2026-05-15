"""
Helpers métier de la commande `migrate-nas` (sans dépendance Typer).

`build_plan`, `run_apply` et `run_status` exposent la logique métier de
manière testable : on peut leur injecter un FakeRsync, une session
in-memory, un IMDbDatasetImporter mocké, sans passer par le Container ni
une vraie DB.

`_build_raw_finalizer` est l'unique point de wiring vers le Container :
appelé par `run_apply` quand le plan contient des items raw.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from sqlmodel import Session

from src.adapters.cli.commands.migrate_nas_command.progress_ui import (
    _build_with_progress,
    _execute_with_progress,
)
from src.adapters.imdb.dataset_importer import IMDbDatasetImporter
from src.adapters.parsing.guessit_parser import GuessitFilenameParser
from src.container import Container
from src.services.matcher import MatcherService
from src.services.migration.dataclasses import (
    Bucket,
    MigrationPlan,
    TransferOutcome,
)
from src.services.migration.destination_planner import (
    MigrationDestinationPlanner,
)
from src.services.migration.library_presence_checker import (
    LibraryPresenceChecker,
)
from src.services.migration.matching import (
    DefaultDetailsFetcher,
    MigrationMatcher,
)
from src.services.migration.plan_builder import (
    MigrationPlanBuilder,
    deserialize_plan,
    serialize_plan,
    write_review_csvs,
)
from src.services.migration.rating_resolver import MigrationRatingResolver
from src.services.migration.raw_finalizer import MigrationRawFinalizer
from src.services.migration.scanner import (
    DEFAULT_CATEGORY_PREFIXES,
    MigrationScanner,
)
from src.services.migration.state_store import MigrationStateStore
from src.services.migration.transfer_executor import (
    _DEFAULT_MAX_RETRIES,
    _DEFAULT_RETRY_PAUSE_SECONDS,
    MigrationTransferExecutor,
    RsyncRunner,
)
from src.utils.constants import VIDEO_EXTENSIONS


def build_plan(
    *,
    source_root: Path,
    destination_storage_dir: Path,
    destination_video_dir: Path,
    threshold: float,
    output_path: Path,
    csv_dir: Optional[Path],
    session: Session,
    alternative_roots: Optional[list[Path]] = None,
    imdb_importer: Optional[IMDbDatasetImporter] = None,
    imdb_cache_dir: Path = Path(".cache/imdb"),
    include_raw: bool = False,
    show_progress: bool = False,
    category_prefixes: Optional[tuple[str, ...]] = DEFAULT_CATEGORY_PREFIXES,
) -> MigrationPlan:
    """
    Construit le plan, écrit le JSON dans `output_path` et (si fourni) les
    CSV de revue dans `csv_dir`. Retourne le MigrationPlan en mémoire.

    Si `include_raw=True`, les fichiers physiques bruts (vieux NAS sans
    couche symlinks) passent par TMDB/TVDB matching → bucket selon note ou
    NEEDS_VALIDATION. Nécessite des clients API configurés.
    """
    parser = GuessitFilenameParser()
    importer = imdb_importer or IMDbDatasetImporter(
        cache_dir=imdb_cache_dir, session=session
    )
    container = Container()

    scanner = MigrationScanner(
        video_extensions=VIDEO_EXTENSIONS,
        destination_root=destination_storage_dir,
        alternative_roots=alternative_roots or [],
        category_prefixes=category_prefixes,
    )
    resolver = MigrationRatingResolver(
        session=session, parser=parser, imdb_importer=importer
    )
    planner = MigrationDestinationPlanner(
        session=session,
        parser=parser,
        organizer=container.organizer_service(),
        renamer=container.renamer_service(),
        destination_storage_dir=destination_storage_dir,
        destination_video_dir=destination_video_dir,
        source_root=source_root,
    )

    matcher = None
    fetcher = None
    library_checker = None
    if include_raw:
        tmdb = container.tmdb_client()
        tvdb = container.tvdb_client()
        matcher = MigrationMatcher(
            parser=parser,
            tmdb_client=tmdb,
            tvdb_client=tvdb,
            matcher_service=MatcherService(),
        )
        fetcher = DefaultDetailsFetcher(
            tmdb_client=tmdb, tvdb_client=tvdb
        )
        library_checker = LibraryPresenceChecker(
            movie_repo=container.movie_repository(),
            series_repo=container.series_repository(),
            episode_repo=container.episode_repository(),
            parser=parser,
        )

    builder = MigrationPlanBuilder(
        scanner=scanner,
        rating_resolver=resolver,
        destination_planner=planner,
        threshold=threshold,
        matcher=matcher,
        details_fetcher=fetcher,
        include_raw=include_raw,
        library_checker=library_checker,
    )

    if show_progress:
        plan = _build_with_progress(builder, scanner, source_root, destination_storage_dir)
    else:
        plan = builder.build(source_root, destination_storage_dir)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialize_plan(plan), encoding="utf-8")

    if csv_dir is not None:
        write_review_csvs(plan, csv_dir)

    return plan


def run_apply(
    *,
    plan_path: Path,
    state_store_path: Path,
    rsync_runner: Optional[RsyncRunner] = None,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_pause_seconds: int = _DEFAULT_RETRY_PAUSE_SECONDS,
    session: Optional[Session] = None,
    show_progress: bool = False,
    verify_hash: bool = True,
) -> list[TransferOutcome]:
    """
    Charge le plan, initialise le state store et exécute les transferts
    pending. Retourne la liste des outcomes traités cette session.

    Si le plan contient des items raw (`is_symlink_source=False`), un
    MigrationRawFinalizer est automatiquement câblé sur les services du
    container (TMDB/TVDB clients, repos Movie/Series/Episode, organizer,
    renamer). Sans items raw : pas de wiring supplémentaire (mode
    symlinks pur, comportement legacy strict).

    Si `show_progress=True`, affiche une barre Rich avec le compteur
    d'items, le nom du fichier en cours et la phase en cours
    (préparation / copie / vérification / finalisation / commit).
    """
    plan = deserialize_plan(plan_path.read_text(encoding="utf-8"))
    store = MigrationStateStore(state_store_path)
    raw_finalizer = None
    has_raw_items = any(
        not item.is_symlink_source for item in plan.items
    )
    if has_raw_items:
        raw_finalizer = _build_raw_finalizer(plan, session=session)
    try:
        store.init_from_plan(plan)
        if show_progress:
            return _execute_with_progress(
                plan=plan,
                store=store,
                rsync_runner=rsync_runner,
                max_retries=max_retries,
                retry_pause_seconds=retry_pause_seconds,
                raw_finalizer=raw_finalizer,
                verify_hash=verify_hash,
            )
        executor = MigrationTransferExecutor(
            plan=plan,
            state_store=store,
            rsync_runner=rsync_runner,
            max_retries=max_retries,
            retry_pause_seconds=retry_pause_seconds,
            raw_finalizer=raw_finalizer,
            verify_hash=verify_hash,
        )
        return executor.execute_all()
    finally:
        store.close()


def _build_raw_finalizer(
    plan: MigrationPlan, *, session: Optional[Session] = None
) -> MigrationRawFinalizer:
    """Câble un MigrationRawFinalizer depuis le container pour le mode raw."""
    container = Container()
    if session is None:
        from src.infrastructure.persistence.database import get_session

        session = next(get_session())

    config = container.config()
    return MigrationRawFinalizer(
        tmdb_client=container.tmdb_client(),
        tvdb_client=container.tvdb_client(),
        movie_repo=container.movie_repository(),
        series_repo=container.series_repository(),
        episode_repo=container.episode_repository(),
        organizer=container.organizer_service(),
        renamer=container.renamer_service(),
        parser=GuessitFilenameParser(),
        storage_dir=Path(config.storage_dir),
        video_dir=Path(config.video_dir),
        session=session,
    )


def run_status(
    *, plan_path: Path, state_store_path: Path
) -> dict[str, dict[str, Any]]:
    """
    Retourne un résumé combinant les compteurs du plan (par bucket) et
    l'avancement courant (par TransferStatus). Si le state store n'existe
    pas, `progress` est un dict vide.
    """
    plan = deserialize_plan(plan_path.read_text(encoding="utf-8"))
    plan_summary: dict[str, Any] = {"total": len(plan.items)}
    for bucket in Bucket:
        plan_summary[bucket.value] = sum(
            1 for it in plan.items if it.bucket == bucket
        )

    progress_summary: dict[str, int] = {}
    if state_store_path.exists():
        store = MigrationStateStore(state_store_path)
        try:
            for status, count in store.summary().items():
                progress_summary[status.value] = count
        finally:
            store.close()

    return {"plan": plan_summary, "progress": progress_summary}
