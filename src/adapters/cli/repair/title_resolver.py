"""
Resolution de titres alternatifs via TMDB.

Extrait le titre d'un fichier via guessit, recherche sur TMDB,
et retourne les titres alternatifs (titre original, etc.).
"""

from pathlib import Path


class TitleResolver:
    """
    Resolution de titres alternatifs via TMDB.

    Extrait le titre d'un fichier via guessit, recherche sur TMDB,
    et retourne les titres alternatifs (titre original, etc.).
    Utilise un cache pour eviter les appels API redondants.
    """

    def __init__(self, tmdb_client=None) -> None:
        """
        Args:
            tmdb_client: Client TMDB optionnel. Si None, pas de lookup.
        """
        self._tmdb = tmdb_client
        self._cache: dict[str, list[str]] = {}

    async def get_alternative_names(self, link: Path) -> list[str]:
        """
        Retourne les noms alternatifs pour un symlink via TMDB.

        Args:
            link: Chemin du symlink casse

        Returns:
            Liste de noms alternatifs (vide si pas de TMDB ou pas de resultat)
        """
        if not self._tmdb:
            return []

        from guessit import guessit

        # Extraire titre et annee via guessit
        try:
            info = guessit(link.name)
        except Exception:
            return []

        title = info.get("title", "")
        if not title:
            return []

        year = info.get("year")

        # Verifier le cache
        cache_key = f"{title}:{year}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Recherche TMDB (fr-FR : retourne titre original)
        try:
            results = await self._tmdb.search(title, year=year)
        except Exception:
            self._cache[cache_key] = []
            return []

        alternatives: list[str] = []
        seen_titles: set[str] = {title.lower()}

        for result in results[:3]:
            if result.original_title:
                orig = result.original_title
                if orig.lower() not in seen_titles:
                    alt_name = f"{orig} ({year})" if year else orig
                    alternatives.append(alt_name)
                    seen_titles.add(orig.lower())

        # Recherche supplementaire en anglais pour les films non-latins
        # (ex: film HK dont l'original_title est en chinois mais le NAS utilise le titre EN)
        try:
            import httpx
            client = self._tmdb._get_client()
            params = {"query": title, "language": "en-US", "include_adult": "false"}
            response = await client.get("/search/movie", params=params)
            if response.status_code == 200:
                for item in response.json().get("results", [])[:3]:
                    en_title = item.get("title", "")
                    if en_title and en_title.lower() not in seen_titles:
                        alt_name = f"{en_title} ({year})" if year else en_title
                        alternatives.append(alt_name)
                        seen_titles.add(en_title.lower())
        except Exception:
            pass

        self._cache[cache_key] = alternatives
        return alternatives
