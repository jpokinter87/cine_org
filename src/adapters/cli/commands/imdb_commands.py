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
from sqlmodel import Session, select

from src.adapters.cli.helpers import suppress_loguru, with_container
from src.adapters.cli.validation import console
from src.container import Container


def _sync_imdb_for_model(
    session: Session,
    model_class,
    importer,
    limit: int,
) -> tuple[int, int]:
    """
    Synchronise les notes IMDb depuis le cache local pour un type d'entite.

    Itere sur les enregistrements ayant un imdb_id mais pas encore d'imdb_rating
    et applique la note (et le nombre de votes) trouvee dans le cache local.

    Args:
        session: Session SQLModel active
        model_class: MovieModel ou SeriesModel
        importer: IMDbDatasetImporter (ou tout objet exposant get_rating(imdb_id))
        limit: Nombre maximum d'entites a traiter

    Returns:
        Tuple (synced, not_found) — nombre d'entites mises a jour et manquees.
    """
    statement = (
        select(model_class)
        .where(model_class.imdb_id.is_not(None))
        .where(model_class.imdb_rating.is_(None))
        .limit(limit)
    )
    rows = session.exec(statement).all()

    synced = 0
    not_found = 0
    for row in rows:
        rating = importer.get_rating(row.imdb_id)
        if rating:
            row.imdb_rating = rating[0]
            row.imdb_votes = rating[1]
            session.add(row)
            synced += 1
        else:
            not_found += 1

    session.commit()
    return synced, not_found


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
            help="Nombre maximum d'entites a synchroniser (par cible)",
        ),
    ] = 100,
    target: Annotated[
        str,
        typer.Option(
            "--target", "-t",
            help="Cible de la synchronisation : movies, series ou all (defaut)",
        ),
    ] = "all",
) -> None:
    """Synchronise les notes IMDb avec les films et/ou series en base."""
    asyncio.run(_imdb_sync_async(limit, target))


@with_container()
async def _imdb_sync_async(container, limit: int, target: str) -> None:
    """Implementation async de la commande imdb sync."""
    from loguru import logger as loguru_logger

    from src.adapters.imdb.dataset_importer import IMDbDatasetImporter
    from src.infrastructure.persistence.models import MovieModel, SeriesModel

    target = target.lower().strip()
    if target not in {"movies", "series", "all"}:
        console.print(
            f"[red]Cible invalide:[/red] {target!r} (movies, series ou all)"
        )
        return

    session = container.session()
    cache_dir = Path(".cache/imdb")
    importer = IMDbDatasetImporter(cache_dir=cache_dir, session=session)

    # Desactiver les logs loguru pendant l'affichage
    loguru_logger.disable("src")

    try:
        targets = []
        if target in {"movies", "all"}:
            targets.append((MovieModel, "film"))
        if target in {"series", "all"}:
            targets.append((SeriesModel, "serie"))

        any_synced = False
        for model_class, label in targets:
            console.print(
                f"[bold cyan]Synchronisation IMDb {label}s[/bold cyan]\n"
            )
            synced, not_found = _sync_imdb_for_model(
                session=session,
                model_class=model_class,
                importer=importer,
                limit=limit,
            )
            if synced == 0 and not_found == 0:
                console.print(f"  [dim]Aucune {label} a synchroniser.[/dim]\n")
                continue

            any_synced = any_synced or synced > 0
            console.print(f"  [green]{synced}[/green] {label}(s) synchronise(s)")
            if not_found > 0:
                console.print(
                    f"  [yellow]{not_found}[/yellow] non trouve(s) dans le cache IMDb"
                )
            console.print()

        if not any_synced and target == "all":
            console.print(
                "[dim]Tous les imdb_id de la base ont deja une note locale.[/dim]"
            )

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
