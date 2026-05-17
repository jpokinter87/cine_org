"""Commande CLI ``reclassify-shorts`` : migre les courts-métrages existants.

Identifie les films dont la durée est inférieure ou égale au seuil défini
(``Settings.short_film_duration_threshold_seconds``) et qui ne sont pas
encore marqués ``is_short=True``, puis déplace leur symlink dans
``video/`` vers ``Films/Courts/{franchise}/``. Le storage physique n'est
pas touché.

Mode dry-run par défaut : aucune modification n'est effectuée tant que
``--no-dry-run`` n'est pas spécifié.
"""

from typing import Annotated

import typer
from rich.prompt import Confirm
from rich.table import Table

from src.adapters.cli.helpers import suppress_loguru
from src.adapters.cli.validation import console
from src.container import Container
from src.services.short_reclassifier import ShortCandidate, ShortReclassifier


def reclassify_shorts(
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--no-dry-run",
            help="Afficher le plan sans déplacer les symlinks (défaut : actif)",
        ),
    ] = True,
) -> None:
    """Reclasse les films courts existants vers Films/Courts/{franchise}/."""
    container = Container()
    container.database.init()
    settings = container.config()
    video_dir = settings.video_dir
    threshold = settings.short_film_duration_threshold_seconds

    from src.infrastructure.persistence.database import get_session

    session = next(get_session())

    with suppress_loguru():
        console.print("\n[bold cyan]Reclassement des courts-métrages[/bold cyan]\n")
        console.print(
            f"  Seuil de durée : [bold]{threshold} s[/bold] ({threshold // 60} min)\n"
        )

        reclassifier = ShortReclassifier(
            session=session,
            video_dir=video_dir,
            threshold_seconds=threshold,
        )
        candidates = reclassifier.find_candidates()

        if not candidates:
            console.print("[green]Aucun court-métrage à reclasser.[/green]\n")
            return

        _display_candidates(candidates)

        if dry_run:
            console.print(
                "\n[yellow]Mode dry-run : aucune modification effectuée.[/yellow]"
            )
            console.print(
                "[dim]Relancer avec --no-dry-run pour exécuter le reclassement.[/dim]"
            )
            return

        if not Confirm.ask(
            f"\n[bold]Déplacer les symlinks de {len(candidates)} court(s) ?[/bold]",
            default=False,
        ):
            console.print("[yellow]Reclassement annulé.[/yellow]")
            return

        console.print("\n[bold]Exécution...[/bold]\n")
        moved = 0
        failed = 0
        for cand in candidates:
            result = reclassifier.apply(cand)
            if result.moved:
                moved += 1
                console.print(
                    f"  [green]✓[/green] {cand.model.title} → "
                    f"{cand.new_symlink.parent.name}"
                )
            else:
                failed += 1
                console.print(f"  [red]✗[/red] {cand.model.title} : {result.error}")

        console.print(
            f"\n[bold green]Terminé.[/bold green] {moved} déplacés, {failed} en erreur."
        )


def _display_candidates(candidates: list[ShortCandidate]) -> None:
    """Tableau Rich listant les candidats au reclassement."""
    table = Table(
        title=f"{len(candidates)} court(s)-métrage(s) à reclasser",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Titre", style="white")
    table.add_column("Durée", justify="right", style="dim")
    table.add_column("Franchise", style="magenta")
    table.add_column("Destination", style="green", overflow="fold")

    for cand in candidates:
        duration = cand.model.duration_seconds or 0
        franchise = cand.new_symlink.parent.name
        table.add_row(
            cand.model.title,
            f"{duration // 60} min {duration % 60:02d}",
            franchise,
            str(cand.new_symlink),
        )

    console.print(table)
