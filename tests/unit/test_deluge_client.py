"""Tests de l'adaptateur DelugeTorrentClient (RPC simulé)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.adapters.torrent.deluge_client import DelugeTorrentClient
from src.core.ports.torrent_client import TorrentClientUnavailable, TorrentInfo


def _client(rpc: MagicMock) -> DelugeTorrentClient:
    return DelugeTorrentClient(rpc_factory=lambda: rpc)


def test_list_torrents_builds_absolute_paths():
    """save_path + files[i].path donnent les chemins absolus des fichiers."""
    rpc = MagicMock()
    rpc.call.return_value = {
        "abc": {
            "name": "Show.S01",
            "save_path": "/media/NAS64/temp/Séries",
            "files": [
                {"path": "Show.S01/Show.S01E01.mkv"},
                {"path": "Show.S01/Show.S01.nfo"},
            ],
        }
    }

    torrents = _client(rpc).list_torrents()

    assert torrents == [
        TorrentInfo(
            id="abc",
            name="Show.S01",
            files=(
                Path("/media/NAS64/temp/Séries/Show.S01/Show.S01E01.mkv"),
                Path("/media/NAS64/temp/Séries/Show.S01/Show.S01.nfo"),
            ),
        )
    ]
    rpc.connect.assert_called_once()
    rpc.call.assert_called_once_with(
        "core.get_torrents_status", {}, ["name", "save_path", "files"]
    )


def test_remove_deletes_data():
    """Le retrait demande la suppression des données (remove_data=True)."""
    rpc = MagicMock()
    rpc.call.return_value = True

    _client(rpc).remove("abc")

    rpc.call.assert_called_once_with("core.remove_torrent", "abc", True)


def test_connection_error_raises_unavailable():
    """Une erreur de connexion devient TorrentClientUnavailable."""
    rpc = MagicMock()
    rpc.connect.side_effect = ConnectionRefusedError("refusé")

    with pytest.raises(TorrentClientUnavailable):
        _client(rpc).list_torrents()


def test_remove_refused_raises_unavailable():
    """Un refus de Deluge (False) devient TorrentClientUnavailable."""
    rpc = MagicMock()
    rpc.call.return_value = False

    with pytest.raises(TorrentClientUnavailable):
        _client(rpc).remove("abc")


def test_build_torrent_client_none_when_disabled():
    """Intégration non configurée → pas de client (purge historique)."""
    from src.adapters.torrent.deluge_client import build_torrent_client

    assert build_torrent_client(MagicMock(deluge_enabled=False)) is None


def test_build_torrent_client_when_enabled():
    """Identifiants renseignés → client Deluge."""
    from src.adapters.torrent.deluge_client import build_torrent_client

    client = build_torrent_client(MagicMock(deluge_enabled=True))
    assert isinstance(client, DelugeTorrentClient)
