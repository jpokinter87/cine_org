"""
Tests pour SeriesEnricherService.

Verifie l'enrichissement TMDB des series TV, en particulier la lecture
des notes IMDb depuis le cache local apres recuperation de l'imdb_id.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.entities.media import Series
from src.core.ports.api_clients import MediaDetails
from src.services.series_enricher import (
    EnrichmentResult,
    SeriesEnricherService,
)


@pytest.fixture
def mock_series_repo():
    """Mock du repository series (save renvoie l'entite passee)."""
    repo = MagicMock()
    repo.save.side_effect = lambda s: s
    return repo


@pytest.fixture
def mock_tmdb_client():
    """Mock TMDB avec methodes async usuelles."""
    client = AsyncMock()
    return client


@pytest.fixture
def mock_imdb_importer():
    """Mock du IMDbDatasetImporter (cache local)."""
    importer = MagicMock()
    importer.get_rating.return_value = None
    return importer


def _tmdb_search_result(id_: str, title: str, year: int):
    """Construit un SearchResult minimal compatible avec _pick_best_match."""
    obj = MagicMock()
    obj.id = id_
    obj.title = title
    obj.original_title = None
    obj.year = year
    return obj


class TestSeriesEnricherWithIMDbCache:
    """Verifie la passe IMDb (cache local) apres recuperation de l'imdb_id."""

    @pytest.mark.asyncio
    async def test_imdb_rating_populated_when_importer_returns_rating(
        self, mock_series_repo, mock_tmdb_client, mock_imdb_importer
    ):
        """Quand imdb_id est trouve et que le cache IMDb a une note, on la persiste."""
        # Setup serie
        series = Series(id="42", title="Forever", year=1996, tvdb_id=12345)

        # TMDB search → 1 resultat exact
        mock_tmdb_client.search_tv.return_value = [
            _tmdb_search_result("99", "Forever", 1996)
        ]
        # TMDB details
        mock_tmdb_client.get_tv_details.return_value = MediaDetails(
            id="99",
            title="Forever",
            year=1996,
            vote_average=7.8,
            vote_count=1500,
            is_tv=True,
        )
        # External IDs : imdb_id present
        mock_tmdb_client.get_tv_external_ids.return_value = {"imdb_id": "tt0123456"}
        # IMDb cache local : note disponible
        mock_imdb_importer.get_rating.return_value = (8.2, 9876)

        service = SeriesEnricherService(
            series_repo=mock_series_repo,
            tmdb_client=mock_tmdb_client,
            imdb_importer=mock_imdb_importer,
        )

        stats = await service.enrich_series([series], rate_limit_seconds=0)

        assert stats.enriched == 1
        # Le repo a recu une serie avec imdb_rating + imdb_votes peuples
        saved = mock_series_repo.save.call_args[0][0]
        assert saved.imdb_id == "tt0123456"
        assert saved.imdb_rating == 8.2
        assert saved.imdb_votes == 9876
        assert saved.vote_average == 7.8
        assert saved.vote_count == 1500
        mock_imdb_importer.get_rating.assert_called_once_with("tt0123456")

    @pytest.mark.asyncio
    async def test_no_imdb_importer_keeps_existing_behavior(
        self, mock_series_repo, mock_tmdb_client
    ):
        """Sans importer fourni, le service ne lit pas de cache IMDb (compat)."""
        series = Series(id="1", title="Lost", year=2004, tvdb_id=10)
        mock_tmdb_client.search_tv.return_value = [
            _tmdb_search_result("88", "Lost", 2004)
        ]
        mock_tmdb_client.get_tv_details.return_value = MediaDetails(
            id="88", title="Lost", year=2004, vote_average=8.4, is_tv=True
        )
        mock_tmdb_client.get_tv_external_ids.return_value = {"imdb_id": "tt0411008"}

        service = SeriesEnricherService(
            series_repo=mock_series_repo,
            tmdb_client=mock_tmdb_client,
            # imdb_importer omis volontairement
        )
        stats = await service.enrich_series([series], rate_limit_seconds=0)

        assert stats.enriched == 1
        saved = mock_series_repo.save.call_args[0][0]
        # imdb_id est toujours peuple, mais note IMDb reste None
        assert saved.imdb_id == "tt0411008"
        assert saved.imdb_rating is None
        assert saved.imdb_votes is None

    @pytest.mark.asyncio
    async def test_imdb_cache_miss_leaves_ratings_none(
        self, mock_series_repo, mock_tmdb_client, mock_imdb_importer
    ):
        """Si get_rating renvoie None, on n'ecrase pas avec des None erratiques."""
        series = Series(id="3", title="Forever", year=1996, tvdb_id=12345)
        mock_tmdb_client.search_tv.return_value = [
            _tmdb_search_result("99", "Forever", 1996)
        ]
        mock_tmdb_client.get_tv_details.return_value = MediaDetails(
            id="99", title="Forever", year=1996, vote_average=7.8, is_tv=True
        )
        mock_tmdb_client.get_tv_external_ids.return_value = {"imdb_id": "tt0000001"}
        mock_imdb_importer.get_rating.return_value = None

        service = SeriesEnricherService(
            series_repo=mock_series_repo,
            tmdb_client=mock_tmdb_client,
            imdb_importer=mock_imdb_importer,
        )
        stats = await service.enrich_series([series], rate_limit_seconds=0)

        assert stats.enriched == 1
        saved = mock_series_repo.save.call_args[0][0]
        assert saved.imdb_id == "tt0000001"
        assert saved.imdb_rating is None
        assert saved.imdb_votes is None

    @pytest.mark.asyncio
    async def test_imdb_rating_skipped_when_no_imdb_id(
        self, mock_series_repo, mock_tmdb_client, mock_imdb_importer
    ):
        """Pas d'imdb_id externe → on n'appelle pas le cache IMDb."""
        series = Series(id="9", title="Mystery", year=2018, tvdb_id=77)
        mock_tmdb_client.search_tv.return_value = [
            _tmdb_search_result("77", "Mystery", 2018)
        ]
        mock_tmdb_client.get_tv_details.return_value = MediaDetails(
            id="77", title="Mystery", year=2018, vote_average=6.5, is_tv=True
        )
        mock_tmdb_client.get_tv_external_ids.return_value = {"imdb_id": None}

        service = SeriesEnricherService(
            series_repo=mock_series_repo,
            tmdb_client=mock_tmdb_client,
            imdb_importer=mock_imdb_importer,
        )
        stats = await service.enrich_series([series], rate_limit_seconds=0)

        assert stats.enriched == 1
        mock_imdb_importer.get_rating.assert_not_called()

    @pytest.mark.asyncio
    async def test_existing_imdb_id_still_triggers_cache_lookup(
        self, mock_series_repo, mock_tmdb_client, mock_imdb_importer
    ):
        """Si la serie a deja un imdb_id mais pas de note IMDb, on lit le cache."""
        series = Series(
            id="11",
            title="Suits",
            year=2011,
            tvdb_id=42,
            imdb_id="tt1632701",
            imdb_rating=None,
        )
        mock_tmdb_client.search_tv.return_value = [
            _tmdb_search_result("100", "Suits", 2011)
        ]
        mock_tmdb_client.get_tv_details.return_value = MediaDetails(
            id="100", title="Suits", year=2011, vote_average=8.5, is_tv=True
        )
        # get_tv_external_ids ne sera pas force a etre appele car imdb_id existe deja,
        # mais on tolere les deux cas
        mock_tmdb_client.get_tv_external_ids.return_value = {"imdb_id": "tt1632701"}
        mock_imdb_importer.get_rating.return_value = (8.4, 50000)

        service = SeriesEnricherService(
            series_repo=mock_series_repo,
            tmdb_client=mock_tmdb_client,
            imdb_importer=mock_imdb_importer,
        )
        stats = await service.enrich_series([series], rate_limit_seconds=0)

        assert stats.enriched == 1
        saved = mock_series_repo.save.call_args[0][0]
        assert saved.imdb_rating == 8.4
        assert saved.imdb_votes == 50000
        mock_imdb_importer.get_rating.assert_called_once_with("tt1632701")
