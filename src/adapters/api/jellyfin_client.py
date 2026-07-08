"""Client minimal de l'API Jellyfin (scan ciblé + sessions actives)."""

from __future__ import annotations

import httpx
from loguru import logger

from src.adapters.api.retry import request_with_retry


class JellyfinClient:
    """Appels API Jellyfin nécessaires au partage : rafraîchir une bibliothèque,
    lister les sessions de lecture en cours."""

    def __init__(self, base_url: str, api_key: str | None) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None
        self._library_ids: dict[str, str] = {}

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "X-Emby-Token": self._api_key or "",
                    "Accept": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def _library_id(self, name: str) -> str | None:
        if name in self._library_ids:
            return self._library_ids[name]
        client = self._get_client()
        resp = await request_with_retry(client, "GET", "/Library/VirtualFolders")
        for folder in resp.json():
            if folder.get("Name") == name and folder.get("ItemId"):
                self._library_ids[name] = folder["ItemId"]
                return folder["ItemId"]
        logger.warning("Bibliothèque Jellyfin introuvable : {}", name)
        return None

    async def scan_libraries(self) -> None:
        """Déclenche un scan des médiathèques (POST /Library/Refresh).

        C'est le seul déclencheur qui fait découvrir à Jellyfin les fichiers
        fraîchement ajoutés : le refresh ciblé ``POST /Items/{id}/Refresh`` ne
        rafraîchit que les métadonnées des enfants déjà connus, sans ré-énumérer
        le dossier. Le scan est asynchrone côté Jellyfin (≈ 45 s en incrémental) ;
        interroger ``library_item_count`` permet d'attendre l'indexation.
        """
        client = self._get_client()
        await request_with_retry(client, "POST", "/Library/Refresh")

    async def library_item_count(self, name: str) -> int:
        """Nombre d'items indexés dans la bibliothèque nommée (0 si absente)."""
        item_id = await self._library_id(name)
        if item_id is None:
            return 0
        client = self._get_client()
        resp = await request_with_retry(
            client,
            "GET",
            "/Items",
            params={"ParentId": item_id, "Recursive": "true", "Limit": "0"},
        )
        return int(resp.json().get("TotalRecordCount", 0))

    async def get_active_sessions(self) -> list[dict]:
        """Retourne la liste des sessions de lecture actives."""
        client = self._get_client()
        resp = await request_with_retry(client, "GET", "/Sessions")
        return resp.json()

    async def close(self) -> None:
        """Ferme le client HTTP sous-jacent."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
