"""
Repository port interfaces.

Abstract interfaces (ports) defining contracts for data persistence.
Implementations (adapters) will provide concrete storage mechanisms
(SQLite via SQLModel, in-memory for tests, etc.).
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from src.core.entities.video import PendingValidation, VideoFile
from src.core.entities.media import Movie, Series, Episode


class IVideoFileRepository(ABC):
    """
    Video file storage interface.

    Defines operations for persisting and retrieving VideoFile entities.
    """

    @abstractmethod
    def get_by_id(self, video_id: str) -> Optional[VideoFile]:
        """Retrieve a video file by its ID."""
        ...

    @abstractmethod
    def get_by_path(self, path: Path) -> Optional[VideoFile]:
        """Retrieve a video file by its file path."""
        ...

    @abstractmethod
    def get_by_hash(self, file_hash: str) -> Optional[VideoFile]:
        """Retrieve a video file by its content hash."""
        ...

    @abstractmethod
    def save(self, video_file: VideoFile) -> VideoFile:
        """Save a video file (insert or update)."""
        ...

    @abstractmethod
    def delete(self, video_id: str) -> bool:
        """Delete a video file by ID. Returns True if deleted."""
        ...

    @abstractmethod
    def list_pending(self) -> list[PendingValidation]:
        """List all video files with pending validation."""
        ...


class IMovieRepository(ABC):
    """
    Movie metadata storage interface.

    Defines operations for persisting and retrieving Movie entities.
    """

    @abstractmethod
    def get_by_id(self, movie_id: str) -> Optional[Movie]:
        """Retrieve a movie by its internal ID."""
        ...

    @abstractmethod
    def get_by_tmdb_id(self, tmdb_id: int) -> Optional[Movie]:
        """Retrieve a movie by its TMDB ID."""
        ...

    @abstractmethod
    def search_by_title(self, title: str, year: Optional[int] = None) -> list[Movie]:
        """Search movies by title, optionally filtering by year."""
        ...

    @abstractmethod
    def save(self, movie: Movie) -> Movie:
        """Save a movie (insert or update)."""
        ...


class ISeriesRepository(ABC):
    """
    Series metadata storage interface.

    Defines operations for persisting and retrieving Series entities.
    """

    @abstractmethod
    def get_by_id(self, series_id: str) -> Optional[Series]:
        """Retrieve a series by its internal ID."""
        ...

    @abstractmethod
    def get_by_tvdb_id(self, tvdb_id: int) -> Optional[Series]:
        """Retrieve a series by its TVDB ID."""
        ...

    @abstractmethod
    def search_by_title(self, title: str, year: Optional[int] = None) -> list[Series]:
        """Search series by title, optionally filtering by year."""
        ...

    @abstractmethod
    def save(self, series: Series) -> Series:
        """Save a series (insert or update)."""
        ...


class IEpisodeRepository(ABC):
    """
    Episode metadata storage interface.

    Defines operations for persisting and retrieving Episode entities.
    """

    @abstractmethod
    def get_by_id(self, episode_id: str) -> Optional[Episode]:
        """Retrieve an episode by its internal ID."""
        ...

    @abstractmethod
    def get_by_series(
        self,
        series_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> list[Episode]:
        """
        Get episodes for a series.

        Args:
            series_id: The series ID
            season: Optional season number filter
            episode: Optional episode number filter (requires season)

        Returns:
            List of matching episodes
        """
        ...

    @abstractmethod
    def save(self, episode: Episode) -> Episode:
        """Save an episode (insert or update)."""
        ...
