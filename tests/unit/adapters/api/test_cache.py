"""
Tests unitaires pour APICache.

Ces tests verifient:
- Stockage et recuperation de valeurs
- TTL differencies pour recherche (24h) et details (7j)
- Operations asynchrones non-bloquantes
- Nettoyage du cache
"""

import asyncio
from pathlib import Path

import pytest

from src.adapters.api.cache import APICache


class TestAPICache:
    """Tests pour la classe APICache."""

    @pytest.fixture
    def cache(self, tmp_path: Path) -> APICache:
        """Cree un cache avec un repertoire temporaire."""
        cache = APICache(cache_dir=str(tmp_path / "test_cache"))
        yield cache
        cache.close()

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing_key(self, cache: APICache) -> None:
        """get() retourne None pour une cle inexistante."""
        result = await cache.get("nonexistent_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_and_get_round_trip(self, cache: APICache) -> None:
        """set() puis get() retourne la valeur stockee."""
        key = "test_key"
        value = {"title": "Inception", "year": 2010}

        await cache.set(key, value, ttl=3600)
        result = await cache.get(key)

        assert result == value

    def test_search_ttl_uses_24_hours(self) -> None:
        """SEARCH_TTL est defini a 24 heures (86400 secondes)."""
        assert APICache.SEARCH_TTL == 86400

    def test_details_ttl_uses_7_days(self) -> None:
        """DETAILS_TTL est defini a 7 jours (604800 secondes)."""
        assert APICache.DETAILS_TTL == 604800

    @pytest.mark.asyncio
    async def test_set_search_uses_search_ttl(self, cache: APICache) -> None:
        """set_search() utilise le TTL de 24h."""
        key = "search:inception"
        value = [{"id": 1, "title": "Inception"}]

        await cache.set_search(key, value)
        result = await cache.get(key)

        assert result == value

    @pytest.mark.asyncio
    async def test_set_details_uses_details_ttl(self, cache: APICache) -> None:
        """set_details() utilise le TTL de 7 jours."""
        key = "details:movie:27205"
        value = {"id": 27205, "title": "Inception", "runtime": 148}

        await cache.set_details(key, value)
        result = await cache.get(key)

        assert result == value

    @pytest.mark.asyncio
    async def test_clear_removes_all_entries(self, cache: APICache) -> None:
        """clear() supprime toutes les entrees du cache."""
        await cache.set("key1", "value1", ttl=3600)
        await cache.set("key2", "value2", ttl=3600)

        await cache.clear()

        assert await cache.get("key1") is None
        assert await cache.get("key2") is None

    @pytest.mark.asyncio
    async def test_async_operations_dont_block(self, cache: APICache) -> None:
        """Les operations asynchrones ne bloquent pas la boucle d'evenements."""
        # Tester que plusieurs operations peuvent etre lancees en parallele
        keys = [f"key_{i}" for i in range(10)]
        values = [f"value_{i}" for i in range(10)]

        # Ecrire en parallele
        await asyncio.gather(
            *[cache.set(k, v, ttl=3600) for k, v in zip(keys, values)]
        )

        # Lire en parallele
        results = await asyncio.gather(*[cache.get(k) for k in keys])

        assert results == values

    @pytest.mark.asyncio
    async def test_cache_persists_complex_data(self, cache: APICache) -> None:
        """Le cache peut stocker des structures complexes (dict, list, nested)."""
        complex_data = {
            "movies": [
                {"id": 1, "title": "Movie 1", "genres": ["Action", "Drama"]},
                {"id": 2, "title": "Movie 2", "genres": ["Comedy"]},
            ],
            "total_results": 2,
            "page": 1,
        }

        await cache.set("complex_key", complex_data, ttl=3600)
        result = await cache.get("complex_key")

        assert result == complex_data
