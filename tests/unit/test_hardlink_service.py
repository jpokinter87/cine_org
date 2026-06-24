"""
Tests unitaires pour HardlinkService.

Teste la purge des hardlinks expirés, le dry-run, le force,
le nettoyage des dossiers vides, et les statistiques.
"""

import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from src.infrastructure.persistence.models import HardlinkModel
from src.services.hardlink_service import HardlinkService


@pytest.fixture
def db_engine(tmp_path):
    """Engine SQLite en mémoire avec table hardlinks."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def settings(tmp_path):
    """Settings mock avec downloads_dir."""
    s = MagicMock()
    s.downloads_dir = tmp_path / "downloads"
    s.downloads_dir.mkdir()
    s.hardlink_retention_days = 30
    return s


@pytest.fixture
def service(settings):
    """HardlinkService avec settings mock."""
    return HardlinkService(settings)


def _create_hardlink_entry(
    session: Session,
    download_path: str,
    storage_path: str,
    expired: bool = False,
) -> HardlinkModel:
    """Helper pour créer une entrée HardlinkModel."""
    now = datetime.utcnow()
    if expired:
        expires_at = now - timedelta(days=1)
        created_at = now - timedelta(days=31)
    else:
        expires_at = now + timedelta(days=15)
        created_at = now - timedelta(days=15)

    entry = HardlinkModel(
        download_path=download_path,
        storage_path=storage_path,
        created_at=created_at,
        expires_at=expires_at,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


class TestPurgeExpired:
    """Tests pour purge_expired()."""

    def test_purge_removes_expired_hardlinks(
        self, service, db_engine, tmp_path, monkeypatch
    ):
        """Les hardlinks expirés sont supprimés, le fichier storage reste."""
        monkeypatch.setattr(
            "src.services.hardlink_service.get_engine", lambda: db_engine
        )

        # Créer les fichiers
        downloads = tmp_path / "downloads" / "Films"
        downloads.mkdir(parents=True)
        storage = tmp_path / "storage" / "Films"
        storage.mkdir(parents=True)

        storage_file = storage / "Movie (2024).mkv"
        storage_file.write_bytes(b"content")
        download_file = downloads / "Movie.2024.mkv"
        os.link(storage_file, download_file)

        # Entrée expirée en DB
        with Session(db_engine) as session:
            _create_hardlink_entry(
                session,
                str(download_file),
                str(storage_file),
                expired=True,
            )

        result = service.purge_expired()

        assert result.purged == 1
        assert len(result.errors) == 0
        # Hardlink supprimé
        assert not download_file.exists()
        # Fichier storage intact
        assert storage_file.exists()
        assert storage_file.stat().st_nlink == 1

        # Entrée DB supprimée
        with Session(db_engine) as session:
            remaining = list(session.exec(select(HardlinkModel)).all())
            assert len(remaining) == 0

    def test_purge_cleans_empty_dirs(self, service, db_engine, tmp_path, monkeypatch):
        """Les dossiers parents vides sont nettoyés après purge."""
        monkeypatch.setattr(
            "src.services.hardlink_service.get_engine", lambda: db_engine
        )

        downloads = tmp_path / "downloads"
        deep_dir = downloads / "Films" / "SubGroup"
        deep_dir.mkdir(parents=True)
        storage = tmp_path / "storage"
        storage.mkdir(parents=True)

        storage_file = storage / "movie.mkv"
        storage_file.write_bytes(b"data")
        download_file = deep_dir / "movie.scene.mkv"
        os.link(storage_file, download_file)

        with Session(db_engine) as session:
            _create_hardlink_entry(
                session, str(download_file), str(storage_file), expired=True
            )

        service.purge_expired()

        # Le dossier SubGroup (vide) doit être nettoyé
        assert not deep_dir.exists()
        # Films aussi (vide après suppression de SubGroup)
        assert not (downloads / "Films").exists()
        # downloads/ reste (c'est la racine)
        assert downloads.exists()

    def test_purge_removes_residual_non_video_files(
        self, service, db_engine, tmp_path, monkeypatch
    ):
        """Les résidus non-vidéo (.nfo) bloquant le rmdir sont supprimés."""
        monkeypatch.setattr(
            "src.services.hardlink_service.get_engine", lambda: db_engine
        )

        downloads = tmp_path / "downloads"
        torrent_dir = downloads / "Movie.2024.MULTI.1080p-GRP"
        torrent_dir.mkdir(parents=True)
        storage = tmp_path / "storage"
        storage.mkdir(parents=True)

        storage_file = storage / "movie.mkv"
        storage_file.write_bytes(b"data")
        download_file = torrent_dir / "Movie.2024.MULTI.1080p-GRP.mkv"
        os.link(storage_file, download_file)
        # Résidu non-vidéo qui empêchait la suppression du dossier
        nfo = torrent_dir / "Movie.2024.MULTI.1080p-GRP.nfo"
        nfo.write_text("info")

        with Session(db_engine) as session:
            _create_hardlink_entry(
                session, str(download_file), str(storage_file), expired=True
            )

        result = service.purge_expired()

        assert result.purged == 1
        assert result.residuals_removed == 1
        # Résidu et dossier supprimés
        assert not nfo.exists()
        assert not torrent_dir.exists()
        # Fichier storage intact
        assert storage_file.exists()

    def test_purge_keeps_residual_when_video_remains(
        self, service, db_engine, tmp_path, monkeypatch
    ):
        """Si un autre fichier vidéo subsiste, les résidus ne sont pas touchés."""
        monkeypatch.setattr(
            "src.services.hardlink_service.get_engine", lambda: db_engine
        )

        downloads = tmp_path / "downloads"
        torrent_dir = downloads / "Season.Pack"
        torrent_dir.mkdir(parents=True)
        storage = tmp_path / "storage"
        storage.mkdir(parents=True)

        storage_file = storage / "ep1.mkv"
        storage_file.write_bytes(b"data")
        expired_link = torrent_dir / "ep1.mkv"
        os.link(storage_file, expired_link)
        # Un autre fichier vidéo non purgé + un résidu .nfo
        other_video = torrent_dir / "ep2.mkv"
        other_video.write_bytes(b"other")
        nfo = torrent_dir / "pack.nfo"
        nfo.write_text("info")

        with Session(db_engine) as session:
            _create_hardlink_entry(
                session, str(expired_link), str(storage_file), expired=True
            )

        result = service.purge_expired()

        assert result.residuals_removed == 0
        # Hardlink purgé mais le reste du dossier actif est préservé
        assert not expired_link.exists()
        assert other_video.exists()
        assert nfo.exists()
        assert torrent_dir.exists()

    def test_purge_dry_run_no_delete(self, service, db_engine, tmp_path, monkeypatch):
        """dry_run=True n'efface rien."""
        monkeypatch.setattr(
            "src.services.hardlink_service.get_engine", lambda: db_engine
        )

        downloads = tmp_path / "downloads" / "Films"
        downloads.mkdir(parents=True)
        storage = tmp_path / "storage"
        storage.mkdir(parents=True)

        storage_file = storage / "movie.mkv"
        storage_file.write_bytes(b"data")
        download_file = downloads / "movie.mkv"
        os.link(storage_file, download_file)

        with Session(db_engine) as session:
            _create_hardlink_entry(
                session, str(download_file), str(storage_file), expired=True
            )

        result = service.purge_expired(dry_run=True)

        assert result.purged == 1
        assert len(result.freed_paths) == 1
        # Fichier toujours présent
        assert download_file.exists()
        # Entrée DB toujours présente
        with Session(db_engine) as session:
            remaining = list(session.exec(select(HardlinkModel)).all())
            assert len(remaining) == 1

    def test_purge_force_all(self, service, db_engine, tmp_path, monkeypatch):
        """force_all=True purge même les non expirés."""
        monkeypatch.setattr(
            "src.services.hardlink_service.get_engine", lambda: db_engine
        )

        downloads = tmp_path / "downloads" / "Films"
        downloads.mkdir(parents=True)
        storage = tmp_path / "storage"
        storage.mkdir(parents=True)

        storage_file = storage / "movie.mkv"
        storage_file.write_bytes(b"data")
        download_file = downloads / "movie.mkv"
        os.link(storage_file, download_file)

        with Session(db_engine) as session:
            _create_hardlink_entry(
                session, str(download_file), str(storage_file), expired=False
            )

        result = service.purge_expired(force_all=True)

        assert result.purged == 1
        assert not download_file.exists()
        assert storage_file.exists()

    def test_purge_missing_file_graceful(
        self, service, db_engine, tmp_path, monkeypatch
    ):
        """Si le fichier est déjà absent, pas d'erreur."""
        monkeypatch.setattr(
            "src.services.hardlink_service.get_engine", lambda: db_engine
        )

        with Session(db_engine) as session:
            _create_hardlink_entry(
                session,
                str(tmp_path / "downloads" / "gone.mkv"),
                str(tmp_path / "storage" / "gone.mkv"),
                expired=True,
            )

        result = service.purge_expired()

        # L'entrée DB est nettoyée même si le fichier n'existe plus
        assert result.purged == 1
        assert len(result.errors) == 0

    def test_purge_skips_non_expired(self, service, db_engine, tmp_path, monkeypatch):
        """Les hardlinks non expirés ne sont pas purgés."""
        monkeypatch.setattr(
            "src.services.hardlink_service.get_engine", lambda: db_engine
        )

        with Session(db_engine) as session:
            _create_hardlink_entry(
                session,
                str(tmp_path / "downloads" / "active.mkv"),
                str(tmp_path / "storage" / "active.mkv"),
                expired=False,
            )

        result = service.purge_expired()

        assert result.purged == 0
        with Session(db_engine) as session:
            remaining = list(session.exec(select(HardlinkModel)).all())
            assert len(remaining) == 1


class TestListAndStats:
    """Tests pour list_active() et get_stats()."""

    def test_list_active(self, service, db_engine, tmp_path, monkeypatch):
        """list_active() retourne seulement les non expirés."""
        monkeypatch.setattr(
            "src.services.hardlink_service.get_engine", lambda: db_engine
        )

        with Session(db_engine) as session:
            _create_hardlink_entry(
                session, "/dl/active.mkv", "/st/active.mkv", expired=False
            )
            _create_hardlink_entry(
                session, "/dl/expired.mkv", "/st/expired.mkv", expired=True
            )

        active = service.list_active()

        assert len(active) == 1
        assert "active.mkv" in active[0].download_path
        assert active[0].days_remaining >= 0

    def test_get_stats(self, service, db_engine, tmp_path, monkeypatch):
        """get_stats() retourne les compteurs corrects."""
        monkeypatch.setattr(
            "src.services.hardlink_service.get_engine", lambda: db_engine
        )

        with Session(db_engine) as session:
            _create_hardlink_entry(session, "/dl/a.mkv", "/st/a.mkv", expired=False)
            _create_hardlink_entry(session, "/dl/b.mkv", "/st/b.mkv", expired=False)
            _create_hardlink_entry(session, "/dl/c.mkv", "/st/c.mkv", expired=True)

        stats = service.get_stats()

        assert stats.total_active == 2
        assert stats.total_expired == 1
        assert stats.total_entries == 3
