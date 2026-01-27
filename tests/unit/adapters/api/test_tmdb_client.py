"""
Tests for TMDBClient - TMDB API client implementation.

Uses respx to mock httpx calls and verifies:
- Search returns SearchResult objects
- Details returns MediaDetails with French genres
- Cache is checked BEFORE API calls (cache-first pattern)
- 429 responses trigger retry
"""

from unittest.mock import AsyncMock, MagicMock, call

import httpx
import pytest
import respx

from src.adapters.api.cache import APICache
from src.adapters.api.retry import RateLimitError
from src.adapters.api.tmdb_client import TMDBClient
from src.core.ports.api_clients import IMediaAPIClient, MediaDetails, SearchResult
from tests.fixtures.tmdb_responses import (
    TMDB_MOVIE_DETAILS_RESPONSE,
    TMDB_SEARCH_EMPTY_RESPONSE,
    TMDB_SEARCH_RESPONSE,
    TMDB_SEARCH_RESPONSE_WITH_YEAR,
)


@pytest.fixture
def mock_cache() -> AsyncMock:
    """Mock APICache for testing."""
    cache = AsyncMock(spec=APICache)
    cache.get.return_value = None  # Cache miss by default
    return cache


@pytest.fixture
def tmdb_client(mock_cache: AsyncMock) -> TMDBClient:
    """TMDBClient instance with mocked cache."""
    return TMDBClient(api_key="test_api_key", cache=mock_cache)


class TestTMDBClientInterface:
    """Test TMDBClient implements IMediaAPIClient correctly."""

    def test_implements_interface(self, tmdb_client: TMDBClient):
        """TMDBClient should implement IMediaAPIClient."""
        assert isinstance(tmdb_client, IMediaAPIClient)

    def test_source_property_returns_tmdb(self, tmdb_client: TMDBClient):
        """source property should return 'tmdb'."""
        assert tmdb_client.source == "tmdb"


class TestTMDBSearch:
    """Tests for TMDBClient.search() method."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_returns_search_results(
        self, tmdb_client: TMDBClient, mock_cache: AsyncMock
    ):
        """search() should return list of SearchResult objects."""
        # Setup mock
        respx.get("https://api.themoviedb.org/3/search/movie").mock(
            return_value=httpx.Response(200, json=TMDB_SEARCH_RESPONSE)
        )

        # Execute
        results = await tmdb_client.search("Avatar")

        # Verify
        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)

        # Check first result (Avatar 2009)
        assert results[0].id == "19995"
        assert results[0].title == "Avatar"
        assert results[0].year == 2009
        assert results[0].source == "tmdb"

        # Check second result (Avatar: The Way of Water)
        assert results[1].id == "76600"
        assert results[1].title == "Avatar: La Voie de l'eau"
        assert results[1].year == 2022
        assert results[1].source == "tmdb"

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_with_year_filter(
        self, tmdb_client: TMDBClient, mock_cache: AsyncMock
    ):
        """search() with year parameter should filter results."""
        # Setup mock
        respx.get("https://api.themoviedb.org/3/search/movie").mock(
            return_value=httpx.Response(200, json=TMDB_SEARCH_RESPONSE_WITH_YEAR)
        )

        # Execute
        results = await tmdb_client.search("Avatar", year=2009)

        # Verify
        assert len(results) == 1
        assert results[0].year == 2009

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_returns_empty_list_on_no_results(
        self, tmdb_client: TMDBClient, mock_cache: AsyncMock
    ):
        """search() should return empty list when no results found."""
        # Setup mock
        respx.get("https://api.themoviedb.org/3/search/movie").mock(
            return_value=httpx.Response(200, json=TMDB_SEARCH_EMPTY_RESPONSE)
        )

        # Execute
        results = await tmdb_client.search("NonExistentMovie12345")

        # Verify
        assert results == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_caches_results(
        self, tmdb_client: TMDBClient, mock_cache: AsyncMock
    ):
        """search() should cache successful results."""
        # Setup mock
        respx.get("https://api.themoviedb.org/3/search/movie").mock(
            return_value=httpx.Response(200, json=TMDB_SEARCH_RESPONSE)
        )

        # Execute
        await tmdb_client.search("Avatar")

        # Verify cache.set_search was called with correct key
        mock_cache.set_search.assert_called_once()
        call_args = mock_cache.set_search.call_args
        cache_key = call_args[0][0]
        assert "tmdb:search:Avatar" in cache_key
        assert cache_key == "tmdb:search:Avatar:None"

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_returns_cached_on_second_call(
        self, tmdb_client: TMDBClient, mock_cache: AsyncMock
    ):
        """search() should return cached data without API call on cache hit."""
        # Setup: cache returns pre-existing data
        cached_results = [
            SearchResult(id="19995", title="Avatar", year=2009, source="tmdb")
        ]
        mock_cache.get.return_value = cached_results

        # Execute
        results = await tmdb_client.search("Avatar")

        # Verify: returns cached data, no HTTP request made
        assert results == cached_results
        assert not respx.calls  # No HTTP calls made

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_checks_cache_before_api_call(
        self, tmdb_client: TMDBClient, mock_cache: AsyncMock
    ):
        """search() MUST check cache BEFORE making any HTTP request."""
        # Track call order
        call_order = []

        async def track_cache_get(key):
            call_order.append(("cache.get", key))
            return None  # Cache miss

        mock_cache.get.side_effect = track_cache_get

        # Setup HTTP mock that tracks when it's called
        def track_http_call(request):
            call_order.append(("http", str(request.url)))
            return httpx.Response(200, json=TMDB_SEARCH_RESPONSE)

        respx.get("https://api.themoviedb.org/3/search/movie").mock(
            side_effect=track_http_call
        )

        # Execute
        await tmdb_client.search("Avatar")

        # Verify: cache.get was called BEFORE http request
        assert len(call_order) >= 2
        assert call_order[0][0] == "cache.get", (
            f"Expected cache.get first, got {call_order[0]}"
        )
        assert call_order[1][0] == "http", (
            f"Expected http second, got {call_order[1]}"
        )


class TestTMDBGetDetails:
    """Tests for TMDBClient.get_details() method."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_details_returns_media_details(
        self, tmdb_client: TMDBClient, mock_cache: AsyncMock
    ):
        """get_details() should return MediaDetails with all fields."""
        # Setup mock
        respx.get("https://api.themoviedb.org/3/movie/19995").mock(
            return_value=httpx.Response(200, json=TMDB_MOVIE_DETAILS_RESPONSE)
        )

        # Execute
        details = await tmdb_client.get_details("19995")

        # Verify
        assert details is not None
        assert isinstance(details, MediaDetails)
        assert details.id == "19995"
        assert details.title == "Avatar"
        assert details.original_title == "Avatar"
        assert details.year == 2009
        # Duration in seconds (162 minutes * 60)
        assert details.duration_seconds == 9720
        # French genre names
        assert "Action" in details.genres
        assert "Aventure" in details.genres
        assert "Science-Fiction" in details.genres
        # Overview
        assert "marine" in details.overview.lower()
        # Poster URL should be complete
        assert details.poster_url.startswith("https://")

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_details_returns_none_on_404(
        self, tmdb_client: TMDBClient, mock_cache: AsyncMock
    ):
        """get_details() should return None when movie not found (404)."""
        # Setup mock
        respx.get("https://api.themoviedb.org/3/movie/99999999").mock(
            return_value=httpx.Response(404, json={"status_message": "Not found"})
        )

        # Execute
        details = await tmdb_client.get_details("99999999")

        # Verify
        assert details is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_details_caches_results(
        self, tmdb_client: TMDBClient, mock_cache: AsyncMock
    ):
        """get_details() should cache successful results."""
        # Setup mock
        respx.get("https://api.themoviedb.org/3/movie/19995").mock(
            return_value=httpx.Response(200, json=TMDB_MOVIE_DETAILS_RESPONSE)
        )

        # Execute
        await tmdb_client.get_details("19995")

        # Verify cache.set_details was called with correct key
        mock_cache.set_details.assert_called_once()
        call_args = mock_cache.set_details.call_args
        cache_key = call_args[0][0]
        assert cache_key == "tmdb:details:19995"

    @pytest.mark.asyncio
    @respx.mock
    async def test_details_checks_cache_before_api_call(
        self, tmdb_client: TMDBClient, mock_cache: AsyncMock
    ):
        """get_details() MUST check cache BEFORE making any HTTP request."""
        # Track call order
        call_order = []

        async def track_cache_get(key):
            call_order.append(("cache.get", key))
            return None  # Cache miss

        mock_cache.get.side_effect = track_cache_get

        # Setup HTTP mock that tracks when it's called
        def track_http_call(request):
            call_order.append(("http", str(request.url)))
            return httpx.Response(200, json=TMDB_MOVIE_DETAILS_RESPONSE)

        respx.get("https://api.themoviedb.org/3/movie/19995").mock(
            side_effect=track_http_call
        )

        # Execute
        await tmdb_client.get_details("19995")

        # Verify: cache.get was called BEFORE http request
        assert len(call_order) >= 2
        assert call_order[0][0] == "cache.get", (
            f"Expected cache.get first, got {call_order[0]}"
        )
        assert call_order[1][0] == "http", (
            f"Expected http second, got {call_order[1]}"
        )


class TestTMDBRetry:
    """Tests for retry behavior on rate limiting."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_on_429(
        self, tmdb_client: TMDBClient, mock_cache: AsyncMock
    ):
        """Client should retry on 429 rate limit response."""
        # Setup: first call returns 429, second succeeds
        call_count = 0

        def mock_response(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(
                    429, headers={"Retry-After": "1"}, json={"status_message": "Rate limited"}
                )
            return httpx.Response(200, json=TMDB_SEARCH_RESPONSE)

        respx.get("https://api.themoviedb.org/3/search/movie").mock(
            side_effect=mock_response
        )

        # Execute
        results = await tmdb_client.search("Avatar")

        # Verify: got results after retry
        assert len(results) == 2
        assert call_count == 2  # Two HTTP calls were made


class TestTMDBClientLifecycle:
    """Tests for client lifecycle management."""

    @pytest.mark.asyncio
    async def test_close_cleans_up_resources(self, mock_cache: AsyncMock):
        """close() should properly clean up HTTP client."""
        client = TMDBClient(api_key="test_api_key", cache=mock_cache)

        # Force client creation
        _ = client._get_client()

        # Close should not raise
        await client.close()

        # Client should be closed
        assert client._client is None or client._client.is_closed
