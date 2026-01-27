"""
Tests unitaires pour le mecanisme de retry avec backoff exponentiel.

Ces tests verifient:
- RateLimitError capture le header Retry-After
- with_retry relance sur RateLimitError avec backoff exponentiel
- request_with_retry detecte les 429 et relance automatiquement
- Les echecs permanents remontent apres epuisement des tentatives
"""

import pytest
import httpx
import respx
from tenacity import RetryError

from src.adapters.api.retry import RateLimitError, with_retry, request_with_retry


class TestRateLimitError:
    """Tests pour l'exception RateLimitError."""

    def test_rate_limit_error_stores_retry_after(self) -> None:
        """RateLimitError stocke la valeur Retry-After."""
        error = RateLimitError(retry_after=60)
        assert error.retry_after == 60
        assert "60" in str(error)

    def test_rate_limit_error_without_retry_after(self) -> None:
        """RateLimitError fonctionne sans Retry-After."""
        error = RateLimitError(retry_after=None)
        assert error.retry_after is None


class TestWithRetryDecorator:
    """Tests pour le decorateur with_retry."""

    @pytest.mark.asyncio
    async def test_with_retry_retries_on_rate_limit_error(self) -> None:
        """with_retry relance quand RateLimitError est levee."""
        call_count = 0

        @with_retry(max_attempts=3, max_wait=1)
        async def flaky_function() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RateLimitError(retry_after=1)
            return "success"

        result = await flaky_function()
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_with_retry_stops_after_max_attempts(self) -> None:
        """with_retry abandonne apres max_attempts tentatives."""
        call_count = 0

        @with_retry(max_attempts=3, max_wait=1)
        async def always_fails() -> str:
            nonlocal call_count
            call_count += 1
            raise RateLimitError(retry_after=1)

        with pytest.raises(RateLimitError):
            await always_fails()
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_with_retry_does_not_retry_other_exceptions(self) -> None:
        """with_retry ne relance pas les autres exceptions."""
        call_count = 0

        @with_retry(max_attempts=3, max_wait=1)
        async def raises_value_error() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("not a rate limit error")

        with pytest.raises(ValueError):
            await raises_value_error()
        assert call_count == 1  # Pas de retry


class TestRequestWithRetry:
    """Tests pour request_with_retry avec httpx."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_request_with_retry_raises_on_429(self, respx_mock: respx.Router) -> None:
        """request_with_retry convertit 429 en RateLimitError et relance."""
        # Mock 3 appels: 429, 429, 429 (epuisement)
        route = respx_mock.get("https://api.example.com/data").mock(
            return_value=httpx.Response(429, headers={"Retry-After": "30"})
        )

        async with httpx.AsyncClient() as client:
            with pytest.raises(RateLimitError) as exc_info:
                await request_with_retry(
                    client, "GET", "https://api.example.com/data", max_attempts=3
                )

        assert exc_info.value.retry_after == 30
        assert route.call_count == 3

    @pytest.mark.asyncio
    @respx.mock
    async def test_request_with_retry_retries_then_succeeds(self, respx_mock: respx.Router) -> None:
        """request_with_retry reussit apres des 429 initiaux."""
        # Mock: 429 puis 200
        route = respx_mock.get("https://api.example.com/data").mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "1"}),
                httpx.Response(200, json={"status": "ok"}),
            ]
        )

        async with httpx.AsyncClient() as client:
            response = await request_with_retry(
                client, "GET", "https://api.example.com/data", max_attempts=3
            )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_request_with_retry_passes_on_success(self, respx_mock: respx.Router) -> None:
        """request_with_retry retourne directement sur 200."""
        route = respx_mock.get("https://api.example.com/data").mock(
            return_value=httpx.Response(200, json={"data": "value"})
        )

        async with httpx.AsyncClient() as client:
            response = await request_with_retry(
                client, "GET", "https://api.example.com/data"
            )

        assert response.status_code == 200
        assert response.json() == {"data": "value"}
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_request_with_retry_raises_on_other_errors(self, respx_mock: respx.Router) -> None:
        """request_with_retry leve HTTPStatusError sur autres erreurs."""
        route = respx_mock.get("https://api.example.com/data").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await request_with_retry(
                    client, "GET", "https://api.example.com/data"
                )

        assert exc_info.value.response.status_code == 500
        assert route.call_count == 1  # Pas de retry sur 500

    @pytest.mark.asyncio
    @respx.mock
    async def test_request_with_retry_429_without_retry_after(self, respx_mock: respx.Router) -> None:
        """request_with_retry gere 429 sans header Retry-After."""
        route = respx_mock.get("https://api.example.com/data").mock(
            side_effect=[
                httpx.Response(429),  # Sans Retry-After
                httpx.Response(200, json={"ok": True}),
            ]
        )

        async with httpx.AsyncClient() as client:
            response = await request_with_retry(
                client, "GET", "https://api.example.com/data", max_attempts=3
            )

        assert response.status_code == 200
        assert route.call_count == 2
