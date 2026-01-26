"""
Media metadata entities.

Entities representing movies and TV shows with their metadata
from external APIs (TMDB, TVDB).
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class Movie:
    """
    Movie metadata from TMDB.

    Represents enriched movie information retrieved from The Movie Database API.

    Attributes:
        id: Internal database ID
        tmdb_id: The Movie Database ID
        title: Localized title (French for this application)
        original_title: Original language title
        year: Release year
        genres: Tuple of genre names (French, in hierarchy order)
        duration_seconds: Runtime in seconds
        overview: Plot summary
        poster_path: Path to poster image on TMDB CDN
    """

    id: Optional[str] = None
    tmdb_id: Optional[int] = None
    title: str = ""
    original_title: Optional[str] = None
    year: Optional[int] = None
    genres: tuple[str, ...] = ()
    duration_seconds: Optional[int] = None
    overview: Optional[str] = None
    poster_path: Optional[str] = None


@dataclass
class Series:
    """
    TV series metadata from TVDB.

    Represents enriched series information retrieved from TheTVDB API.

    Attributes:
        id: Internal database ID
        tvdb_id: TheTVDB ID
        title: Localized title
        original_title: Original language title
        year: First air date year
        genres: Tuple of genre names
        overview: Series description
        poster_path: Path to poster image
    """

    id: Optional[str] = None
    tvdb_id: Optional[int] = None
    title: str = ""
    original_title: Optional[str] = None
    year: Optional[int] = None
    genres: tuple[str, ...] = ()
    overview: Optional[str] = None
    poster_path: Optional[str] = None


@dataclass
class Episode:
    """
    Individual episode of a TV series.

    Attributes:
        id: Internal database ID
        series_id: Reference to parent Series
        season_number: Season number (1-indexed)
        episode_number: Episode number within season (1-indexed)
        title: Episode title
        air_date: Original air date
        duration_seconds: Episode runtime in seconds
        overview: Episode description
    """

    id: Optional[str] = None
    series_id: Optional[str] = None
    season_number: int = 0
    episode_number: int = 0
    title: str = ""
    air_date: Optional[date] = None
    duration_seconds: Optional[int] = None
    overview: Optional[str] = None
