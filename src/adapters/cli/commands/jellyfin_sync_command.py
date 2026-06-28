"""Commande CLI `jellyfin-sync` : génère l'arbre Jellyfin dédié + NFO."""

from typing import Annotated

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.adapters.cli.validation import console
from src.container import Container
from src.infrastructure.persistence.database import get_session
from src.services.jellyfin.jellyfin_sync_service import JellyfinSyncService


def jellyfin_sync(
    movies_only: Annotated[
        bool, typer.Option("--movies-only", help="Synchroniser seulement les films")
    ] = False,
    series_only: Annotated[
        bool, typer.Option("--series-only", help="Synchroniser seulement les séries")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Simuler sans rien écrire")
    ] = False,
    prune: Annotated[
        bool,
        typer.Option(
            "--prune",
            help="Supprimer de l'arbre Jellyfin les entrées absentes de la base",
        ),
    ] = False,
) -> None:
    """Génère un arbre de symlinks dédié + NFO pour Jellyfin (films et séries)."""
    container = Container()
    config = container.config()
    container.database.init()

    jellyfin_dir = config.jellyfin_dir
    console.print(f"[cyan]Arbre Jellyfin :[/cyan] {jellyfin_dir}")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("[cyan]Synchronisation en cours...", total=None)
        session = next(get_session())
        service = JellyfinSyncService(session, jellyfin_dir)
        report = service.sync(
            movies_only=movies_only,
            series_only=series_only,
            dry_run=dry_run,
            prune=prune,
        )

    prefix = "[yellow](simulation)[/yellow] " if dry_run else ""
    console.print(f"{prefix}[green]Films liés :[/green] {report.movies}")
    console.print(
        f"{prefix}[green]Séries liées :[/green] {report.series} "
        f"([green]épisodes :[/green] {report.episodes})"
    )
    if report.id_less:
        console.print(
            f"[yellow]Sans identifiant (titre/année seuls) :[/yellow] {len(report.id_less)}"
        )
    if report.skipped:
        console.print(
            f"[yellow]Ignorés (source absente) :[/yellow] {len(report.skipped)}"
        )
    if report.pruned:
        console.print(f"[magenta]Élagués :[/magenta] {len(report.pruned)}")
    if report.errors:
        console.print(f"[red]Erreurs :[/red] {len(report.errors)}")
