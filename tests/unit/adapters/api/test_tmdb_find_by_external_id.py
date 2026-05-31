"""Tests pour TMDBClient.find_by_external_id (resolution par identifiant externe).

Verifie qu'on peut retrouver l'equivalent TMDB d'une serie via son tvdb_id ou
son imdb_id (plus fiable que la recherche par titre traduit).
"""

import httpx
import pytest
import respx

from src.adapters.api.cache import APICache
from src.adapters.api.tmdb_client import TMDBClient


@pytest.fixture
def cache(tmp_path):
    """Cache API temporaire."""
    return APICache(cache_dir=tmp_path / "api_cache")


@pytest.fixture
def client(cache):
    """Client TMDB de test."""
    return TMDBClient(api_key="test_key", cache=cache)


@pytest.mark.asyncio
@respx.mock
async def test_find_by_tvdb_id_retourne_resultat_tv(client):
    """find_by_external_id resout une serie via son tvdb_id."""
    route = respx.get("https://api.themoviedb.org/3/find/280847").mock(
        return_value=httpx.Response(
            200,
            json={
                "movie_results": [],
                "tv_results": [
                    {
                        "id": 61828,
                        "name": "Detectorists",
                        "original_name": "Detectorists",
                        "first_air_date": "2014-10-02",
                    }
                ],
            },
        )
    )

    results = await client.find_by_external_id("280847", "tvdb_id")

    assert route.called
    # Le parametre external_source doit valoir tvdb_id
    assert route.calls.last.request.url.params["external_source"] == "tvdb_id"
    assert len(results) == 1
    assert results[0].id == "61828"
    assert results[0].title == "Detectorists"
    assert results[0].year == 2014
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_find_by_imdb_id_retourne_resultat_tv(client):
    """find_by_external_id resout une serie via son imdb_id."""
    respx.get("https://api.themoviedb.org/3/find/tt4082744").mock(
        return_value=httpx.Response(
            200,
            json={
                "tv_results": [
                    {
                        "id": 61828,
                        "name": "Detectorists",
                        "first_air_date": "2014-10-02",
                    }
                ],
            },
        )
    )

    results = await client.find_by_external_id("tt4082744", "imdb_id")

    assert len(results) == 1
    assert results[0].id == "61828"
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_find_by_external_id_sans_resultat_tv_retourne_liste_vide(client):
    """Sans tv_results, find_by_external_id retourne une liste vide."""
    respx.get("https://api.themoviedb.org/3/find/999999").mock(
        return_value=httpx.Response(
            200,
            json={"movie_results": [{"id": 1}], "tv_results": []},
        )
    )

    results = await client.find_by_external_id("999999", "tvdb_id")

    assert results == []
    await client.close()
