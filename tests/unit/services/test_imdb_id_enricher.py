"""
Tests pour ImdbIdEnricherService.

Verifie l'enrichissement des imdb_id via l'API TMDB pour les films existants en base.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.entities.media import Movie
from src.services.imdb_id_enricher import ImdbIdEnricherService, EnrichmentStats


class TestImdbIdEnricherService:
    """Tests pour ImdbIdEnricherService."""

    @pytest.fixture
    def mock_movie_repository(self):
        """Mock pour le repository des films."""
        repo = MagicMock()
        repo.list_without_imdb_id.return_value = []
        return repo

    @pytest.fixture
    def mock_tmdb_client(self):
        """Mock pour le client TMDB."""
        client = AsyncMock()
        return client

    @pytest.fixture
    def service(self, mock_movie_repository, mock_tmdb_client):
        """Service ImdbIdEnricher avec mocks."""
        return ImdbIdEnricherService(
            movie_repo=mock_movie_repository,
            tmdb_client=mock_tmdb_client,
        )

    @pytest.mark.asyncio
    async def test_enrich_imdb_ids_empty_database(self, service, mock_movie_repository):
        """Ne devrait rien faire si aucun film sans imdb_id."""
        mock_movie_repository.list_without_imdb_id.return_value = []

        stats = await service.enrich_imdb_ids(limit=10)

        assert stats.total == 0
        assert stats.enriched == 0
        assert stats.failed == 0

    @pytest.mark.asyncio
    async def test_enrich_imdb_ids_with_movies(
        self, service, mock_movie_repository, mock_tmdb_client
    ):
        """Devrait enrichir les films sans imdb_id."""
        # Setup: 2 films sans imdb_id
        movie1 = Movie(id="1", tmdb_id=19995, title="Avatar", year=2009)
        movie2 = Movie(id="2", tmdb_id=27205, title="Inception", year=2010)
        mock_movie_repository.list_without_imdb_id.return_value = [movie1, movie2]

        # Setup: TMDB retourne les external_ids
        mock_tmdb_client.get_external_ids.side_effect = [
            {"imdb_id": "tt0499549", "wikidata_id": None},
            {"imdb_id": "tt1375666", "wikidata_id": None},
        ]

        stats = await service.enrich_imdb_ids(limit=10)

        # Verifie les stats
        assert stats.total == 2
        assert stats.enriched == 2
        assert stats.failed == 0

        # Verifie que save a ete appele pour chaque film
        assert mock_movie_repository.save.call_count == 2

    @pytest.mark.asyncio
    async def test_enrich_imdb_ids_respects_limit(
        self, service, mock_movie_repository, mock_tmdb_client
    ):
        """Devrait respecter la limite de films a enrichir."""
        # Setup: 5 films sans imdb_id
        movies = [
            Movie(id=str(i), tmdb_id=i, title=f"Film {i}", year=2020)
            for i in range(1, 6)
        ]
        mock_movie_repository.list_without_imdb_id.return_value = movies[:2]  # Limit=2

        # Setup: TMDB retourne les external_ids
        mock_tmdb_client.get_external_ids.return_value = {"imdb_id": "tt0000001"}

        stats = await service.enrich_imdb_ids(limit=2)

        assert stats.total == 2
        assert mock_movie_repository.list_without_imdb_id.call_args[0][0] == 2

    @pytest.mark.asyncio
    async def test_enrich_imdb_ids_handles_api_failure(
        self, service, mock_movie_repository, mock_tmdb_client
    ):
        """Devrait gerer les erreurs API gracieusement."""
        # Setup: 1 film sans imdb_id
        movie = Movie(id="1", tmdb_id=19995, title="Avatar", year=2009)
        mock_movie_repository.list_without_imdb_id.return_value = [movie]

        # Setup: TMDB retourne None (erreur)
        mock_tmdb_client.get_external_ids.return_value = None

        stats = await service.enrich_imdb_ids(limit=10)

        assert stats.total == 1
        assert stats.enriched == 0
        assert stats.failed == 1

    @pytest.mark.asyncio
    async def test_enrich_imdb_ids_handles_missing_imdb_id(
        self, service, mock_movie_repository, mock_tmdb_client
    ):
        """Devrait gerer le cas ou TMDB n'a pas d'imdb_id."""
        # Setup: 1 film sans imdb_id
        movie = Movie(id="1", tmdb_id=19995, title="Avatar", year=2009)
        mock_movie_repository.list_without_imdb_id.return_value = [movie]

        # Setup: TMDB retourne un dict sans imdb_id
        mock_tmdb_client.get_external_ids.return_value = {"imdb_id": None}

        stats = await service.enrich_imdb_ids(limit=10)

        assert stats.total == 1
        assert stats.enriched == 0
        assert stats.not_found == 1
        # save ne doit pas etre appele
        assert mock_movie_repository.save.call_count == 0

    @pytest.mark.asyncio
    async def test_enrich_imdb_ids_updates_movie_with_imdb_id(
        self, service, mock_movie_repository, mock_tmdb_client
    ):
        """Devrait mettre a jour le film avec l'imdb_id."""
        # Setup: 1 film sans imdb_id
        movie = Movie(id="1", tmdb_id=19995, title="Avatar", year=2009)
        mock_movie_repository.list_without_imdb_id.return_value = [movie]

        # Setup: TMDB retourne l'imdb_id
        mock_tmdb_client.get_external_ids.return_value = {"imdb_id": "tt0499549"}

        await service.enrich_imdb_ids(limit=10)

        # Verifie que le film sauvegarde a l'imdb_id
        saved_movie = mock_movie_repository.save.call_args[0][0]
        assert saved_movie.imdb_id == "tt0499549"

    @pytest.mark.asyncio
    async def test_enrich_imdb_ids_skips_without_tmdb_id(
        self, service, mock_movie_repository, mock_tmdb_client
    ):
        """Devrait ignorer les films sans tmdb_id."""
        # Setup: 1 film sans tmdb_id
        movie = Movie(id="1", tmdb_id=None, title="Film inconnu", year=2020)
        mock_movie_repository.list_without_imdb_id.return_value = [movie]

        stats = await service.enrich_imdb_ids(limit=10)

        assert stats.total == 1
        assert stats.skipped == 1
        # get_external_ids ne doit pas etre appele
        assert mock_tmdb_client.get_external_ids.call_count == 0

    @pytest.mark.asyncio
    async def test_enrich_imdb_ids_with_rate_limiting(
        self, service, mock_movie_repository, mock_tmdb_client
    ):
        """Devrait appliquer le rate limiting entre les appels."""
        import time

        # Setup: 2 films sans imdb_id
        movies = [
            Movie(id="1", tmdb_id=19995, title="Avatar", year=2009),
            Movie(id="2", tmdb_id=27205, title="Inception", year=2010),
        ]
        mock_movie_repository.list_without_imdb_id.return_value = movies

        mock_tmdb_client.get_external_ids.return_value = {"imdb_id": "tt0000001"}

        start = time.time()
        await service.enrich_imdb_ids(limit=10, rate_limit_seconds=0.1)
        duration = time.time() - start

        # Au moins 0.1 seconde entre les 2 appels
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
        assert stats.not_found == 0

    def test_stats_with_values(self):
        """Devrait creer des stats avec les valeurs fournies."""
        stats = EnrichmentStats(total=10, enriched=7, failed=1, skipped=1, not_found=1)
        assert stats.total == 10
        assert stats.enriched == 7
        assert stats.failed == 1
        assert stats.skipped == 1
        assert stats.not_found == 1
