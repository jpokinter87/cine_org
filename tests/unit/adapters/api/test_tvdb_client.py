"""
Tests du client TVDB API v4.

Utilise respx pour simuler les requetes HTTP et tester le comportement
complet du client : authentification, traductions, cache et retry.

Approche TDD : ces tests sont ecrits AVANT l'implementation.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from src.adapters.api.cache import APICache
from src.core.ports.api_clients import IMediaAPIClient, MediaDetails, SearchResult
from tests.fixtures.tvdb_responses import (
    TVDB_LOGIN_RESPONSE,
    TVDB_NOT_FOUND_RESPONSE,
    TVDB_SEARCH_EMPTY_RESPONSE,
    TVDB_SEARCH_RESPONSE,
    TVDB_SEARCH_TRANSLATED_RESPONSE,
    TVDB_SERIES_EPISODES_ENG_RESPONSE,
    TVDB_SERIES_EPISODES_FRA_RESPONSE,
    TVDB_SERIES_EPISODES_PAGE0_RESPONSE,
    TVDB_SERIES_EPISODES_PAGE1_RESPONSE,
    TVDB_SERIES_EXTENDED_RESPONSE,
    TVDB_SERIES_TRANSLATION_ENG_RESPONSE,
    TVDB_SERIES_TRANSLATION_FRA_RESPONSE,
)

BASE = "https://api4.thetvdb.com/v4"


@pytest.fixture
def mock_cache() -> MagicMock:
    """APICache simule pour les tests."""
    cache = MagicMock(spec=APICache)
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.set_search = AsyncMock()
    cache.set_details = AsyncMock()
    return cache


@pytest.fixture
def api_key() -> str:
    """Cle API de test."""
    return "test-api-key-12345"


def mock_login() -> respx.Route:
    """Simule l'endpoint de login v4."""
    return respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
    )


def mock_episodes(series_id: int = 81189) -> None:
    """Simule les deux endpoints d'episodes traduits (fra puis eng)."""
    respx.get(f"{BASE}/series/{series_id}/episodes/default/fra").mock(
        return_value=httpx.Response(200, json=TVDB_SERIES_EPISODES_FRA_RESPONSE)
    )
    respx.get(f"{BASE}/series/{series_id}/episodes/default/eng").mock(
        return_value=httpx.Response(200, json=TVDB_SERIES_EPISODES_ENG_RESPONSE)
    )


class TestTVDBClientAuthentication:
    """Authentification JWT de l'API v4."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_login_obtains_jwt_token(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Le client POST /login avec la cle API et stocke le token."""
        from src.adapters.api.tvdb_client import TVDBClient

        login_route = mock_login()
        respx.get(f"{BASE}/search").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_EMPTY_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            await client.search("Test")

            assert login_route.called
            request = login_route.calls[0].request
            assert b'"apikey"' in request.content
            assert api_key.encode() in request.content
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_token_read_from_data_envelope(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Le token v4 est imbrique dans ``data.token``, pas a la racine."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        search_route = respx.get(f"{BASE}/search").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_EMPTY_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            await client.search("Test")

            expected = TVDB_LOGIN_RESPONSE["data"]["token"]
            assert search_route.called
            request = search_route.calls[0].request
            assert request.headers.get("Authorization") == f"Bearer {expected}"
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_token_refresh_on_expiry(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Le token est renouvele quand il a expire."""
        from src.adapters.api.tvdb_client import TVDBClient

        login_route = mock_login()
        respx.get(f"{BASE}/search").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_EMPTY_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            await client.search("Test1")
            assert login_route.call_count == 1

            client._token_expiry = datetime.now() - timedelta(hours=1)

            await client.search("Test2")
            assert login_route.call_count == 2
        finally:
            await client.close()


class TestTVDBClientSearch:
    """Recherche de series via /search."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_returns_search_results(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """La recherche renvoie des SearchResult typés source='tvdb'."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        respx.get(f"{BASE}/search").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            results = await client.search("Breaking Bad")

            assert len(results) == 2
            assert all(isinstance(r, SearchResult) for r in results)
            assert results[0].title == "Breaking Bad"
            assert results[0].year == 2008
            assert results[0].source == "tvdb"
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_uses_tvdb_id_not_prefixed_id(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """L'id retenu est ``tvdb_id`` (81189), pas ``id`` ('series-81189')."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        respx.get(f"{BASE}/search").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            results = await client.search("Breaking Bad")

            assert results[0].id == "81189"
            assert results[1].id == "273181"
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_prefers_french_translation(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Le titre francais du dictionnaire translations est privilegie."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        respx.get(f"{BASE}/search").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_TRANSLATED_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            results = await client.search("The Handmaid's Tale")

            assert results[0].title == "The Handmaid's Tale : La Servante ecarlate"
            assert results[0].original_title == "The Handmaid's Tale"
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_restricts_type_to_series(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """La recherche filtre sur type=series (l'index v4 melange films/series)."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        search_route = respx.get(f"{BASE}/search").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_EMPTY_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            await client.search("Breaking Bad")

            request = search_route.calls[0].request
            assert request.url.params.get("type") == "series"
            assert request.url.params.get("query") == "Breaking Bad"
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_with_empty_results(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Une recherche sans resultat renvoie une liste vide."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        respx.get(f"{BASE}/search").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_EMPTY_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            assert await client.search("Inexistant") == []
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_returns_empty_list_on_404(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Un 404 sur /search est traite comme 'aucun resultat'."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        respx.get(f"{BASE}/search").mock(
            return_value=httpx.Response(404, json=TVDB_NOT_FOUND_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            assert await client.search("Inexistant") == []
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_with_year_filter(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Le filtre annee ecarte les series d'une autre annee."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        respx.get(f"{BASE}/search").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            results = await client.search("Breaking Bad", year=2008)

            assert len(results) == 1
            assert results[0].year == 2008
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_caches_results(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Les resultats de recherche sont mis en cache sous un prefixe v4."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        respx.get(f"{BASE}/search").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            await client.search("Breaking Bad")

            mock_cache.set_search.assert_called_once()
            key = mock_cache.set_search.call_args[0][0]
            assert key.startswith("tvdb4:")
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_checks_cache_before_api_call(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Un cache chaud evite tout appel reseau."""
        from src.adapters.api.tvdb_client import TVDBClient

        cached = [SearchResult(id="81189", title="Breaking Bad", source="tvdb")]
        mock_cache.get = AsyncMock(return_value=cached)

        login_route = mock_login()
        search_route = respx.get(f"{BASE}/search").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            results = await client.search("Breaking Bad")

            assert results == cached
            assert not search_route.called
            assert not login_route.called
        finally:
            await client.close()


class TestTVDBClientGetDetails:
    """Details d'une serie via /series/{id}/extended + traductions."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_details_returns_media_details(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Les details combinent le record etendu et la traduction francaise."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        respx.get(f"{BASE}/series/81189/extended").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_EXTENDED_RESPONSE)
        )
        respx.get(f"{BASE}/series/81189/translations/fra").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_TRANSLATION_FRA_RESPONSE)
        )
        respx.get(f"{BASE}/series/81189/translations/eng").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_TRANSLATION_ENG_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            details = await client.get_details("81189")

            assert isinstance(details, MediaDetails)
            assert details.id == "81189"
            assert details.title == "Breaking Bad"
            assert details.year == 2008
            assert details.overview.startswith("La vie de Walter White")
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_details_extracts_genre_names(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Les genres v4 sont des objets : seul le nom est conserve."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        respx.get(f"{BASE}/series/81189/extended").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_EXTENDED_RESPONSE)
        )
        respx.get(f"{BASE}/series/81189/translations/fra").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_TRANSLATION_FRA_RESPONSE)
        )
        respx.get(f"{BASE}/series/81189/translations/eng").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_TRANSLATION_ENG_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            details = await client.get_details("81189")

            assert details.genres == ("Drama", "Crime", "Thriller")
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_details_uses_absolute_image_url(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """L'URL du poster v4 est absolue : aucun prefixe ne doit etre ajoute."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        respx.get(f"{BASE}/series/81189/extended").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_EXTENDED_RESPONSE)
        )
        respx.get(f"{BASE}/series/81189/translations/fra").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_TRANSLATION_FRA_RESPONSE)
        )
        respx.get(f"{BASE}/series/81189/translations/eng").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_TRANSLATION_ENG_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            details = await client.get_details("81189")

            assert details.poster_url == (
                "https://artworks.thetvdb.com/banners/posters/81189-10.jpg"
            )
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_details_falls_back_to_base_name_without_fr(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Sans traduction francaise (404), le nom du record etendu est utilise."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        respx.get(f"{BASE}/series/81189/extended").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_EXTENDED_RESPONSE)
        )
        respx.get(f"{BASE}/series/81189/translations/fra").mock(
            return_value=httpx.Response(404, json=TVDB_NOT_FOUND_RESPONSE)
        )
        respx.get(f"{BASE}/series/81189/translations/eng").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_TRANSLATION_ENG_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            details = await client.get_details("81189")

            assert details.title == "Breaking Bad"
            assert details.overview is not None
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_details_does_not_flag_is_tv(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """is_tv reste False : ce drapeau designe une serie TMDB.

        Le positionner ferait etiqueter la source 'tmdb_tv' cote validation
        alors que l'identifiant est un id TVDB, et l'aval irait interroger
        TMDB avec cet id.
        """
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        respx.get(f"{BASE}/series/81189/extended").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_EXTENDED_RESPONSE)
        )
        respx.get(f"{BASE}/series/81189/translations/fra").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_TRANSLATION_FRA_RESPONSE)
        )
        respx.get(f"{BASE}/series/81189/translations/eng").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_TRANSLATION_ENG_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            details = await client.get_details("81189")

            assert details.is_tv is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_details_returns_none_on_404(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Une serie inconnue renvoie None."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        respx.get(f"{BASE}/series/999999/extended").mock(
            return_value=httpx.Response(404, json=TVDB_NOT_FOUND_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            assert await client.get_details("999999") is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_details_checks_cache_before_api_call(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Un cache chaud evite tout appel reseau."""
        from src.adapters.api.tvdb_client import TVDBClient

        cached = MediaDetails(id="81189", title="Breaking Bad", year=2008)
        mock_cache.get = AsyncMock(return_value=cached)

        login_route = mock_login()
        extended_route = respx.get(f"{BASE}/series/81189/extended").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_EXTENDED_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            details = await client.get_details("81189")

            assert details == cached
            assert not extended_route.called
            assert not login_route.called
        finally:
            await client.close()


class TestTVDBClientInterface:
    """Conformite au port IMediaAPIClient."""

    @pytest.mark.asyncio
    async def test_source_property_returns_tvdb(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """La source reste 'tvdb' : la v4 ne change pas l'identifiant."""
        from src.adapters.api.tvdb_client import TVDBClient

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            assert client.source == "tvdb"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_implements_imediaapiclient(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Le client implemente bien le port."""
        from src.adapters.api.tvdb_client import TVDBClient

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            assert isinstance(client, IMediaAPIClient)
        finally:
            await client.close()


class TestTVDBClientRateLimiting:
    """Gestion des 429 via le retry partage."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_on_429(self, mock_cache: MagicMock, api_key: str) -> None:
        """Une reponse 429 declenche un retry puis reussit."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        respx.get(f"{BASE}/search").mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "1"}),
                httpx.Response(200, json=TVDB_SEARCH_RESPONSE),
            ]
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            results = await client.search("Breaking Bad")

            assert len(results) == 2
        finally:
            await client.close()


class TestTVDBClientGetSeasonEpisodeCount:
    """Comptage des episodes d'une saison."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_episode_count_for_season(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Le compte reflete les episodes de la saison demandee."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        mock_episodes()

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            assert await client.get_season_episode_count("81189", 1) == 7
            assert await client.get_season_episode_count("81189", 2) == 13
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_none_for_unknown_season(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Une saison absente renvoie None."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        mock_episodes()

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            assert await client.get_season_episode_count("81189", 99) is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_none_on_404_series(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Une serie inconnue renvoie None."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        respx.get(f"{BASE}/series/999999/episodes/default/fra").mock(
            return_value=httpx.Response(404, json=TVDB_NOT_FOUND_RESPONSE)
        )
        respx.get(f"{BASE}/series/999999/episodes/default/eng").mock(
            return_value=httpx.Response(404, json=TVDB_NOT_FOUND_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            assert await client.get_season_episode_count("999999", 1) is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_handles_pagination(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Les pages suivantes sont suivies via links.next."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        respx.get(f"{BASE}/series/81189/episodes/default/fra").mock(
            side_effect=[
                httpx.Response(200, json=TVDB_SERIES_EPISODES_PAGE0_RESPONSE),
                httpx.Response(200, json=TVDB_SERIES_EPISODES_PAGE1_RESPONSE),
            ]
        )
        respx.get(f"{BASE}/series/81189/episodes/default/eng").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_EPISODES_ENG_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            assert await client.get_season_episode_count("81189", 1) == 520
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_single_fetch_serves_all_seasons(self, api_key: str) -> None:
        """Un seul aller-retour par langue sert toutes les saisons.

        Utilise un cache reellement memorisant (et non le mock toujours vide)
        puisque c'est precisement l'aller-retour economise qui est teste.
        """
        from src.adapters.api.tvdb_client import TVDBClient

        store: dict = {}
        memo_cache = MagicMock(spec=APICache)
        memo_cache.get = AsyncMock(side_effect=lambda key: store.get(key))
        memo_cache.set_details = AsyncMock(
            side_effect=lambda key, value: store.__setitem__(key, value)
        )
        memo_cache.set_search = AsyncMock()

        mock_login()
        fra_route = respx.get(f"{BASE}/series/81189/episodes/default/fra").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_EPISODES_FRA_RESPONSE)
        )
        respx.get(f"{BASE}/series/81189/episodes/default/eng").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_EPISODES_ENG_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=memo_cache)
        try:
            await client.get_season_episode_count("81189", 1)
            await client.get_season_episode_count("81189", 2)
            await client.get_episode_details("81189", 1, 1)

            assert fra_route.call_count == 1
        finally:
            await client.close()


class TestTVDBClientGetEpisodeDetails:
    """Details d'un episode."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_episode_with_french_title(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Le titre francais est privilegie."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        mock_episodes()

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            episode = await client.get_episode_details("81189", 1, 1)

            assert episode is not None
            assert episode.title == "Chute libre"
            assert episode.season_number == 1
            assert episode.episode_number == 1
            assert episode.air_date == "2008-01-20"
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_falls_back_to_english_title(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Sans titre francais, le titre anglais prend le relais."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        mock_episodes()

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            episode = await client.get_episode_details("81189", 1, 7)

            assert episode is not None
            assert episode.title == "English title 7"
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_falls_back_when_french_title_is_none(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Un titre francais a None (et non '') bascule aussi sur l'anglais."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        mock_episodes()

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            episode = await client.get_episode_details("81189", 0, 1)

            assert episode is not None
            assert episode.title == "Good Cop / Bad Cop"
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_none_for_invalid_episode(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Un episode inexistant renvoie None."""
        from src.adapters.api.tvdb_client import TVDBClient

        mock_login()
        mock_episodes()

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            assert await client.get_episode_details("81189", 1, 99) is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_cached_episode(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """Un cache chaud evite tout appel reseau."""
        from src.adapters.api.tvdb_client import TVDBClient
        from src.core.ports.api_clients import EpisodeDetails

        cached = [
            EpisodeDetails(
                id="349232",
                title="Chute libre",
                season_number=1,
                episode_number=1,
            )
        ]
        mock_cache.get = AsyncMock(return_value=cached)

        login_route = mock_login()
        fra_route = respx.get(f"{BASE}/series/81189/episodes/default/fra").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_EPISODES_FRA_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            episode = await client.get_episode_details("81189", 1, 1)

            assert episode is not None
            assert episode.title == "Chute libre"
            assert not fra_route.called
            assert not login_route.called
        finally:
            await client.close()
