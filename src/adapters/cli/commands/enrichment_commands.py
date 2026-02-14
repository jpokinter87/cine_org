"""
Commandes CLI d'enrichissement ratings et IMDB IDs.
"""

import asyncio
from typing import Annotated

import typer
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

from src.adapters.cli.helpers import suppress_loguru, with_container
from src.adapters.cli.validation import console


def enrich_ratings(
    limit: Annotated[
        int,
        typer.Option(
            "--limit", "-l",
            help="Nombre maximum de films a enrichir",
        ),
    ] = 100,
) -> None:
    """Enrichit les notes TMDB (vote_average, vote_count) pour les films sans notes."""
    asyncio.run(_enrich_ratings_async(limit))


@with_container()
async def _enrich_ratings_async(container, limit: int) -> None:
    """Implementation async de la commande enrich-ratings."""
    from src.services.ratings_enricher import RatingsEnricherService

    # Creer le service d'enrichissement des notes
    movie_repo = container.movie_repository()
    tmdb_client = container.tmdb_client()

    service = RatingsEnricherService(
        movie_repo=movie_repo,
        tmdb_client=tmdb_client,
    )

    # Verifier d'abord combien de films sont a enrichir
    movies_to_enrich = movie_repo.list_without_ratings(limit)

    if not movies_to_enrich:
        console.print("[yellow]Aucun film a enrichir.[/yellow]")
        console.print("[dim]Tous les films ont deja leurs notes TMDB.[/dim]")
        return

    console.print(
        f"[bold cyan]Enrichissement des notes TMDB[/bold cyan]: {len(movies_to_enrich)} film(s)\n"
    )

    with suppress_loguru():
        stats = await service.enrich_ratings(limit=limit, rate_limit_seconds=0.25)

        # Afficher le resume
        console.print(f"\n[bold]Resume:[/bold]")
        console.print(f"  [green]{stats.enriched}[/green] enrichi(s)")
        if stats.failed > 0:
            console.print(f"  [red]{stats.failed}[/red] echec(s)")
        if stats.skipped > 0:
            console.print(f"  [yellow]{stats.skipped}[/yellow] ignore(s)")


def enrich_imdb_ids(
    limit: Annotated[
        int,
        typer.Option(
            "--limit", "-l",
            help="Nombre maximum de films a enrichir",
        ),
    ] = 100,
) -> None:
    """Recupere les imdb_id depuis TMDB pour les films sans cette information."""
    asyncio.run(_enrich_imdb_ids_async(limit))


@with_container()
async def _enrich_imdb_ids_async(container, limit: int) -> None:
    """Implementation async de la commande enrich-imdb-ids."""
    from src.services.imdb_id_enricher import ImdbIdEnricherService, EnrichmentResult, ProgressInfo

    # Creer le service d'enrichissement des imdb_id
    movie_repo = container.movie_repository()
    tmdb_client = container.tmdb_client()

    service = ImdbIdEnricherService(
        movie_repo=movie_repo,
        tmdb_client=tmdb_client,
    )

    # Verifier d'abord combien de films sont a enrichir
    movies_to_enrich = movie_repo.list_without_imdb_id(limit)

    if not movies_to_enrich:
        console.print("[yellow]Aucun film a enrichir.[/yellow]")
        console.print("[dim]Tous les films ont deja leur imdb_id.[/dim]")
        return

    total = len(movies_to_enrich)
    console.print(
        f"[bold cyan]Enrichissement des imdb_id[/bold cyan]: {total} film(s)\n"
    )

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
            task = progress.add_task("[cyan]Enrichissement...", total=total)

            def on_progress(info: ProgressInfo) -> None:
                """Callback de progression."""
                # Mettre a jour la barre de progression
                progress.update(task, completed=info.current)

                # Afficher le resultat pour chaque film
                year_str = f" ({info.movie_year})" if info.movie_year else ""
                title = f"{info.movie_title}{year_str}"

                if info.result == EnrichmentResult.SUCCESS:
                    progress.console.print(f"  [green]✓[/green] {title} → {info.imdb_id}")
                elif info.result == EnrichmentResult.FAILED:
                    progress.console.print(f"  [red]✗[/red] {title} - echec API")
                elif info.result == EnrichmentResult.NOT_FOUND:
                    progress.console.print(f"  [yellow]?[/yellow] {title} - pas d'imdb_id sur TMDB")
                elif info.result == EnrichmentResult.SKIPPED:
                    progress.console.print(f"  [dim]-[/dim] {title} - ignore (sans tmdb_id)")

            stats = await service.enrich_imdb_ids(
                limit=limit,
                rate_limit_seconds=0.25,
                on_progress=on_progress,
            )

        # Afficher le resume
        console.print(f"\n[bold]Resume:[/bold]")
        console.print(f"  [green]{stats.enriched}[/green] enrichi(s)")
        if stats.failed > 0:
            console.print(f"  [red]{stats.failed}[/red] echec(s) API")
        if stats.not_found > 0:
            console.print(f"  [yellow]{stats.not_found}[/yellow] sans imdb_id sur TMDB")
        if stats.skipped > 0:
            console.print(f"  [dim]{stats.skipped}[/dim] ignore(s) (sans tmdb_id)")
