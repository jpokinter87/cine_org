"""
Client TVDB API v4 pour les series TV.

Implemente IMediaAPIClient pour rechercher et recuperer les metadonnees
des series TV depuis TVDB. Gere l'authentification JWT, le caching et
le rate limiting automatiquement.

Reference API: https://thetvdb.github.io/v4-api/
"""

from datetime import datetime, timedelta
from typing import Optional

import httpx

from src.adapters.api.cache import APICache
from src.adapters.api.retry import request_with_retry
from src.core.ports.api_clients import IMediaAPIClient, MediaDetails, SearchResult


class TVDBClient(IMediaAPIClient):
    """
    Client TVDB pour la recherche de series TV.

    Utilise l'API TVDB v4 avec authentification JWT. Le token est obtenu
    automatiquement a la premiere requete et rafraichi avant expiration.

    Attributes:
        BASE_URL: URL de base de l'API TVDB v4

    Example:
        cache = APICache(cache_dir=".cache/api")
        client = TVDBClient(api_key="your-api-key", cache=cache)
        results = await client.search("Breaking Bad")
        details = await client.get_details("81189")
        await client.close()
    """

    BASE_URL = "https://api4.thetvdb.com/v4"

    def __init__(self, api_key: str, cache: APICache) -> None:
        """
        Initialise le client TVDB.

        Args:
            api_key: Cle API TVDB (Project API Key depuis le compte TVDB)
            cache: Instance de APICache pour le caching des resultats
        """
        self._api_key = api_key
        self._cache = cache
        self._token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """
        Retourne le client HTTP, cree s'il n'existe pas.

        Utilise un client unique pour beneficier du connection pooling.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
        return self._client

    async def _ensure_token(self) -> str:
        """
        S'assure qu'un token JWT valide est disponible.

        Obtient un nouveau token si:
        - Aucun token n'existe
        - Le token est expire ou proche de l'expiration

        Le token TVDB est valide 1 mois, on le rafraichit 1 jour avant.

        Returns:
            Token JWT valide
        """
        if self._token and self._token_expiry and datetime.now() < self._token_expiry:
            return self._token

        # Obtenir un nouveau token
        client = await self._get_client()
        response = await client.post(
            "/login",
            json={"apikey": self._api_key},
        )
        response.raise_for_status()
        data = response.json()

        self._token = data["data"]["token"]
        # Token valide 1 mois, rafraichir 1 jour avant expiration
        self._token_expiry = datetime.now() + timedelta(days=29)
        return self._token

    def _get_auth_headers(self) -> dict[str, str]:
        """Retourne les headers d'authentification avec le token JWT."""
        if not self._token:
            raise RuntimeError("Token not available. Call _ensure_token() first.")
        return {"Authorization": f"Bearer {self._token}"}

    async def search(
        self,
        query: str,
        year: Optional[int] = None,
    ) -> list[SearchResult]:
        """
        Recherche des series TV par titre.

        Verifie le cache avant d'appeler l'API. Les resultats sont caches
        pendant 24 heures.

        Args:
            query: Titre de la serie a rechercher
            year: Annee optionnelle pour filtrer les resultats

        Returns:
            Liste de SearchResult avec id, title, year, source="tvdb"
        """
        # Cache-first: verifier le cache avant toute requete HTTP
        cache_key = f"tvdb:search:{query}:{year}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Cache miss: obtenir le token et faire la requete
        await self._ensure_token()
        client = await self._get_client()

        params = {"q": query, "type": "series"}
        if year:
            params["year"] = str(year)

        response = await request_with_retry(
            client,
            "GET",
            "/search",
            params=params,
            headers=self._get_auth_headers(),
        )
        data = response.json()

        # Convertir les resultats en SearchResult
        results = [
            SearchResult(
                id=str(item["id"]),
                title=item["name"],
                year=int(item["year"]) if item.get("year") else None,
                source="tvdb",
            )
            for item in data.get("data", [])
        ]

        # Cacher les resultats
        await self._cache.set_search(cache_key, results)
        return results

    async def get_details(self, media_id: str) -> Optional[MediaDetails]:
        """
        Recupere les details complets d'une serie.

        Verifie le cache avant d'appeler l'API. Les details sont caches
        pendant 7 jours.

        Args:
            media_id: ID TVDB de la serie

        Returns:
            MediaDetails avec les informations completes, ou None si non trouve
        """
        # Cache-first: verifier le cache avant toute requete HTTP
        cache_key = f"tvdb:details:{media_id}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Cache miss: obtenir le token et faire la requete
        await self._ensure_token()
        client = await self._get_client()

        try:
            response = await request_with_retry(
                client,
                "GET",
                f"/series/{media_id}/extended",
                headers=self._get_auth_headers(),
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

        data = response.json()
        series = data.get("data", {})

        # Extraire l'annee depuis firstAired ou year
        year = None
        if series.get("year"):
            year = int(series["year"])
        elif series.get("firstAired"):
            year = int(series["firstAired"][:4])

        # Extraire les genres
        genres = tuple(g["name"] for g in series.get("genres", []))

        # Construire MediaDetails
        details = MediaDetails(
            id=str(series["id"]),
            title=series["name"],
            original_title=series.get("originalName"),
            year=year,
            genres=genres,
            duration_seconds=None,  # Series n'ont pas de duree unique
            overview=series.get("overview"),
            poster_url=series.get("image"),
        )

        # Cacher les details
        await self._cache.set_details(cache_key, details)
        return details

    @property
    def source(self) -> str:
        """Retourne l'identifiant de la source API."""
        return "tvdb"

    async def close(self) -> None:
        """Ferme le client HTTP et libere les ressources."""
        if self._client:
            await self._client.aclose()
            self._client = None
