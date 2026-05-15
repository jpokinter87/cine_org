"""
Sous-commandes Typer pour `migrate-nas`.

Délègue toute la logique aux helpers `build_plan`/`run_apply`/`run_status`
de `orchestrators.py` — ce module ne contient que le wiring CLI (signatures
Typer, parsing args, affichage Rich des résumés).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.table import Table

from src.adapters.cli.commands.migrate_nas_command.orchestrators import (
    build_plan,
    run_apply,
    run_status,
)
from src.adapters.cli.validation import console
from src.container import Container
from src.services.migration.dataclasses import (
    Bucket,
    MigrationPlan,
    TransferStatus,
)
from src.services.migration.scanner import DEFAULT_CATEGORY_PREFIXES


migrate_nas_app = typer.Typer(
    name="migrate-nas",
    help="Migration filtrée par note depuis d'anciens NAS vers le nouveau",
    rich_markup_mode="rich",
)


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
    fast: Annotated[
        bool,
        typer.Option(
            "--fast",
            help=(
                "Mode rapide : skip les hashs xxh3_64 source+destination "
                "(gain ~2 lectures complètes par fichier). On fait confiance "
                "aux checksums internes de rsync (rolling MD5). "
                "Reprise basée sur la taille du fichier (suffisant si rsync "
                "--inplace a achevé). Recommandé pour des transferts de "
                "gros volumes sur réseau fiable."
            ),
        ),
    ] = False,
) -> None:
    """Exécute les transferts pending et met à jour le state store."""
    state_path = state_store or plan_path.with_suffix(plan_path.suffix + ".state.sqlite")
    mode_label = (
        "[yellow]fast (no hash verify)[/yellow]" if fast else "verify+hash"
    )
    console.print(
        f"[bold cyan]Exécution[/bold cyan] depuis [yellow]{plan_path}[/yellow] "
        f"(state: [dim]{state_path}[/dim], mode: {mode_label})"
    )
    outcomes = run_apply(
        plan_path=plan_path,
        state_store_path=state_path,
        show_progress=True,
        verify_hash=not fast,
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
