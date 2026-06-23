"""
Commande CLI `check-completeness`.

Confronte chaque série de la vidéothèque à TVDB pour détecter les épisodes
ou saisons déjà diffusés mais absents, et persiste le verdict de complétude.
"""

import asyncio
from datetime import date
from typing import Annotated, Optional

import typer
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from sqlmodel import select

from src.adapters.cli.helpers import suppress_loguru, with_container
from src.adapters.cli.validation import console
from src.infrastructure.persistence.database import get_session
from src.infrastructure.persistence.models import SeriesModel
from src.services.completeness.completeness_checker import (
    CompletenessChecker,
    check_series_model,
)


def check_completeness(
    series_id: Annotated[
        Optional[int],
        typer.Option(
            "--series-id",
            help="Vérifier une seule série (ID interne) au lieu de tout le parc",
        ),
    ] = None,
) -> None:
    """Vérifie la complétude des séries par rapport à TVDB."""
    asyncio.run(_check_completeness_async(series_id))


@with_container()
async def _check_completeness_async(container, series_id: Optional[int]) -> None:
    """Implémentation async de check-completeness."""
    tvdb_client = container.tvdb_client()
    checker = CompletenessChecker(tvdb_client)
    today = date.today()

    session = next(get_session())
    try:
        statement = select(SeriesModel)
        if series_id is not None:
            statement = statement.where(SeriesModel.id == series_id)
        series_list = session.exec(statement).all()

        if not series_list:
            console.print("[yellow]Aucune série à vérifier.[/yellow]")
            return

        total = len(series_list)
        console.print(
            f"[bold cyan]Vérification de complétude[/bold cyan] : "
            f"{total} série(s)\n"
        )

        tally = {"complete": 0, "incomplete": 0, "unverifiable": 0}

        with suppress_loguru():
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(),
                console=console,
                transient=False,
            ) as progress:
                task = progress.add_task("[cyan]Analyse…", total=total)
                for i, series in enumerate(series_list):
                    verdict = await check_series_model(
                        session, checker, series, today
                    )
                    tally[verdict] = tally.get(verdict, 0) + 1
                    progress.update(task, completed=i + 1)
                    if verdict == "incomplete":
                        progress.console.print(
                            f"  [yellow]✗[/yellow] {series.title} "
                            f"({series.year or '?'})"
                        )

        console.print("\n[bold]Résumé :[/bold]")
        console.print(f"  [green]{tally['complete']}[/green] complète(s)")
        console.print(f"  [yellow]{tally['incomplete']}[/yellow] incomplète(s)")
        console.print(
            f"  [dim]{tally['unverifiable']}[/dim] non vérifiable(s) (sans tvdb_id)"
        )
    finally:
        session.close()
