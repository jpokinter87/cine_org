"""Commande CLI purge-hardlinks : rotation des hardlinks de seeding."""

from typing import Annotated

import typer
from rich.table import Table

from src.adapters.cli.validation import console
from src.container import Container


def purge_hardlinks(
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="Afficher les hardlinks à purger sans supprimer"
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Purger tous les hardlinks (même non expirés)"),
    ] = False,
) -> None:
    """Purge les hardlinks de seeding expirés dans downloads/."""
    container = Container()
    container.database.init()

    service = container.hardlink_service()

    # Afficher les stats avant purge
    stats = service.get_stats()
    if stats.total_entries == 0:
        console.print("[dim]Aucun hardlink enregistré.[/dim]")
        return

    target = "tous les" if force else "les expirés"
    console.print(f"[bold cyan]Purge des hardlinks de seeding ({target})[/bold cyan]\n")
    console.print(
        f"  Actifs : [green]{stats.total_active}[/green]  "
        f"Expirés : [yellow]{stats.total_expired}[/yellow]  "
        f"Total : {stats.total_entries}"
    )

    if not force and stats.total_expired == 0:
        console.print("\n[dim]Aucun hardlink expiré à purger.[/dim]")
        return

    # Purge
    result = service.purge_expired(force_all=force, dry_run=dry_run)

    if dry_run:
        console.print("\n[yellow]Mode dry-run — aucun fichier supprimé[/yellow]\n")

    if result.freed_paths:
        table = Table(title=f"{'À purger' if dry_run else 'Purgés'}")
        table.add_column("Fichier", style="cyan")
        for path in result.freed_paths:
            # Afficher juste le nom du fichier pour la lisibilité
            table.add_row(str(path).split("/")[-1])
        console.print(table)

    if result.errors:
        console.print(f"\n[red]{len(result.errors)} erreur(s) :[/red]")
        for error in result.errors:
            console.print(f"  [red]•[/red] {error}")

    action = "seraient purgés" if dry_run else "purgés"
    console.print(f"\n[bold green]{result.purged}[/bold green] hardlink(s) {action}")

    if result.residuals_removed:
        console.print(
            f"[dim]{result.residuals_removed} fichier(s) résiduel(s) "
            f"non-vidéo (.nfo, etc.) supprimé(s)[/dim]"
        )
