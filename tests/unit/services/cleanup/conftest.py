"""Fixtures partagees pour les tests du CleanupService."""

from unittest.mock import MagicMock

import pytest

from src.services.cleanup import CleanupService


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_repair_service():
    """Mock du RepairService."""
    service = MagicMock()
    service.find_broken_symlinks = MagicMock(return_value=[])
    service.find_possible_targets = MagicMock(return_value=[])
    service.repair_symlink = MagicMock(return_value=True)
    service.build_file_index = MagicMock(return_value=100)
    return service


@pytest.fixture
def mock_organizer_service():
    """Mock du OrganizerService."""
    service = MagicMock()
    return service


@pytest.fixture
def mock_video_file_repo():
    """Mock du IVideoFileRepository."""
    repo = MagicMock()
    repo.get_by_symlink_path = MagicMock(return_value=None)
    repo.get_by_path = MagicMock(return_value=None)
    repo.update_symlink_path = MagicMock(return_value=True)
    mock_session = MagicMock()
    mock_session.exec.return_value.first.return_value = None
    repo._session = mock_session
    return repo


@pytest.fixture
def mock_movie_repo():
    """Mock du IMovieRepository."""
    repo = MagicMock()
    repo.get_by_id = MagicMock(return_value=None)
    repo._session = MagicMock()
    return repo


@pytest.fixture
def mock_series_repo():
    """Mock du ISeriesRepository."""
    repo = MagicMock()
    repo.get_by_id = MagicMock(return_value=None)
    repo._session = MagicMock()
    return repo


@pytest.fixture
def mock_episode_repo():
    """Mock du IEpisodeRepository."""
    repo = MagicMock()
    repo.get_by_id = MagicMock(return_value=None)
    repo._session = MagicMock()
    return repo


@pytest.fixture
def temp_dirs(tmp_path):
    """Cree les repertoires temporaires pour les tests."""
    video_dir = tmp_path / "video"
    video_dir.mkdir()
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    return {"video": video_dir, "storage": storage_dir}


@pytest.fixture
def cleanup_service(
    mock_repair_service,
    mock_organizer_service,
    mock_video_file_repo,
    mock_movie_repo,
    mock_series_repo,
    mock_episode_repo,
):
    """Cree un CleanupService avec des mocks."""
    return CleanupService(
        repair_service=mock_repair_service,
        organizer_service=mock_organizer_service,
        video_file_repo=mock_video_file_repo,
        movie_repo=mock_movie_repo,
        series_repo=mock_series_repo,
        episode_repo=mock_episode_repo,
    )
