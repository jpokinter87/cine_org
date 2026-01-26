"""
Immutable value objects representing domain concepts without identity.

Value objects are defined by their attributes rather than by identity.
They are immutable and can be freely shared and compared by value.

Exports:
- Resolution: Video resolution (width x height)
- VideoCodec: Video codec information (HEVC, H.264, etc.)
- AudioCodec: Audio codec information with channels
- Language: Language with ISO code and name
- MediaInfo: Composite of all technical media information
"""

from src.core.value_objects.media_info import (
    Resolution,
    VideoCodec,
    AudioCodec,
    Language,
    MediaInfo,
)

__all__ = [
    "Resolution",
    "VideoCodec",
    "AudioCodec",
    "Language",
    "MediaInfo",
]
