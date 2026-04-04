"""
Tests unitaires pour les hardlinks seeding.

Teste la création de hardlinks après transfert, le fallback en cas d'erreur,
et le filtrage des hardlinks par le scanner.
"""

import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

from src.adapters.file_system import FileSystemAdapter
from src.services.transferer import TransfererService


# ====================
# Fixtures
# ====================


@pytest.fixture
def real_transferer(tmp_path):
    """TransfererService avec FileSystemAdapter réel pour tester les hardlinks."""
    storage_dir = tmp_path / "storage"
    video_dir = tmp_path / "video"
    downloads_dir = tmp_path / "downloads"
    storage_dir.mkdir()
    video_dir.mkdir()
    (downloads_dir / "Films").mkdir(parents=True)

    fs = FileSystemAdapter()
    symlink_mgr = Mock()
    return TransfererService(
        file_system=fs,
        symlink_manager=symlink_mgr,
        storage_dir=storage_dir,
        video_dir=video_dir,
    )


@pytest.fixture
def source_file(tmp_path):
    """Crée un fichier source réaliste dans downloads."""
    downloads = tmp_path / "downloads" / "Films"
    downloads.mkdir(parents=True, exist_ok=True)
    source = downloads / "Movie.2024.1080p.BluRay.x264-GROUP.mkv"
    source.write_bytes(b"x" * 1024)  # 1KB de contenu
    return source


@pytest.fixture
def storage_dest(tmp_path):
    """Chemin destination dans storage."""
    dest_dir = tmp_path / "storage" / "Films" / "Drame" / "M-Mz"
    dest_dir.mkdir(parents=True)
    return dest_dir / "Movie (2024) FR DTS x264 1080p.mkv"


# ====================
# Tests hardlink creation
# ====================


class TestHardlinkCreation:
    """Tests pour la création de hardlinks après transfert."""

    def test_transfer_creates_hardlink(
        self, real_transferer, source_file, storage_dest
    ):
        """Après transfert, un hardlink doit exister au chemin original."""
        original_source = Path(source_file)

        with (
            patch("src.infrastructure.persistence.database.get_engine"),
            patch("sqlmodel.Session") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__ = Mock(return_value=mock_session)
            mock_session_cls.return_value.__exit__ = Mock(return_value=False)

            result = real_transferer.transfer_file(
                source=source_file,
                destination=storage_dest,
                create_symlink=False,
            )

        assert result.success
        # Le fichier storage existe
        assert storage_dest.exists()
        # Le hardlink existe au chemin original
        assert original_source.exists()
        # Même inode = hardlink
        assert original_source.stat().st_ino == storage_dest.stat().st_ino
        # nlink = 2 (storage + downloads)
        assert storage_dest.stat().st_nlink == 2

    def test_transfer_records_hardlink_in_db(
        self, real_transferer, source_file, storage_dest
    ):
        """Le hardlink doit être enregistré en DB avec date d'expiration."""
        with (
            patch("src.infrastructure.persistence.database.get_engine"),
            patch("sqlmodel.Session") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__ = Mock(return_value=mock_session)
            mock_session_cls.return_value.__exit__ = Mock(return_value=False)

            real_transferer.transfer_file(
                source=source_file,
                destination=storage_dest,
                create_symlink=False,
            )

        # Vérifier que session.add a été appelé avec un HardlinkModel
        mock_session.add.assert_called_once()
        hardlink_model = mock_session.add.call_args[0][0]
        assert str(source_file) in hardlink_model.download_path
        assert str(storage_dest) in hardlink_model.storage_path
        assert hardlink_model.expires_at > hardlink_model.created_at
        mock_session.commit.assert_called_once()

    def test_transfer_hardlink_crossdevice_fallback(
        self, real_transferer, source_file, storage_dest
    ):
        """Si os.link échoue (cross-device), le transfert réussit quand même."""
        with patch("os.link", side_effect=OSError("cross-device")):
            result = real_transferer.transfer_file(
                source=source_file,
                destination=storage_dest,
                create_symlink=False,
            )

        # Le transfert a réussi (move OK)
        assert result.success
        assert storage_dest.exists()
        # Mais pas de hardlink au chemin original
        assert not source_file.exists()

    def test_transfer_hardlink_db_failure_graceful(
        self, real_transferer, source_file, storage_dest
    ):
        """Si l'enregistrement DB échoue, le hardlink existe quand même."""
        with patch(
            "src.infrastructure.persistence.database.get_engine",
            side_effect=Exception("DB error"),
        ):
            result = real_transferer.transfer_file(
                source=source_file,
                destination=storage_dest,
                create_symlink=False,
            )

        assert result.success
        # Le hardlink a été créé même si la DB a échoué
        assert source_file.exists()
        assert storage_dest.exists()
        assert source_file.stat().st_ino == storage_dest.stat().st_ino


# ====================
# Tests scanner filtering
# ====================


class TestScannerHardlinkFiltering:
    """Tests pour le filtrage des hardlinks par le scanner."""

    def test_scanner_ignores_hardlinks(self, tmp_path):
        """Les fichiers avec nlink > 1 doivent être ignorés par list_video_files."""
        scan_dir = tmp_path / "downloads" / "Films"
        scan_dir.mkdir(parents=True)

        # Créer un fichier et un hardlink
        original = scan_dir / "movie.mkv"
        original.write_bytes(b"x" * 1024)
        hardlink = tmp_path / "storage" / "movie_renamed.mkv"
        hardlink.parent.mkdir(parents=True)
        os.link(original, hardlink)

        # Le fichier a maintenant nlink=2
        assert original.stat().st_nlink == 2

        adapter = FileSystemAdapter()
        results = list(adapter.list_video_files(scan_dir, min_file_size_bytes=0))

        # Le hardlink ne doit pas apparaître dans les résultats
        assert len(results) == 0

    def test_scanner_includes_normal_files(self, tmp_path):
        """Les fichiers normaux (nlink=1) doivent être inclus."""
        scan_dir = tmp_path / "downloads" / "Films"
        scan_dir.mkdir(parents=True)

        normal_file = scan_dir / "new_movie.mkv"
        normal_file.write_bytes(b"x" * 1024)

        # nlink=1 (pas de hardlink)
        assert normal_file.stat().st_nlink == 1

        adapter = FileSystemAdapter()
        results = list(adapter.list_video_files(scan_dir, min_file_size_bytes=0))

        assert len(results) == 1
        assert results[0] == normal_file

    def test_scanner_fallback_ignores_hardlinks(self, tmp_path):
        """Le fallback du scanner doit aussi ignorer les hardlinks."""
        from src.services.scanner import ScannerService

        scan_dir = tmp_path / "downloads" / "Films"
        scan_dir.mkdir(parents=True)

        # Créer hardlink
        original = scan_dir / "serie.mkv"
        original.write_bytes(b"x" * 1024)
        hardlink = tmp_path / "storage" / "serie_renamed.mkv"
        hardlink.parent.mkdir(parents=True)
        os.link(original, hardlink)

        mock_fs = MagicMock()
        mock_fs.get_size.return_value = 1024
        mock_parser = MagicMock()
        mock_extractor = MagicMock()
        settings = MagicMock()
        settings.min_file_size_mb = 0
        settings.downloads_dir = tmp_path / "downloads"

        scanner = ScannerService(mock_fs, mock_parser, mock_extractor, settings)
        results = list(scanner._list_video_files_fallback(scan_dir, 0))

        assert len(results) == 0

    def test_scanner_fallback_includes_normal_files(self, tmp_path):
        """Le fallback du scanner inclut les fichiers normaux."""
        from src.services.scanner import ScannerService

        scan_dir = tmp_path / "downloads" / "Films"
        scan_dir.mkdir(parents=True)

        normal = scan_dir / "new_serie.mkv"
        normal.write_bytes(b"x" * 1024)

        mock_fs = MagicMock()
        mock_fs.get_size.return_value = 1024
        mock_parser = MagicMock()
        mock_extractor = MagicMock()
        settings = MagicMock()
        settings.min_file_size_mb = 0
        settings.downloads_dir = tmp_path / "downloads"

        scanner = ScannerService(mock_fs, mock_parser, mock_extractor, settings)
        results = list(scanner._list_video_files_fallback(scan_dir, 0))

        assert len(results) == 1
        assert results[0] == normal
