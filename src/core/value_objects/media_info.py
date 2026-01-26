"""
Media information value objects.

Immutable value objects representing technical information about video files.
All value objects use @dataclass(frozen=True) to guarantee immutability.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Resolution:
    """
    Video resolution (width x height).

    Attributes:
        width: Horizontal resolution in pixels
        height: Vertical resolution in pixels

    Properties:
        label: Human-readable label (4K, 1080p, 720p, SD)
    """

    width: int
    height: int

    @property
    def label(self) -> str:
        """Return human-readable resolution label based on height."""
        if self.height >= 2160:
            return "4K"
        elif self.height >= 1080:
            return "1080p"
        elif self.height >= 720:
            return "720p"
        else:
            return "SD"


@dataclass(frozen=True)
class VideoCodec:
    """
    Video codec information.

    Attributes:
        name: Codec name (e.g., "HEVC", "H.264", "AV1")
        profile: Optional codec profile (e.g., "Main 10", "High")
    """

    name: str
    profile: Optional[str] = None


@dataclass(frozen=True)
class AudioCodec:
    """
    Audio codec information with channel configuration.

    Attributes:
        name: Codec name (e.g., "AAC", "DTS-HD", "TrueHD")
        channels: Optional channel configuration (e.g., "5.1", "7.1", "2.0")
    """

    name: str
    channels: Optional[str] = None


@dataclass(frozen=True)
class Language:
    """
    Language with ISO 639-1 code and full name.

    Attributes:
        code: ISO 639-1 language code (e.g., "fr", "en")
        name: Full language name (e.g., "French", "English")
    """

    code: str
    name: str


@dataclass(frozen=True)
class MediaInfo:
    """
    Composite value object containing all technical media information.

    Aggregates resolution, codecs, languages, and duration extracted
    from a video file via mediainfo.

    Attributes:
        resolution: Video resolution (width x height)
        video_codec: Video codec information
        audio_codecs: Tuple of audio codecs (tuple for immutability)
        audio_languages: Tuple of audio languages
        duration_seconds: Duration in seconds
    """

    resolution: Optional[Resolution] = None
    video_codec: Optional[VideoCodec] = None
    audio_codecs: tuple[AudioCodec, ...] = ()
    audio_languages: tuple[Language, ...] = ()
    duration_seconds: Optional[int] = None
