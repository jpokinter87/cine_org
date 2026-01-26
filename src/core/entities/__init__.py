"""
Business entities representing core domain concepts.

Entities are mutable objects with identity that persist over time.
They encapsulate business rules and behavior.

Exports:
- VideoFile: Represents a video file with its metadata
- PendingValidation: A video file awaiting user validation
- Movie: Movie metadata from TMDB
- Series: TV series metadata from TVDB
- Episode: Individual episode of a series
"""

from src.core.entities.video import VideoFile, PendingValidation, ValidationStatus
from src.core.entities.media import Movie, Series, Episode

__all__ = [
    "VideoFile",
    "PendingValidation",
    "ValidationStatus",
    "Movie",
    "Series",
    "Episode",
]
