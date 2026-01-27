"""
Tests unitaires pour ScannerService.

Ces tests utilisent des mocks pour IFileSystem et IFilenameParser,
sans creer de vrais fichiers sur le disque.
"""

from pathlib import Path
from typing import Iterator, Optional
from unittest.mock import MagicMock, patch

import pytest

from src.adapters.file_system import FileSystemAdapter, IGNORED_PATTERNS, VIDEO_EXTENSIONS
from src.config import Settings
from src.core.ports.file_system import IFileSystem
from src.core.ports.parser import IFilenameParser
from src.core.value_objects import MediaType, ParsedFilename
from src.services.scanner import ScannerService, ScanResult


class TestScannerFiltering:
    """Tests pour le filtrage des fichiers par le scanner."""

    def test_scan_filters_small_files(
        self,
        mock_file_system: MagicMock,
        mock_filename_parser: MagicMock,
        test_settings: Settings,
    ) -> None:
        """Les fichiers < 100MB doivent etre exclus du scan."""
        # Arrange: fichier de 50MB (en dessous du seuil de 100MB)
        small_file = test_settings.downloads_dir / "Films" / "small_movie.mkv"
        small_file.parent.mkdir(parents=True, exist_ok=True)
        small_file.touch()

        # Simuler une taille de 50MB
        mock_file_system.get_size.return_value = 50 * 1024 * 1024  # 50 MB

        # Utiliser FileSystemAdapter pour le filtrage reel
        adapter = FileSystemAdapter()
        results = list(adapter.list_video_files(
            test_settings.downloads_dir / "Films",
            min_file_size_bytes=test_settings.min_file_size_mb * 1024 * 1024
        ))

        # Assert: le fichier ne doit pas etre inclus (fichier vide donc 0 bytes)
        assert len(results) == 0

    def test_scan_filters_sample_files(
        self,
        mock_file_system: MagicMock,
        mock_filename_parser: MagicMock,
        test_settings: Settings,
    ) -> None:
        """Les fichiers contenant 'sample' dans le nom doivent etre exclus."""
        # Arrange: fichiers avec patterns ignores
        films_dir = test_settings.downloads_dir / "Films"
        sample_files = [
            films_dir / "Movie.Sample.mkv",
            films_dir / "sample-movie.mp4",
            films_dir / "Movie-SAMPLE.mkv",
        ]
        for f in sample_files:
            f.touch()

        # Utiliser FileSystemAdapter pour le filtrage reel
        adapter = FileSystemAdapter()
        results = list(adapter.list_video_files(films_dir, min_file_size_bytes=0))

        # Assert: aucun fichier sample ne doit etre inclus
        assert len(results) == 0

    def test_scan_filters_all_ignored_patterns(
        self,
        test_settings: Settings,
    ) -> None:
        """Tous les patterns ignores (sample, trailer, preview, extras, bonus) sont exclus."""
        # Arrange: creer un fichier pour chaque pattern ignore
        films_dir = test_settings.downloads_dir / "Films"
        for pattern in IGNORED_PATTERNS:
            ignored_file = films_dir / f"Movie.{pattern}.mkv"
            ignored_file.touch()

        # Utiliser FileSystemAdapter pour le filtrage reel
        adapter = FileSystemAdapter()
        results = list(adapter.list_video_files(films_dir, min_file_size_bytes=0))

        # Assert: aucun fichier avec pattern ignore ne doit etre inclus
        assert len(results) == 0

    def test_scan_filters_symlinks(
        self,
        test_settings: Settings,
    ) -> None:
        """Les symlinks doivent etre exclus pour eviter les doublons."""
        # Arrange: creer un vrai fichier et un symlink vers lui
        films_dir = test_settings.downloads_dir / "Films"
        real_file = films_dir / "RealMovie.mkv"
        real_file.touch()

        symlink_file = films_dir / "SymlinkMovie.mkv"
        symlink_file.symlink_to(real_file)

        # Utiliser FileSystemAdapter pour le filtrage reel
        adapter = FileSystemAdapter()
        results = list(adapter.list_video_files(films_dir, min_file_size_bytes=0))

        # Assert: seul le vrai fichier est inclus, pas le symlink
        assert len(results) == 1
        assert results[0].name == "RealMovie.mkv"

    def test_scan_detects_video_extensions(
        self,
        test_settings: Settings,
    ) -> None:
        """Seuls les fichiers avec extensions video valides sont inclus."""
        # Arrange: creer des fichiers avec differentes extensions
        films_dir = test_settings.downloads_dir / "Films"
        video_files = [
            films_dir / "movie.mkv",
            films_dir / "movie.mp4",
            films_dir / "movie.avi",
        ]
        non_video_files = [
            films_dir / "movie.txt",
            films_dir / "movie.srt",
            films_dir / "movie.nfo",
            films_dir / "movie.jpg",
        ]

        for f in video_files + non_video_files:
            f.touch()

        # Utiliser FileSystemAdapter pour le filtrage reel
        adapter = FileSystemAdapter()
        results = list(adapter.list_video_files(films_dir, min_file_size_bytes=0))

        # Assert: seuls les fichiers video sont inclus
        result_names = {r.name for r in results}
        assert result_names == {"movie.mkv", "movie.mp4", "movie.avi"}

    def test_all_video_extensions_supported(self) -> None:
        """Verifier que toutes les extensions video attendues sont supportees."""
        expected_extensions = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"}
        assert VIDEO_EXTENSIONS == expected_extensions


class TestScannerTypeHint:
    """Tests pour la detection de type et le type hint du repertoire."""

    def test_scan_provides_type_hint_from_directory_films(
        self,
        mock_file_system: MagicMock,
        mock_filename_parser: MagicMock,
        test_settings: Settings,
    ) -> None:
        """Les fichiers dans Films/ recoivent MediaType.MOVIE comme type_hint."""
        # Arrange
        films_dir = test_settings.downloads_dir / "Films"
        movie_file = films_dir / "Inception.2010.1080p.mkv"
        movie_file.touch()

        # Configurer le mock pour enregistrer les appels
        parse_calls: list[tuple[str, MediaType]] = []
        def track_parse(filename: str, type_hint: Optional[MediaType] = None) -> ParsedFilename:
            parse_calls.append((filename, type_hint))
            return ParsedFilename(title="Inception", year=2010, media_type=MediaType.MOVIE)

        mock_filename_parser.parse.side_effect = track_parse

        # Mock list_video_files to return file only for Films directory
        def list_video_files_by_dir(directory: Path, min_file_size_bytes: int = 0) -> Iterator[Path]:
            if "Films" in str(directory):
                yield movie_file
            # Series/ retourne rien

        mock_file_system.list_video_files = MagicMock(side_effect=list_video_files_by_dir)
        mock_file_system.get_size.return_value = 500 * 1024 * 1024

        scanner = ScannerService(mock_file_system, mock_filename_parser, test_settings)

        # Act
        results = list(scanner.scan_downloads())

        # Assert: le parser a ete appele avec MOVIE comme type_hint
        assert len(parse_calls) == 1
        assert parse_calls[0][1] == MediaType.MOVIE

    def test_scan_provides_type_hint_from_directory_series(
        self,
        mock_file_system: MagicMock,
        mock_filename_parser: MagicMock,
        test_settings: Settings,
    ) -> None:
        """Les fichiers dans Series/ recoivent MediaType.SERIES comme type_hint."""
        # Arrange
        series_dir = test_settings.downloads_dir / "Series"
        series_file = series_dir / "Breaking.Bad.S01E01.mkv"
        series_file.touch()

        # Configurer le mock pour enregistrer les appels
        parse_calls: list[tuple[str, MediaType]] = []
        def track_parse(filename: str, type_hint: Optional[MediaType] = None) -> ParsedFilename:
            parse_calls.append((filename, type_hint))
            return ParsedFilename(
                title="Breaking Bad",
                media_type=MediaType.SERIES,
                season=1,
                episode=1,
            )

        mock_filename_parser.parse.side_effect = track_parse

        # Creer un mock file_system avec list_video_files qui retourne les fichiers
        # selon le repertoire scanne
        def list_video_files_by_dir(directory: Path, min_file_size_bytes: int = 0) -> Iterator[Path]:
            if "Series" in str(directory):
                yield series_file
            # Films/ retourne rien
        mock_file_system.list_video_files = MagicMock(side_effect=list_video_files_by_dir)
        mock_file_system.get_size.return_value = 500 * 1024 * 1024

        scanner = ScannerService(mock_file_system, mock_filename_parser, test_settings)

        # Act
        results = list(scanner.scan_downloads())

        # Assert: le parser a ete appele avec SERIES comme type_hint
        assert len(parse_calls) == 1
        assert parse_calls[0][1] == MediaType.SERIES


class TestScannerCorrectedLocation:
    """Tests pour la detection de fichiers mal places."""

    def test_scan_detects_corrected_location_series_in_films(
        self,
        mock_file_system: MagicMock,
        mock_filename_parser: MagicMock,
        test_settings: Settings,
    ) -> None:
        """Une serie dans Films/ est detectee comme mal placee (corrected_location=True)."""
        # Arrange: fichier de serie dans le repertoire Films
        films_dir = test_settings.downloads_dir / "Films"
        series_file = films_dir / "Breaking.Bad.S01E01.mkv"
        series_file.touch()

        # Le parser detecte que c'est une serie malgre le type_hint MOVIE
        def parse_as_series(filename: str, type_hint: Optional[MediaType] = None) -> ParsedFilename:
            return ParsedFilename(
                title="Breaking Bad",
                media_type=MediaType.SERIES,  # Detecte comme serie
                season=1,
                episode=1,
            )

        mock_filename_parser.parse.side_effect = parse_as_series

        # Mock list_video_files to return file only for Films directory
        def list_video_files_by_dir(directory: Path, min_file_size_bytes: int = 0) -> Iterator[Path]:
            if "Films" in str(directory):
                yield series_file
            # Series/ retourne rien

        mock_file_system.list_video_files = MagicMock(side_effect=list_video_files_by_dir)
        mock_file_system.get_size.return_value = 500 * 1024 * 1024

        scanner = ScannerService(mock_file_system, mock_filename_parser, test_settings)

        # Act
        results = list(scanner.scan_downloads())

        # Assert: le fichier est marque comme mal place
        assert len(results) == 1
        assert results[0].corrected_location is True
        assert results[0].source_directory == "Films"
        assert results[0].detected_type == MediaType.SERIES

    def test_scan_detects_corrected_location_movie_in_series(
        self,
        mock_file_system: MagicMock,
        mock_filename_parser: MagicMock,
        test_settings: Settings,
    ) -> None:
        """Un film dans Series/ est detecte comme mal place (corrected_location=True)."""
        # Arrange: fichier de film dans le repertoire Series
        series_dir = test_settings.downloads_dir / "Series"
        movie_file = series_dir / "Inception.2010.1080p.mkv"
        movie_file.touch()

        # Le parser detecte que c'est un film malgre le type_hint SERIES
        def parse_as_movie(filename: str, type_hint: Optional[MediaType] = None) -> ParsedFilename:
            return ParsedFilename(
                title="Inception",
                year=2010,
                media_type=MediaType.MOVIE,  # Detecte comme film
            )

        mock_filename_parser.parse.side_effect = parse_as_movie

        # Mock list_video_files to return file only for Series directory
        def list_video_files_by_dir(directory: Path, min_file_size_bytes: int = 0) -> Iterator[Path]:
            if "Series" in str(directory):
                yield movie_file
            # Films/ retourne rien

        mock_file_system.list_video_files = MagicMock(side_effect=list_video_files_by_dir)
        mock_file_system.get_size.return_value = 500 * 1024 * 1024

        scanner = ScannerService(mock_file_system, mock_filename_parser, test_settings)

        # Act
        results = list(scanner.scan_downloads())

        # Assert: le fichier est marque comme mal place
        assert len(results) == 1
        assert results[0].corrected_location is True
        assert results[0].source_directory == "Series"
        assert results[0].detected_type == MediaType.MOVIE

    def test_scan_correct_location_movie_in_films(
        self,
        mock_file_system: MagicMock,
        mock_filename_parser: MagicMock,
        test_settings: Settings,
    ) -> None:
        """Un film dans Films/ n'est pas mal place (corrected_location=False)."""
        # Arrange
        films_dir = test_settings.downloads_dir / "Films"
        movie_file = films_dir / "Inception.2010.1080p.mkv"
        movie_file.touch()

        def parse_as_movie(filename: str, type_hint: Optional[MediaType] = None) -> ParsedFilename:
            return ParsedFilename(
                title="Inception",
                year=2010,
                media_type=MediaType.MOVIE,
            )

        mock_filename_parser.parse.side_effect = parse_as_movie

        # Mock list_video_files to return file only for Films directory
        def list_video_files_by_dir(directory: Path, min_file_size_bytes: int = 0) -> Iterator[Path]:
            if "Films" in str(directory):
                yield movie_file
            # Series/ retourne rien

        mock_file_system.list_video_files = MagicMock(side_effect=list_video_files_by_dir)
        mock_file_system.get_size.return_value = 500 * 1024 * 1024

        scanner = ScannerService(mock_file_system, mock_filename_parser, test_settings)

        # Act
        results = list(scanner.scan_downloads())

        # Assert: le fichier n'est pas mal place
        assert len(results) == 1
        assert results[0].corrected_location is False

    def test_scan_unknown_type_not_corrected(
        self,
        mock_file_system: MagicMock,
        mock_filename_parser: MagicMock,
        test_settings: Settings,
    ) -> None:
        """Un fichier avec type UNKNOWN n'est pas considere mal place."""
        # Arrange
        films_dir = test_settings.downloads_dir / "Films"
        unknown_file = films_dir / "random_video.mkv"
        unknown_file.touch()

        def parse_as_unknown(filename: str, type_hint: Optional[MediaType] = None) -> ParsedFilename:
            return ParsedFilename(
                title="random_video",
                media_type=MediaType.UNKNOWN,
            )

        mock_filename_parser.parse.side_effect = parse_as_unknown

        # Mock list_video_files to return file only for Films directory
        def list_video_files_by_dir(directory: Path, min_file_size_bytes: int = 0) -> Iterator[Path]:
            if "Films" in str(directory):
                yield unknown_file
            # Series/ retourne rien

        mock_file_system.list_video_files = MagicMock(side_effect=list_video_files_by_dir)
        mock_file_system.get_size.return_value = 500 * 1024 * 1024

        scanner = ScannerService(mock_file_system, mock_filename_parser, test_settings)

        # Act
        results = list(scanner.scan_downloads())

        # Assert: type UNKNOWN n'est jamais considere mal place
        assert len(results) == 1
        assert results[0].corrected_location is False


class TestScanResult:
    """Tests pour la structure ScanResult."""

    def test_scan_returns_scan_result_with_all_fields(
        self,
        mock_file_system: MagicMock,
        mock_filename_parser: MagicMock,
        test_settings: Settings,
    ) -> None:
        """ScanResult contient tous les champs attendus (media_info=None dans ce plan)."""
        # Arrange
        films_dir = test_settings.downloads_dir / "Films"
        movie_file = films_dir / "Inception.2010.BluRay.1080p.mkv"
        movie_file.touch()

        parsed = ParsedFilename(
            title="Inception",
            year=2010,
            media_type=MediaType.MOVIE,
            video_codec="H.264",
            audio_codec="DTS",
            resolution="1080p",
            source="BluRay",
        )
        # Clear default side_effect and set return_value
        mock_filename_parser.parse.side_effect = None
        mock_filename_parser.parse.return_value = parsed

        # Mock list_video_files to return file only for Films directory
        def list_video_files_by_dir(directory: Path, min_file_size_bytes: int = 0) -> Iterator[Path]:
            if "Films" in str(directory):
                yield movie_file
            # Series/ retourne rien

        mock_file_system.list_video_files = MagicMock(side_effect=list_video_files_by_dir)
        mock_file_system.get_size.return_value = 500 * 1024 * 1024

        scanner = ScannerService(mock_file_system, mock_filename_parser, test_settings)

        # Act
        results = list(scanner.scan_downloads())

        # Assert: tous les champs sont peuples
        assert len(results) == 1
        result = results[0]

        # VideoFile
        assert result.video_file is not None
        assert result.video_file.path == movie_file
        assert result.video_file.filename == "Inception.2010.BluRay.1080p.mkv"
        assert result.video_file.size_bytes == 500 * 1024 * 1024

        # ParsedFilename
        assert result.parsed_info == parsed
        assert result.parsed_info.title == "Inception"
        assert result.parsed_info.year == 2010

        # Type et source
        assert result.detected_type == MediaType.MOVIE
        assert result.source_directory == "Films"
        assert result.corrected_location is False

        # MediaInfo est None dans ce plan
        assert result.media_info is None

    def test_scan_multiple_files(
        self,
        mock_file_system: MagicMock,
        mock_filename_parser: MagicMock,
        test_settings: Settings,
    ) -> None:
        """Le scanner retourne un ScanResult pour chaque fichier video."""
        # Arrange
        films_dir = test_settings.downloads_dir / "Films"
        movie1 = films_dir / "Movie1.mkv"
        movie2 = films_dir / "Movie2.mkv"
        movie1.touch()
        movie2.touch()

        # Mock list_video_files to return files only for Films directory
        def list_video_files_by_dir(directory: Path, min_file_size_bytes: int = 0) -> Iterator[Path]:
            if "Films" in str(directory):
                yield movie1
                yield movie2
            # Series/ retourne rien

        mock_file_system.list_video_files = MagicMock(side_effect=list_video_files_by_dir)
        mock_file_system.get_size.return_value = 500 * 1024 * 1024

        scanner = ScannerService(mock_file_system, mock_filename_parser, test_settings)

        # Act
        results = list(scanner.scan_downloads())

        # Assert
        assert len(results) == 2
        filenames = {r.video_file.filename for r in results}
        assert filenames == {"Movie1.mkv", "Movie2.mkv"}

    def test_scan_empty_directory(
        self,
        mock_file_system: MagicMock,
        mock_filename_parser: MagicMock,
        test_settings: Settings,
    ) -> None:
        """Le scanner retourne une liste vide si aucun fichier video n'est trouve."""
        # Arrange: directories vides
        mock_file_system.list_video_files = MagicMock(return_value=iter([]))

        scanner = ScannerService(mock_file_system, mock_filename_parser, test_settings)

        # Act
        results = list(scanner.scan_downloads())

        # Assert
        assert len(results) == 0
