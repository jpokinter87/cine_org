"""Test de TVDBClient.find_series_id_by_imdb_id (resolution par IMDb ID)."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from src.adapters.api.cache import APICache
from src.adapters.api.tvdb_client import TVDBClient
from tests.fixtures.tvdb_responses import (
    TVDB_LOGIN_RESPONSE,
    TVDB_NOT_FOUND_RESPONSE,
    TVDB_REMOTE_ID_EMPTY_RESPONSE,
    TVDB_REMOTE_ID_RESPONSE,
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


@pytest.mark.asyncio
@respx.mock
async def test_find_series_id_by_imdb_id_returns_first_match(mock_cache) -> None:
    """Retourne l'ID TVDB de la premiere serie correspondante."""
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
    )
    route = respx.get(f"{BASE}/search/remoteid/tt0903747").mock(
        return_value=httpx.Response(200, json=TVDB_REMOTE_ID_RESPONSE)
    )

    client = TVDBClient(api_key="x", cache=mock_cache)
    try:
        assert await client.find_series_id_by_imdb_id("tt0903747") == "81189"
        assert route.called
    finally:
        await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_find_series_id_by_imdb_id_returns_none_on_404(mock_cache) -> None:
    """TVDB repond 404 quand aucune serie ne correspond."""
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
    )
    respx.get(f"{BASE}/search/remoteid/tt0000000").mock(
        return_value=httpx.Response(404, json=TVDB_NOT_FOUND_RESPONSE)
    )

    client = TVDBClient(api_key="x", cache=mock_cache)
    try:
        assert await client.find_series_id_by_imdb_id("tt0000000") is None
    finally:
        await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_find_series_id_by_imdb_id_returns_none_on_empty_data(
    mock_cache,
) -> None:
    """Une reponse sans donnees retourne None."""
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
    )
    respx.get(f"{BASE}/search/remoteid/tt0000000").mock(
        return_value=httpx.Response(200, json=TVDB_REMOTE_ID_EMPTY_RESPONSE)
    )

    client = TVDBClient(api_key="x", cache=mock_cache)
    try:
        assert await client.find_series_id_by_imdb_id("tt0000000") is None
    finally:
        await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_find_series_id_ignores_non_series_matches(mock_cache) -> None:
    """Un remote id resolvant vers un film (pas une serie) retourne None."""
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
    )
    respx.get(f"{BASE}/search/remoteid/tt1234567").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "success",
                "data": [{"movie": {"id": 555, "name": "Un film"}}],
            },
        )
    )

    client = TVDBClient(api_key="x", cache=mock_cache)
    try:
        assert await client.find_series_id_by_imdb_id("tt1234567") is None
    finally:
        await client.close()
