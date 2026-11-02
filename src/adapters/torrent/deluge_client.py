"""Adaptateur Deluge (RPC du démon deluged) pour ITorrentClient."""

from pathlib import Path
from typing import Any, Callable, Optional

from deluge_client import DelugeRPCClient

from src.core.ports.torrent_client import (
    ITorrentClient,
    TorrentClientUnavailable,
    TorrentInfo,
)


class DelugeTorrentClient(ITorrentClient):
    """Client du démon Deluge. Une connexion RPC par appel (usage ponctuel)."""

    def __init__(self, rpc_factory: Callable[[], Any]) -> None:
        self._rpc_factory = rpc_factory

    @classmethod
    def from_settings(cls, settings) -> "DelugeTorrentClient":
        """Construit le client à partir des réglages CINEORG_DELUGE_*."""
        return cls(
            lambda: DelugeRPCClient(
                settings.deluge_host,
                settings.deluge_port,
                settings.deluge_username,
                settings.deluge_password,
                decode_utf8=True,
            )
        )

    def _call(self, method: str, *args: Any) -> Any:
        try:
            rpc = self._rpc_factory()
            rpc.connect()
            return rpc.call(method, *args)
        except Exception as e:
            raise TorrentClientUnavailable(f"Deluge injoignable : {e}") from e

    def list_torrents(self) -> list[TorrentInfo]:
        status = self._call(
            "core.get_torrents_status", {}, ["name", "save_path", "files"]
        )
        return [
            TorrentInfo(
                id=torrent_id,
                name=t["name"],
                files=tuple(Path(t["save_path"]) / f["path"] for f in t["files"]),
            )
            for torrent_id, t in status.items()
        ]

    def remove(self, torrent_id: str) -> None:
        if not self._call("core.remove_torrent", torrent_id, True):
            raise TorrentClientUnavailable(
                f"Deluge a refusé le retrait du torrent {torrent_id}"
            )


def build_torrent_client(settings) -> Optional[ITorrentClient]:
    """Client Deluge si CINEORG_DELUGE_USERNAME/PASSWORD sont renseignés, sinon None."""
    if not settings.deluge_enabled:
        return None
    return DelugeTorrentClient.from_settings(settings)
