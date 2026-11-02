"""
Tests de la purge des hardlinks pilotée par un client BitTorrent (Deluge).

Le torrent est retiré (avec ses données) quand tous ses fichiers suivis ont
expiré ; reporté sinon ; bloqué s'il contient une copie unique.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from src.core.ports.torrent_client import (
    ITorrentClient,
    TorrentClientUnavailable,
    TorrentInfo,
)
from src.infrastructure.persistence.models import HardlinkModel
from src.services.hardlink_service import HardlinkService


class FakeTorrentClient(ITorrentClient):
    """Client en mémoire : enregistre les retraits."""

    def __init__(self, torrents: list[TorrentInfo], unavailable: bool = False):
        self.torrents = torrents
        self.unavailable = unavailable
        self.removed: list[str] = []

    def list_torrents(self) -> list[TorrentInfo]:
        if self.unavailable:
            raise TorrentClientUnavailable("Deluge injoignable")
        return self.torrents

    def remove(self, torrent_id: str) -> None:
        self.removed.append(torrent_id)


@pytest.fixture
def engine(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("src.services.hardlink_service.get_engine", lambda: engine)
    return engine


@pytest.fixture
def dirs(tmp_path):
    downloads, storage = tmp_path / "downloads", tmp_path / "storage"
    downloads.mkdir()
    storage.mkdir()
    return downloads, storage


@pytest.fixture
def settings(dirs):
    s = MagicMock()
    s.downloads_dir = dirs[0]
    return s


def _seed(dirs, rel: str) -> tuple[Path, Path]:
    """Crée un fichier storage et son hardlink de seeding dans downloads."""
    downloads, storage = dirs
    target = storage / Path(rel).name
    target.write_bytes(b"video")
    link = downloads / rel
    link.parent.mkdir(parents=True, exist_ok=True)
    os.link(target, link)
    return link, target


def _entry(engine, link: Path, target: Path, expired: bool) -> None:
    now = datetime.utcnow()
    delta = timedelta(days=1)
    with Session(engine) as session:
        session.add(
            HardlinkModel(
                download_path=str(link),
                storage_path=str(target),
                created_at=now - timedelta(days=91),
                expires_at=now - delta if expired else now + delta,
            )
        )
        session.commit()


def _remaining(engine) -> int:
    with Session(engine) as session:
        return len(session.exec(select(HardlinkModel)).all())


def test_removes_torrent_when_all_files_expired(engine, dirs, settings):
    """Pack dont tous les fichiers suivis ont expiré → torrent retiré, entrées supprimées."""
    e1, s1 = _seed(dirs, "Pack/Show.S01E01.mkv")
    e2, s2 = _seed(dirs, "Pack/Show.S01E02.mkv")
    nfo = dirs[0] / "Pack/Show.nfo"
    nfo.write_text("nfo")
    _entry(engine, e1, s1, expired=True)
    _entry(engine, e2, s2, expired=True)
    client = FakeTorrentClient([TorrentInfo("t1", "Pack", (e1, e2, nfo))])

    result = HardlinkService(settings, client).purge_expired()

    assert client.removed == ["t1"]
    assert result.removed_torrents == ["Pack"]
    assert result.purged == 2
    assert _remaining(engine) == 0
    assert s1.exists() and s2.exists()


def test_defers_torrent_while_a_file_is_active(engine, dirs, settings):
    """Un épisode du pack encore actif → torrent reporté, rien supprimé."""
    e1, s1 = _seed(dirs, "Pack/Show.S01E01.mkv")
    e2, s2 = _seed(dirs, "Pack/Show.S01E02.mkv")
    _entry(engine, e1, s1, expired=True)
    _entry(engine, e2, s2, expired=False)
    client = FakeTorrentClient([TorrentInfo("t1", "Pack", (e1, e2))])

    result = HardlinkService(settings, client).purge_expired()

    assert client.removed == []
    assert result.deferred == [("Pack", 1)]
    assert result.purged == 0
    assert _remaining(engine) == 2
    assert e1.exists()


def test_blocks_torrent_with_untracked_single_copy(engine, dirs, settings):
    """Vidéo non suivie et sans autre copie (nlink == 1) → torrent bloqué."""
    e1, s1 = _seed(dirs, "Pack/Show.S01E01.mkv")
    lonely = dirs[0] / "Pack/Show.S01E02.mkv"
    lonely.write_bytes(b"unique")
    _entry(engine, e1, s1, expired=True)
    client = FakeTorrentClient([TorrentInfo("t1", "Pack", (e1, lonely))])

    result = HardlinkService(settings, client).purge_expired()

    assert client.removed == []
    assert result.blocked[0][0] == "Pack"
    assert "Show.S01E02.mkv" in result.blocked[0][1]
    assert _remaining(engine) == 1


def test_blocks_torrent_whose_storage_target_is_gone(engine, dirs, settings):
    """Cible storage absente (version écartée) → le fichier downloads est unique → bloqué."""
    e1, s1 = _seed(dirs, "Show.S01E01.mkv")
    _entry(engine, e1, s1, expired=True)
    s1.unlink()
    client = FakeTorrentClient([TorrentInfo("t1", "Show.S01E01.mkv", (e1,))])

    result = HardlinkService(settings, client).purge_expired()

    assert client.removed == []
    assert result.blocked and "Show.S01E01.mkv" in result.blocked[0][1]
    assert e1.exists()


def test_removes_torrent_when_storage_was_renamed(engine, dirs, settings):
    """Fichier storage renommé (ré-association) : l'autre lien existe → retrait permis."""
    e1, s1 = _seed(dirs, "Show.S01E01.mkv")
    _entry(engine, e1, s1, expired=True)
    s1.rename(s1.with_name("Show (2026) - S01E01.mkv"))
    client = FakeTorrentClient([TorrentInfo("t1", "Show.S01E01.mkv", (e1,))])

    result = HardlinkService(settings, client).purge_expired()

    assert client.removed == ["t1"]
    assert not result.blocked


def test_unavailable_client_purges_nothing(engine, dirs, settings):
    """Deluge injoignable → aucune purge, erreur reportée, entrées conservées."""
    e1, s1 = _seed(dirs, "Film.mkv")
    _entry(engine, e1, s1, expired=True)
    client = FakeTorrentClient([], unavailable=True)

    result = HardlinkService(settings, client).purge_expired()

    assert result.purged == 0
    assert result.errors
    assert e1.exists()
    assert _remaining(engine) == 1


def test_entry_without_torrent_falls_back_to_unlink(engine, dirs, settings):
    """Torrent déjà retiré à la main → lien supprimé comme avant, entrée supprimée."""
    e1, s1 = _seed(dirs, "Film/Film.mkv")
    _entry(engine, e1, s1, expired=True)
    client = FakeTorrentClient([])

    result = HardlinkService(settings, client).purge_expired()

    assert result.purged == 1
    assert not e1.exists()
    assert not (dirs[0] / "Film").exists()
    assert s1.exists()
    assert _remaining(engine) == 0


def test_dry_run_removes_nothing(engine, dirs, settings):
    """Dry-run : le torrent est annoncé mais ni retiré ni effacé de la base."""
    e1, s1 = _seed(dirs, "Film.mkv")
    _entry(engine, e1, s1, expired=True)
    client = FakeTorrentClient([TorrentInfo("t1", "Film.mkv", (e1,))])

    result = HardlinkService(settings, client).purge_expired(dry_run=True)

    assert client.removed == []
    assert result.removed_torrents == ["Film.mkv"]
    assert result.purged == 1
    assert _remaining(engine) == 1


def test_force_all_removes_active_torrents(engine, dirs, settings):
    """--force : les entrées non expirées sont traitées comme expirées."""
    e1, s1 = _seed(dirs, "Film.mkv")
    _entry(engine, e1, s1, expired=False)
    client = FakeTorrentClient([TorrentInfo("t1", "Film.mkv", (e1,))])

    result = HardlinkService(settings, client).purge_expired(force_all=True)

    assert client.removed == ["t1"]
    assert result.removed_torrents == ["Film.mkv"]
    assert _remaining(engine) == 0
