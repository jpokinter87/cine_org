"""Tests : SeriesEnricherService resout TMDB par tvdb_id avant la recherche titre.

Permet a `enrich-series` de rattraper les fiches au titre traduit (ex: « Les
Detectoristes ») en s'appuyant sur le tvdb_id deja en base.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.core.entities.media import Series
from src.core.ports.api_clients import SearchResult
from src.services.series_enricher import EnrichmentResult, SeriesEnricherService


@pytest.mark.asyncio
async def test_enrich_one_resout_par_tvdb_id_sans_recherche_titre():
    """Une serie au titre traduit est enrichie via son tvdb_id."""
    tmdb_client = MagicMock()
    tmdb_client.find_by_external_id = AsyncMock(
        return_value=[SearchResult(id="61828", title="Detectorists", year=2014)]
    )
    tmdb_client.search_tv = AsyncMock(return_value=[])
    tmdb_client.get_tv_details = AsyncMock(
        return_value=MagicMock(
            vote_average=8.1,
            vote_count=176,
            poster_url="http://poster",
            genres=("Comédie",),
            overview="Deux passionnés de détecteurs de métaux.",
            original_title="Detectorists",
            director="Mackenzie Crook",
            cast=("Mackenzie Crook",),
        )
    )
    tmdb_client.get_tv_external_ids = AsyncMock(return_value={"imdb_id": "tt4082744"})

    series_repo = MagicMock()
    series = Series(
        title="Les Détectoristes",
        year=2014,
        tvdb_id=280847,
        id="1027",
    )

    service = SeriesEnricherService(
        series_repo=series_repo,
        tmdb_client=tmdb_client,
    )

    result = await service._enrich_one(series)

    assert result == EnrichmentResult.SUCCESS
    assert series.tmdb_id == 61828
    assert series.vote_average == 8.1
    assert series.vote_count == 176
    assert series.imdb_id == "tt4082744"
    tmdb_client.find_by_external_id.assert_awaited_once_with("280847", "tvdb_id")
    tmdb_client.search_tv.assert_not_called()
    series_repo.save.assert_called_once()


@pytest.mark.asyncio
async def test_enrich_one_repli_recherche_titre_sans_identifiant_externe():
    """Sans tvdb_id ni imdb_id, on retombe sur la recherche par titre normalise."""
    tmdb_client = MagicMock()
    tmdb_client.find_by_external_id = AsyncMock(return_value=[])
    tmdb_client.search_tv = AsyncMock(
        return_value=[SearchResult(id="78903", title="Utopia", year=2020)]
    )
    tmdb_client.get_tv_details = AsyncMock(
        return_value=MagicMock(
            vote_average=7.2,
            vote_count=473,
            poster_url=None,
            genres=(),
            overview=None,
            original_title=None,
            director=None,
            cast=(),
        )
    )
    tmdb_client.get_tv_external_ids = AsyncMock(return_value={"imdb_id": "tt8303474"})

    series_repo = MagicMock()
    # Titre embarquant l'annee : doit etre normalise avant la recherche.
    series = Series(title="Utopia (2020)", year=2020, id="1101")

    service = SeriesEnricherService(
        series_repo=series_repo,
        tmdb_client=tmdb_client,
    )

    result = await service._enrich_one(series)

    assert result == EnrichmentResult.SUCCESS
    assert series.tmdb_id == 78903
    assert series.vote_average == 7.2
    # La recherche titre doit utiliser le titre normalise « Utopia ».
    tmdb_client.search_tv.assert_awaited_once_with("Utopia", year=2020)
