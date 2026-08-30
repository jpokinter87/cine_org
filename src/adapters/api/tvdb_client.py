"""
Client TVDB API v4 pour les series TV.

Implemente IMediaAPIClient pour rechercher et recuperer les metadonnees
des series TV depuis TVDB. Gere l'authentification JWT, le caching et
le rate limiting automatiquement.

Difference majeure avec la v3 : la localisation ne passe plus par l'en-tete
``Accept-Language`` mais par des endpoints dedies (``/translations/{lang}``,
``/episodes/{season-type}/{lang}``) dont les codes langue sont en ISO 639-3
("fra", "eng") et non ISO 639-1.

Reference API: https://thetvdb.github.io/v4-api/
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

    Utilise l'API TVDB v4 avec authentification JWT. Le token est obtenu
    automatiquement a la premiere requete et rafraichi avant expiration.

    Les episodes d'une serie sont recuperes en un seul aller-retour par
    langue (l'endpoint v4 renvoie toutes les saisons d'un coup), puis
    servis depuis le cache pour tous les appels ulterieurs.

    Attributes:
        BASE_URL: URL de base de l'API TVDB v4
        SEASON_TYPE: Ordre de saison utilise (canon TVDB par defaut)
        LANG_FR / LANG_EN: Codes langue ISO 639-3 attendus par la v4

    Example:
        cache = APICache(cache_dir=".cache/api")
        client = TVDBClient(api_key="your-api-key", cache=cache)
        results = await client.search("Breaking Bad")
        details = await client.get_details("81189")
        await client.close()
    """

    BASE_URL = "https://api4.thetvdb.com/v4"
    SEASON_TYPE = "default"
    LANG_FR = "fra"
    LANG_EN = "eng"

    def __init__(self, api_key: str, cache: APICache) -> None:
        """
        Initialise le client TVDB.

        Args:
            api_key: Cle API TVDB v4 (generee depuis le dashboard TVDB)
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

        Obtient un nouveau token si aucun n'existe ou s'il est proche
        de l'expiration. Le token TVDB est valide 1 mois, on le rafraichit
        avec une semaine de marge.

        Returns:
            Token JWT valide
        """
        if self._token and self._token_expiry and datetime.now() < self._token_expiry:
            return self._token

        client = await self._get_client()
        response = await client.post(
            "/login",
            json={"apikey": self._api_key},
        )
        response.raise_for_status()
        data = response.json()

        self._token = data["data"]["token"]
        self._token_expiry = datetime.now() + timedelta(days=23)
        return self._token

    def _get_auth_headers(self) -> dict[str, str]:
        """
        Retourne les headers d'authentification avec le token JWT.

        La v4 n'accepte plus ``Accept-Language`` : la langue se choisit
        via l'URL des endpoints de traduction.
        """
        if not self._token:
            raise RuntimeError("Token indisponible. Appeler _ensure_token() d'abord.")
        return {"Authorization": f"Bearer {self._token}"}

    async def _get_json(
        self,
        url: str,
        params: Optional[dict] = None,
    ) -> Optional[dict]:
        """
        Execute un GET authentifie et renvoie la charge utile ``data``.

        Args:
            url: Chemin relatif de l'endpoint
            params: Parametres de requete optionnels

        Returns:
            Contenu du champ ``data``, ou None si la ressource est absente (404)
        """
        await self._ensure_token()
        client = await self._get_client()

        try:
            response = await request_with_retry(
                client,
                "GET",
                url,
                params=params,
                headers=self._get_auth_headers(),
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

        return response.json().get("data")

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
        cache_key = f"tvdb4:search:{query}:{year}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        data = await self._get_json(
            "/search",
            params={"query": query, "type": "series"},
        )
        if data is None:
            return []

        results = []
        for item in data:
            item_year = _parse_year(item.get("year")) or _parse_year(
                item.get("first_air_time")
            )
            if year and item_year and item_year != year:
                continue

            # L'id v4 est prefixe ("series-81189") : seul tvdb_id est exploitable.
            series_id = item.get("tvdb_id")
            if not series_id:
                continue

            name = item.get("name") or ""
            translations = item.get("translations") or {}
            title = translations.get(self.LANG_FR) or name
            original_title = name if name and name != title else None

            results.append(
                SearchResult(
                    id=str(series_id),
                    title=title,
                    original_title=original_title,
                    year=item_year,
                    source="tvdb",
                )
            )

        await self._cache.set_search(cache_key, results)
        return results

    async def find_series_id_by_imdb_id(self, imdb_id: str) -> Optional[str]:
        """
        Retrouve l'ID TVDB d'une serie a partir de son ID IMDb.

        Certains arcs ou saisons sont publies sur IMDb comme titres distincts
        (ex. tt14986406, *Bleach: Thousand-Year Blood War*, rattache par TVDB a
        la saison 17 de BLEACH). L'endpoint les renvoie alors enveloppes dans
        ``season`` ou ``episode`` : on remonte a la serie parente via
        ``seriesId``.

        Args:
            imdb_id: ID IMDb de la serie (format "tt1234567")

        Returns:
            ID TVDB sous forme de chaine, ou None si aucune correspondance
        """
        data = await self._get_json(f"/search/remoteid/{imdb_id}")
        if not data:
            return None

        # L'endpoint resout aussi les films et les personnes : seules les
        # correspondances rattachables a une serie sont retenues, la
        # correspondance serie directe primant sur saison puis episode.
        for key, id_field in (
            ("series", "id"),
            ("season", "seriesId"),
            ("episode", "seriesId"),
        ):
            for item in data:
                match = item.get(key)
                if match and match.get(id_field):
                    return str(match[id_field])

        return None

    async def get_details(self, media_id: str) -> Optional[MediaDetails]:
        """
        Recupere les details complets d'une serie.

        Combine le record etendu (genres, poster, annee) et les traductions
        francaise puis anglaise pour le titre et le resume.

        Verifie le cache avant d'appeler l'API. Les details sont caches
        pendant 7 jours.

        Args:
            media_id: ID TVDB de la serie

        Returns:
            MediaDetails avec les informations completes, ou None si non trouve
        """
        cache_key = f"tvdb4:details:{media_id}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        series = await self._get_json(f"/series/{media_id}/extended")
        if series is None:
            return None

        fr = await self._get_json(f"/series/{media_id}/translations/{self.LANG_FR}")
        en = await self._get_json(f"/series/{media_id}/translations/{self.LANG_EN}")
        fr = fr or {}
        en = en or {}

        base_name = series.get("name") or ""
        title = fr.get("name") or base_name
        original_title = en.get("name") or base_name
        if original_title == title:
            original_title = None

        overview = fr.get("overview") or series.get("overview") or en.get("overview")

        genres = tuple(g["name"] for g in series.get("genres") or [] if g.get("name"))

        details = MediaDetails(
            id=str(series["id"]),
            title=title,
            original_title=original_title,
            year=_parse_year(series.get("year"))
            or _parse_year(series.get("firstAired")),
            genres=genres,
            duration_seconds=None,  # Series n'ont pas de duree unique
            overview=overview,
            poster_url=series.get("image") or None,  # URL deja absolue en v4
        )
        # NB: is_tv reste a False. Ce drapeau signale une serie *TMDB* : le
        # positionner ici ferait etiqueter la source "tmdb_tv" (routes/validation)
        # alors que l'id est un id TVDB, et l'aval interrogerait TMDB avec.

        await self._cache.set_details(cache_key, details)
        return details

    async def _load_episodes(self, series_id: str) -> list[EpisodeDetails]:
        """
        Charge tous les episodes d'une serie, toutes saisons confondues.

        L'endpoint v4 renvoie la serie complete (specials inclus) en une
        requete par langue. Le resultat est mis en cache : les appels
        suivants (details d'un episode, comptage, liste complete) le
        relisent sans nouvel aller-retour reseau.

        Les titres francais sont privilegies, avec repli sur l'anglais
        quand la traduction est absente (chaine vide ou None).

        Args:
            series_id: ID TVDB de la serie

        Returns:
            Liste d'EpisodeDetails, specials (saison 0) compris
        """
        cache_key = f"tvdb4:episodes:{series_id}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        fr_raw = await self._fetch_episodes_raw(series_id, self.LANG_FR)
        en_raw = await self._fetch_episodes_raw(series_id, self.LANG_EN)

        en_by_key = {(ep.get("seasonNumber"), ep.get("number")): ep for ep in en_raw}

        # Une serie sans aucune traduction francaise se rabat sur l'anglais.
        base_raw = fr_raw or en_raw

        episodes: list[EpisodeDetails] = []
        for ep in base_raw:
            season = ep.get("seasonNumber")
            number = ep.get("number")
            if season is None or number is None:
                continue

            en_ep = en_by_key.get((season, number)) or {}
            title = ep.get("name") or en_ep.get("name") or ""

            episodes.append(
                EpisodeDetails(
                    id=str(ep.get("id", "")),
                    title=title,
                    season_number=season,
                    episode_number=number,
                    overview=ep.get("overview") or en_ep.get("overview"),
                    air_date=ep.get("aired"),
                )
            )

        await self._cache.set_details(cache_key, episodes)
        return episodes

    async def _fetch_episodes_raw(
        self,
        series_id: str,
        language: str,
    ) -> list[dict]:
        """
        Recupere les episodes bruts d'une serie dans une langue donnee.

        Suit la pagination via ``links.next`` (500 episodes par page).

        Args:
            series_id: ID TVDB de la serie
            language: Code langue ISO 639-3 (fra, eng)

        Returns:
            Liste des dictionnaires episode bruts (vide si serie inconnue)
        """
        await self._ensure_token()
        client = await self._get_client()

        all_episodes: list[dict] = []
        page = 0

        while True:
            try:
                response = await request_with_retry(
                    client,
                    "GET",
                    f"/series/{series_id}/episodes/{self.SEASON_TYPE}/{language}",
                    params={"page": str(page)},
                    headers=self._get_auth_headers(),
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    return all_episodes
                raise

            payload = response.json()
            all_episodes.extend((payload.get("data") or {}).get("episodes") or [])

            if not (payload.get("links") or {}).get("next"):
                break
            page += 1

        return all_episodes

    async def get_episode_details(
        self,
        series_id: str,
        season: int,
        episode: int,
    ) -> Optional[EpisodeDetails]:
        """
        Recupere les details d'un episode specifique.

        Args:
            series_id: ID TVDB de la serie
            season: Numero de saison
            episode: Numero d'episode

        Returns:
            EpisodeDetails avec le titre de l'episode, ou None si non trouve
        """
        for ep in await self._load_episodes(series_id):
            if ep.season_number == season and ep.episode_number == episode:
                return ep
        return None

    async def get_season_episode_count(
        self, series_id: str, season: int
    ) -> Optional[int]:
        """
        Retourne le nombre d'episodes d'une saison pour une serie.

        Args:
            series_id: ID TVDB de la serie
            season: Numero de saison

        Returns:
            Nombre d'episodes, ou None si la saison n'existe pas
        """
        count = sum(
            1
            for ep in await self._load_episodes(series_id)
            if ep.season_number == season
        )
        return count or None

    async def get_all_episodes(self, series_id: str) -> list[EpisodeDetails]:
        """
        Recupere tous les episodes d'une serie (saisons >= 1).

        Les specials (saison 0) sont exclus : ils ne correspondent a aucun
        fichier attendu dans la videotheque et fausseraient la completude.

        Args:
            series_id: ID TVDB de la serie

        Returns:
            Liste d'EpisodeDetails (season_number, episode_number, air_date, title)
        """
        return [
            ep for ep in await self._load_episodes(series_id) if ep.season_number != 0
        ]

    @property
    def source(self) -> str:
        """Retourne l'identifiant de la source API."""
        return "tvdb"

    async def close(self) -> None:
        """Ferme le client HTTP et libere les ressources."""
        if self._client:
            await self._client.aclose()
            self._client = None


def _parse_year(value: Optional[str]) -> Optional[int]:
    """
    Extrait une annee depuis une chaine v4 ("2008" ou "2008-01-20").

    Args:
        value: Valeur brute renvoyee par l'API

    Returns:
        Annee sur 4 chiffres, ou None si la valeur est inexploitable
    """
    if not value or len(str(value)) < 4:
        return None
    try:
        return int(str(value)[:4])
    except ValueError:
        return None
