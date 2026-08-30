"""Tests de TVDBClient.get_season_names (noms de saisons + traductions).

Les arcs d'anime sont livres par les teams sous le nom de l'arc
(« BLEACH.Thousand-Year.Blood.War.S01 ») alors que le fournisseur les
range dans une saison de la serie mere. Retrouver ce nom de saison est le
signal qui permet de detecter le decalage.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from src.adapters.api.cache import APICache
from src.adapters.api.tvdb_client import TVDBClient
from tests.fixtures.tvdb_responses import TVDB_LOGIN_RESPONSE

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


def _extended(seasons: list[dict]) -> dict:
    return {"status": "success", "data": {"id": 74796, "seasons": seasons}}


@pytest.mark.asyncio
@respx.mock
async def test_get_season_names_collecte_nom_de_base_et_traduction(mock_cache) -> None:
    """Le nom natif et la traduction anglaise sont tous deux retenus."""
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
    )
    respx.get(f"{BASE}/series/74796/extended").mock(
        return_value=httpx.Response(
            200,
            json=_extended(
                [
                    {
                        "id": 2008655,
                        "number": 17,
                        "name": "千年血戦篇",
                        "nameTranslations": ["eng,jpn"],
                        "type": {"type": "official"},
                    }
                ]
            ),
        )
    )
    respx.get(f"{BASE}/seasons/2008655/translations/eng").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "success",
                "data": {"name": "Bleach: Thousand-Year Blood War"},
            },
        )
    )

    client = TVDBClient(api_key="x", cache=mock_cache)
    try:
        names = await client.get_season_names("74796")
    finally:
        await client.close()

    assert names == {17: ("千年血戦篇", "Bleach: Thousand-Year Blood War")}


@pytest.mark.asyncio
@respx.mock
async def test_get_season_names_ignore_saisons_non_officielles(mock_cache) -> None:
    """Seul l'ordre de diffusion officiel est retenu."""
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
    )
    respx.get(f"{BASE}/series/74796/extended").mock(
        return_value=httpx.Response(
            200,
            json=_extended(
                [
                    {
                        "id": 1,
                        "number": 1,
                        "name": "Saison DVD",
                        "nameTranslations": [],
                        "type": {"type": "dvd"},
                    },
                    {
                        "id": 2,
                        "number": 1,
                        "name": "Arc introductif",
                        "nameTranslations": [],
                        "type": {"type": "official"},
                    },
                ]
            ),
        )
    )

    client = TVDBClient(api_key="x", cache=mock_cache)
    try:
        names = await client.get_season_names("74796")
    finally:
        await client.close()

    assert names == {1: ("Arc introductif",)}


@pytest.mark.asyncio
@respx.mock
async def test_get_season_names_serie_inconnue_retourne_vide(mock_cache) -> None:
    """Une serie absente ne fait pas echouer l'appelant."""
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
    )
    respx.get(f"{BASE}/series/999/extended").mock(
        return_value=httpx.Response(404, json={"status": "failure", "data": None})
    )

    client = TVDBClient(api_key="x", cache=mock_cache)
    try:
        assert await client.get_season_names("999") == {}
    finally:
        await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_get_season_names_relit_le_cache(mock_cache) -> None:
    """Un resultat en cache evite tout aller-retour reseau."""
    mock_cache.get = AsyncMock(return_value={17: ("Thousand-Year Blood War",)})
    route = respx.get(f"{BASE}/series/74796/extended")

    client = TVDBClient(api_key="x", cache=mock_cache)
    try:
        assert await client.get_season_names("74796") == {
            17: ("Thousand-Year Blood War",)
        }
    finally:
        await client.close()

    assert not route.called
