"""
Service d'enrichissement des notes TMDB pour les films existants.

Ce service permet de recuperer les notes (vote_average, vote_count) depuis TMDB
pour les films qui n'ont pas encore ces informations en base.
"""

import asyncio
from dataclasses import dataclass

from src.core.entities.media import Movie
from src.core.ports.api_clients import IMediaAPIClient
from src.core.ports.repositories import IMovieRepository


@dataclass
class EnrichmentStats:
    """Statistiques d'enrichissement des notes."""

    total: int = 0
    enriched: int = 0
    failed: int = 0
    skipped: int = 0


class RatingsEnricherService:
    """
    Service pour enrichir les notes TMDB des films existants.

    Recupere vote_average et vote_count depuis l'API TMDB pour les films
    qui n'ont pas ces informations en base.
    """

    def __init__(
        self,
        movie_repo: IMovieRepository,
        tmdb_client: IMediaAPIClient,
    ) -> None:
        """
        Initialise le service d'enrichissement.

        Args:
            movie_repo: Repository des films
            tmdb_client: Client API TMDB
        """
        self._movie_repo = movie_repo
        self._tmdb_client = tmdb_client

    async def enrich_ratings(
        self,
        limit: int = 100,
        rate_limit_seconds: float = 0.25,
    ) -> EnrichmentStats:
        """
        Enrichit les notes TMDB pour les films sans notes.

        Args:
            limit: Nombre maximum de films a enrichir
            rate_limit_seconds: Delai entre les appels API (rate limiting)

        Returns:
            Statistiques d'enrichissement
        """
        stats = EnrichmentStats()

        # Recuperer les films sans notes
        movies = self._movie_repo.list_without_ratings(limit)
        stats.total = len(movies)

        for i, movie in enumerate(movies):
            # Rate limiting (sauf premier appel)
            if i > 0 and rate_limit_seconds > 0:
                await asyncio.sleep(rate_limit_seconds)

            # Recuperer les details depuis TMDB
            if movie.tmdb_id is None:
                stats.skipped += 1
                continue

            details = await self._tmdb_client.get_details(str(movie.tmdb_id))

            if details is None:
                stats.failed += 1
                continue

            # Mettre a jour le film avec les notes
            movie.vote_average = details.vote_average
            movie.vote_count = details.vote_count

            # Sauvegarder
            self._movie_repo.save(movie)
            stats.enriched += 1

        return stats
