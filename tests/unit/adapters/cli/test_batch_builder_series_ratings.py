"""
Tests pour l'enrichissement notes des nouvelles series via batch_builder.

Verifie que le helper _enrich_series_metadata recupere proprement
tmdb_id + vote_average + vote_count + imdb_id + imdb_rating + imdb_votes
en chainant search_tv → get_tv_details → get_tv_external_ids → cache IMDb.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.cli.batch_builder import _enrich_series_metadata
from src.core.ports.api_clients import MediaDetails


def _search_result(id_: str, title: str, year: int):
    obj = MagicMock()
    obj.id = id_
    obj.title = title
    obj.original_title = None
    obj.year = year
    return obj


def _container_with_imdb_cache(rating_table: dict[str, tuple[float, int]]):
    """Construit un container minimal exposant session() pour IMDbDatasetImporter."""
    fake_importer = MagicMock()
    fake_importer.get_rating.side_effect = lambda imdb_id: rating_table.get(imdb_id)
    # Par defaut, le repli par titre ne trouve rien (teste a part).
    fake_importer.find_tconst_by_title.return_value = None

    container = MagicMock()
    container.session.return_value = (
        MagicMock()
    )  # session reelle non utilisee par le mock
    return container, fake_importer


@pytest.mark.asyncio
async def test_enrich_series_returns_full_tuple_when_all_data_available(monkeypatch):
    """Cas nominal : titre+annee unique, TMDB renvoie note + imdb_id, cache IMDb a la note."""
    tmdb = AsyncMock()
    tmdb._api_key = "fake-key"
    tmdb.search_tv.return_value = [_search_result("99", "Forever", 1996)]
    tmdb.get_tv_details.return_value = MediaDetails(
        id="99",
        title="Forever",
        year=1996,
        vote_average=7.8,
        vote_count=1500,
        is_tv=True,
    )
    tmdb.get_tv_external_ids.return_value = {"imdb_id": "tt0123456"}

    container, fake_importer = _container_with_imdb_cache({"tt0123456": (8.2, 9876)})

    # Patch IMDbDatasetImporter pour qu'il retourne notre fake quand instancie
    monkeypatch.setattr(
        "src.adapters.imdb.dataset_importer.IMDbDatasetImporter",
        lambda **kwargs: fake_importer,
    )

    result = await _enrich_series_metadata(
        title="Forever",
        year=1996,
        tmdb_client=tmdb,
        container=container,
    )

    assert result == (99, 7.8, 1500, "tt0123456", 8.2, 9876)


@pytest.mark.asyncio
async def test_enrich_series_returns_none_when_no_search_result():
    """Aucun match TMDB → tuple de None."""
    tmdb = AsyncMock()
    tmdb._api_key = "fake-key"
    tmdb.search_tv.return_value = []
    container = MagicMock()

    result = await _enrich_series_metadata(
        title="Inconnue Quelconque",
        year=2050,
        tmdb_client=tmdb,
        container=container,
    )
    assert result == (None, None, None, None, None, None)


@pytest.mark.asyncio
async def test_enrich_series_handles_missing_imdb_id(monkeypatch):
    """Si TMDB n'a pas d'imdb_id, on conserve les notes TMDB et on saute le cache IMDb."""
    tmdb = AsyncMock()
    tmdb._api_key = "fake-key"
    tmdb.search_tv.return_value = [_search_result("88", "Mystery", 2020)]
    tmdb.get_tv_details.return_value = MediaDetails(
        id="88",
        title="Mystery",
        year=2020,
        vote_average=6.5,
        vote_count=200,
        is_tv=True,
    )
    tmdb.get_tv_external_ids.return_value = {"imdb_id": None}

    container, fake_importer = _container_with_imdb_cache({})
    monkeypatch.setattr(
        "src.adapters.imdb.dataset_importer.IMDbDatasetImporter",
        lambda **kwargs: fake_importer,
    )

    result = await _enrich_series_metadata(
        title="Mystery",
        year=2020,
        tmdb_client=tmdb,
        container=container,
    )
    assert result == (88, 6.5, 200, None, None, None)
    fake_importer.get_rating.assert_not_called()


@pytest.mark.asyncio
async def test_enrich_series_swallows_api_errors():
    """Toute exception API renvoie un tuple None plutot que d'interrompre le workflow."""
    tmdb = AsyncMock()
    tmdb._api_key = "fake-key"
    tmdb.search_tv.side_effect = RuntimeError("TMDB indispo")
    container = MagicMock()

    result = await _enrich_series_metadata(
        title="Whatever",
        year=2024,
        tmdb_client=tmdb,
        container=container,
    )
    assert result == (None, None, None, None, None, None)


@pytest.mark.asyncio
async def test_enrich_series_no_api_key_returns_none():
    """Sans cle API, on ne touche pas a TMDB."""
    tmdb = AsyncMock()
    tmdb._api_key = None
    container = MagicMock()

    result = await _enrich_series_metadata(
        title="Whatever",
        year=2024,
        tmdb_client=tmdb,
        container=container,
    )
    assert result == (None, None, None, None, None, None)
    tmdb.search_tv.assert_not_called()
