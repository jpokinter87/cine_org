"""
Ports (abstract interfaces) defining contracts for adapters.

Ports are the boundaries of the hexagonal architecture. They define
what the core domain needs from the outside world without specifying
how those needs are met.

Repository ports: Data persistence contracts
- IVideoFileRepository: Video file storage
- IMovieRepository: Movie metadata storage
- ISeriesRepository: Series metadata storage
- IEpisodeRepository: Episode metadata storage

API client ports: External service contracts
- IMediaAPIClient: Base interface for media metadata APIs
- SearchResult: Search result from API
- MediaDetails: Detailed media information from API

File system ports: File operation contracts
- IFileSystem: Basic file operations
- ISymlinkManager: Symlink management operations
"""

from src.core.ports.repositories import (
    IVideoFileRepository,
    IMovieRepository,
    ISeriesRepository,
    IEpisodeRepository,
)
from src.core.ports.api_clients import (
    IMediaAPIClient,
    SearchResult,
    MediaDetails,
)
from src.core.ports.file_system import (
    IFileSystem,
    ISymlinkManager,
)

__all__ = [
    # Repositories
    "IVideoFileRepository",
    "IMovieRepository",
    "ISeriesRepository",
    "IEpisodeRepository",
    # API clients
    "IMediaAPIClient",
    "SearchResult",
    "MediaDetails",
    # File system
    "IFileSystem",
    "ISymlinkManager",
]
