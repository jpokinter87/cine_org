"""
Tests unitaires pour ImporterService.

Tests couvrant:
- Detection des doublons par hash
- Import de nouveaux fichiers
- Detection du type (Films/Series)
- Generateur de resultats
- Gestion des erreurs
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.entities.video import PendingValidation, VideoFile
from src.core.value_objects import MediaInfo, Resolution, VideoCodec
from src.services.importer import ImportDecision, ImporterService, ImportResult


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_file_system():
    """Mock pour IFileSystem."""
    fs = MagicMock()
    fs.get_size.return_value = 1_500_000_000  # 1.5 Go
    fs.exists.return_value = True
    return fs


@pytest.fixture
def mock_filename_parser():
    """Mock pour IFilenameParser."""
    parser = MagicMock()
    parsed = MagicMock()
    parsed.title = "Avatar"
    parsed.year = 2009
    parser.parse.return_value = parsed
    return parser


@pytest.fixture
def mock_media_info_extractor():
    """Mock pour IMediaInfoExtractor."""
    extractor = MagicMock()
    media_info = MediaInfo(
        resolution=Resolution(width=1920, height=1080),
        video_codec=VideoCodec(name="HEVC"),
        audio_codecs=(),
        audio_languages=(),
        duration_seconds=7200,
    )
    extractor.extract.return_value = media_info
    return extractor


@pytest.fixture
def mock_video_file_repo():
    """Mock pour IVideoFileRepository."""
    repo = MagicMock()
    repo.get_by_hash.return_value = None
    repo.get_by_path.return_value = None
    repo.save.side_effect = lambda vf: VideoFile(
        id="1",
        path=vf.path,
        filename=vf.filename,
        size_bytes=vf.size_bytes,
        file_hash=vf.file_hash,
        media_info=vf.media_info,
    )
    return repo


@pytest.fixture
def mock_pending_repo():
    """Mock pour PendingValidationRepository."""
    repo = MagicMock()
    repo.save.side_effect = lambda p: PendingValidation(
        id="1",
        video_file=p.video_file,
        candidates=p.candidates,
    )
    return repo


@pytest.fixture
def mock_compute_hash():
    """Mock pour la fonction de calcul de hash."""
    return MagicMock(return_value="abc123def456")


@pytest.fixture
def importer_service(
    mock_file_system,
    mock_filename_parser,
    mock_media_info_extractor,
    mock_video_file_repo,
    mock_pending_repo,
    mock_compute_hash,
):
    """Cree un ImporterService avec tous les mocks."""
    return ImporterService(
        file_system=mock_file_system,
        filename_parser=mock_filename_parser,
        media_info_extractor=mock_media_info_extractor,
        video_file_repo=mock_video_file_repo,
        pending_repo=mock_pending_repo,
        compute_hash_fn=mock_compute_hash,
    )


# ============================================================================
# Tests: _should_import
# ============================================================================


class TestShouldImport:
    """Tests pour la detection des doublons."""

    def test_skip_known_hash(
        self,
        importer_service,
        mock_video_file_repo,
        mock_compute_hash,
    ):
        """Fichier avec hash existant -> SKIP_KNOWN."""
        file_path = Path("/storage/Films/A/Avatar (2009)/Avatar (2009).mkv")
        existing_vf = VideoFile(
            id="1",
            path=file_path,
            filename="Avatar (2009).mkv",
            file_hash="abc123def456",
        )
        mock_video_file_repo.get_by_hash.return_value = existing_vf

        decision, existing = importer_service._should_import(file_path)

        assert decision == ImportDecision.SKIP_KNOWN
        assert existing == existing_vf
        mock_compute_hash.assert_called_once_with(file_path)

    def test_import_new_file(
        self,
        importer_service,
        mock_video_file_repo,
        mock_compute_hash,
    ):
        """Nouveau fichier (hash inconnu) -> IMPORT."""
        file_path = Path("/storage/Films/I/Inception (2010)/Inception (2010).mkv")
        mock_video_file_repo.get_by_hash.return_value = None
        mock_video_file_repo.get_by_path.return_value = None

        decision, existing = importer_service._should_import(file_path)

        assert decision == ImportDecision.IMPORT
        assert existing is None

    def test_update_path_same_hash_different_path(
        self,
        importer_service,
        mock_video_file_repo,
        mock_compute_hash,
    ):
        """Fichier connu par hash mais path different -> UPDATE_PATH."""
        old_path = Path("/storage/Films/A/Avatar (2009)/Avatar.mkv")
        new_path = Path("/storage/Films/A/Avatar (2009)/Avatar (2009).mkv")
        existing_vf = VideoFile(
            id="1",
            path=old_path,
            filename="Avatar.mkv",
            file_hash="abc123def456",
        )
        mock_video_file_repo.get_by_hash.return_value = existing_vf

        decision, existing = importer_service._should_import(new_path)

        assert decision == ImportDecision.UPDATE_PATH
        assert existing == existing_vf

    def test_reimport_modified_file(
        self,
        importer_service,
        mock_video_file_repo,
        mock_compute_hash,
    ):
        """Fichier au meme path mais hash different -> IMPORT (fichier modifie)."""
        file_path = Path("/storage/Films/A/Avatar (2009)/Avatar (2009).mkv")
        existing_vf = VideoFile(
            id="1",
            path=file_path,
            filename="Avatar (2009).mkv",
            file_hash="old_hash_different",  # Hash different
        )
        mock_video_file_repo.get_by_hash.return_value = None  # Hash actuel pas trouve
        mock_video_file_repo.get_by_path.return_value = existing_vf  # Path existe

        decision, existing = importer_service._should_import(file_path)

        assert decision == ImportDecision.IMPORT
        assert existing is None


# ============================================================================
# Tests: _import_file
# ============================================================================


class TestImportFile:
    """Tests pour l'import de fichiers."""

    def test_import_new_file_creates_video_file_and_pending(
        self,
        importer_service,
        mock_video_file_repo,
        mock_pending_repo,
        mock_media_info_extractor,
    ):
        """Nouveau fichier -> VideoFile et PendingValidation crees."""
        file_path = Path("/storage/Films/I/Inception (2010)/Inception (2010).mkv")

        result = importer_service._import_file(file_path)

        assert result.decision == ImportDecision.IMPORT
        assert result.filename == "Inception (2010).mkv"
        assert result.error_message is None

        # VideoFile a ete sauvegarde
        mock_video_file_repo.save.assert_called_once()
        saved_vf = mock_video_file_repo.save.call_args[0][0]
        assert saved_vf.path == file_path
        assert saved_vf.file_hash == "abc123def456"

        # PendingValidation a ete cree
        mock_pending_repo.save.assert_called_once()

    def test_import_extracts_media_info(
        self,
        importer_service,
        mock_video_file_repo,
        mock_media_info_extractor,
    ):
        """Import extrait les metadonnees techniques via media_info_extractor."""
        file_path = Path("/storage/Films/A/Avatar (2009)/Avatar (2009).mkv")

        importer_service._import_file(file_path)

        mock_media_info_extractor.extract.assert_called_once_with(file_path)
        saved_vf = mock_video_file_repo.save.call_args[0][0]
        assert saved_vf.media_info is not None
        assert saved_vf.media_info.resolution.width == 1920


# ============================================================================
# Tests: _detect_import_type
# ============================================================================


class TestDetectImportType:
    """Tests pour la detection du type de media."""

    def test_detect_movie_type(self, importer_service):
        """Fichier dans Films/ -> import_type = 'movie'."""
        file_path = Path("/storage/Films/A/Avatar (2009)/Avatar (2009).mkv")

        import_type = importer_service._detect_import_type(file_path)

        assert import_type == "movie"

    def test_detect_series_type(self, importer_service):
        """Fichier dans Series/ -> import_type = 'series'."""
        file_path = Path("/storage/Series/B/Breaking Bad (2008)/S01/Episode.mkv")

        import_type = importer_service._detect_import_type(file_path)

        assert import_type == "series"

    def test_detect_series_type_accented(self, importer_service):
        """Fichier dans Séries/ (avec accent) -> import_type = 'series'."""
        file_path = Path("/storage/Séries/B/Breaking Bad (2008)/S01/Episode.mkv")

        import_type = importer_service._detect_import_type(file_path)

        assert import_type == "series"

    def test_detect_unknown_type(self, importer_service):
        """Fichier hors Films/ et Series/ -> import_type = 'unknown'."""
        file_path = Path("/downloads/Video/Random.mkv")

        import_type = importer_service._detect_import_type(file_path)

        assert import_type == "unknown"


# ============================================================================
# Tests: scan_library
# ============================================================================


class TestScanLibrary:
    """Tests pour le scan de bibliotheque."""

    def test_scan_library_yields_results(
        self,
        importer_service,
        mock_video_file_repo,
        mock_pending_repo,
    ):
        """scan_library retourne un generateur qui yield les resultats."""
        # Creer une structure de fichiers temporaire
        with patch.object(Path, 'rglob') as mock_rglob:
            # Simuler 3 fichiers video
            file1 = MagicMock()
            file1.is_dir.return_value = False
            file1.is_symlink.return_value = False
            file1.suffix = ".mkv"
            file1.name = "Avatar (2009).mkv"
            file1.__str__ = lambda x: "/storage/Films/A/Avatar (2009).mkv"
            file1.parents = [
                Path("/storage/Films/A"),
                Path("/storage/Films"),
                Path("/storage"),
            ]

            file2 = MagicMock()
            file2.is_dir.return_value = False
            file2.is_symlink.return_value = False
            file2.suffix = ".mkv"
            file2.name = "Inception (2010).mkv"
            file2.__str__ = lambda x: "/storage/Films/I/Inception (2010).mkv"
            file2.parents = [
                Path("/storage/Films/I"),
                Path("/storage/Films"),
                Path("/storage"),
            ]

            # Un repertoire (doit etre ignore)
            dir1 = MagicMock()
            dir1.is_dir.return_value = True
            dir1.is_symlink.return_value = False

            # Un fichier non-video (doit etre ignore)
            file_txt = MagicMock()
            file_txt.is_dir.return_value = False
            file_txt.is_symlink.return_value = False
            file_txt.suffix = ".txt"
            file_txt.name = "readme.txt"

            mock_rglob.return_value = [file1, dir1, file_txt, file2]

            # Appeler scan_library
            results = list(importer_service.scan_library(Path("/storage")))

        # Verifier que seuls les fichiers video sont traites
        assert len(results) == 2
        assert all(isinstance(r, ImportResult) for r in results)

    def test_scan_library_is_generator(self, importer_service):
        """scan_library est un generateur (lazy evaluation)."""
        with patch.object(Path, 'rglob') as mock_rglob:
            mock_rglob.return_value = []

            result = importer_service.scan_library(Path("/storage"))

            # C'est un generateur, pas une liste
            from typing import Generator
            assert hasattr(result, '__iter__')
            assert hasattr(result, '__next__')

    def test_scan_library_ignores_symlinks(self, importer_service):
        """scan_library ignore les symlinks."""
        with patch.object(Path, 'rglob') as mock_rglob:
            symlink = MagicMock()
            symlink.is_dir.return_value = False
            symlink.is_symlink.return_value = True

            mock_rglob.return_value = [symlink]

            results = list(importer_service.scan_library(Path("/storage")))

        assert len(results) == 0

    def test_scan_library_ignores_sample_files(self, importer_service):
        """scan_library ignore les fichiers sample."""
        with patch.object(Path, 'rglob') as mock_rglob:
            sample_file = MagicMock()
            sample_file.is_dir.return_value = False
            sample_file.is_symlink.return_value = False
            sample_file.suffix = ".mkv"
            sample_file.name = "movie.sample.mkv"

            mock_rglob.return_value = [sample_file]

            results = list(importer_service.scan_library(Path("/storage")))

        assert len(results) == 0


# ============================================================================
# Tests: Dry run mode
# ============================================================================


class TestDryRunMode:
    """Tests pour le mode dry-run."""

    def test_dry_run_does_not_save_video_file(
        self,
        mock_file_system,
        mock_filename_parser,
        mock_media_info_extractor,
        mock_video_file_repo,
        mock_pending_repo,
        mock_compute_hash,
    ):
        """En mode dry-run, VideoFile n'est pas sauvegarde."""
        service = ImporterService(
            file_system=mock_file_system,
            filename_parser=mock_filename_parser,
            media_info_extractor=mock_media_info_extractor,
            video_file_repo=mock_video_file_repo,
            pending_repo=mock_pending_repo,
            compute_hash_fn=mock_compute_hash,
            dry_run=True,
        )

        file_path = Path("/storage/Films/A/Avatar (2009)/Avatar (2009).mkv")
        result = service._import_file(file_path)

        assert result.decision == ImportDecision.IMPORT
        mock_video_file_repo.save.assert_not_called()
        mock_pending_repo.save.assert_not_called()


# ============================================================================
# Tests: Error handling
# ============================================================================


class TestErrorHandling:
    """Tests pour la gestion des erreurs."""

    def test_process_file_handles_exceptions(
        self,
        importer_service,
        mock_compute_hash,
    ):
        """Les erreurs sont capturees et retournent ImportDecision.ERROR."""
        mock_compute_hash.side_effect = PermissionError("Access denied")

        file_path = Path("/storage/Films/A/Avatar (2009)/Avatar (2009).mkv")
        result = importer_service._process_file(file_path)

        assert result.decision == ImportDecision.ERROR
        assert "Access denied" in result.error_message


# ============================================================================
# Tests: ImportResult dataclass
# ============================================================================


class TestImportResult:
    """Tests pour la dataclass ImportResult."""

    def test_import_result_creation(self):
        """ImportResult peut etre cree avec tous les champs."""
        result = ImportResult(
            filename="test.mkv",
            decision=ImportDecision.IMPORT,
            error_message=None,
        )

        assert result.filename == "test.mkv"
        assert result.decision == ImportDecision.IMPORT
        assert result.error_message is None

    def test_import_result_with_error(self):
        """ImportResult avec message d'erreur."""
        result = ImportResult(
            filename="broken.mkv",
            decision=ImportDecision.ERROR,
            error_message="File corrupted",
        )

        assert result.decision == ImportDecision.ERROR
        assert result.error_message == "File corrupted"


# ============================================================================
# Tests: ImportDecision enum
# ============================================================================


class TestImportDecision:
    """Tests pour l'enum ImportDecision."""

    def test_import_decision_values(self):
        """Verifie les valeurs de l'enum."""
        assert ImportDecision.IMPORT.value == "import"
        assert ImportDecision.SKIP_KNOWN.value == "skip_known"
        assert ImportDecision.UPDATE_PATH.value == "update_path"
        assert ImportDecision.ERROR.value == "error"
