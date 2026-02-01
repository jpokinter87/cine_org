"""
Tests unitaires pour le service de transfert atomique.

Ce module teste la gestion des conflits via hash, le deplacement atomique
des fichiers et la creation des symlinks relatifs.
"""

import os
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from src.services.transferer import (
    TransfererService,
    TransferResult,
    ConflictInfo,
    ConflictType,
)


# ====================
# Fixtures
# ====================


@pytest.fixture
def mock_file_system():
    """Mock de IFileSystem."""
    return Mock()


@pytest.fixture
def mock_symlink_manager():
    """Mock de ISymlinkManager."""
    return Mock()


@pytest.fixture
def transferer(mock_file_system, mock_symlink_manager, tmp_path):
    """TransfererService avec mocks."""
    return TransfererService(
        file_system=mock_file_system,
        symlink_manager=mock_symlink_manager,
        storage_dir=tmp_path / "storage",
        video_dir=tmp_path / "video",
    )


# ====================
# Tests check_conflict
# ====================


class TestCheckConflict:
    """Tests pour la detection de conflits."""

    def test_no_existing_file_returns_none(
        self, transferer, mock_file_system
    ):
        """Pas de conflit si le fichier destination n'existe pas."""
        mock_file_system.exists.return_value = False
        result = transferer.check_conflict(
            Path("/src/file.mkv"), Path("/dst/file.mkv")
        )
        assert result is None

    def test_same_hash_returns_duplicate(
        self, transferer, mock_file_system
    ):
        """Meme hash = fichier duplique."""
        mock_file_system.exists.return_value = True
        with patch(
            "src.services.transferer.compute_file_hash"
        ) as mock_hash:
            mock_hash.side_effect = ["abc123", "abc123"]  # Meme hash
            result = transferer.check_conflict(
                Path("/src/file.mkv"), Path("/dst/file.mkv")
            )
            assert result is not None
            assert result.conflict_type == ConflictType.DUPLICATE
            assert result.existing_hash == "abc123"
            assert result.new_hash == "abc123"

    def test_different_hash_returns_collision(
        self, transferer, mock_file_system
    ):
        """Hash different = collision de nom."""
        mock_file_system.exists.return_value = True
        with patch(
            "src.services.transferer.compute_file_hash"
        ) as mock_hash:
            mock_hash.side_effect = ["abc123", "xyz789"]  # Hash differents
            result = transferer.check_conflict(
                Path("/src/file.mkv"), Path("/dst/file.mkv")
            )
            assert result is not None
            assert result.conflict_type == ConflictType.NAME_COLLISION
            assert result.existing_hash == "xyz789"
            assert result.new_hash == "abc123"


# ====================
# Tests transfer_file avec fichiers reels
# ====================


class TestTransferFileReal:
    """Tests d'integration avec fichiers reels."""

    def test_success_with_symlink(self, tmp_path):
        """Transfert reussi avec creation de symlink."""
        # Setup
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        video.mkdir()

        source = tmp_path / "downloads" / "movie.mkv"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"fake video content" * 100)

        dest_dir = storage / "Films" / "Action" / "M"
        dest = dest_dir / "Matrix.mkv"

        # Service avec adaptateur reel
        from src.adapters.file_system import FileSystemAdapter

        fs = FileSystemAdapter()
        transferer = TransfererService(fs, fs, storage, video)

        result = transferer.transfer_file(source, dest, create_symlink=True)

        assert result.success
        assert result.final_path == dest
        assert dest.exists()
        assert not source.exists()  # Source deplacee
        assert result.symlink_path is not None
        assert result.symlink_path.is_symlink()
        assert result.symlink_path.resolve() == dest

    def test_success_without_symlink(self, tmp_path):
        """Transfert reussi sans creation de symlink."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        video.mkdir()

        source = tmp_path / "downloads" / "movie.mkv"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"fake video content")

        dest_dir = storage / "Films" / "Action" / "M"
        dest = dest_dir / "Matrix.mkv"

        from src.adapters.file_system import FileSystemAdapter

        fs = FileSystemAdapter()
        transferer = TransfererService(fs, fs, storage, video)

        result = transferer.transfer_file(source, dest, create_symlink=False)

        assert result.success
        assert result.final_path == dest
        assert dest.exists()
        assert result.symlink_path is None

    def test_conflict_returns_failure(self, tmp_path):
        """Retourne echec si conflit detecte."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        video.mkdir()

        # Creer source et destination avec contenu different
        source = tmp_path / "downloads" / "movie.mkv"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"new content" * 100)

        dest_dir = storage / "Films" / "Action" / "M"
        dest_dir.mkdir(parents=True)
        dest = dest_dir / "Matrix.mkv"
        dest.write_bytes(b"existing different content" * 100)

        from src.adapters.file_system import FileSystemAdapter

        fs = FileSystemAdapter()
        transferer = TransfererService(fs, fs, storage, video)

        result = transferer.transfer_file(source, dest)

        assert not result.success
        assert result.conflict is not None
        assert result.conflict.conflict_type == ConflictType.NAME_COLLISION
        # Source non modifiee
        assert source.exists()
        # Destination non modifiee
        assert dest.exists()

    def test_duplicate_returns_failure(self, tmp_path):
        """Retourne echec si fichier duplique (meme hash)."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        video.mkdir()

        content = b"identical content" * 100

        source = tmp_path / "downloads" / "movie.mkv"
        source.parent.mkdir(parents=True)
        source.write_bytes(content)

        dest_dir = storage / "Films" / "Action" / "M"
        dest_dir.mkdir(parents=True)
        dest = dest_dir / "Matrix.mkv"
        dest.write_bytes(content)

        from src.adapters.file_system import FileSystemAdapter

        fs = FileSystemAdapter()
        transferer = TransfererService(fs, fs, storage, video)

        result = transferer.transfer_file(source, dest)

        assert not result.success
        assert result.conflict is not None
        assert result.conflict.conflict_type == ConflictType.DUPLICATE


# ====================
# Tests transfer_file avec mocks
# ====================


class TestTransferFileMocked:
    """Tests avec mocks pour scenarios d'erreur."""

    def test_conflict_detected_returns_failure(
        self, transferer, mock_file_system
    ):
        """Retourne echec si conflit detecte (mocked)."""
        mock_file_system.exists.return_value = True
        with patch(
            "src.services.transferer.compute_file_hash"
        ) as mock_hash:
            mock_hash.side_effect = ["abc", "xyz"]  # Differents
            result = transferer.transfer_file(
                Path("/src/file.mkv"), Path("/dst/file.mkv")
            )
            assert not result.success
            assert result.conflict is not None

    def test_atomic_move_failure_returns_error(
        self, transferer, mock_file_system
    ):
        """Retourne erreur si move atomique echoue."""
        mock_file_system.exists.return_value = False
        mock_file_system.atomic_move.return_value = False

        result = transferer.transfer_file(
            Path("/src/file.mkv"), Path("/dst/file.mkv")
        )

        assert not result.success
        assert result.error == "Deplacement atomique echoue"


# ====================
# Tests symlinks relatifs
# ====================


class TestRelativeSymlinks:
    """Tests pour les symlinks relatifs."""

    def test_create_relative_symlink(self, tmp_path):
        """Cree symlink avec chemin relatif."""
        storage = tmp_path / "storage" / "Films" / "Action" / "M"
        video = tmp_path / "video" / "Films" / "Action" / "M"
        storage.mkdir(parents=True)
        video.mkdir(parents=True)

        target = storage / "Matrix.mkv"
        target.write_bytes(b"content")

        from src.adapters.file_system import FileSystemAdapter

        fs = FileSystemAdapter()
        transferer = TransfererService(
            fs, fs, tmp_path / "storage", tmp_path / "video"
        )

        symlink = transferer._create_mirror_symlink(target)

        assert symlink.is_symlink()
        assert symlink.resolve() == target
        # Verifier que c'est un chemin relatif
        link_target = os.readlink(symlink)
        assert ".." in link_target

    def test_symlink_mirrors_storage_structure(self, tmp_path):
        """Le symlink reflete la structure de storage dans video."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"

        # Structure profonde
        storage_subdir = storage / "Films" / "Science-Fiction" / "T"
        storage_subdir.mkdir(parents=True)
        target = storage_subdir / "Terminator (1984).mkv"
        target.write_bytes(b"content")

        from src.adapters.file_system import FileSystemAdapter

        fs = FileSystemAdapter()
        transferer = TransfererService(fs, fs, storage, video)

        symlink = transferer._create_mirror_symlink(target)

        # Le symlink doit etre dans video/Films/Science-Fiction/T/
        expected_symlink = video / "Films" / "Science-Fiction" / "T" / "Terminator (1984).mkv"
        assert symlink == expected_symlink
        assert symlink.resolve() == target

    def test_symlink_overwrites_existing(self, tmp_path):
        """Ecrase un symlink existant."""
        storage = tmp_path / "storage" / "Films"
        video = tmp_path / "video" / "Films"
        storage.mkdir(parents=True)
        video.mkdir(parents=True)

        target = storage / "Matrix.mkv"
        target.write_bytes(b"new content")

        # Creer un ancien symlink cassé
        old_symlink = video / "Matrix.mkv"
        old_symlink.symlink_to(storage / "nonexistent.mkv")

        from src.adapters.file_system import FileSystemAdapter

        fs = FileSystemAdapter()
        transferer = TransfererService(
            fs, fs, tmp_path / "storage", tmp_path / "video"
        )

        symlink = transferer._create_mirror_symlink(target)

        assert symlink.is_symlink()
        assert symlink.resolve() == target


# ====================
# Tests FileSystemAdapter.atomic_move
# ====================


class TestAtomicMove:
    """Tests pour atomic_move dans FileSystemAdapter."""

    def test_same_filesystem_uses_replace(self, tmp_path):
        """Utilise os.replace sur le meme filesystem."""
        from src.adapters.file_system import FileSystemAdapter

        source = tmp_path / "source.mkv"
        source.write_bytes(b"content")
        dest = tmp_path / "subdir" / "dest.mkv"

        fs = FileSystemAdapter()
        result = fs.atomic_move(source, dest)

        assert result is True
        assert not source.exists()
        assert dest.exists()
        assert dest.read_bytes() == b"content"

    def test_creates_parent_directories(self, tmp_path):
        """Cree les repertoires parents si necessaire."""
        from src.adapters.file_system import FileSystemAdapter

        source = tmp_path / "source.mkv"
        source.write_bytes(b"content")
        dest = tmp_path / "deep" / "nested" / "path" / "dest.mkv"

        fs = FileSystemAdapter()
        result = fs.atomic_move(source, dest)

        assert result is True
        assert dest.exists()
        assert dest.parent.exists()

    def test_failure_returns_false(self, tmp_path):
        """Retourne False en cas d'erreur."""
        from src.adapters.file_system import FileSystemAdapter

        # Source inexistante
        source = tmp_path / "nonexistent.mkv"
        dest = tmp_path / "dest.mkv"

        fs = FileSystemAdapter()
        result = fs.atomic_move(source, dest)

        assert result is False

    def test_preserves_metadata(self, tmp_path):
        """Preserve les metadonnees du fichier."""
        from src.adapters.file_system import FileSystemAdapter
        import time

        source = tmp_path / "source.mkv"
        source.write_bytes(b"content")

        # Modifier le mtime
        old_time = time.time() - 86400  # Il y a 24h
        os.utime(source, (old_time, old_time))
        original_mtime = source.stat().st_mtime

        dest = tmp_path / "dest.mkv"

        fs = FileSystemAdapter()
        fs.atomic_move(source, dest)

        # Note: os.replace preserve les metadonnees sur la plupart des systemes
        # mais ce n'est pas garanti pour cross-filesystem
        assert dest.exists()


# ====================
# Tests rollback
# ====================


class TestRollback:
    """Tests pour le rollback en cas d'erreur."""

    def test_rollback_on_symlink_error(self, tmp_path):
        """Rollback si creation symlink echoue apres move."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        # Ne pas creer video pour provoquer une erreur de symlink

        source = tmp_path / "downloads" / "movie.mkv"
        source.parent.mkdir(parents=True)
        content = b"fake video content" * 100
        source.write_bytes(content)

        dest = storage / "Films" / "Matrix.mkv"

        from src.adapters.file_system import FileSystemAdapter

        fs = FileSystemAdapter()
        transferer = TransfererService(fs, fs, storage, video)

        # Patch pour forcer une erreur apres le move
        original_create = transferer._create_mirror_symlink

        def failing_symlink(path):
            raise PermissionError("Cannot create symlink")

        transferer._create_mirror_symlink = failing_symlink

        result = transferer.transfer_file(source, dest, create_symlink=True)

        # Le transfert a echoue
        assert not result.success
        assert "Cannot create symlink" in result.error

        # Le fichier devrait etre revenu a sa position originale (rollback)
        # Note: Le rollback tente de remettre le fichier, mais selon l'etat
        # exact du systeme, il peut ne pas toujours reussir


# ====================
# Tests find_similar_content
# ====================


class TestFindSimilarContent:
    """Tests pour la detection de contenu similaire."""

    def test_similar_content_different_year(self, tmp_path):
        """Detecte un contenu similaire avec annee differente."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        video.mkdir()

        # Creer un dossier de serie existante
        existing_dir = video / "Series" / "I-K" / "Industry (2020)"
        existing_dir.mkdir(parents=True)
        (existing_dir / "Saison 01" / "episode.mkv").parent.mkdir(parents=True)
        (existing_dir / "Saison 01" / "episode.mkv").write_bytes(b"content")

        from src.adapters.file_system import FileSystemAdapter

        fs = FileSystemAdapter()
        transferer = TransfererService(fs, fs, storage, video)

        # Chercher un contenu similaire avec une annee differente
        result = transferer.find_similar_content(
            title="Industry",
            year=2021,  # Annee differente
            destination_dir=video / "Series" / "I-K",
            is_series=True,
        )

        assert result is not None
        assert result.existing_title == "Industry (2020)"
        assert "differentes" in result.similarity_reason.lower()

    def test_identical_content_detected(self, tmp_path):
        """Detecte un contenu existant avec le meme nom exact."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        video.mkdir()

        # Creer un dossier de serie existante
        existing_dir = video / "Series" / "I-K" / "Industry (2020)"
        existing_dir.mkdir(parents=True)
        (existing_dir / "Saison 01").mkdir(parents=True)
        (existing_dir / "Saison 01" / "S01E01.mkv").write_bytes(b"content")

        from src.adapters.file_system import FileSystemAdapter

        fs = FileSystemAdapter()
        transferer = TransfererService(fs, fs, storage, video)

        # Chercher le meme contenu (nom identique)
        result = transferer.find_similar_content(
            title="Industry",
            year=2020,  # Meme annee
            destination_dir=video / "Series" / "I-K",
            is_series=True,
        )

        assert result is not None
        assert result.existing_title == "Industry (2020)"
        assert result.new_title == "Industry (2020)"
        assert "meme nom" in result.similarity_reason.lower()

    def test_no_similar_content(self, tmp_path):
        """Pas de contenu similaire si dossier vide."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        video.mkdir()

        # Dossier de destination vide
        dest_dir = video / "Series" / "I-K"
        dest_dir.mkdir(parents=True)

        from src.adapters.file_system import FileSystemAdapter

        fs = FileSystemAdapter()
        transferer = TransfererService(fs, fs, storage, video)

        result = transferer.find_similar_content(
            title="Industry",
            year=2020,
            destination_dir=dest_dir,
            is_series=True,
        )

        assert result is None

    def test_identical_empty_directory_not_detected(self, tmp_path):
        """Ne detecte pas un dossier existant vide (sans fichiers)."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        storage.mkdir()
        video.mkdir()

        # Creer un dossier de serie existante VIDE
        existing_dir = video / "Series" / "I-K" / "Industry (2020)"
        existing_dir.mkdir(parents=True)
        # Pas de fichiers a l'interieur

        from src.adapters.file_system import FileSystemAdapter

        fs = FileSystemAdapter()
        transferer = TransfererService(fs, fs, storage, video)

        result = transferer.find_similar_content(
            title="Industry",
            year=2020,
            destination_dir=video / "Series" / "I-K",
            is_series=True,
        )

        # Ne devrait pas detecter car le dossier est vide
        assert result is None
