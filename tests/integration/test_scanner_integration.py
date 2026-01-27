"""
Tests d'integration pour le scanner avec les vrais adaptateurs.

Ces tests utilisent les implementations reelles (pas de mocks) pour valider
que le flow complet fonctionne: FileSystemAdapter, GuessitFilenameParser,
MediaInfoExtractor et ScannerService ensemble.
"""

from pathlib import Path

import pytest

from src.adapters.file_system import FileSystemAdapter
from src.adapters.parsing.guessit_parser import GuessitFilenameParser
from src.adapters.parsing.mediainfo_extractor import MediaInfoExtractor
from src.config import Settings
from src.container import Container
from src.core.value_objects import MediaType
from src.services.scanner import ScannerService


@pytest.fixture
def integration_settings(tmp_path: Path) -> Settings:
    """Settings pour les tests d'integration avec fichiers de petite taille acceptes."""
    downloads_dir = tmp_path / "downloads"
    storage_dir = tmp_path / "storage"
    video_dir = tmp_path / "video"

    # Creer les sous-repertoires de telechargements
    (downloads_dir / "Films").mkdir(parents=True)
    (downloads_dir / "Series").mkdir(parents=True)
    storage_dir.mkdir(parents=True)
    video_dir.mkdir(parents=True)

    # Creer un Settings avec _env_file=None pour ignorer .env
    return Settings(
        _env_file=None,  # Ignorer le fichier .env pour les tests
        downloads_dir=downloads_dir,
        storage_dir=storage_dir,
        video_dir=video_dir,
        database_url=f"sqlite:///{tmp_path}/test.db",
        min_file_size_mb=1,  # Minimum 1 pour accepter les petits fichiers
        max_files_per_subdir=50,
        match_score_threshold=85,
        log_file=tmp_path / "test.log",
    )


class TestScannerIntegrationFlow:
    """Tests d'integration du flow complet du scanner."""

    @pytest.fixture
    def real_adapters(self) -> tuple[FileSystemAdapter, GuessitFilenameParser, MediaInfoExtractor]:
        """Retourne les implementations reelles des adaptateurs."""
        return (
            FileSystemAdapter(),
            GuessitFilenameParser(),
            MediaInfoExtractor(),
        )

    def test_scanner_with_real_adapters_finds_movie(
        self,
        real_adapters: tuple[FileSystemAdapter, GuessitFilenameParser, MediaInfoExtractor],
        integration_settings: Settings,
    ) -> None:
        """Test du flow complet avec un fichier film."""
        file_system, filename_parser, media_info_extractor = real_adapters

        # Modifier min_file_size_mb pour accepter les petits fichiers
        # On utilise model_copy pour creer une copie avec modification
        settings = integration_settings.model_copy(update={"min_file_size_mb": 1})

        # Creer un fichier video dans Films/ (taille > min pour etre detecte)
        films_dir = settings.downloads_dir / "Films"
        movie_file = films_dir / "Inception.2010.1080p.BluRay.x264.mkv"
        # Ecrire du contenu pour avoir une taille > 0
        movie_file.write_bytes(b"X" * 2 * 1024 * 1024)  # 2 MB

        scanner = ScannerService(
            file_system=file_system,
            filename_parser=filename_parser,
            media_info_extractor=media_info_extractor,
            settings=settings,
        )

        # Act
        results = list(scanner.scan_downloads())

        # Assert
        assert len(results) == 1
        result = results[0]

        # Verifier que guessit a parse correctement
        assert result.parsed_info.title == "Inception"
        assert result.parsed_info.year == 2010
        assert result.detected_type == MediaType.MOVIE
        assert result.source_directory == "Films"
        assert result.corrected_location is False

        # media_info sera None pour un fichier factice (pas un vrai video)
        # mais l'extracteur a ete appele sans erreur

    def test_scanner_with_real_adapters_finds_series(
        self,
        real_adapters: tuple[FileSystemAdapter, GuessitFilenameParser, MediaInfoExtractor],
        integration_settings: Settings,
    ) -> None:
        """Test du flow complet avec un fichier serie."""
        file_system, filename_parser, media_info_extractor = real_adapters

        settings = integration_settings.model_copy(update={"min_file_size_mb": 1})

        # Creer un fichier video dans Series/
        series_dir = settings.downloads_dir / "Series"
        series_file = series_dir / "Breaking.Bad.S01E01.720p.HDTV.mkv"
        series_file.write_bytes(b"X" * 2 * 1024 * 1024)  # 2 MB

        scanner = ScannerService(
            file_system=file_system,
            filename_parser=filename_parser,
            media_info_extractor=media_info_extractor,
            settings=settings,
        )

        # Act
        results = list(scanner.scan_downloads())

        # Assert
        assert len(results) == 1
        result = results[0]

        # Verifier que guessit a parse correctement
        assert result.parsed_info.title == "Breaking Bad"
        assert result.parsed_info.season == 1
        assert result.parsed_info.episode == 1
        assert result.detected_type == MediaType.SERIES
        assert result.source_directory == "Series"
        assert result.corrected_location is False

    def test_scanner_type_hint_respected_for_films(
        self,
        real_adapters: tuple[FileSystemAdapter, GuessitFilenameParser, MediaInfoExtractor],
        integration_settings: Settings,
    ) -> None:
        """Test que le type_hint du repertoire est respecte.

        Quand un fichier avec nom ressemblant a une serie est dans Films/,
        le type_hint MOVIE est fourni a guessit et respecte.
        C'est le comportement attendu: le repertoire source fait foi.
        """
        file_system, filename_parser, media_info_extractor = real_adapters

        settings = integration_settings.model_copy(update={"min_file_size_mb": 1})

        # Creer un fichier avec nom de serie dans Films/
        # Le type_hint MOVIE sera respecte par guessit
        films_dir = settings.downloads_dir / "Films"
        series_like_file = films_dir / "Game.of.Thrones.S03E09.mkv"
        series_like_file.write_bytes(b"X" * 2 * 1024 * 1024)  # 2 MB

        scanner = ScannerService(
            file_system=file_system,
            filename_parser=filename_parser,
            media_info_extractor=media_info_extractor,
            settings=settings,
        )

        # Act
        results = list(scanner.scan_downloads())

        # Assert
        assert len(results) == 1
        result = results[0]

        # Le type_hint MOVIE est respecte, donc pas de corrected_location
        # Le repertoire source Films/ fait foi
        assert result.detected_type == MediaType.MOVIE
        assert result.source_directory == "Films"
        assert result.corrected_location is False  # Type correspond au repertoire

    def test_scanner_filters_non_video_files(
        self,
        real_adapters: tuple[FileSystemAdapter, GuessitFilenameParser, MediaInfoExtractor],
        integration_settings: Settings,
    ) -> None:
        """Test que les fichiers non-video sont filtres."""
        file_system, filename_parser, media_info_extractor = real_adapters

        settings = integration_settings.model_copy(update={"min_file_size_mb": 1})
        films_dir = settings.downloads_dir / "Films"

        # Creer un fichier video et des fichiers non-video
        (films_dir / "Movie.mkv").write_bytes(b"X" * 2 * 1024 * 1024)
        (films_dir / "Movie.srt").write_text("subtitles")
        (films_dir / "Movie.nfo").write_text("info")

        scanner = ScannerService(
            file_system=file_system,
            filename_parser=filename_parser,
            media_info_extractor=media_info_extractor,
            settings=settings,
        )

        # Act
        results = list(scanner.scan_downloads())

        # Assert: seul le mkv est inclus
        assert len(results) == 1
        assert results[0].video_file.filename == "Movie.mkv"

    def test_scanner_handles_double_episodes(
        self,
        real_adapters: tuple[FileSystemAdapter, GuessitFilenameParser, MediaInfoExtractor],
        integration_settings: Settings,
    ) -> None:
        """Test que les doubles episodes sont correctement detectes."""
        file_system, filename_parser, media_info_extractor = real_adapters

        settings = integration_settings.model_copy(update={"min_file_size_mb": 1})
        series_dir = settings.downloads_dir / "Series"
        double_ep = series_dir / "Show.S01E01E02.720p.mkv"
        double_ep.write_bytes(b"X" * 2 * 1024 * 1024)  # 2 MB

        scanner = ScannerService(
            file_system=file_system,
            filename_parser=filename_parser,
            media_info_extractor=media_info_extractor,
            settings=settings,
        )

        # Act
        results = list(scanner.scan_downloads())

        # Assert
        assert len(results) == 1
        result = results[0]
        assert result.parsed_info.episode == 1
        assert result.parsed_info.episode_end == 2


class TestContainerIntegration:
    """Tests d'integration via le container DI."""

    @pytest.fixture
    def container_with_test_settings(self, tmp_path: Path) -> Container:
        """Container configure avec des settings de test."""
        # Creer la structure de repertoires
        downloads_dir = tmp_path / "downloads"
        (downloads_dir / "Films").mkdir(parents=True)
        (downloads_dir / "Series").mkdir(parents=True)
        (tmp_path / "storage").mkdir()
        (tmp_path / "video").mkdir()

        # Le container utilise les settings par defaut
        # mais on va override avec les settings de test
        container = Container()

        # Override config provider pour utiliser nos settings de test
        test_settings = Settings(
            _env_file=None,  # Ignorer le fichier .env pour les tests
            downloads_dir=downloads_dir,
            storage_dir=tmp_path / "storage",
            video_dir=tmp_path / "video",
            database_url=f"sqlite:///{tmp_path}/test.db",
            min_file_size_mb=1,
            log_file=tmp_path / "test.log",
        )
        container.config.override(test_settings)

        return container

    def test_container_provides_working_scanner(
        self,
        container_with_test_settings: Container,
    ) -> None:
        """Test que le container fournit un scanner fonctionnel."""
        container = container_with_test_settings

        # Creer un fichier de test avec taille suffisante
        downloads_dir = container.config().downloads_dir
        test_file = downloads_dir / "Films" / "Test.Movie.2020.mkv"
        test_file.write_bytes(b"X" * 2 * 1024 * 1024)  # 2 MB

        # Obtenir le scanner depuis le container
        scanner = container.scanner_service()

        # Act
        results = list(scanner.scan_downloads())

        # Assert
        assert len(results) == 1
        assert results[0].parsed_info.title is not None

    def test_container_singletons_are_reused(
        self,
        container_with_test_settings: Container,
    ) -> None:
        """Test que les singletons du container sont bien reutilises."""
        container = container_with_test_settings

        # Les adaptateurs sont des singletons
        fs1 = container.file_system()
        fs2 = container.file_system()
        assert fs1 is fs2

        parser1 = container.filename_parser()
        parser2 = container.filename_parser()
        assert parser1 is parser2

        extractor1 = container.media_info_extractor()
        extractor2 = container.media_info_extractor()
        assert extractor1 is extractor2

    def test_scanner_service_is_factory(
        self,
        container_with_test_settings: Container,
    ) -> None:
        """Test que le scanner_service est une factory (nouvelle instance a chaque appel)."""
        container = container_with_test_settings

        scanner1 = container.scanner_service()
        scanner2 = container.scanner_service()

        # Mais les adaptateurs injectes sont les memes (singletons)
        assert scanner1._file_system is scanner2._file_system
        assert scanner1._filename_parser is scanner2._filename_parser
