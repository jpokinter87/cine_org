"""
Tests for TVDB API client.

Uses respx to mock HTTP requests and test the full client behavior
including authentication, caching, and retry logic.

TDD approach: These tests are written BEFORE the implementation.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch

import httpx
import pytest
import respx

from src.adapters.api.cache import APICache
from src.adapters.api.retry import RateLimitError
from src.core.ports.api_clients import IMediaAPIClient, MediaDetails, SearchResult
from tests.fixtures.tvdb_responses import (
    TVDB_LOGIN_RESPONSE,
    TVDB_SEARCH_EMPTY_RESPONSE,
    TVDB_SEARCH_RESPONSE,
    TVDB_SERIES_DETAILS_RESPONSE,
    TVDB_SERIES_NOT_FOUND_RESPONSE,
)


@pytest.fixture
def mock_cache() -> MagicMock:
    """Mock APICache for testing."""
    cache = MagicMock(spec=APICache)
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.set_search = AsyncMock()
    cache.set_details = AsyncMock()
    return cache


@pytest.fixture
def api_key() -> str:
    """Test API key."""
    return "test-api-key-12345"


class TestTVDBClientAuthentication:
    """Test TVDB JWT authentication."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_login_obtains_jwt_token(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """
        Test that login endpoint is called and JWT token is obtained.

        The client should POST to /login with the API key and store the token.
        """
        from src.adapters.api.tvdb_client import TVDBClient

        # Mock the login endpoint (API v3)
        login_route = respx.post("https://api.thetvdb.com/login").mock(
            return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
        )
        # Mock search endpoint (to trigger authentication)
        search_route = respx.get("https://api.thetvdb.com/search/series").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_EMPTY_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            await client.search("Test")

            # Verify login was called with correct payload
            assert login_route.called
            request = login_route.calls[0].request
            assert b'"apikey"' in request.content
            assert api_key.encode() in request.content
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_includes_auth_header(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """
        Test that search requests include the Authorization header with Bearer token.
        """
        from src.adapters.api.tvdb_client import TVDBClient

        token = TVDB_LOGIN_RESPONSE["token"]

        # Mock endpoints (API v3)
        respx.post("https://api.thetvdb.com/login").mock(
            return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
        )
        search_route = respx.get("https://api.thetvdb.com/search/series").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_EMPTY_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            await client.search("Test")

            # Verify Authorization header in search request
            assert search_route.called
            request = search_route.calls[0].request
            assert request.headers.get("Authorization") == f"Bearer {token}"
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_token_refresh_on_expiry(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """
        Test that token is refreshed when it expires.

        Token should be refreshed proactively (1 day before actual expiry).
        """
        from src.adapters.api.tvdb_client import TVDBClient

        # First login response
        login_route = respx.post("https://api.thetvdb.com/login").mock(
            return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
        )
        respx.get("https://api.thetvdb.com/search/series").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_EMPTY_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            # First call - should get token
            await client.search("Test1")
            assert login_route.call_count == 1

            # Simulate expired token by setting expiry to past
            client._token_expiry = datetime.now() - timedelta(hours=1)

            # Second call - should refresh token
            await client.search("Test2")
            assert login_route.call_count == 2
        finally:
            await client.close()


class TestTVDBClientSearch:
    """Test TVDB search functionality."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_returns_search_results(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """
        Test that search returns properly formatted SearchResult objects.
        """
        from src.adapters.api.tvdb_client import TVDBClient

        # Mock endpoints
        respx.post("https://api.thetvdb.com/login").mock(
            return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
        )
        respx.get("https://api.thetvdb.com/search/series").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            results = await client.search("Breaking Bad")

            assert len(results) == 2
            assert isinstance(results[0], SearchResult)

            # Check first result (Breaking Bad)
            assert results[0].id == "81189"
            assert results[0].title == "Breaking Bad"
            assert results[0].year == 2008
            assert results[0].source == "tvdb"

            # Check second result (Metastasis)
            assert results[1].id == "273181"
            assert results[1].title == "Metastasis"
            assert results[1].year == 2014
            assert results[1].source == "tvdb"
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_with_empty_results(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """
        Test that search returns empty list when no results found.
        """
        from src.adapters.api.tvdb_client import TVDBClient

        # Mock endpoints
        respx.post("https://api.thetvdb.com/login").mock(
            return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
        )
        respx.get("https://api.thetvdb.com/search/series").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_EMPTY_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            results = await client.search("NonexistentSeries12345")

            assert results == []
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_returns_empty_list_on_404(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """
        Test that search returns empty list when TVDB returns 404.

        TVDB returns 404 when no series matches the search query,
        instead of returning an empty data array.
        """
        from src.adapters.api.tvdb_client import TVDBClient

        # Mock endpoints
        respx.post("https://api.thetvdb.com/login").mock(
            return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
        )
        respx.get("https://api.thetvdb.com/search/series").mock(
            return_value=httpx.Response(404, json={"Error": "Resource not found"})
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            results = await client.search("24 heures dans la vie d'une femme")

            # Should return empty list, not raise exception
            assert results == []
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_caches_results(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """
        Test that search results are cached with set_search.
        """
        from src.adapters.api.tvdb_client import TVDBClient

        # Mock endpoints
        respx.post("https://api.thetvdb.com/login").mock(
            return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
        )
        respx.get("https://api.thetvdb.com/search/series").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            await client.search("Breaking Bad")

            # Verify cache.set_search was called
            mock_cache.set_search.assert_called_once()
            call_args = mock_cache.set_search.call_args
            cache_key = call_args[0][0]
            cached_value = call_args[0][1]

            assert "tvdb:search:Breaking Bad:None" == cache_key
            assert len(cached_value) == 2
            assert isinstance(cached_value[0], SearchResult)
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_checks_cache_before_api_call(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """
        Test that cache is checked BEFORE any HTTP request is made.

        If data is in cache, no HTTP request should be made.
        """
        from src.adapters.api.tvdb_client import TVDBClient

        # Setup cache to return cached results
        cached_results = [
            SearchResult(id="81189", title="Breaking Bad", year=2008, source="tvdb")
        ]
        mock_cache.get = AsyncMock(return_value=cached_results)

        # Mock endpoints (should NOT be called)
        login_route = respx.post("https://api.thetvdb.com/login").mock(
            return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
        )
        search_route = respx.get("https://api.thetvdb.com/search/series").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            results = await client.search("Breaking Bad")

            # Verify cache.get was called
            mock_cache.get.assert_called_once_with("tvdb:search:Breaking Bad:None")

            # Verify results came from cache
            assert results == cached_results

            # Verify NO HTTP requests were made (neither login nor search)
            assert not login_route.called
            assert not search_route.called
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_with_year_filter(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """
        Test that search with year includes year in cache key.

        Note: TVDB API v3 doesn't support year filter in query params.
        The year filtering is done client-side after receiving results.
        """
        from src.adapters.api.tvdb_client import TVDBClient

        # Mock endpoints
        respx.post("https://api.thetvdb.com/login").mock(
            return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
        )
        search_route = respx.get("https://api.thetvdb.com/search/series").mock(
            return_value=httpx.Response(200, json=TVDB_SEARCH_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            results = await client.search("Breaking Bad", year=2008)

            # Verify cache key includes year
            mock_cache.get.assert_called_with("tvdb:search:Breaking Bad:2008")

            # Verify search was called
            assert search_route.called

            # Year filtering is done client-side - only 2008 results returned
            # TVDB_SEARCH_RESPONSE has Breaking Bad (2008) and Metastasis (2014)
            assert len(results) == 1
            assert results[0].year == 2008
        finally:
            await client.close()


class TestTVDBClientGetDetails:
    """Test TVDB get_details functionality."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_details_returns_media_details(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """
        Test that get_details returns properly formatted MediaDetails.
        """
        from src.adapters.api.tvdb_client import TVDBClient

        # Mock endpoints
        respx.post("https://api.thetvdb.com/login").mock(
            return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
        )
        respx.get("https://api.thetvdb.com/series/81189").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_DETAILS_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            details = await client.get_details("81189")

            assert details is not None
            assert isinstance(details, MediaDetails)
            assert details.id == "81189"
            assert details.title == "Breaking Bad"
            assert details.year == 2008
            assert details.genres == ("Crime", "Drama", "Thriller")
            # TV series don't have a single duration
            assert details.duration_seconds is None
            assert details.poster_url == "https://artworks.thetvdb.com/banners/posters/81189-10.jpg"
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_details_returns_none_on_404(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """
        Test that get_details returns None when series not found (404).
        """
        from src.adapters.api.tvdb_client import TVDBClient

        # Mock endpoints
        respx.post("https://api.thetvdb.com/login").mock(
            return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
        )
        respx.get("https://api.thetvdb.com/series/99999999").mock(
            return_value=httpx.Response(404, json=TVDB_SERIES_NOT_FOUND_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            details = await client.get_details("99999999")

            assert details is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_details_caches_results(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """
        Test that details are cached with set_details.
        """
        from src.adapters.api.tvdb_client import TVDBClient

        # Mock endpoints
        respx.post("https://api.thetvdb.com/login").mock(
            return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
        )
        respx.get("https://api.thetvdb.com/series/81189").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_DETAILS_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            await client.get_details("81189")

            # Verify cache.set_details was called
            mock_cache.set_details.assert_called_once()
            call_args = mock_cache.set_details.call_args
            cache_key = call_args[0][0]
            cached_value = call_args[0][1]

            assert cache_key == "tvdb:details:81189"
            assert isinstance(cached_value, MediaDetails)
            assert cached_value.id == "81189"
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_details_checks_cache_before_api_call(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """
        Test that cache is checked BEFORE any HTTP request is made.

        If data is in cache, no HTTP request should be made.
        """
        from src.adapters.api.tvdb_client import TVDBClient

        # Setup cache to return cached details
        cached_details = MediaDetails(
            id="81189",
            title="Breaking Bad",
            year=2008,
            genres=("Crime", "Drama", "Thriller"),
        )
        mock_cache.get = AsyncMock(return_value=cached_details)

        # Mock endpoints (should NOT be called)
        login_route = respx.post("https://api.thetvdb.com/login").mock(
            return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
        )
        details_route = respx.get("https://api.thetvdb.com/series/81189").mock(
            return_value=httpx.Response(200, json=TVDB_SERIES_DETAILS_RESPONSE)
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            details = await client.get_details("81189")

            # Verify cache.get was called
            mock_cache.get.assert_called_once_with("tvdb:details:81189")

            # Verify details came from cache
            assert details == cached_details

            # Verify NO HTTP requests were made
            assert not login_route.called
            assert not details_route.called
        finally:
            await client.close()


class TestTVDBClientInterface:
    """Test TVDBClient implements IMediaAPIClient interface."""

    @pytest.mark.asyncio
    async def test_source_property_returns_tvdb(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """
        Test that source property returns 'tvdb'.
        """
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
        """
        Test that TVDBClient is an instance of IMediaAPIClient.
        """
        from src.adapters.api.tvdb_client import TVDBClient

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            assert isinstance(client, IMediaAPIClient)
        finally:
            await client.close()


class TestTVDBClientRateLimiting:
    """Test TVDB rate limiting and retry behavior."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_on_429(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """
        Test that 429 responses trigger automatic retry.
        """
        from src.adapters.api.tvdb_client import TVDBClient

        # Mock login
        respx.post("https://api.thetvdb.com/login").mock(
            return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
        )

        # Mock search: first call returns 429, second returns success
        call_count = 0

        def search_response(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(429, headers={"Retry-After": "1"})
            return httpx.Response(200, json=TVDB_SEARCH_RESPONSE)

        search_route = respx.get("https://api.thetvdb.com/search/series").mock(
            side_effect=search_response
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            results = await client.search("Breaking Bad")

            # Verify multiple calls were made (retry after 429)
            assert search_route.call_count >= 2
            # Verify final result is successful
            assert len(results) == 2
        finally:
            await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_after_max_retries(
        self, mock_cache: MagicMock, api_key: str
    ) -> None:
        """
        Test that RateLimitError is raised after max retries exhausted.
        """
        from src.adapters.api.tvdb_client import TVDBClient

        # Mock login
        respx.post("https://api.thetvdb.com/login").mock(
            return_value=httpx.Response(200, json=TVDB_LOGIN_RESPONSE)
        )

        # Mock search: always returns 429
        respx.get("https://api.thetvdb.com/search/series").mock(
            return_value=httpx.Response(429, headers={"Retry-After": "1"})
        )

        client = TVDBClient(api_key=api_key, cache=mock_cache)
        try:
            with pytest.raises(RateLimitError):
                await client.search("Breaking Bad")
        finally:
            await client.close()
