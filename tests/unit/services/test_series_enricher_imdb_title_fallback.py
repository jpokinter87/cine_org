"""Test : repli IMDb par titre quand TMDB ne fournit pas d'imdb_id.

Cas « Félix, Maude et la fin du monde » : TMDB connaît la série mais sans
imdb_id ni note. Le tconst est retrouvé via imdb_akas (find_tconst_by_title),
puis la note IMDb est lue dans le cache local.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.core.entities.media import Series
from src.core.ports.api_clients import SearchResult
from src.services.series_enricher import EnrichmentResult, SeriesEnricherService


@pytest.mark.asyncio
async def test_repli_imdb_par_titre_quand_tmdb_sans_imdb_id():
    """Sans imdb_id côté TMDB, on retrouve le tconst via le titre puis la note."""
    tmdb_client = MagicMock()
    tmdb_client.find_by_external_id = AsyncMock(
        return_value=[SearchResult(id="108687", title="Félix, Maude...", year=2021)]
    )
    tmdb_client.search_tv = AsyncMock(return_value=[])
    tmdb_client.get_tv_details = AsyncMock(
        return_value=MagicMock(
            vote_average=0.0,
            vote_count=0,
            poster_url=None,
            genres=(),
            overview=None,
            original_title=None,
            director=None,
            cast=(),
        )
    )
    # TMDB ne fournit aucun imdb_id pour cette série québécoise.
    tmdb_client.get_tv_external_ids = AsyncMock(return_value={"imdb_id": None})

    importer = MagicMock()
    importer.find_tconst_by_title = MagicMock(return_value="tt14131062")
    importer.get_rating = MagicMock(return_value=(7.2, 34))

    series_repo = MagicMock()
    series = Series(
        title="Félix, Maude et la fin du monde", year=2021, tvdb_id=399037, id="259"
    )

    service = SeriesEnricherService(
        series_repo=series_repo,
        tmdb_client=tmdb_client,
        imdb_importer=importer,
    )

    result = await service._enrich_one(series)

    assert result == EnrichmentResult.SUCCESS
    assert series.imdb_id == "tt14131062"
    assert series.imdb_rating == 7.2
    assert series.imdb_votes == 34
    importer.find_tconst_by_title.assert_called_once_with(
        "Félix, Maude et la fin du monde"
    )
    importer.get_rating.assert_called_once_with("tt14131062")


@pytest.mark.asyncio
async def test_pas_de_repli_si_tmdb_fournit_imdb_id():
    """Si TMDB donne déjà un imdb_id, on n'interroge pas imdb_akas."""
    tmdb_client = MagicMock()
    tmdb_client.find_by_external_id = AsyncMock(
        return_value=[SearchResult(id="100", title="X", year=2020)]
    )
    tmdb_client.search_tv = AsyncMock(return_value=[])
    tmdb_client.get_tv_details = AsyncMock(
        return_value=MagicMock(
            vote_average=8.0,
            vote_count=10,
            poster_url=None,
            genres=(),
            overview=None,
            original_title=None,
            director=None,
            cast=(),
        )
    )
    tmdb_client.get_tv_external_ids = AsyncMock(return_value={"imdb_id": "tt0001"})

    importer = MagicMock()
    importer.find_tconst_by_title = MagicMock(return_value="tt9999999")
    importer.get_rating = MagicMock(return_value=(8.1, 500))

    series_repo = MagicMock()
    series = Series(title="X", year=2020, tvdb_id=1, id="1")

    service = SeriesEnricherService(
        series_repo=series_repo, tmdb_client=tmdb_client, imdb_importer=importer
    )

    await service._enrich_one(series)

    assert series.imdb_id == "tt0001"
    importer.find_tconst_by_title.assert_not_called()
