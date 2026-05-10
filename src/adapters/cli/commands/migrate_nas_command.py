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
from src.services.migration.destination_planner import (
    MigrationDestinationPlanner,
)
from src.services.migration.plan_builder import (
    MigrationPlanBuilder,
    deserialize_plan,
    serialize_plan,
    write_review_csvs,
)
from src.services.migration.rating_resolver import MigrationRatingResolver
from src.services.migration.scanner import MigrationScanner
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
) -> MigrationPlan:
    """
    Construit le plan, écrit le JSON dans `output_path` et (si fourni) les
    CSV de revue dans `csv_dir`. Retourne le MigrationPlan en mémoire.
    """
    parser = GuessitFilenameParser()
    importer = imdb_importer or IMDbDatasetImporter(
        cache_dir=imdb_cache_dir, session=session
    )

    scanner = MigrationScanner(
        video_extensions=VIDEO_EXTENSIONS,
        destination_root=destination_storage_dir,
        alternative_roots=alternative_roots or [],
    )
    resolver = MigrationRatingResolver(
        session=session, parser=parser, imdb_importer=importer
    )
    planner = MigrationDestinationPlanner(
        session=session,
        parser=parser,
        organizer=Container().organizer_service(),
        renamer=Container().renamer_service(),
        destination_storage_dir=destination_storage_dir,
        destination_video_dir=destination_video_dir,
        source_root=source_root,
    )
    builder = MigrationPlanBuilder(
        scanner=scanner,
        rating_resolver=resolver,
        destination_planner=planner,
        threshold=threshold,
    )

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
    bandwidth_steps_mbps: tuple[int, ...] = (25, 20, 15, 10, 5),
) -> list[TransferOutcome]:
    """
    Charge le plan, initialise le state store et exécute les transferts
    pending. Retourne la liste des outcomes traités cette session.
    """
    plan = deserialize_plan(plan_path.read_text(encoding="utf-8"))
    store = MigrationStateStore(state_store_path)
    try:
        store.init_from_plan(plan)
        executor = MigrationTransferExecutor(
            plan=plan,
            state_store=store,
            rsync_runner=rsync_runner,
            bandwidth_steps_mbps=bandwidth_steps_mbps,
        )
        return executor.execute_all()
    finally:
        store.close()


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
) -> None:
    """Construit le plan de migration (lecture seule)."""
    container = Container()
    container.database.init()
    config = container.config()
    from src.infrastructure.persistence.database import get_session

    session = next(get_session())

    console.print(
        f"[bold cyan]Construction du plan[/bold cyan] "
        f"depuis [yellow]{source}[/yellow] "
        f"(seuil note ≥ [magenta]{threshold}[/magenta])"
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
    outcomes = run_apply(plan_path=plan_path, state_store_path=state_path)

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
        ("BROKEN", s.broken),
        ("ALREADY_ON_DESTINATION", s.already_on_destination),
        ("NOT_SYMLINK", s.not_symlink),
        ("NON_VIDEO", s.non_video),
        ("TOTAL", s.total_symlinks),
    ):
        if value:
            table.add_row(label, str(value))
    console.print(table)
    if s.total_size_bytes:
        gb = s.total_size_bytes / (1024**3)
        console.print(
            f"[dim]Volume à transférer : [magenta]{gb:.1f} Go[/magenta][/dim]"
        )
