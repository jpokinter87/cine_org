"""Commande CLI consolidate : detection et rapatriement de fichiers sur volumes externes."""

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from src.adapters.cli.validation import console
from src.container import Container


def consolidate(
    scan_dir: Annotated[
        Optional[Path],
        typer.Argument(
            help="Repertoire a scanner (defaut: storage_dir de la config)",
        ),
    ] = None,
    do_consolidate: Annotated[
        bool,
        typer.Option(
            "--consolidate",
            help="Effectue le rapatriement (sinon affiche seulement le rapport)",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Simule sans copier les fichiers",
        ),
    ] = False,
) -> None:
    """
    Detecte et rapatrie les fichiers stockes sur des volumes externes.

    Scanne la zone de stockage pour trouver les symlinks pointant vers
    d'autres volumes et permet de rapatrier les fichiers.

    Exemples:
      cineorg consolidate                    # Rapport des symlinks externes
      cineorg consolidate --consolidate      # Rapatrie les fichiers accessibles
      cineorg consolidate --consolidate --dry-run  # Simulation
    """
    from rich.status import Status

    from src.adapters.cli.consolidation_helpers import (
        ConsolidationProgress,
        display_consolidation_prompt,
        display_examples,
        display_final_summary,
        display_inaccessible_warning,
        display_summary,
    )
    from src.services.consolidation import (
        ConsolidationService,
        ConsolidationStatus,
        ExternalSymlink,
    )

    container = Container()
    config = container.config()

    # Determiner le repertoire a scanner
    storage_dir = scan_dir if scan_dir else Path(config.storage_dir)

    if not storage_dir.exists():
        console.print(f"[red]Erreur: Repertoire introuvable: {storage_dir}[/red]")
        raise typer.Exit(1)

    service = ConsolidationService(storage_dir, dry_run=dry_run)

    # Scanner les symlinks externes
    console.print(f"[bold cyan]Scan:[/bold cyan] {storage_dir}")

    with Status("[cyan]Recherche des symlinks externes...", console=console) as status:
        symlinks: list[ExternalSymlink] = list(service.scan_external_symlinks())
        status.update(f"[cyan]{len(symlinks)} symlinks externes trouves")

    if not symlinks:
        console.print("[green]Aucun symlink externe detecte.[/green]")
        console.print("[dim]Tous les fichiers sont dans la zone de stockage.[/dim]")
        return

    # Afficher le resume par volume
    summary = service.get_summary(symlinks)

    display_summary(symlinks, summary)

    # Compter les accessibles et inaccessibles
    accessible = [s for s in symlinks if s.status == ConsolidationStatus.ACCESSIBLE]
    inaccessible = [s for s in symlinks if s.status == ConsolidationStatus.INACCESSIBLE]

    display_inaccessible_warning(len(inaccessible))

    # Si pas de consolidation demandee, afficher quelques exemples
    if not do_consolidate:
        display_examples(symlinks)
        display_consolidation_prompt()
        return

    # Effectuer la consolidation
    if not accessible:
        console.print("\n[yellow]Aucun fichier accessible a rapatrier.[/yellow]")
        return

    ConsolidationProgress.display_initial_message(len(accessible), dry_run)

    consolidated = 0
    errors = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Copie...", total=len(accessible))

        for symlink in accessible:
            progress.update(task, description=f"[cyan]{symlink.symlink_path.name[:40]}")

            result = service.consolidate(symlink)

            if result.status == ConsolidationStatus.CONSOLIDATED:
                consolidated += 1
            elif result.status == ConsolidationStatus.ERROR:
                errors += 1
                ConsolidationProgress.display_error(symlink.symlink_path.name, result.error_message)

            progress.advance(task)

        progress.update(task, description="[green]Termine")

    # Resume
    display_final_summary(consolidated, errors, len(inaccessible), dry_run)
