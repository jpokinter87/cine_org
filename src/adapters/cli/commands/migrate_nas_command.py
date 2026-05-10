"""
Commande CLI `migrate-nas` : migration filtrée d'anciens NAS vers le nouveau.

Trois sous-commandes :

* `plan` : scanne une arborescence source, classe chaque fichier par note
  combinée IMDb/TMDB/personnelle, écrit un plan JSON et trois CSV de revue
  (low_rated, unrated, broken). Aucune opération destructive.
* `apply` : consomme un plan JSON, lance les transferts via rsync (sans
  --remove-source-files), vérifie l'intégrité xxh3_64 et swappe les
  symlinks. Reprenable via un state store SQLite.
* `status` : affiche l'état d'avancement (par bucket et par TransferStatus).

Les helpers `build_plan`, `run_apply` et `run_status` exposent la logique
métier sans dépendance Typer pour faciliter les tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Optional

import typer
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from sqlmodel import Session

from src.adapters.cli.validation import console
from src.adapters.imdb.dataset_importer import IMDbDatasetImporter
from src.adapters.parsing.guessit_parser import GuessitFilenameParser
from src.container import Container
from src.services.migration.dataclasses import (
    Bucket,
    MigrationPlan,
    TransferOutcome,
    TransferStatus,
)
from src.services.matcher import MatcherService
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
    MigrationTransferExecutor,
    RsyncRunner,
)
from src.utils.constants import VIDEO_EXTENSIONS


migrate_nas_app = typer.Typer(
    name="migrate-nas",
    help="Migration filtrée par note depuis d'anciens NAS vers le nouveau",
    rich_markup_mode="rich",
)


# ---- Helpers métier (testables sans Typer) -------------------------------


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


def _build_with_progress(
    builder: MigrationPlanBuilder,
    scanner: MigrationScanner,
    source_root: Path,
    destination_root: Path,
) -> MigrationPlan:
    """Lance build() en affichant une barre de progression Rich.

    Pré-compte les fichiers vidéo (rapide : juste un walk filesystem) puis
    relance le scanner avec une barre qui suit chaque candidat traité, le
    nom courant, et la ventilation par bucket en temps réel.
    """
    # Désactiver loguru pendant l'affichage Rich (mémoire CineOrg).
    from loguru import logger as loguru_logger

    loguru_logger.disable("src")
    try:
        console.print("[dim]Comptage initial des fichiers vidéo…[/dim]")
        total = sum(1 for _ in scanner.scan(source_root))
        console.print(
            f"[dim]{total} fichier(s) vidéo détecté(s) — démarrage du plan.[/dim]"
        )
        console.print(
            "[dim]Légende buckets : "
            "[bold]M[/bold]igrate · "
            "[bold]L[/bold]ow_rated · "
            "[bold]U[/bold]nrated · "
            "needs_[bold]V[/bold]alidation · "
            "[bold]P[/bold]résent (déjà en DB) · "
            "[bold]B[/bold]roken · "
            "[bold]A[/bold]lready_on_destination"
            "[/dim]\n"
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=40),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Scan & classification", total=total)

            def on_progress(item, stats) -> None:
                progress.update(
                    task,
                    advance=1,
                    description=(
                        f"M={stats.to_migrate} L={stats.low_rated} U={stats.unrated} "
                        f"V={stats.needs_validation} P={stats.already_in_library} "
                        f"B={stats.broken} A={stats.already_on_destination}"
                    ),
                )

            return builder.build(
                source_root, destination_root, on_progress=on_progress
            )
    finally:
        loguru_logger.enable("src")


def run_apply(
    *,
    plan_path: Path,
    state_store_path: Path,
    rsync_runner: Optional[RsyncRunner] = None,
    bandwidth_steps_mbps: tuple[int, ...] = (25, 20, 15, 10, 5),
    session: Optional[Session] = None,
    show_progress: bool = False,
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
    (preparing / copying / verifying / finalizing / committed).
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
                bandwidth_steps_mbps=bandwidth_steps_mbps,
                raw_finalizer=raw_finalizer,
            )
        executor = MigrationTransferExecutor(
            plan=plan,
            state_store=store,
            rsync_runner=rsync_runner,
            bandwidth_steps_mbps=bandwidth_steps_mbps,
            raw_finalizer=raw_finalizer,
        )
        return executor.execute_all()
    finally:
        store.close()


def _execute_with_progress(
    *,
    plan: MigrationPlan,
    store: MigrationStateStore,
    rsync_runner: Optional[RsyncRunner],
    bandwidth_steps_mbps: tuple[int, ...],
    raw_finalizer,
) -> list[TransferOutcome]:
    """Exécute les transferts avec barre de progression Rich."""
    from loguru import logger as loguru_logger

    pending_ids = set(store.pending_items())
    pending_items = [
        i
        for i in plan.items
        if i.bucket == Bucket.MIGRATE and i.item_id in pending_ids
    ]
    total = len(pending_items)
    total_size_gb = sum(i.size_bytes or 0 for i in pending_items) / (1024**3)
    if total == 0:
        console.print("[yellow]Aucun item à transférer (tous déjà committed).[/yellow]")
        return []

    console.print(
        f"[cyan]{total} item(s) pending — volume estimé : "
        f"[bold]{total_size_gb:.1f} GB[/bold][/cyan]"
    )
    console.print(
        "[dim]Phases : preparing → copying → verifying → finalizing → committed[/dim]\n"
    )

    counters = {"committed": 0, "failed": 0}

    loguru_logger.disable("src")
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=30),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Démarrage…", total=total)

            def on_event(item, phase: str) -> None:
                size_mb = (item.size_bytes or 0) / (1024**2)
                short = item.symlink_path.name[:55]
                if phase == "committed":
                    counters["committed"] += 1
                    progress.update(
                        task,
                        advance=1,
                        description=(
                            f"[green]✓[/green] {short} "
                            f"({counters['committed']}/{total})"
                        ),
                    )
                elif phase.startswith("failed"):
                    counters["failed"] += 1
                    progress.update(
                        task,
                        advance=1,
                        description=f"[red]✗[/red] {short}",
                    )
                else:
                    progress.update(
                        task,
                        description=f"[{phase}] {short} ({size_mb:.0f} MB)",
                    )

            executor = MigrationTransferExecutor(
                plan=plan,
                state_store=store,
                rsync_runner=rsync_runner,
                bandwidth_steps_mbps=bandwidth_steps_mbps,
                raw_finalizer=raw_finalizer,
                on_event=on_event,
            )
            outcomes = executor.execute_all()
            # Capture les FAILED qui n'ont pas émis "failed_*" (status update direct).
            for o in outcomes:
                if o.status in (
                    TransferStatus.FAILED_COPY,
                    TransferStatus.FAILED_VERIFY,
                    TransferStatus.FAILED_OTHER,
                ) and counters["failed"] == 0:
                    counters["failed"] += 1
            return outcomes
    finally:
        loguru_logger.enable("src")


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


# ---- Sous-commandes Typer ------------------------------------------------


@migrate_nas_app.command("plan")
def plan_command(
    source: Annotated[
        Path,
        typer.Option(
            "--source",
            help="Racine de l'arborescence source (anciens NAS, montés en lecture).",
        ),
    ],
    output: Annotated[
        Path,
        typer.Option("--output", help="Chemin du fichier plan.json à écrire."),
    ],
    csv_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--csv-dir",
            help="Répertoire où écrire les CSV de revue (low_rated/unrated/broken).",
        ),
    ] = None,
    alt_root: Annotated[
        Optional[list[Path]],
        typer.Option(
            "--alt-root",
            help="Racine alternative pour retrouver les cibles brisées (multi).",
        ),
    ] = None,
    threshold: Annotated[
        float,
        typer.Option("--threshold", help="Note minimale (0-10) pour migrer."),
    ] = 6.0,
    include_raw: Annotated[
        bool,
        typer.Option(
            "--include-raw/--no-include-raw",
            help=(
                "Active le mode raw : les fichiers physiques bruts (vieux NAS sans "
                "couche symlinks) sont identifiés via TMDB/TVDB et classés selon "
                "leur note. Les matches ambigus vont dans needs_validation.csv "
                "pour retraitement via `process`. Nécessite des clés API valides."
            ),
        ),
    ] = False,
    category: Annotated[
        Optional[list[str]],
        typer.Option(
            "--category",
            help=(
                "Préfixe de répertoire à inclure (insensible à la casse/accents). "
                "Multi : --category film --category seri. Défaut : film, seri, anim. "
                "Permet d'ignorer Docs/, TV/, Musique/ etc. lors du scan."
            ),
        ),
    ] = None,
    all_categories: Annotated[
        bool,
        typer.Option(
            "--all-categories",
            help=(
                "Désactive le filtrage par catégorie : scan toute l'arborescence "
                "source sans whitelist. Inverse du défaut (Films/Séries/Animations)."
            ),
        ),
    ] = False,
) -> None:
    """Construit le plan de migration (lecture seule)."""
    container = Container()
    container.database.init()
    config = container.config()
    from src.infrastructure.persistence.database import get_session

    session = next(get_session())

    mode_label = "[green]symlinks + raw[/green]" if include_raw else "symlinks"

    if all_categories:
        category_prefixes: Optional[tuple[str, ...]] = None
        category_label = "[red]toutes catégories (filtrage désactivé)[/red]"
    else:
        category_prefixes = (
            tuple(category) if category else DEFAULT_CATEGORY_PREFIXES
        )
        category_label = ", ".join(category_prefixes)

    console.print(
        f"[bold cyan]Construction du plan[/bold cyan] "
        f"depuis [yellow]{source}[/yellow] "
        f"(seuil note ≥ [magenta]{threshold}[/magenta], mode {mode_label}, "
        f"catégories : [dim]{category_label}[/dim])"
    )

    plan = build_plan(
        source_root=source,
        destination_storage_dir=Path(config.storage_dir),
        destination_video_dir=Path(config.video_dir),
        threshold=threshold,
        output_path=output,
        csv_dir=csv_dir,
        session=session,
        alternative_roots=list(alt_root) if alt_root else None,
        include_raw=include_raw,
        show_progress=True,
        category_prefixes=category_prefixes,
    )

    _display_plan_summary(plan, output, csv_dir)


@migrate_nas_app.command("apply")
def apply_command(
    plan_path: Annotated[
        Path,
        typer.Argument(help="Chemin du plan JSON produit par `plan`."),
    ],
    state_store: Annotated[
        Optional[Path],
        typer.Option(
            "--state-store",
            help="Chemin du journal SQLite reprenable (défaut: <plan>.state.sqlite).",
        ),
    ] = None,
) -> None:
    """Exécute les transferts pending et met à jour le state store."""
    state_path = state_store or plan_path.with_suffix(plan_path.suffix + ".state.sqlite")
    console.print(
        f"[bold cyan]Exécution[/bold cyan] depuis [yellow]{plan_path}[/yellow] "
        f"(state: [dim]{state_path}[/dim])"
    )
    outcomes = run_apply(
        plan_path=plan_path,
        state_store_path=state_path,
        show_progress=True,
    )

    committed = sum(1 for o in outcomes if o.status == TransferStatus.COMMITTED)
    failed = sum(
        1
        for o in outcomes
        if o.status
        in (
            TransferStatus.FAILED_COPY,
            TransferStatus.FAILED_VERIFY,
            TransferStatus.FAILED_OTHER,
        )
    )
    console.print(
        f"[green]{committed} commit[/green] / [red]{failed} échec[/red] "
        f"sur {len(outcomes)} item(s) traité(s)."
    )


@migrate_nas_app.command("status")
def status_command(
    plan_path: Annotated[
        Path,
        typer.Argument(help="Chemin du plan JSON."),
    ],
    state_store: Annotated[
        Optional[Path],
        typer.Option("--state-store", help="Chemin du journal SQLite."),
    ] = None,
) -> None:
    """Affiche l'avancement du plan."""
    state_path = state_store or plan_path.with_suffix(plan_path.suffix + ".state.sqlite")
    summary = run_status(plan_path=plan_path, state_store_path=state_path)

    plan_table = Table(title="Plan (par bucket)", show_header=True)
    plan_table.add_column("Bucket", style="cyan")
    plan_table.add_column("Items", justify="right", style="yellow")
    for bucket in Bucket:
        n = summary["plan"].get(bucket.value, 0)
        if n:
            plan_table.add_row(bucket.value, str(n))
    plan_table.add_row("TOTAL", str(summary["plan"]["total"]))
    console.print(plan_table)

    if summary["progress"]:
        progress_table = Table(title="Avancement (par TransferStatus)", show_header=True)
        progress_table.add_column("Statut", style="cyan")
        progress_table.add_column("Items", justify="right", style="yellow")
        for status_value, count in summary["progress"].items():
            progress_table.add_row(status_value, str(count))
        console.print(progress_table)
    else:
        console.print(
            "[dim]Aucun state store actif — la migration n'a pas encore commencé.[/dim]"
        )


def _display_plan_summary(
    plan: MigrationPlan, output: Path, csv_dir: Optional[Path]
) -> None:
    console.print(f"\n[green]Plan écrit :[/green] {output}")
    if csv_dir:
        console.print(f"[green]CSV de revue :[/green] {csv_dir}")
    table = Table(title="Résumé du plan", show_header=True)
    table.add_column("Bucket", style="cyan")
    table.add_column("Items", justify="right", style="yellow")
    s = plan.stats
    for label, value in (
        ("MIGRATE", s.to_migrate),
        ("LOW_RATED", s.low_rated),
        ("UNRATED", s.unrated),
        ("NEEDS_VALIDATION", s.needs_validation),
        ("ALREADY_IN_LIBRARY", s.already_in_library),
        ("BROKEN", s.broken),
        ("ALREADY_ON_DESTINATION", s.already_on_destination),
        ("NOT_SYMLINK", s.not_symlink),
        ("NON_VIDEO", s.non_video),
        ("TOTAL", s.total_symlinks),
    ):
        if value:
            table.add_row(label, str(value))
    console.print(table)
    if s.needs_validation and csv_dir:
        console.print(
            f"[yellow]→ {s.needs_validation} item(s) à valider via [bold]process[/bold] : "
            f"voir {csv_dir}/needs_validation.csv[/yellow]"
        )
    if s.already_in_library and csv_dir:
        console.print(
            f"[cyan]→ {s.already_in_library} item(s) déjà en bibliothèque CineOrg "
            f"(source à supprimer manuellement) : voir {csv_dir}/already_in_library.csv[/cyan]"
        )
    if s.total_size_bytes:
        gb = s.total_size_bytes / (1024**3)
        console.print(
            f"[dim]Volume à transférer : [magenta]{gb:.1f} Go[/magenta][/dim]"
        )
