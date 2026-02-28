"""
Client TVDB API v3 pour les series TV.

Implemente IMediaAPIClient pour rechercher et recuperer les metadonnees
des series TV depuis TVDB. Gere l'authentification JWT, le caching et
le rate limiting automatiquement.

Note: Utilise l'API v3 (legacy) car plus compatible avec les cles existantes.
Reference API: https://api.thetvdb.com/swagger
"""

from datetime import datetime, timedelta
from typing import Optional

import httpx

from src.adapters.api.cache import APICache
from src.adapters.api.retry import request_with_retry
from src.core.ports.api_clients import (
    EpisodeDetails,
    IMediaAPIClient,
    MediaDetails,
    SearchResult,
)


class TVDBClient(IMediaAPIClient):
    """
    Client TVDB pour la recherche de series TV.

    Utilise l'API TVDB v3 avec authentification JWT. Le token est obtenu
    automatiquement a la premiere requete et rafraichi avant expiration.

    Attributes:
        BASE_URL: URL de base de l'API TVDB v3

    Example:
        cache = APICache(cache_dir=".cache/api")
        client = TVDBClient(api_key="your-api-key", cache=cache)
        results = await client.search("Breaking Bad")
        details = await client.get_details("81189")
        await client.close()
    """

    BASE_URL = "https://api.thetvdb.com"

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

        # API v3: token directement dans la reponse (pas dans "data")
        self._token = data["token"]
        # Token valide ~1 semaine, rafraichir 1 jour avant expiration
        self._token_expiry = datetime.now() + timedelta(days=6)
        return self._token

    def _get_auth_headers(self, language: Optional[str] = None) -> dict[str, str]:
        """
        Retourne les headers d'authentification avec le token JWT.

        Args:
            language: Code langue ISO 639-1 optionnel (ex: "fr", "en")
                     pour demander les donnees dans cette langue.
        """
        if not self._token:
            raise RuntimeError("Token not available. Call _ensure_token() first.")
        headers = {"Authorization": f"Bearer {self._token}"}
        if language:
            headers["Accept-Language"] = language
        return headers

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

        # API v3: endpoint /search/series avec parametre name
        params = {"name": query}

        try:
            response = await request_with_retry(
                client,
                "GET",
                "/search/series",
                params=params,
                headers=self._get_auth_headers(language="fr"),
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # TVDB retourne 404 quand aucune serie ne correspond
                return []
            raise

        data = response.json()

        # Aussi rechercher en anglais pour obtenir le titre original
        en_names: dict[str, str] = {}
        try:
            en_response = await request_with_retry(
                client,
                "GET",
                "/search/series",
                params=params,
                headers=self._get_auth_headers(language="en"),
            )
            en_data = en_response.json()
            for item in en_data.get("data", []):
                en_names[str(item["id"])] = item.get("seriesName", "")
        except Exception:
            pass  # Si la requete EN echoue, on continue sans

        # API v3: resultats dans "data" array
        results = []
        for item in data.get("data", []):
            # Extraire l'annee depuis firstAired (format: YYYY-MM-DD)
            first_aired = item.get("firstAired", "")
            item_year = int(first_aired[:4]) if first_aired and len(first_aired) >= 4 else None

            # Filtrer par annee si specifie
            if year and item_year and item_year != year:
                continue

            series_id = str(item["id"])
            fr_title = item.get("seriesName", "")
            # Titre anglais depuis la recherche EN, sinon fallback sur aliases
            en_title = en_names.get(series_id)
            if not en_title or en_title == fr_title:
                # Pas de titre EN different, essayer les aliases
                aliases = item.get("aliases", [])
                en_title = aliases[0] if aliases else None

            results.append(
                SearchResult(
                    id=series_id,
                    title=fr_title,
                    original_title=en_title,
                    year=item_year,
                    source="tvdb",
                )
            )

        # Cacher les resultats
        await self._cache.set_search(cache_key, results)
        return results

    async def get_details(self, media_id: str) -> Optional[MediaDetails]:
        """
        Recupere les details complets d'une serie.

        Privilegie le titre en francais, avec fallback sur l'anglais
        si la traduction francaise n'existe pas.

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

        # Essayer d'abord en francais
        series = await self._fetch_series_details(client, media_id, language="fr")
        if series is None:
            return None

        # Si le titre francais est vide, essayer en anglais
        title = series.get("seriesName", "")
        if not title:
            series_en = await self._fetch_series_details(client, media_id, language="en")
            if series_en:
                title = series_en.get("seriesName", "")
                # Utiliser les autres donnees anglaises si meilleures
                if not series.get("overview") and series_en.get("overview"):
                    series = series_en

        # Extraire l'annee depuis firstAired (format: YYYY-MM-DD)
        year = None
        first_aired = series.get("firstAired", "")
        if first_aired and len(first_aired) >= 4:
            year = int(first_aired[:4])

        # API v3: genres est une liste de strings
        genres = tuple(series.get("genre", []))

        # Construire l'URL du poster
        # L'API v3 retourne des paths variés :
        #   "/banners/posters/xxx.jpg" (déjà complet)
        #   "posters/xxx.jpg" ou "series/xxx/posters/xxx.jpg" (besoin de /banners/)
        #   "v4/series/xxx/posters/xxx.jpg" (besoin de /banners/)
        poster_path = series.get("poster")
        if poster_path:
            if not poster_path.startswith("/"):
                poster_path = f"/{poster_path}"
            if not poster_path.startswith("/banners/"):
                poster_path = f"/banners{poster_path}"
            poster_url = f"https://artworks.thetvdb.com{poster_path}"
        else:
            poster_url = None

        # Construire MediaDetails
        details = MediaDetails(
            id=str(series["id"]),
            title=title or series.get("seriesName", ""),
            original_title=series.get("aliases", [None])[0] if series.get("aliases") else None,
            year=year,
            genres=genres,
            duration_seconds=None,  # Series n'ont pas de duree unique
            overview=series.get("overview"),
            poster_url=poster_url,
        )

        # Cacher les details
        await self._cache.set_details(cache_key, details)
        return details

    async def _fetch_series_details(
        self,
        client: httpx.AsyncClient,
        media_id: str,
        language: str,
    ) -> Optional[dict]:
        """
        Recupere les donnees brutes d'une serie depuis l'API.

        Args:
            client: Client HTTP
            media_id: ID TVDB de la serie
            language: Code langue (fr, en)

        Returns:
            Dictionnaire des donnees serie ou None
        """
        try:
            response = await request_with_retry(
                client,
                "GET",
                f"/series/{media_id}",
                headers=self._get_auth_headers(language=language),
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

        data = response.json()
        return data.get("data", {})

    async def get_episode_details(
        self,
        series_id: str,
        season: int,
        episode: int,
    ) -> Optional[EpisodeDetails]:
        """
        Recupere les details d'un episode specifique.

        Privilegie le titre en francais, avec fallback sur l'anglais
        si la traduction francaise n'existe pas.

        Utilise un fetch bulk par saison : le premier appel pour un episode
        d'une saison charge tous les episodes de cette saison en une seule
        requete API, les suivants sont servis depuis le cache.

        Args:
            series_id: ID TVDB de la serie
            season: Numero de saison
            episode: Numero d'episode

        Returns:
            EpisodeDetails avec le titre de l'episode, ou None si non trouve
        """
        # Cache-first: verifier le cache avant toute requete HTTP
        cache_key = f"tvdb:episode:{series_id}:S{season:02d}E{episode:02d}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Cache miss: pré-peupler le cache via bulk fetch de la saison
        await self._fetch_season_episodes(series_id, season)

        # Vérifier si l'épisode est maintenant en cache après le bulk fetch
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Épisode non trouvé dans la saison (numéro invalide)
        return None

    async def _fetch_season_episodes(
        self,
        series_id: str,
        season: int,
    ) -> dict[int, EpisodeDetails]:
        """
        Charge tous les episodes d'une saison en bulk et les met en cache.

        Si la saison a deja ete chargee (cle bulk marker), retourne
        immediatement sans appel API.

        Args:
            series_id: ID TVDB de la serie
            season: Numero de saison

        Returns:
            Dictionnaire episode_number -> EpisodeDetails
        """
        # Vérifier si la saison a déjà été pré-peuplée
        bulk_key = f"tvdb:season_bulk:{series_id}:S{season:02d}"
        cached_bulk = await self._cache.get(bulk_key)
        if cached_bulk is not None:
            return {}  # Déjà pré-peuplé, les épisodes sont dans le cache individuel

        await self._ensure_token()
        client = await self._get_client()

        # Fetch FR puis EN pour titres fallback
        fr_episodes = await self._fetch_all_season_episodes_raw(
            client, series_id, season, language="fr"
        )
        en_episodes = await self._fetch_all_season_episodes_raw(
            client, series_id, season, language="en"
        )

        # Index EN par numéro d'épisode pour fallback titre
        en_by_num: dict[int, dict] = {}
        for ep in en_episodes:
            ep_num = ep.get("airedEpisodeNumber")
            if ep_num is not None:
                en_by_num[ep_num] = ep

        # Construire et cacher chaque épisode
        result: dict[int, EpisodeDetails] = {}
        for ep_data in fr_episodes:
            ep_num = ep_data.get("airedEpisodeNumber")
            if ep_num is None:
                continue

            # Fallback titre EN si FR vide
            episode_title = ep_data.get("episodeName", "")
            if not episode_title:
                en_ep = en_by_num.get(ep_num)
                if en_ep:
                    episode_title = en_ep.get("episodeName", "")
                    if episode_title:
                        ep_data = en_ep

            details = EpisodeDetails(
                id=str(ep_data.get("id", "")),
                title=ep_data.get("episodeName", ""),
                season_number=ep_data.get("airedSeason", season),
                episode_number=ep_num,
                overview=ep_data.get("overview"),
                air_date=ep_data.get("firstAired"),
            )

            # Cacher individuellement
            ep_cache_key = f"tvdb:episode:{series_id}:S{season:02d}E{ep_num:02d}"
            await self._cache.set_details(ep_cache_key, details)
            result[ep_num] = details

        # Cacher aussi le count de la saison
        count_key = f"tvdb:season_count:{series_id}:S{season:02d}"
        await self._cache.set_details(count_key, len(fr_episodes))

        # Marquer la saison comme pré-peuplée
        await self._cache.set_details(bulk_key, True)

        return result

    async def _fetch_all_season_episodes_raw(
        self,
        client: httpx.AsyncClient,
        series_id: str,
        season: int,
        language: str,
    ) -> list[dict]:
        """
        Recupere toutes les donnees brutes des episodes d'une saison (paginee).

        Args:
            client: Client HTTP
            series_id: ID TVDB de la serie
            season: Numero de saison
            language: Code langue (fr, en)

        Returns:
            Liste des dictionnaires episode bruts
        """
        all_episodes: list[dict] = []
        page = 1

        while True:
            try:
                params: dict[str, str] = {"airedSeason": str(season)}
                if page > 1:
                    params["page"] = str(page)

                response = await request_with_retry(
                    client,
                    "GET",
                    f"/series/{series_id}/episodes/query",
                    params=params,
                    headers=self._get_auth_headers(language=language),
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    return []
                raise

            data = response.json()
            episodes = data.get("data", [])
            all_episodes.extend(episodes)

            # Vérifier pagination
            links = data.get("links", {})
            last_page = links.get("last", 1)
            if page >= last_page:
                break
            page += 1

        return all_episodes

    async def get_season_episode_count(
        self, series_id: str, season: int
    ) -> Optional[int]:
        """
        Retourne le nombre d'episodes d'une saison pour une serie.

        Utilise le bulk fetch par saison si pas en cache, ce qui
        pre-peuple aussi les details de chaque episode.

        Args:
            series_id: ID TVDB de la serie
            season: Numero de saison

        Returns:
            Nombre d'episodes, ou None si la saison n'existe pas (404)
        """
        cache_key = f"tvdb:season_count:{series_id}:S{season:02d}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Utiliser le bulk fetch qui cache aussi le count
        episodes = await self._fetch_season_episodes(series_id, season)

        # Re-vérifier le cache (le bulk fetch l'a peuplé)
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Si la saison n'existe pas (0 épisodes retournés par le bulk)
        return len(episodes) if episodes else None

    @property
    def source(self) -> str:
        """Retourne l'identifiant de la source API."""
        return "tvdb"

    async def close(self) -> None:
        """Ferme le client HTTP et libere les ressources."""
        if self._client:
            await self._client.aclose()
            self._client = None
