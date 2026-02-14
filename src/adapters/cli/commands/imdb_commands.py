"""
Commandes CLI pour la gestion des datasets IMDb (import, sync, stats).
"""

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from src.adapters.cli.helpers import suppress_loguru, with_container
from src.adapters.cli.validation import console
from src.container import Container


# Application Typer pour les commandes IMDb
imdb_app = typer.Typer(
    name="imdb",
    help="Commandes de gestion des datasets IMDb",
    rich_markup_mode="rich",
)


@imdb_app.command("import")
def imdb_import(
    force: Annotated[
        bool,
        typer.Option(
            "--force", "-f",
            help="Force le re-telechargement meme si le fichier est recent",
        ),
    ] = False,
) -> None:
    """Telecharge et importe les notes IMDb depuis les datasets publics."""
    asyncio.run(_imdb_import_async(force))


@with_container()
async def _imdb_import_async(container, force: bool) -> None:
    """Implementation async de la commande imdb import."""
    from rich.status import Status

    from src.adapters.imdb.dataset_importer import IMDbDatasetImporter

    # Repertoire de cache pour les datasets
    cache_dir = Path(".cache/imdb")
    cache_dir.mkdir(parents=True, exist_ok=True)

    session = container.session()
    importer = IMDbDatasetImporter(cache_dir=cache_dir, session=session)

    with suppress_loguru():
        ratings_file = cache_dir / "title.ratings.tsv.gz"

        # Verifier si un telechargement est necessaire
        if force or importer.needs_update(ratings_file, max_age_days=7):
            with Status("[cyan]Telechargement du dataset title.ratings...", console=console):
                ratings_file = await importer.download_dataset("title.ratings")
            console.print("[green]Telechargement termine.[/green]")
        else:
            console.print("[yellow]Dataset recent, pas de telechargement necessaire.[/yellow]")
            console.print("[dim]Utilisez --force pour forcer le re-telechargement.[/dim]")

        # Import en base
        with Status("[cyan]Import des notes en base...", console=console):
            stats = importer.import_ratings(ratings_file)

        console.print(f"\n[bold]Resume de l'import:[/bold]")
        console.print(f"  [green]{stats.imported:,}[/green] notes importees")
        if stats.errors > 0:
            console.print(f"  [red]{stats.errors:,}[/red] erreurs")


@imdb_app.command("sync")
def imdb_sync(
    limit: Annotated[
        int,
        typer.Option(
            "--limit", "-l",
            help="Nombre maximum de films a synchroniser",
        ),
    ] = 100,
) -> None:
    """Synchronise les notes IMDb avec les films en base."""
    asyncio.run(_imdb_sync_async(limit))


@with_container()
async def _imdb_sync_async(container, limit: int) -> None:
    """Implementation async de la commande imdb sync."""
    from loguru import logger as loguru_logger

    from src.adapters.imdb.dataset_importer import IMDbDatasetImporter

    # Recuperer les repositories
    movie_repo = container.movie_repository()
    session = container.session()

    cache_dir = Path(".cache/imdb")
    importer = IMDbDatasetImporter(cache_dir=cache_dir, session=session)

    # Desactiver les logs loguru pendant l'affichage
    loguru_logger.disable("src")

    try:
        # Lister les films avec imdb_id mais sans imdb_rating
        from sqlmodel import select
        from src.infrastructure.persistence.models import MovieModel

        statement = (
            select(MovieModel)
            .where(MovieModel.imdb_id.isnot(None))
            .where(MovieModel.imdb_rating.is_(None))
            .limit(limit)
        )
        movies_to_sync = session.exec(statement).all()

        if not movies_to_sync:
            console.print("[yellow]Aucun film a synchroniser.[/yellow]")
            console.print("[dim]Tous les films avec imdb_id ont deja leurs notes IMDb.[/dim]")
            return

        console.print(f"[bold cyan]Synchronisation IMDb[/bold cyan]: {len(movies_to_sync)} film(s)\n")

        synced = 0
        not_found = 0

        for movie in movies_to_sync:
            rating = importer.get_rating(movie.imdb_id)

            if rating:
                movie.imdb_rating = rating[0]
                movie.imdb_votes = rating[1]
                session.add(movie)
                synced += 1
                console.print(f"  [green]✓[/green] {movie.title} - {rating[0]}/10 ({rating[1]:,} votes)")
            else:
                not_found += 1
                console.print(f"  [yellow]?[/yellow] {movie.title} - non trouve dans le cache IMDb")

        session.commit()

        console.print(f"\n[bold]Resume:[/bold]")
        console.print(f"  [green]{synced}[/green] synchronise(s)")
        if not_found > 0:
            console.print(f"  [yellow]{not_found}[/yellow] non trouve(s)")

    finally:
        loguru_logger.enable("src")


@imdb_app.command("stats")
def imdb_stats() -> None:
    """Affiche les statistiques du cache IMDb local."""
    asyncio.run(_imdb_stats_async())


@with_container()
async def _imdb_stats_async(container) -> None:
    """Implementation async de la commande imdb stats."""
    from src.adapters.imdb.dataset_importer import IMDbDatasetImporter

    cache_dir = Path(".cache/imdb")
    session = next(container.session.provider())
    importer = IMDbDatasetImporter(cache_dir=cache_dir, session=session)

    stats = importer.get_stats()

    console.print("[bold cyan]Statistiques du cache IMDb[/bold cyan]\n")
    console.print(f"  Nombre d'enregistrements: [bold]{stats['count']:,}[/bold]")
    if stats['last_updated']:
        console.print(f"  Derniere mise a jour: [bold]{stats['last_updated']}[/bold]")
    else:
        console.print("  [yellow]Aucune donnee importee.[/yellow]")
        console.print("  [dim]Utilisez 'cineorg imdb import' pour importer les notes.[/dim]")
