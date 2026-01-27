"""
Fixtures pytest partagees pour les tests CineOrg.

Ce module contient les fixtures communes utilisees dans les tests:
- Mocks des interfaces (IFileSystem, IFilenameParser)
- Settings de test avec chemins temporaires
"""

from pathlib import Path
from typing import Iterator, Optional
from unittest.mock import MagicMock

import pytest

from src.config import Settings
from src.core.ports.file_system import IFileSystem
from src.core.ports.parser import IFilenameParser, IMediaInfoExtractor
from src.core.value_objects import MediaInfo, MediaType, ParsedFilename


@pytest.fixture
def mock_file_system() -> MagicMock:
    """
    Mock de IFileSystem pour les tests.

    Le mock implemente toutes les methodes de IFileSystem.
    Les valeurs de retour doivent etre configurees dans chaque test.
    """
    mock = MagicMock(spec=IFileSystem)
    mock.exists.return_value = True
    mock.read_metadata.return_value = None
    mock.move.return_value = True
    mock.copy.return_value = True
    mock.delete.return_value = True
    mock.calculate_hash.return_value = "abc123hash"
    mock.get_size.return_value = 500 * 1024 * 1024  # 500 MB par defaut
    return mock


@pytest.fixture
def mock_filename_parser() -> MagicMock:
    """
    Mock de IFilenameParser pour les tests.

    Retourne un ParsedFilename basique par defaut.
    Configurer le mock dans chaque test pour des comportements specifiques.
    """
    mock = MagicMock(spec=IFilenameParser)

    def default_parse(filename: str, type_hint: Optional[MediaType] = None) -> ParsedFilename:
        """Parse basique qui utilise le type_hint ou UNKNOWN."""
        # Extraire le titre (nom sans extension)
        title = Path(filename).stem
        media_type = type_hint if type_hint else MediaType.UNKNOWN
        return ParsedFilename(title=title, media_type=media_type)

    mock.parse.side_effect = default_parse
    return mock


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """
    Settings de test avec chemins temporaires.

    Utilise tmp_path de pytest pour creer une structure de repertoires
    isolee pour chaque test.
    """
    downloads_dir = tmp_path / "downloads"
    storage_dir = tmp_path / "storage"
    video_dir = tmp_path / "video"

    # Creer les sous-repertoires de telechargements
    (downloads_dir / "Films").mkdir(parents=True)
    (downloads_dir / "Series").mkdir(parents=True)
    storage_dir.mkdir(parents=True)
    video_dir.mkdir(parents=True)

    return Settings(
        downloads_dir=downloads_dir,
        storage_dir=storage_dir,
        video_dir=video_dir,
        database_url=f"sqlite:///{tmp_path}/test.db",
        min_file_size_mb=100,
        max_files_per_subdir=50,
        match_score_threshold=85,
        log_file=tmp_path / "test.log",
    )


@pytest.fixture
def mock_media_info_extractor() -> MagicMock:
    """
    Mock de IMediaInfoExtractor pour les tests.

    Retourne None par defaut (pas de metadonnees techniques).
    Configurer le mock dans chaque test pour des comportements specifiques.
    """
    mock = MagicMock(spec=IMediaInfoExtractor)
    mock.extract.return_value = None
    return mock


@pytest.fixture
def parsed_movie() -> ParsedFilename:
    """ParsedFilename pour un film type."""
    return ParsedFilename(
        title="Inception",
        year=2010,
        media_type=MediaType.MOVIE,
        video_codec="H.264",
        audio_codec="DTS",
        resolution="1080p",
        source="BluRay",
    )


@pytest.fixture
def parsed_series() -> ParsedFilename:
    """ParsedFilename pour une serie type."""
    return ParsedFilename(
        title="Breaking Bad",
        year=2008,
        media_type=MediaType.SERIES,
        season=1,
        episode=1,
        episode_title="Pilot",
        video_codec="HEVC",
        audio_codec="AAC",
        resolution="1080p",
        source="WEB-DL",
    )
