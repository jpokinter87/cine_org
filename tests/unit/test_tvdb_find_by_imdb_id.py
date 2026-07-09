"""Test de TVDBClient.find_series_id_by_imdb_id (résolution par IMDb ID)."""

import httpx
import pytest

from src.adapters.api import tvdb_client as tvdb_module
from src.adapters.api.tvdb_client import TVDBClient


def _client_with_stubs(monkeypatch, responder):
    client = TVDBClient(api_key="x", cache=None)

    async def fake_ensure_token():
        return None

    async def fake_get_client():
        return object()

    monkeypatch.setattr(client, "_ensure_token", fake_ensure_token)
    monkeypatch.setattr(client, "_get_client", fake_get_client)
    monkeypatch.setattr(client, "_get_auth_headers", lambda language=None: {})
    monkeypatch.setattr(tvdb_module, "request_with_retry", responder)
    return client


@pytest.mark.asyncio
async def test_find_series_id_by_imdb_id_returns_first_match(monkeypatch):
    """Retourne l'ID TVDB du premier résultat."""
    captured = {}

    async def responder(http_client, method, url, params=None, headers=None):
        captured["url"] = url
        captured["params"] = params
        return httpx.Response(200, json={"data": [{"id": 87654}, {"id": 111}]})

    client = _client_with_stubs(monkeypatch, responder)
    assert await client.find_series_id_by_imdb_id("tt1156398") == "87654"
    assert captured["url"] == "/search/series"
    assert captured["params"] == {"imdbId": "tt1156398"}


@pytest.mark.asyncio
async def test_find_series_id_by_imdb_id_returns_none_on_404(monkeypatch):
    """TVDB répond 404 quand aucune série ne correspond."""

    async def responder(http_client, method, url, params=None, headers=None):
        raise httpx.HTTPStatusError(
            "not found",
            request=httpx.Request("GET", "https://api.thetvdb.com/search/series"),
            response=httpx.Response(404),
        )

    client = _client_with_stubs(monkeypatch, responder)
    assert await client.find_series_id_by_imdb_id("tt0000000") is None


@pytest.mark.asyncio
async def test_find_series_id_by_imdb_id_returns_none_on_empty_data(monkeypatch):
    """Une réponse sans données retourne None."""

    async def responder(http_client, method, url, params=None, headers=None):
        return httpx.Response(200, json={"data": []})

    client = _client_with_stubs(monkeypatch, responder)
    assert await client.find_series_id_by_imdb_id("tt0000000") is None
