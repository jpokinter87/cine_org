"""Commande CLI ``cineorg check-missing-files``.

Scanne ``MovieModel`` et ``EpisodeModel`` à la recherche de fiches dont le
``file_path`` ne pointe plus sur un fichier existant. Avec ``--prune``,
envoie les fiches détectées en corbeille (réversible via la maintenance web).
"""

from typing import Annotated

import typer
from rich.prompt import Confirm
from rich.table import Table

from src.adapters.cli.helpers import suppress_loguru
from src.adapters.cli.validation import console
from src.container import Container
from src.services.missing_files_scanner import MissingFilesScanner


def check_missing_files(
    prune: Annotated[
        bool,
        typer.Option(
            "--prune",
            help="Envoyer en corbeille les fiches dont le fichier est manquant",
        ),
    ] = False,
) -> None:
    """Liste les fiches DB pointant vers un fichier qui n'existe plus."""
    container = Container()
    container.database.init()

    from src.infrastructure.persistence.database import get_session

    session = next(get_session())

    with suppress_loguru():
        console.print(
            "\n[bold cyan]Scan des fiches sans fichier physique[/bold cyan]\n"
        )

        scanner = MissingFilesScanner(session)
        records = scanner.find_missing()

        if not records:
            console.print(
                "[green]Aucune fiche orpheline.[/green] "
                "Toutes les entrées DB pointent vers un fichier existant.\n"
            )
            return

        table = Table(
            title=f"{len(records)} fiche(s) sans fichier",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Type", style="dim", no_wrap=True)
        table.add_column("ID", justify="right", style="dim")
        table.add_column("Titre", style="white")
        table.add_column("Chemin attendu", style="red dim", overflow="fold")
        for rec in records:
            table.add_row(
                rec.entity_type,
                str(rec.entity_id),
                rec.title,
                rec.file_path,
            )
        console.print(table)

        if not prune:
            console.print("\n[yellow]Mode dry-run : aucune fiche supprimée.[/yellow]")
            console.print(
                "[dim]Relancer avec --prune pour envoyer ces fiches en corbeille "
                "(les fichiers storage absents restent absents ; les VideoFileModel "
                "associés sont purgés).[/dim]"
            )
            return

        if not Confirm.ask(
            f"\n[bold]Envoyer ces {len(records)} fiche(s) en corbeille ?[/bold]",
            default=False,
        ):
            console.print("[yellow]Pruning annulé.[/yellow]")
            return

        pruned = scanner.prune(records)
        console.print(
            f"\n[bold green]Terminé.[/bold green] "
            f"{pruned} fiche(s) envoyée(s) en corbeille."
        )
        console.print(
            "[dim]Restauration possible via /maintenance/trash si nécessaire.[/dim]"
        )
