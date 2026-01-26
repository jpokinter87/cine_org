"""Media information value objects."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Resolution:
    """Video resolution."""

    pass  # Will be implemented in Task 2


@dataclass(frozen=True)
class VideoCodec:
    """Video codec information."""

    pass  # Will be implemented in Task 2


@dataclass(frozen=True)
class AudioCodec:
    """Audio codec information."""

    pass  # Will be implemented in Task 2


@dataclass(frozen=True)
class Language:
    """Language with ISO code."""

    pass  # Will be implemented in Task 2


@dataclass(frozen=True)
class MediaInfo:
    """Composite of all technical media information."""

    pass  # Will be implemented in Task 2
