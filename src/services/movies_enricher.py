"""
Service d'enrichissement des credits (realisateur, acteurs) pour les films existants.

Recupere director et cast depuis TMDB pour les films qui ont un tmdb_id
mais pas encore ces informations en base.
"""

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from src.core.entities.media import Movie
from src.core.ports.api_clients import IMediaAPIClient
from src.core.ports.repositories import IMovieRepository


class EnrichmentResult(str, Enum):
    """Resultat d'enrichissement pour un film."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ProgressInfo:
    """Information de progression pour le callback."""

    current: int
    total: int
    movie_title: str
    movie_year: Optional[int]
    result: EnrichmentResult


@dataclass
class MoviesEnrichmentStats:
    """Statistiques d'enrichissement des films."""

    total: int = 0
    enriched: int = 0
    failed: int = 0
    skipped: int = 0


class MoviesEnricherService:
    """
    Service pour enrichir les credits (realisateur, acteurs) des films existants.

    Recupere director et cast depuis TMDB pour les films qui ont un tmdb_id.
    """

    def __init__(
        self,
        movie_repo: IMovieRepository,
        tmdb_client: IMediaAPIClient,
    ) -> None:
        self._movie_repo = movie_repo
        self._tmdb_client = tmdb_client

    async def enrich_credits(
        self,
        movies: list[Movie],
        rate_limit_seconds: float = 0.25,
        on_progress: Optional[Callable[[ProgressInfo], None]] = None,
    ) -> MoviesEnrichmentStats:
        """
        Enrichit les credits pour une liste de films.

        Args:
            movies: Films a enrichir
            rate_limit_seconds: Delai entre les appels API
            on_progress: Callback de progression optionnel

        Returns:
            Statistiques d'enrichissement
        """
        stats = MoviesEnrichmentStats(total=len(movies))

        for i, movie in enumerate(movies):
            if i > 0 and rate_limit_seconds > 0:
                await asyncio.sleep(rate_limit_seconds)

            if movie.tmdb_id is None:
                stats.skipped += 1
                result = EnrichmentResult.SKIPPED
            else:
                details = await self._tmdb_client.get_details(str(movie.tmdb_id))
                if details is None:
                    stats.failed += 1
                    result = EnrichmentResult.FAILED
                else:
                    if details.director:
                        movie.director = details.director
                    if details.cast:
                        movie.cast = details.cast
                    # Enrichir aussi le poster si manquant
                    if not movie.poster_path and details.poster_url:
                        movie.poster_path = details.poster_url
                    self._movie_repo.save(movie)
                    stats.enriched += 1
                    result = EnrichmentResult.SUCCESS

            if on_progress:
                on_progress(ProgressInfo(
                    current=i + 1,
                    total=stats.total,
                    movie_title=movie.title,
                    movie_year=movie.year,
                    result=result,
                ))

        return stats
