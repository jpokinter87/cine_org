"""
Cache persistant pour les API externes avec TTL differencies.

Le cache utilise diskcache pour la persistence sur disque, ce qui permet
de conserver les donnees entre les redemarrages de l'application.

TTL par defaut:
- Recherches (SEARCH_TTL): 24 heures - les resultats de recherche changent souvent
- Details (DETAILS_TTL): 7 jours - les metadonnees d'un film/serie changent rarement
"""

import asyncio
from functools import partial
from typing import Any, Optional

from diskcache import Cache


class APICache:
    """
    Cache asynchrone avec TTL pour les appels API.

    Utilise diskcache pour la persistence et run_in_executor pour
    les operations asynchrones non-bloquantes.

    Attributes:
        SEARCH_TTL: Duree de vie des resultats de recherche (24h)
        DETAILS_TTL: Duree de vie des details (7 jours)

    Example:
        cache = APICache(cache_dir=".cache/api")
        await cache.set_search("tmdb:search:inception", results)
        data = await cache.get("tmdb:search:inception")
    """

    SEARCH_TTL = 24 * 60 * 60  # 24 heures en secondes (86400)
    DETAILS_TTL = 7 * 24 * 60 * 60  # 7 jours en secondes (604800)

    def __init__(self, cache_dir: str = ".cache/api") -> None:
        """
        Initialise le cache avec un repertoire de stockage.

        Args:
            cache_dir: Chemin vers le repertoire du cache (cree si inexistant)
        """
        self._cache = Cache(cache_dir)

    async def get(self, key: str) -> Optional[Any]:
        """
        Recupere une valeur du cache.

        Args:
            key: Cle unique identifiant la donnee

        Returns:
            La valeur stockee ou None si absente ou expiree
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._cache.get, key)

    async def set(self, key: str, value: Any, ttl: int) -> None:
        """
        Stocke une valeur dans le cache avec un TTL.

        Args:
            key: Cle unique identifiant la donnee
            value: Valeur a stocker (doit etre serializable)
            ttl: Duree de vie en secondes
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, partial(self._cache.set, key, value, expire=ttl)
        )

    async def set_search(self, key: str, value: Any) -> None:
        """
        Stocke un resultat de recherche (TTL de 24h).

        Args:
            key: Cle unique (ex: "tmdb:search:inception")
            value: Resultats de recherche
        """
        await self.set(key, value, self.SEARCH_TTL)

    async def set_details(self, key: str, value: Any) -> None:
        """
        Stocke les details d'un media (TTL de 7 jours).

        Args:
            key: Cle unique (ex: "tmdb:movie:27205")
            value: Details du media
        """
        await self.set(key, value, self.DETAILS_TTL)

    async def clear(self) -> None:
        """Supprime toutes les entrees du cache."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._cache.clear)

    def close(self) -> None:
        """Ferme la connexion au cache (a appeler a la fin)."""
        self._cache.close()
