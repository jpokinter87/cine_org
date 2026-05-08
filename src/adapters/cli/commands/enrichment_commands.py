"""
Commandes CLI d'enrichissement ratings, IMDB IDs, series, credits films et collections.
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
from sqlalchemy import or_
from sqlmodel import select

from src.adapters.cli.helpers import suppress_loguru, with_container
from src.adapters.cli.validation import console


def enrich_ratings(
    limit: Annotated[
        int,
        typer.Option(
            "--limit", "-l",
            help="Nombre maximum de films a enrichir",
        ),
    ] = 2000,
) -> None:
    """Enrichit les notes TMDB (vote_average, vote_count) pour les films sans notes."""
    asyncio.run(_enrich_ratings_async(limit))


@with_container()
async def _enrich_ratings_async(container, limit: int) -> None:
    """Implementation async de la commande enrich-ratings."""
    from src.services.ratings_enricher import (
        EnrichmentResult,
        ProgressInfo,
        RatingsEnricherService,
    )

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

    total = len(movies_to_enrich)
    console.print(
        f"[bold cyan]Enrichissement des notes TMDB[/bold cyan]: {total} film(s)\n"
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
                progress.update(task, completed=info.current)
                year_str = f" ({info.movie_year})" if info.movie_year else ""
                title = f"{info.movie_title}{year_str}"

                if info.result == EnrichmentResult.SUCCESS:
                    progress.console.print(f"  [green]✓[/green] {title}")
                elif info.result == EnrichmentResult.FAILED:
                    progress.console.print(f"  [red]✗[/red] {title} - echec API")
                elif info.result == EnrichmentResult.SKIPPED:
                    progress.console.print(f"  [dim]-[/dim] {title} - ignore (sans tmdb_id)")

            stats = await service.enrich_ratings(
                limit=limit,
                rate_limit_seconds=0.25,
                on_progress=on_progress,
            )

        # Afficher le resume
        console.print("\n[bold]Resume:[/bold]")
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
        console.print("\n[bold]Resume:[/bold]")
        console.print(f"  [green]{stats.enriched}[/green] enrichi(s)")
        if stats.failed > 0:
            console.print(f"  [red]{stats.failed}[/red] echec(s) API")
        if stats.not_found > 0:
            console.print(f"  [yellow]{stats.not_found}[/yellow] sans imdb_id sur TMDB")
        if stats.skipped > 0:
            console.print(f"  [dim]{stats.skipped}[/dim] ignore(s) (sans tmdb_id)")


def enrich_series(
    limit: Annotated[
        int,
        typer.Option(
            "--limit", "-l",
            help="Nombre maximum de series a enrichir",
        ),
    ] = 200,
    force: Annotated[
        bool,
        typer.Option(
            "--force", "-f",
            help="Re-enrichir meme les series avec poster",
        ),
    ] = False,
) -> None:
    """Enrichit les series depuis TMDB (poster, notes, genres, createurs, acteurs)."""
    asyncio.run(_enrich_series_async(limit, force))


@with_container()
async def _enrich_series_async(container, limit: int, force: bool) -> None:
    """Implementation async de la commande enrich-series."""
    from pathlib import Path

    from src.adapters.imdb.dataset_importer import IMDbDatasetImporter
    from src.infrastructure.persistence.models import SeriesModel
    from src.infrastructure.persistence.database import get_session
    from src.services.series_enricher import (
        SeriesEnricherService,
        EnrichmentResult,
        ProgressInfo,
    )

    tmdb_client = container.tmdb_client()
    series_repo = container.series_repository()
    episode_repo = container.episode_repository()

    # Importer IMDb local : permet d'enrichir aussi imdb_rating/imdb_votes
    # en une seule commande, sans devoir relancer `imdb sync` ensuite.
    imdb_session = container.session()
    imdb_importer = IMDbDatasetImporter(
        cache_dir=Path(".cache/imdb"), session=imdb_session
    )

    # Recuperer les series a enrichir directement via SQL
    session = next(get_session())
    try:
        if force:
            stmt = select(SeriesModel).limit(limit)
        else:
            stmt = (
                select(SeriesModel)
                .where(
                    or_(
                        SeriesModel.poster_path.is_(None),
                        SeriesModel.vote_average.is_(None),
                        SeriesModel.director.is_(None),
                    )
                )
                .limit(limit)
            )
        models = session.exec(stmt).all()
    finally:
        session.close()

    if not models:
        console.print("[yellow]Aucune serie a enrichir.[/yellow]")
        console.print("[dim]Toutes les series ont deja leurs metadonnees TMDB.[/dim]")
        return

    # Convertir en entites via le repo
    series_list = []
    for m in models:
        series_list.append(series_repo._to_entity(m))

    console.print(
        f"[bold cyan]Enrichissement TMDB des series[/bold cyan]: {len(series_list)} serie(s)\n"
    )

    service = SeriesEnricherService(
        series_repo=series_repo,
        tmdb_client=tmdb_client,
        imdb_importer=imdb_importer,
        episode_repo=episode_repo,
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
            task = progress.add_task("[cyan]Enrichissement...", total=len(series_list))

            def on_progress(info: ProgressInfo) -> None:
                progress.update(task, completed=info.current)
                year_str = f" ({info.series_year})" if info.series_year else ""
                title = f"{info.series_title}{year_str}"

                if info.result == EnrichmentResult.SUCCESS:
                    progress.console.print(f"  [green]✓[/green] {title}")
                elif info.result == EnrichmentResult.NOT_FOUND:
                    progress.console.print(f"  [yellow]?[/yellow] {title} - non trouve sur TMDB")
                elif info.result == EnrichmentResult.FAILED:
                    progress.console.print(f"  [red]✗[/red] {title} - echec API")

            stats = await service.enrich_series(
                series_list=series_list,
                rate_limit_seconds=0.3,
                on_progress=on_progress,
            )

        console.print("\n[bold]Resume:[/bold]")
        console.print(f"  [green]{stats.enriched}[/green] enrichie(s)")
        if stats.not_found > 0:
            console.print(f"  [yellow]{stats.not_found}[/yellow] non trouvee(s) sur TMDB")
        if stats.failed > 0:
            console.print(f"  [red]{stats.failed}[/red] echec(s) API")
        if stats.skipped > 0:
            console.print(f"  [dim]{stats.skipped}[/dim] ignoree(s)")

    await tmdb_client.close()


def enrich_movies_credits(
    limit: Annotated[
        int,
        typer.Option(
            "--limit", "-l",
            help="Nombre maximum de films a enrichir",
        ),
    ] = 200,
) -> None:
    """Enrichit les credits (realisateur, acteurs) des films depuis TMDB."""
    asyncio.run(_enrich_movies_credits_async(limit))


@with_container()
async def _enrich_movies_credits_async(container, limit: int) -> None:
    """Implementation async de la commande enrich-movies-credits."""
    from src.infrastructure.persistence.models import MovieModel
    from src.infrastructure.persistence.database import get_session
    from src.services.movies_enricher import (
        MoviesEnricherService,
        EnrichmentResult,
        ProgressInfo,
    )

    tmdb_client = container.tmdb_client()
    movie_repo = container.movie_repository()

    # Recuperer les films sans director
    session = next(get_session())
    try:
        stmt = (
            select(MovieModel)
            .where(MovieModel.tmdb_id.isnot(None))
            .where(MovieModel.director.is_(None))
            .limit(limit)
        )
        models = session.exec(stmt).all()
    finally:
        session.close()

    if not models:
        console.print("[yellow]Aucun film a enrichir.[/yellow]")
        console.print("[dim]Tous les films ont deja leurs credits.[/dim]")
        return

    movies = [movie_repo._to_entity(m) for m in models]

    console.print(
        f"[bold cyan]Enrichissement credits TMDB[/bold cyan]: {len(movies)} film(s)\n"
    )

    service = MoviesEnricherService(
        movie_repo=movie_repo,
        tmdb_client=tmdb_client,
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
            task = progress.add_task("[cyan]Enrichissement...", total=len(movies))

            def on_progress(info: ProgressInfo) -> None:
                progress.update(task, completed=info.current)
                year_str = f" ({info.movie_year})" if info.movie_year else ""
                title = f"{info.movie_title}{year_str}"

                if info.result == EnrichmentResult.SUCCESS:
                    progress.console.print(f"  [green]✓[/green] {title}")
                elif info.result == EnrichmentResult.FAILED:
                    progress.console.print(f"  [red]✗[/red] {title} - echec API")
                elif info.result == EnrichmentResult.SKIPPED:
                    progress.console.print(f"  [dim]-[/dim] {title} - ignore (sans tmdb_id)")

            stats = await service.enrich_credits(
                movies=movies,
                rate_limit_seconds=0.25,
                on_progress=on_progress,
            )

        console.print("\n[bold]Resume:[/bold]")
        console.print(f"  [green]{stats.enriched}[/green] enrichi(s)")
        if stats.failed > 0:
            console.print(f"  [red]{stats.failed}[/red] echec(s) API")
        if stats.skipped > 0:
            console.print(f"  [dim]{stats.skipped}[/dim] ignore(s) (sans tmdb_id)")

    await tmdb_client.close()


def enrich_collections(
    limit: Annotated[
        int,
        typer.Option(
            "--limit", "-l",
            help="Nombre maximum de films a enrichir",
        ),
    ] = 6000,
) -> None:
    """Enrichit les collections/sagas TMDB pour les films sans cette information."""
    asyncio.run(_enrich_collections_async(limit))


@with_container()
async def _enrich_collections_async(container, limit: int) -> None:
    """Implementation async de la commande enrich-collections."""
    import asyncio as _asyncio

    from src.infrastructure.persistence.database import get_session
    from src.infrastructure.persistence.models import MovieModel

    tmdb_client = container.tmdb_client()

    # Recuperer les films sans collection_id (jamais verifies)
    session = next(get_session())
    try:
        stmt = (
            select(MovieModel)
            .where(MovieModel.tmdb_id.isnot(None))
            .where(MovieModel.collection_id.is_(None))
            .limit(limit)
        )
        models = list(session.exec(stmt).all())
    finally:
        session.close()

    if not models:
        console.print("[yellow]Aucun film a enrichir.[/yellow]")
        console.print("[dim]Tous les films ont deja ete verifies pour les collections.[/dim]")
        return

    total = len(models)
    enriched = 0
    no_collection = 0
    failed = 0

    console.print(
        f"[bold cyan]Enrichissement collections TMDB[/bold cyan]: {total} film(s)\n"
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
            task = progress.add_task("[cyan]Collections...", total=total)

            for model in models:
                year_str = f" ({model.year})" if model.year else ""
                title = f"{model.title}{year_str}"

                try:
                    details = await tmdb_client.get_details(
                        str(model.tmdb_id), skip_cache=True
                    )

                    session = next(get_session())
                    try:
                        db_model = session.get(MovieModel, model.id)
                        if db_model and details and details.collection_id:
                            db_model.collection_id = details.collection_id
                            db_model.collection_name = details.collection_name
                            session.add(db_model)
                            session.commit()
                            enriched += 1
                            progress.console.print(
                                f"  [green]✓[/green] {title} → {details.collection_name}"
                            )
                        elif db_model:
                            # Sentinel : 0 = verifie, pas de collection
                            db_model.collection_id = 0
                            session.add(db_model)
                            session.commit()
                            no_collection += 1
                    finally:
                        session.close()

                except Exception:
                    failed += 1
                    progress.console.print(f"  [red]✗[/red] {title} - echec API")

                progress.update(task, advance=1)
                await _asyncio.sleep(0.15)

    console.print("\n[bold]Resume:[/bold]")
    console.print(f"  [green]{enriched}[/green] avec collection")
    console.print(f"  [dim]{no_collection}[/dim] sans collection")
    if failed > 0:
        console.print(f"  [red]{failed}[/red] echec(s) API")

    await tmdb_client.close()
