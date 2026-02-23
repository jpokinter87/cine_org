"""
Client TMDB pour la recherche et recuperation de metadonnees films.

Implemente l'interface IMediaAPIClient pour TMDB (The Movie Database).
Utilise le cache persistant et le mecanisme de retry pour gerer
le rate limiting.

Usage:
    cache = APICache()
    client = TMDBClient(api_key="your_key", cache=cache)
    results = await client.search("Avatar", year=2009)
    details = await client.get_details("19995")
    await client.close()
"""

from typing import Optional

import httpx

from src.adapters.api.cache import APICache
from src.adapters.api.retry import request_with_retry
from src.core.ports.api_clients import IMediaAPIClient, MediaDetails, SearchResult
from src.utils.constants import TMDB_GENRE_MAPPING, TMDB_TV_GENRE_MAPPING


class TMDBClient(IMediaAPIClient):
    """
    Client API TMDB pour les metadonnees de films.

    Implemente IMediaAPIClient avec:
    - Recherche de films par titre (avec filtre annee optionnel)
    - Recuperation des details complets d'un film
    - Cache persistant (24h recherches, 7j details)
    - Retry automatique sur rate limiting (429)

    Attributes:
        TMDB_BASE_URL: URL de base de l'API TMDB v3
        TMDB_IMAGE_BASE_URL: URL de base pour les images (posters)

    Example:
        cache = APICache()
        client = TMDBClient(api_key="xxx", cache=cache)

        results = await client.search("Inception", year=2010)
        if results:
            details = await client.get_details(results[0].id)
            print(f"{details.title} ({details.year}) - {details.genres}")

        await client.close()
    """

    TMDB_BASE_URL = "https://api.themoviedb.org/3"
    TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

    def __init__(self, api_key: str, cache: APICache) -> None:
        """
        Initialise le client TMDB.

        Args:
            api_key: Cle API TMDB (Read Access Token v4)
            cache: Instance APICache pour le caching des resultats
        """
        self._api_key = api_key
        self._cache = cache
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        """
        Retourne le client HTTP, le cree si necessaire (lazy init).

        Supporte les deux modes d'authentification TMDB:
        - API Key v3 (32 caracteres hex) : passe en parametre api_key
        - Read Access Token v4 (long JWT) : passe en header Bearer

        Returns:
            httpx.AsyncClient configure pour l'API TMDB
        """
        if self._client is None or self._client.is_closed:
            # Detecter le type de cle : v3 (32 hex) vs v4 (long JWT)
            is_v4_token = len(self._api_key) > 40

            headers = {"Accept": "application/json"}
            params = {}

            if is_v4_token:
                headers["Authorization"] = f"Bearer {self._api_key}"
            else:
                # API Key v3 : passer en parametre de requete
                params["api_key"] = self._api_key

            self._client = httpx.AsyncClient(
                base_url=self.TMDB_BASE_URL,
                headers=headers,
                params=params,
                timeout=30.0,
            )
        return self._client

    @property
    def source(self) -> str:
        """Retourne l'identifiant de la source API."""
        return "tmdb"

    async def search(
        self,
        query: str,
        year: Optional[int] = None,
    ) -> list[SearchResult]:
        """
        Recherche des films par titre.

        Utilise le pattern cache-first: verifie le cache AVANT de faire
        un appel API. Les resultats sont caches pour 24 heures.

        Args:
            query: Titre du film a rechercher
            year: Annee de sortie optionnelle pour filtrer

        Returns:
            Liste de SearchResult (vide si aucun resultat)
        """
        # Build cache key (sans l'annee car on ne filtre plus par annee)
        cache_key = f"tmdb:search:{query}"

        # CACHE-FIRST: Check cache before API call
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Cache miss - make API request
        client = self._get_client()
        params = {
            "query": query,
            "language": "fr-FR",
            "include_adult": "false",
        }
        # Note: On ne filtre PAS par annee dans la requete API car l'annee
        # dans les noms de fichiers est souvent decalee de ±1 an (sortie FR
        # vs sortie originale). L'annee est utilisee pour le scoring ensuite.

        response = await request_with_retry(
            client, "GET", "/search/movie", params=params
        )
        data = response.json()

        # Transform results
        results = []
        for item in data.get("results", []):
            # Extract year from release_date (format: YYYY-MM-DD)
            release_date = item.get("release_date", "")
            item_year = int(release_date[:4]) if release_date else None

            # Extraire titre localise (FR) et titre original
            localized_title = item.get("title", "")
            original_title = item.get("original_title", "")

            results.append(
                SearchResult(
                    id=str(item["id"]),
                    title=localized_title or original_title,
                    original_title=original_title if original_title != localized_title else None,
                    year=item_year,
                    source=self.source,
                )
            )

        # Cache results
        await self._cache.set_search(cache_key, results)

        return results

    async def get_details(self, media_id: str) -> Optional[MediaDetails]:
        """
        Recupere les details complets d'un film.

        Utilise le pattern cache-first: verifie le cache AVANT de faire
        un appel API. Les details sont caches pour 7 jours.

        Args:
            media_id: ID TMDB du film

        Returns:
            MediaDetails avec toutes les informations, ou None si non trouve
        """
        # Build cache key
        cache_key = f"tmdb:details:{media_id}"

        # CACHE-FIRST: Check cache before API call
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Cache miss - make API request avec credits
        client = self._get_client()
        try:
            response = await request_with_retry(
                client,
                "GET",
                f"/movie/{media_id}",
                params={"language": "fr-FR", "append_to_response": "credits"},
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

        data = response.json()

        # Extract year from release_date
        release_date = data.get("release_date", "")
        year = int(release_date[:4]) if release_date else None

        # Extract genres (French names from API, fallback to mapping)
        genres = tuple(
            genre.get("name", TMDB_GENRE_MAPPING.get(genre["id"], "Inconnu"))
            for genre in data.get("genres", [])
        )

        # Build poster URL
        poster_path = data.get("poster_path")
        poster_url = f"{self.TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else None

        # Convert runtime from minutes to seconds
        runtime_minutes = data.get("runtime")
        duration_seconds = runtime_minutes * 60 if runtime_minutes else None

        # Extract credits: director and main cast
        director = None
        cast: tuple[str, ...] = ()
        credits_data = data.get("credits", {})

        # Find director in crew
        for crew_member in credits_data.get("crew", []):
            if crew_member.get("job") == "Director":
                director = crew_member.get("name")
                break

        # Get top 4 actors from cast
        cast_list = credits_data.get("cast", [])[:4]
        cast = tuple(actor.get("name", "") for actor in cast_list if actor.get("name"))

        # Extract vote data
        vote_average = data.get("vote_average")
        vote_count = data.get("vote_count")

        details = MediaDetails(
            id=str(data["id"]),
            title=data.get("title", data.get("original_title", "")),
            original_title=data.get("original_title"),
            year=year,
            genres=genres,
            duration_seconds=duration_seconds,
            overview=data.get("overview"),
            poster_url=poster_url,
            director=director,
            cast=cast,
            vote_average=vote_average,
            vote_count=vote_count,
        )

        # Cache results
        await self._cache.set_details(cache_key, details)

        return details

    async def search_tv(
        self,
        query: str,
        year: Optional[int] = None,
    ) -> list[SearchResult]:
        """
        Recherche des series TV par titre.

        Args:
            query: Titre de la serie a rechercher
            year: Annee de premiere diffusion optionnelle

        Returns:
            Liste de SearchResult (vide si aucun resultat)
        """
        cache_key = f"tmdb:search_tv:{query}"

        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        client = self._get_client()
        params = {
            "query": query,
            "language": "fr-FR",
            "include_adult": "false",
        }

        response = await request_with_retry(
            client, "GET", "/search/tv", params=params
        )
        data = response.json()

        results = []
        for item in data.get("results", []):
            first_air_date = item.get("first_air_date", "")
            item_year = int(first_air_date[:4]) if first_air_date and len(first_air_date) >= 4 else None

            localized_title = item.get("name", "")
            original_title = item.get("original_name", "")

            results.append(
                SearchResult(
                    id=str(item["id"]),
                    title=localized_title or original_title,
                    original_title=original_title if original_title != localized_title else None,
                    year=item_year,
                    source=self.source,
                )
            )

        await self._cache.set_search(cache_key, results)
        return results

    async def get_tv_details(self, tv_id: str) -> Optional[MediaDetails]:
        """
        Recupere les details complets d'une serie TV.

        Inclut les credits (createurs et acteurs principaux).

        Args:
            tv_id: ID TMDB de la serie TV

        Returns:
            MediaDetails avec toutes les informations, ou None si non trouve
        """
        cache_key = f"tmdb:tv_details:{tv_id}"

        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        client = self._get_client()
        try:
            response = await request_with_retry(
                client,
                "GET",
                f"/tv/{tv_id}",
                params={"language": "fr-FR", "append_to_response": "credits"},
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

        data = response.json()

        # Annee depuis first_air_date
        first_air_date = data.get("first_air_date", "")
        year = int(first_air_date[:4]) if first_air_date and len(first_air_date) >= 4 else None

        # Genres (noms FR depuis l'API, fallback sur mapping TV)
        genres = tuple(
            genre.get("name", TMDB_TV_GENRE_MAPPING.get(genre["id"], "Inconnu"))
            for genre in data.get("genres", [])
        )

        # Poster
        poster_path = data.get("poster_path")
        poster_url = f"{self.TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else None

        # Createur(s) : equivalent du realisateur pour les series
        creators = data.get("created_by", [])
        director = ", ".join(c.get("name", "") for c in creators[:2]) if creators else None

        # Acteurs principaux depuis credits
        cast: tuple[str, ...] = ()
        credits_data = data.get("credits", {})
        cast_list = credits_data.get("cast", [])[:5]
        cast = tuple(actor.get("name", "") for actor in cast_list if actor.get("name"))

        # Notes
        vote_average = data.get("vote_average")
        vote_count = data.get("vote_count")

        details = MediaDetails(
            id=str(data["id"]),
            title=data.get("name", data.get("original_name", "")),
            original_title=data.get("original_name"),
            year=year,
            genres=genres,
            overview=data.get("overview"),
            poster_url=poster_url,
            director=director,
            cast=cast,
            vote_average=vote_average,
            vote_count=vote_count,
        )

        await self._cache.set_details(cache_key, details)
        return details

    async def find_by_imdb_id(self, imdb_id: str) -> Optional[MediaDetails]:
        """
        Recherche un film ou une série via son ID IMDb.

        Utilise l'endpoint TMDB /find/{external_id} avec source=imdb_id.
        Si un film est trouvé, retourne ses détails complets via get_details.

        Args:
            imdb_id: ID IMDb (format ttXXXXXXX)

        Returns:
            MediaDetails si trouvé, None sinon
        """
        client = self._get_client()
        try:
            response = await request_with_retry(
                client,
                "GET",
                f"/find/{imdb_id}",
                params={"language": "fr-FR", "external_source": "imdb_id"},
            )
        except httpx.HTTPStatusError:
            return None

        data = response.json()

        # Chercher dans les résultats films
        movie_results = data.get("movie_results", [])
        if movie_results:
            tmdb_id = str(movie_results[0]["id"])
            return await self.get_details(tmdb_id)

        # Chercher dans les résultats séries TV
        tv_results = data.get("tv_results", [])
        if tv_results:
            item = tv_results[0]
            # Construire un MediaDetails directement
            release_date = item.get("first_air_date", "")
            year = int(release_date[:4]) if release_date and len(release_date) >= 4 else None
            poster_path = item.get("poster_path")
            poster_url = f"{self.TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else None

            return MediaDetails(
                id=str(item["id"]),
                title=item.get("name", item.get("original_name", "")),
                original_title=item.get("original_name"),
                year=year,
                genres=tuple(
                    TMDB_GENRE_MAPPING.get(gid, "Inconnu")
                    for gid in item.get("genre_ids", [])
                ),
                overview=item.get("overview"),
                poster_url=poster_url,
                vote_average=item.get("vote_average"),
                vote_count=item.get("vote_count"),
            )

        return None

    async def get_external_ids(self, media_id: str) -> Optional[dict[str, str | None]]:
        """
        Recupere les IDs externes (IMDb, Wikidata, etc.) pour un film.

        Args:
            media_id: ID TMDB du film

        Returns:
            Dictionnaire avec les IDs externes, ou None si non trouve
        """
        client = self._get_client()
        try:
            response = await request_with_retry(
                client,
                "GET",
                f"/movie/{media_id}/external_ids",
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

        data = response.json()

        return {
            "imdb_id": data.get("imdb_id"),
            "wikidata_id": data.get("wikidata_id"),
            "facebook_id": data.get("facebook_id"),
            "instagram_id": data.get("instagram_id"),
            "twitter_id": data.get("twitter_id"),
        }

    async def close(self) -> None:
        """
        Ferme le client HTTP.

        Doit etre appele a la fin de l'utilisation pour liberer
        les ressources reseau.
        """
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
