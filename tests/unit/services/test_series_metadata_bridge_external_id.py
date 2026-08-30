"""Tests : le pont d'ingestion resout TMDB par tvdb_id quand le titre echoue.

Regression « Les Detectoristes » : titre francais non matchable par search_tv,
mais resolvable via le tvdb_id (TMDB /find).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.adapters.cli.batch_builder import _enrich_series_metadata


@pytest.mark.asyncio
async def test_enrich_series_metadata_resout_par_tvdb_id_quand_titre_echoue():
    """Quand search_tv echoue, le tvdb_id permet de recuperer la note."""
    tmdb_client = MagicMock()
    tmdb_client._api_key = "fake_key"
    # Le titre francais ne matche aucun resultat TMDB...
    tmdb_client.search_tv = AsyncMock(return_value=[])
    # ...mais le tvdb_id resout directement via /find.
    tmdb_client.find_by_external_id = AsyncMock(return_value=[MagicMock(id="61828")])
    tmdb_client.get_tv_details = AsyncMock(
        return_value=MagicMock(vote_average=8.1, vote_count=176),
    )
    tmdb_client.get_tv_external_ids = AsyncMock(
        return_value={"imdb_id": "tt4082744"},
    )

    container = MagicMock()
    container.session = MagicMock()

    with patch(
        "src.adapters.imdb.dataset_importer.IMDbDatasetImporter"
    ) as mock_importer_cls:
        mock_importer = MagicMock()
        mock_importer.get_rating = MagicMock(return_value=(8.6, 25000))
        mock_importer_cls.return_value = mock_importer

        result = await _enrich_series_metadata(
            title="Les Détectoristes",
            year=2014,
            tmdb_client=tmdb_client,
            container=container,
            tvdb_id=280847,
        )

    tmdb_id, vote_avg, vote_count, imdb_id, imdb_rating, imdb_votes = result
    assert tmdb_id == 61828
    assert vote_avg == 8.1
    assert vote_count == 176
    assert imdb_id == "tt4082744"
    assert imdb_rating == 8.6
    assert imdb_votes == 25000
    tmdb_client.find_by_external_id.assert_awaited_once_with("280847", "tvdb_id")
    tmdb_client.search_tv.assert_not_called()
