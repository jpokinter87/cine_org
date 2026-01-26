"""
API client port interfaces.

Abstract interfaces (ports) defining contracts for external media APIs.
Implementations (adapters) will provide concrete API clients
(TMDB for movies, TVDB for TV shows).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class SearchResult:
    """
    Search result from a media API.

    Represents a single result from an API search query.
    Multiple results are returned and scored against the original query.

    Attributes:
        id: API-specific ID (TMDB ID or TVDB ID)
        title: Title from the API
        year: Release/air year
        score: Match score (0-100) calculated by the matcher
        source: API source identifier ("tmdb" or "tvdb")
    """

    id: str
    title: str
    year: Optional[int] = None
    score: float = 0.0
    source: str = ""


@dataclass
class MediaDetails:
    """
    Detailed media information from API.

    Extended information retrieved after selecting a match.
    Used to enrich the local database entry.

    Attributes:
        id: API-specific ID
        title: Localized title
        original_title: Original language title
        year: Release/air year
        genres: List of genre names
        duration_seconds: Runtime in seconds (for movies)
        overview: Plot summary/description
        poster_url: Full URL to poster image
    """

    id: str
    title: str
    original_title: Optional[str] = None
    year: Optional[int] = None
    genres: tuple[str, ...] = ()
    duration_seconds: Optional[int] = None
    overview: Optional[str] = None
    poster_url: Optional[str] = None


class IMediaAPIClient(ABC):
    """
    Base interface for media metadata APIs.

    Defines the contract for searching and retrieving media information
    from external APIs. Implementations handle TMDB (movies) and TVDB (TV).
    """

    @abstractmethod
    async def search(
        self,
        query: str,
        year: Optional[int] = None,
    ) -> list[SearchResult]:
        """
        Search for media by title.

        Args:
            query: Search query (title)
            year: Optional year filter to narrow results

        Returns:
            List of search results, unscored (scoring done by matcher)
        """
        ...

    @abstractmethod
    async def get_details(self, media_id: str) -> Optional[MediaDetails]:
        """
        Get detailed information for a specific media item.

        Args:
            media_id: API-specific ID

        Returns:
            Detailed media information, or None if not found
        """
        ...

    @property
    @abstractmethod
    def source(self) -> str:
        """Return the API source identifier (e.g., 'tmdb', 'tvdb')."""
        ...
