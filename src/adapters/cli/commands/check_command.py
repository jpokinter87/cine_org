"""Commande CLI check : verification d'integrite de la videotheque."""

from pathlib import Path
from typing import Annotated

import typer
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
)

from src.adapters.cli.validation import console
from src.container import Container


def check(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Afficher le rapport au format JSON"),
    ] = False,
    verify_hash: Annotated[
        bool,
        typer.Option("--verify-hash", help="Verifier les hash de fichiers (lent)"),
    ] = False,
) -> None:
    """Verifie l'integrite de la videotheque."""
    container = Container()
    config = container.config()
    container.database.init()

    # Creer le checker avec les paths
    checker = container.integrity_checker(
        storage_dir=Path(config.storage_dir),
        video_dir=Path(config.video_dir),
    )

    console.print("[bold cyan]Verification d'integrite[/bold cyan]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        check_task = progress.add_task("[cyan]Verification en cours...", total=None)

        report = checker.check(verify_hash=verify_hash)

        progress.update(check_task, description="[green]Termine")

    # Afficher le rapport
    if json_output:
        console.print(report.to_json())
    else:
        console.print(report.format_text())

        # Afficher les suggestions si issues detectees
        if report.has_issues and report.suggestions:
            console.print("\n[bold yellow]Commandes suggerees:[/bold yellow]")
            for suggestion in report.suggestions:
                console.print(f"  {suggestion}")
