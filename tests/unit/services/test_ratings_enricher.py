"""
Tests pour RatingsEnricherService.

Verifie l'enrichissement des notes TMDB pour les films existants en base.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.entities.media import Movie
from src.core.ports.api_clients import MediaDetails
from src.services.ratings_enricher import RatingsEnricherService, EnrichmentStats


class TestRatingsEnricherService:
    """Tests pour RatingsEnricherService."""

    @pytest.fixture
    def mock_movie_repository(self):
        """Mock pour le repository des films."""
        repo = MagicMock()
        repo.list_without_ratings.return_value = []
        return repo

    @pytest.fixture
    def mock_tmdb_client(self):
        """Mock pour le client TMDB."""
        client = AsyncMock()
        return client

    @pytest.fixture
    def service(self, mock_movie_repository, mock_tmdb_client):
        """Service RatingsEnricher avec mocks."""
        return RatingsEnricherService(
            movie_repo=mock_movie_repository,
            tmdb_client=mock_tmdb_client,
        )

    @pytest.mark.asyncio
    async def test_enrich_ratings_empty_database(self, service, mock_movie_repository):
        """Ne devrait rien faire si aucun film sans notes."""
        mock_movie_repository.list_without_ratings.return_value = []

        stats = await service.enrich_ratings(limit=10)

        assert stats.total == 0
        assert stats.enriched == 0
        assert stats.failed == 0

    @pytest.mark.asyncio
    async def test_enrich_ratings_with_movies(
        self, service, mock_movie_repository, mock_tmdb_client
    ):
        """Devrait enrichir les films sans notes."""
        # Setup: 2 films sans notes
        movie1 = Movie(id="1", tmdb_id=19995, title="Avatar", year=2009)
        movie2 = Movie(id="2", tmdb_id=27205, title="Inception", year=2010)
        mock_movie_repository.list_without_ratings.return_value = [movie1, movie2]

        # Setup: TMDB retourne les notes
        mock_tmdb_client.get_details.side_effect = [
            MediaDetails(
                id="19995",
                title="Avatar",
                year=2009,
                vote_average=7.6,
                vote_count=27000,
            ),
            MediaDetails(
                id="27205",
                title="Inception",
                year=2010,
                vote_average=8.4,
                vote_count=32000,
            ),
        ]

        stats = await service.enrich_ratings(limit=10)

        # Verifie les stats
        assert stats.total == 2
        assert stats.enriched == 2
        assert stats.failed == 0

        # Verifie que save a ete appele pour chaque film
        assert mock_movie_repository.save.call_count == 2

    @pytest.mark.asyncio
    async def test_enrich_ratings_respects_limit(
        self, service, mock_movie_repository, mock_tmdb_client
    ):
        """Devrait respecter la limite de films a enrichir."""
        # Setup: 5 films sans notes
        movies = [
            Movie(id=str(i), tmdb_id=i, title=f"Film {i}", year=2020)
            for i in range(1, 6)
        ]
        mock_movie_repository.list_without_ratings.return_value = movies[:2]  # Limit=2

        # Setup: TMDB retourne les notes
        mock_tmdb_client.get_details.return_value = MediaDetails(
            id="1",
            title="Film",
            vote_average=7.0,
            vote_count=1000,
        )

        stats = await service.enrich_ratings(limit=2)

        assert stats.total == 2
        assert mock_movie_repository.list_without_ratings.call_args[0][0] == 2

    @pytest.mark.asyncio
    async def test_enrich_ratings_handles_api_failure(
        self, service, mock_movie_repository, mock_tmdb_client
    ):
        """Devrait gerer les erreurs API gracieusement."""
        # Setup: 1 film sans notes
        movie = Movie(id="1", tmdb_id=19995, title="Avatar", year=2009)
        mock_movie_repository.list_without_ratings.return_value = [movie]

        # Setup: TMDB retourne None (erreur)
        mock_tmdb_client.get_details.return_value = None

        stats = await service.enrich_ratings(limit=10)

        assert stats.total == 1
        assert stats.enriched == 0
        assert stats.failed == 1

    @pytest.mark.asyncio
    async def test_enrich_ratings_updates_movie_with_votes(
        self, service, mock_movie_repository, mock_tmdb_client
    ):
        """Devrait mettre a jour le film avec les notes TMDB."""
        # Setup: 1 film sans notes
        movie = Movie(id="1", tmdb_id=19995, title="Avatar", year=2009)
        mock_movie_repository.list_without_ratings.return_value = [movie]

        # Setup: TMDB retourne les notes
        mock_tmdb_client.get_details.return_value = MediaDetails(
            id="19995",
            title="Avatar",
            year=2009,
            vote_average=7.6,
            vote_count=27000,
        )

        await service.enrich_ratings(limit=10)

        # Verifie que le film sauvegarde a les notes
        saved_movie = mock_movie_repository.save.call_args[0][0]
        assert saved_movie.vote_average == 7.6
        assert saved_movie.vote_count == 27000

    @pytest.mark.asyncio
    async def test_enrich_ratings_with_rate_limiting(
        self, service, mock_movie_repository, mock_tmdb_client
    ):
        """Devrait appliquer le rate limiting entre les appels."""
        import time

        # Setup: 2 films sans notes
        movies = [
            Movie(id="1", tmdb_id=19995, title="Avatar", year=2009),
            Movie(id="2", tmdb_id=27205, title="Inception", year=2010),
        ]
        mock_movie_repository.list_without_ratings.return_value = movies

        mock_tmdb_client.get_details.return_value = MediaDetails(
            id="1",
            title="Film",
            vote_average=7.0,
            vote_count=1000,
        )

        start = time.time()
        await service.enrich_ratings(limit=10, rate_limit_seconds=0.1)
        duration = time.time() - start

        # Au moins 0.1 seconde entre les 2 appels
        # (tolerance de 0.05s pour les fluctuations)
        assert duration >= 0.1


class TestEnrichmentStats:
    """Tests pour la dataclass EnrichmentStats."""

    def test_stats_creation(self):
        """Devrait creer des stats avec les valeurs par defaut."""
        stats = EnrichmentStats()
        assert stats.total == 0
        assert stats.enriched == 0
        assert stats.failed == 0
        assert stats.skipped == 0

    def test_stats_with_values(self):
        """Devrait creer des stats avec les valeurs fournies."""
        stats = EnrichmentStats(total=10, enriched=8, failed=1, skipped=1)
        assert stats.total == 10
        assert stats.enriched == 8
        assert stats.failed == 1
        assert stats.skipped == 1
