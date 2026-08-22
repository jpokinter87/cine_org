"""Test de TVDBClient.get_all_episodes (agregation de toutes les saisons)."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from src.adapters.api.cache import APICache
from src.adapters.api.tvdb_client import TVDBClient
from tests.fixtures.tvdb_responses import (
    TVDB_LOGIN_RESPONSE,
    TVDB_NOT_FOUND_RESPONSE,
    TVDB_SERIES_EPISODES_ENG_RESPONSE,
    TVDB_SERIES_EPISODES_FRA_RESPONSE,
)

BASE = "https://api4.thetvdb.com/v4"


@pytest.fixture
def mock_cache() -> MagicMock:
    """APICache simule."""
    cache = MagicMock(spec=APICache)
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.set_search = AsyncMock()
    cache.set_details = AsyncMock()
    return cache


def _mock_series(series_id: int = 81189) -> None:
    """Simule le login et les deux endpoints d'episodes traduits."""
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
    )
    respx.get(f"{BASE}/series/{series_id}/episodes/default/fra").mock(
        return_value=httpx.Response(200, json=TVDB_SERIES_EPISODES_FRA_RESPONSE)
    )
    respx.get(f"{BASE}/series/{series_id}/episodes/default/eng").mock(
        return_value=httpx.Response(200, json=TVDB_SERIES_EPISODES_ENG_RESPONSE)
    )


@pytest.mark.asyncio
@respx.mock
async def test_get_all_episodes_aggregates_seasons(mock_cache) -> None:
    """Agrege les episodes de toutes les saisons en une seule liste."""
    _mock_series()

    client = TVDBClient(api_key="x", cache=mock_cache)
    try:
        episodes = await client.get_all_episodes("81189")

        assert len(episodes) == 20  # 7 (S1) + 13 (S2), specials exclus
        keys = {(e.season_number, e.episode_number) for e in episodes}
        assert (1, 1) in keys
        assert (2, 13) in keys

        by_key = {(e.season_number, e.episode_number): e for e in episodes}
        assert by_key[(1, 1)].title == "Chute libre"
        assert by_key[(1, 1)].air_date == "2008-01-20"
    finally:
        await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_get_all_episodes_excludes_specials(mock_cache) -> None:
    """La saison 0 (specials) est exclue, comme le faisait la v3."""
    _mock_series()

    client = TVDBClient(api_key="x", cache=mock_cache)
    try:
        episodes = await client.get_all_episodes("81189")

        assert all(e.season_number != 0 for e in episodes)
    finally:
        await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_get_all_episodes_falls_back_to_english_title(mock_cache) -> None:
    """Un episode sans titre francais reprend le titre anglais."""
    _mock_series()

    client = TVDBClient(api_key="x", cache=mock_cache)
    try:
        episodes = await client.get_all_episodes("81189")

        by_key = {(e.season_number, e.episode_number): e for e in episodes}
        assert by_key[(1, 7)].title == "English title 7"
    finally:
        await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_get_all_episodes_returns_empty_on_404(mock_cache) -> None:
    """Une serie inconnue retourne une liste vide."""
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
    )
    respx.get(f"{BASE}/series/999999/episodes/default/fra").mock(
        return_value=httpx.Response(404, json=TVDB_NOT_FOUND_RESPONSE)
    )
    respx.get(f"{BASE}/series/999999/episodes/default/eng").mock(
        return_value=httpx.Response(404, json=TVDB_NOT_FOUND_RESPONSE)
    )

    client = TVDBClient(api_key="x", cache=mock_cache)
    try:
        assert await client.get_all_episodes("999999") == []
    finally:
        await client.close()
