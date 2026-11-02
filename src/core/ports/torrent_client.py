"""Port du client BitTorrent (retrait des torrents à l'expiration du seeding)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


class TorrentClientUnavailable(Exception):
    """Le client BitTorrent est injoignable ou a refusé la requête."""


@dataclass(frozen=True)
class TorrentInfo:
    """Torrent chargé dans le client, avec les chemins absolus de ses fichiers."""

    id: str
    name: str
    files: tuple[Path, ...]


class ITorrentClient(ABC):
    """Interface d'un client BitTorrent."""

    @abstractmethod
    def list_torrents(self) -> list[TorrentInfo]:
        """Liste les torrents chargés. Lève TorrentClientUnavailable."""

    @abstractmethod
    def remove(self, torrent_id: str) -> None:
        """Retire le torrent et supprime ses données. Lève TorrentClientUnavailable."""
