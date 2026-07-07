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
        logger.warning("Bibliothèque Jellyfin introuvable : %s", name)
        return None

    async def refresh_library(self, name: str) -> None:
        """Lance un scan ciblé de la bibliothèque nommée (no-op si absente)."""
        item_id = await self._library_id(name)
        if item_id is None:
            return
        client = self._get_client()
        await request_with_retry(
            client,
            "POST",
            f"/Items/{item_id}/Refresh",
            params={
                "Recursive": "true",
                "MetadataRefreshMode": "Default",
                "ImageRefreshMode": "Default",
            },
        )

    async def get_active_sessions(self) -> list[dict]:
        """Retourne la liste des sessions de lecture actives."""
        client = self._get_client()
        resp = await request_with_retry(client, "GET", "/Sessions")
        return resp.json()

    async def close(self) -> None:
        """Ferme le client HTTP sous-jacent."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
