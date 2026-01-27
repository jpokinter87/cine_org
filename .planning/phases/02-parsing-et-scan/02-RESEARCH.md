# Phase 2: Parsing et Scan - Research

**Researched:** 2026-01-27
**Domain:** Video filename parsing, technical metadata extraction, directory scanning
**Confidence:** HIGH

## Summary

This phase implements the scanning and parsing functionality for CineOrg: recursively scanning download directories for video files and extracting both filename metadata (via guessit) and technical metadata (via pymediainfo). The domain is well-established with two mature libraries dominating the ecosystem.

**guessit** (v3.8.0) is the de facto standard for parsing video filenames, capable of extracting title, year, season, episode, video codec, audio codec, resolution, release group, and more from scene-style filenames. It uses pattern-based rules via the Rebulk engine and handles both movies and TV shows. **pymediainfo** (v7.0.1) wraps the MediaInfo library to extract technical metadata like codec details, resolution, duration, audio tracks, and language information directly from video container files.

Both libraries are already specified in the project requirements (commented out in requirements.txt) and fit the hexagonal architecture established in Phase 1. The implementation requires creating domain ports (interfaces) and infrastructure adapters for these libraries.

**Primary recommendation:** Use guessit with explicit type hints from directory location (Films/Series) to improve detection accuracy. Use pymediainfo with `full=True` for complete metadata and handle duration conversion from milliseconds to seconds.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| guessit | 3.8.0 | Filename parsing | Industry standard, used by Medusa/SickChill/Sonarr, mature regex engine |
| pymediainfo | 7.0.1 | Technical metadata extraction | Official Python wrapper for MediaInfo, cross-platform |
| pathlib | stdlib | Directory scanning | Modern Python path handling, built-in recursive glob |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| rebulk | 3.2.0+ | Pattern engine | Transitive dependency of guessit |
| babelfish | 0.6.1+ | Language/country codes | Transitive dependency of guessit |
| MediaInfo (system) | varies | Binary dependency | Required by pymediainfo on non-wheel installs |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| guessit | PTN (parse-torrent-name) | Simpler but less accurate, fewer properties extracted |
| guessit | Manual regex | Full control but massive maintenance burden, edge cases |
| pymediainfo | ffprobe | No Python wrapper needed but output parsing complex |

**Installation:**
```bash
pip install guessit>=3.8.0 pymediainfo>=7.0.1
```

Note: pymediainfo wheels include MediaInfo library. For system-wide MediaInfo, use `pip install pymediainfo --no-binary pymediainfo`.

## Architecture Patterns

### Recommended Project Structure

Following Phase 1's hexagonal architecture:

```
src/
├── core/
│   ├── entities/
│   │   ├── video.py              # VideoFile entity (exists)
│   │   └── parsed_info.py        # NEW: ParsedFilename, MediaType enum
│   ├── ports/
│   │   ├── file_system.py        # IFileSystem (exists, extend)
│   │   └── parser.py             # NEW: IFilenameParser, IMediaInfoExtractor
│   └── value_objects/
│       └── media_info.py         # Resolution, VideoCodec, etc. (exists)
├── services/
│   └── scanner.py                # NEW: ScannerService
└── adapters/
    └── parsing/                  # NEW: Infrastructure adapters
        ├── __init__.py
        ├── guessit_parser.py     # GuessitFilenameParser
        └── mediainfo_extractor.py # MediaInfoExtractor
```

### Pattern 1: Filename Parser Port and Adapter

**What:** Abstract interface for filename parsing, implemented by guessit adapter
**When to use:** Any operation needing to extract metadata from filenames

```python
# Source: Hexagonal architecture pattern
# File: src/core/ports/parser.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class MediaType(Enum):
    """Type of media content."""
    MOVIE = "movie"
    SERIES = "series"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class ParsedFilename:
    """Value object containing parsed filename information."""
    title: str
    year: Optional[int] = None
    media_type: MediaType = MediaType.UNKNOWN
    # Series-specific
    season: Optional[int] = None
    episode: Optional[int] = None
    episode_end: Optional[int] = None  # For double episodes
    episode_title: Optional[str] = None
    # Technical hints from filename
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    resolution: Optional[str] = None
    source: Optional[str] = None  # HDTV, BluRay, WEB-DL
    release_group: Optional[str] = None
    language: Optional[str] = None

class IFilenameParser(ABC):
    """Port for filename parsing operations."""

    @abstractmethod
    def parse(
        self,
        filename: str,
        type_hint: Optional[MediaType] = None
    ) -> ParsedFilename:
        """
        Parse a video filename to extract metadata.

        Args:
            filename: The video filename (with or without path)
            type_hint: Optional hint for movie/series detection

        Returns:
            ParsedFilename with extracted metadata
        """
        ...
```

### Pattern 2: MediaInfo Extractor Port

**What:** Abstract interface for technical metadata extraction
**When to use:** Extracting codecs, resolution, duration, languages from video files

```python
# Source: Hexagonal architecture pattern
# File: src/core/ports/parser.py (continued)

from pathlib import Path
from src.core.value_objects import MediaInfo

class IMediaInfoExtractor(ABC):
    """Port for extracting technical metadata from video files."""

    @abstractmethod
    def extract(self, file_path: Path) -> Optional[MediaInfo]:
        """
        Extract technical metadata from a video file.

        Args:
            file_path: Path to the video file

        Returns:
            MediaInfo with extracted metadata, or None if extraction fails
        """
        ...
```

### Pattern 3: Scanner Service (Application Layer)

**What:** Orchestrates scanning, parsing, and filtering
**When to use:** Entry point for scan operations from CLI/Web

```python
# Source: Clean Architecture use case pattern
# File: src/services/scanner.py

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from src.core.entities.video import VideoFile
from src.core.ports.parser import IFilenameParser, IMediaInfoExtractor, MediaType
from src.core.ports.file_system import IFileSystem
from src.config import Settings

@dataclass
class ScanResult:
    """Result of scanning a single file."""
    video_file: VideoFile
    parsed_info: ParsedFilename
    detected_type: MediaType
    corrected_location: bool  # True if file was in wrong directory

class ScannerService:
    """Scans directories and extracts metadata from video files."""

    def __init__(
        self,
        file_system: IFileSystem,
        filename_parser: IFilenameParser,
        media_info_extractor: IMediaInfoExtractor,
        settings: Settings,
    ):
        self._fs = file_system
        self._parser = filename_parser
        self._extractor = media_info_extractor
        self._settings = settings

    def scan_downloads(self) -> Iterator[ScanResult]:
        """
        Scan downloads directory for new video files.

        Yields:
            ScanResult for each valid video file found
        """
        downloads = self._settings.downloads_dir

        # Scan both Films and Series directories
        for subdir, type_hint in [("Films", MediaType.MOVIE), ("Series", MediaType.SERIES)]:
            source_dir = downloads / subdir
            if source_dir.exists():
                yield from self._scan_directory(source_dir, type_hint)

    def _scan_directory(
        self,
        directory: Path,
        type_hint: MediaType
    ) -> Iterator[ScanResult]:
        """Recursively scan a directory for video files."""
        # Implementation uses file_system port for listing
        # Filters by extension, size, ignored patterns
        # Parses each file and yields results
        ...
```

### Pattern 4: Guessit Adapter Implementation

**What:** Concrete implementation of IFilenameParser using guessit
**When to use:** Production code parsing video filenames

```python
# Source: guessit official documentation
# File: src/adapters/parsing/guessit_parser.py

from typing import Optional
from guessit import guessit

from src.core.ports.parser import IFilenameParser, ParsedFilename, MediaType

class GuessitFilenameParser(IFilenameParser):
    """Filename parser using guessit library."""

    def parse(
        self,
        filename: str,
        type_hint: Optional[MediaType] = None
    ) -> ParsedFilename:
        """Parse filename using guessit."""

        # Build options dict
        options = {}
        if type_hint == MediaType.MOVIE:
            options['type'] = 'movie'
        elif type_hint == MediaType.SERIES:
            options['type'] = 'episode'

        # Call guessit
        result = guessit(filename, options)

        # Map guessit result to domain object
        return ParsedFilename(
            title=result.get('title', ''),
            year=result.get('year'),
            media_type=self._map_type(result.get('type')),
            season=result.get('season'),
            episode=result.get('episode'),
            episode_end=self._get_episode_end(result),
            episode_title=result.get('episode_title'),
            video_codec=result.get('video_codec'),
            audio_codec=result.get('audio_codec'),
            resolution=result.get('screen_size'),
            source=result.get('source'),
            release_group=result.get('release_group'),
            language=self._extract_language(result),
        )

    def _map_type(self, guessit_type: Optional[str]) -> MediaType:
        """Map guessit type to domain enum."""
        if guessit_type == 'movie':
            return MediaType.MOVIE
        elif guessit_type == 'episode':
            return MediaType.SERIES
        return MediaType.UNKNOWN

    def _get_episode_end(self, result: dict) -> Optional[int]:
        """Extract episode end for double episodes."""
        episode = result.get('episode')
        if isinstance(episode, list) and len(episode) > 1:
            return episode[-1]
        return None

    def _extract_language(self, result: dict) -> Optional[str]:
        """Extract primary language from guessit result."""
        lang = result.get('language')
        if lang:
            # Babelfish Language object
            if hasattr(lang, 'alpha2'):
                return lang.alpha2.upper()
            elif isinstance(lang, list) and lang:
                return lang[0].alpha2.upper() if hasattr(lang[0], 'alpha2') else None
        return None
```

### Pattern 5: MediaInfo Adapter Implementation

**What:** Concrete implementation of IMediaInfoExtractor using pymediainfo
**When to use:** Production code extracting technical metadata

```python
# Source: pymediainfo official documentation
# File: src/adapters/parsing/mediainfo_extractor.py

from pathlib import Path
from typing import Optional
from pymediainfo import MediaInfo as PyMediaInfo

from src.core.ports.parser import IMediaInfoExtractor
from src.core.value_objects import (
    MediaInfo, Resolution, VideoCodec, AudioCodec, Language
)

class MediaInfoExtractor(IMediaInfoExtractor):
    """Technical metadata extractor using pymediainfo."""

    def extract(self, file_path: Path) -> Optional[MediaInfo]:
        """Extract technical metadata from a video file."""
        if not file_path.exists():
            return None

        try:
            mi = PyMediaInfo.parse(str(file_path), full=True)
        except Exception:
            return None

        return MediaInfo(
            resolution=self._extract_resolution(mi),
            video_codec=self._extract_video_codec(mi),
            audio_codecs=self._extract_audio_codecs(mi),
            audio_languages=self._extract_audio_languages(mi),
            duration_seconds=self._extract_duration(mi),
        )

    def _extract_resolution(self, mi: PyMediaInfo) -> Optional[Resolution]:
        """Extract video resolution."""
        for track in mi.video_tracks:
            width = track.width
            height = track.height
            if width and height:
                return Resolution(width=int(width), height=int(height))
        return None

    def _extract_video_codec(self, mi: PyMediaInfo) -> Optional[VideoCodec]:
        """Extract video codec information."""
        for track in mi.video_tracks:
            codec_name = track.format or track.codec_id
            if codec_name:
                return VideoCodec(
                    name=self._normalize_video_codec(codec_name),
                    profile=track.format_profile
                )
        return None

    def _extract_audio_codecs(self, mi: PyMediaInfo) -> tuple[AudioCodec, ...]:
        """Extract all audio codecs."""
        codecs = []
        for track in mi.audio_tracks:
            codec_name = track.format or track.commercial_name or track.codec_id
            if codec_name:
                channels = self._format_channels(track.channel_s)
                codecs.append(AudioCodec(
                    name=self._normalize_audio_codec(codec_name),
                    channels=channels
                ))
        return tuple(codecs)

    def _extract_audio_languages(self, mi: PyMediaInfo) -> tuple[Language, ...]:
        """Extract audio track languages."""
        languages = []
        seen = set()
        for track in mi.audio_tracks:
            lang_code = track.language
            if lang_code and lang_code not in seen:
                seen.add(lang_code)
                languages.append(Language(
                    code=lang_code[:2].lower(),  # ISO 639-1
                    name=self._get_language_name(lang_code)
                ))
        return tuple(languages)

    def _extract_duration(self, mi: PyMediaInfo) -> Optional[int]:
        """Extract duration in seconds."""
        # Duration in pymediainfo is in milliseconds
        for track in mi.video_tracks:
            if track.duration:
                return int(float(track.duration) / 1000)
        # Fallback to general track
        for track in mi.general_tracks:
            if track.duration:
                return int(float(track.duration) / 1000)
        return None

    def _format_channels(self, channel_count) -> Optional[str]:
        """Format channel count to standard notation."""
        if not channel_count:
            return None
        try:
            count = int(channel_count)
            if count == 2:
                return "2.0"
            elif count == 6:
                return "5.1"
            elif count == 8:
                return "7.1"
            else:
                return str(count)
        except (ValueError, TypeError):
            return None

    def _normalize_video_codec(self, codec: str) -> str:
        """Normalize video codec name."""
        codec_lower = codec.lower()
        mapping = {
            'avc': 'x264', 'h264': 'x264', 'x264': 'x264',
            'hevc': 'x265', 'h265': 'x265', 'x265': 'x265',
            'av1': 'AV1', 'vp9': 'VP9',
        }
        return mapping.get(codec_lower, codec)

    def _normalize_audio_codec(self, codec: str) -> str:
        """Normalize audio codec name."""
        codec_lower = codec.lower()
        mapping = {
            'aac': 'AAC', 'ac-3': 'AC3', 'ac3': 'AC3',
            'dts': 'DTS', 'dts-hd': 'DTS-HD', 'dts-hd ma': 'DTS-HD',
            'truehd': 'TrueHD', 'flac': 'FLAC', 'mp3': 'MP3',
            'e-ac-3': 'EAC3', 'eac3': 'EAC3',
        }
        return mapping.get(codec_lower, codec)

    def _get_language_name(self, code: str) -> str:
        """Get full language name from code."""
        # Common mappings
        names = {
            'fr': 'Francais', 'en': 'Anglais', 'de': 'Allemand',
            'es': 'Espagnol', 'it': 'Italien', 'ja': 'Japonais',
            'ko': 'Coreen', 'zh': 'Chinois', 'pt': 'Portugais',
            'fre': 'Francais', 'fra': 'Francais',
            'eng': 'Anglais', 'ger': 'Allemand', 'deu': 'Allemand',
        }
        return names.get(code.lower()[:3], code)
```

### Anti-Patterns to Avoid

- **Calling guessit directly in services:** Always go through the port interface for testability
- **Ignoring type hints from directory:** Use Films/Series directory to provide type hint to guessit
- **Treating pymediainfo duration as seconds:** It returns milliseconds, divide by 1000
- **Not handling missing MediaInfo attributes:** Many attributes can be None, use defensive access
- **Synchronous file scanning for large directories:** Use generator/iterator pattern to avoid memory issues
- **Hardcoding extensions:** Use constants from a central location (src/utils/constants.py)

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Filename parsing | Custom regex | guessit | 1000s of edge cases (scene rules, anime, etc.) |
| Media metadata | ffprobe parsing | pymediainfo | Cross-platform, handles all containers |
| Type detection (movie/series) | Heuristics | guessit + directory hint | Pattern matching is complex |
| Language codes | Manual mapping | babelfish (via guessit) | ISO 639 has many formats |
| Recursive file listing | os.walk | pathlib.rglob | Modern, type-safe, generator-based |

**Key insight:** Video filename parsing is an incredibly complex domain with thousands of edge cases. guessit encodes years of community knowledge about scene naming conventions. Custom solutions will fail on edge cases.

## Common Pitfalls

### Pitfall 1: Guessit Type Detection Ambiguity
**What goes wrong:** "Star Wars Episode IV" detected as series episode 4
**Why it happens:** guessit sees "Episode" pattern without context
**How to avoid:** Provide `type='movie'` hint when scanning Films/ directory
**Warning signs:** Movies showing season/episode numbers, wrong type detection

### Pitfall 2: pymediainfo Duration Units
**What goes wrong:** Duration shown as 7200000 instead of 7200 seconds
**Why it happens:** pymediainfo returns milliseconds, not seconds
**How to avoid:** Always divide `track.duration` by 1000
**Warning signs:** Impossibly long durations in output

### Pitfall 3: Missing Audio Language Metadata
**What goes wrong:** Language returns None even when audio is present
**Why it happens:** Not all video files have language tags embedded
**How to avoid:** Fallback to guessit filename parsing for language hints
**Warning signs:** Many files with None language despite being labeled in filename

### Pitfall 4: Guessit Episode List Handling
**What goes wrong:** Double episodes (S01E01E02) not parsed correctly
**Why it happens:** guessit returns list for episode field, code expects int
**How to avoid:** Check if episode is list, extract first and last for range
**Warning signs:** TypeError when accessing episode number, missing double episodes

### Pitfall 5: MediaInfo Binary Not Found
**What goes wrong:** pymediainfo raises exception or returns empty data
**Why it happens:** MediaInfo library not installed (non-wheel install on Linux)
**How to avoid:** Use wheel install or ensure libmediainfo is in PATH
**Warning signs:** Empty tracks, RuntimeError about library not found

### Pitfall 6: Scanning Symlinks vs Real Files
**What goes wrong:** Scanner processes same file multiple times via different symlinks
**Why it happens:** rglob follows symlinks by default
**How to avoid:** Skip symlinks in scanner: `if path.is_symlink(): continue`
**Warning signs:** Duplicate files in scan results, infinite loops in symlinked trees

### Pitfall 7: Sample Files Matching
**What goes wrong:** "sample.mkv" or "movie-sample.mkv" included in scan
**Why it happens:** Only checking extension, not filename patterns
**How to avoid:** Filter out files matching IGNORED_PATTERNS (sample, trailer, preview)
**Warning signs:** Small files in results, files under 100MB

## Code Examples

Verified patterns from official sources:

### Basic guessit Usage
```python
# Source: https://github.com/guessit-io/guessit
from guessit import guessit

# Movie example
result = guessit("Inception.2010.1080p.BluRay.x264-SPARKS.mkv")
# Returns: {'title': 'Inception', 'year': 2010, 'screen_size': '1080p',
#           'source': 'Blu-ray', 'video_codec': 'H.264',
#           'release_group': 'SPARKS', 'container': 'mkv', 'type': 'movie'}

# TV episode example
result = guessit("Breaking.Bad.S01E01.720p.HDTV.x264-CTU.mkv")
# Returns: {'title': 'Breaking Bad', 'season': 1, 'episode': 1,
#           'screen_size': '720p', 'source': 'HDTV',
#           'video_codec': 'H.264', 'release_group': 'CTU', 'type': 'episode'}

# With type hint
result = guessit("Movie.Name.2020.mkv", {'type': 'movie'})
```

### Guessit Options Dictionary
```python
# Source: https://guessit.readthedocs.io/en/latest/
from guessit import guessit

# Force type detection
result = guessit(filename, {'type': 'episode'})  # or 'movie'

# Allow specific languages only
result = guessit(filename, {'allowed_languages': ['en', 'fr']})

# Handle files like "serie.213.avi" as episode 213 (not S02E13)
result = guessit(filename, {'episode_prefer_number': True})

# Provide expected title (helps with parsing)
result = guessit(filename, {'expected_title': 'Breaking Bad'})

# Exclude certain properties from detection
result = guessit(filename, {'excludes': ['mimetype', 'uuid']})
```

### pymediainfo Basic Usage
```python
# Source: https://pymediainfo.readthedocs.io/en/stable/
from pymediainfo import MediaInfo

# Parse file
mi = MediaInfo.parse("/path/to/video.mkv", full=True)

# Access video tracks
for track in mi.video_tracks:
    print(f"Resolution: {track.width}x{track.height}")
    print(f"Codec: {track.format}")
    print(f"Duration: {track.duration} ms")  # Note: milliseconds!

# Access audio tracks
for track in mi.audio_tracks:
    print(f"Codec: {track.format}")
    print(f"Channels: {track.channel_s}")
    print(f"Language: {track.language}")

# Shorthand access
video = mi.video_tracks[0] if mi.video_tracks else None
audio_count = len(mi.audio_tracks)
```

### Directory Scanning with Filtering
```python
# Source: Python pathlib documentation + project patterns
from pathlib import Path
from typing import Iterator

VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v'}
IGNORED_PATTERNS = {'sample', 'trailer', 'preview', 'extras', 'bonus'}
MIN_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB

def scan_video_files(directory: Path) -> Iterator[Path]:
    """Recursively scan for video files, filtering appropriately."""
    for path in directory.rglob('*'):
        # Skip directories and symlinks
        if not path.is_file() or path.is_symlink():
            continue

        # Check extension
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue

        # Check for ignored patterns in filename
        filename_lower = path.stem.lower()
        if any(pattern in filename_lower for pattern in IGNORED_PATTERNS):
            continue

        # Check minimum size
        try:
            if path.stat().st_size < MIN_SIZE_BYTES:
                continue
        except OSError:
            continue

        yield path
```

### Type Detection with Directory Hint
```python
# Source: Project specifications + guessit patterns
from pathlib import Path
from guessit import guessit

def detect_media_type(file_path: Path, downloads_dir: Path) -> str:
    """Detect media type using directory location and guessit."""

    # Get relative path from downloads
    try:
        relative = file_path.relative_to(downloads_dir)
        first_dir = relative.parts[0].lower() if relative.parts else ''
    except ValueError:
        first_dir = ''

    # Use directory as hint
    if first_dir == 'films':
        type_hint = 'movie'
    elif first_dir in ('series', 'series'):
        type_hint = 'episode'
    else:
        type_hint = None

    # Parse with guessit
    options = {'type': type_hint} if type_hint else {}
    result = guessit(file_path.name, options)

    guessit_type = result.get('type', 'unknown')

    # Return detected type (guessit may override if filename clearly indicates)
    return guessit_type
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| guessit 2.x | guessit 3.x (Rebulk engine) | 2018 | Better accuracy, extensible rules |
| pymediainfo 4.x | pymediainfo 7.x | 2023 | Python 3.9+ required, better typing |
| os.path for scanning | pathlib | Python 3.4+ | Modern, type-safe path handling |
| Direct library calls | Hexagonal ports | Architecture pattern | Testable, swappable implementations |

**Deprecated/outdated:**
- guessit `--type` CLI flag sometimes ignored in 3.x: use Python API with options dict
- pymediainfo `parse_speed` default changed: explicit setting recommended for consistent behavior
- `os.walk()` for directory scanning: prefer `pathlib.rglob()` for modern code

## Open Questions

Things that couldn't be fully resolved:

1. **Language Detection Priority**
   - What we know: pymediainfo may have language tags, guessit parses from filename
   - What's unclear: Which source to prefer when they conflict
   - Recommendation: Prefer pymediainfo (actual file metadata) over filename hints. Fall back to guessit only when pymediainfo returns None.

2. **Multi-episode File Handling**
   - What we know: guessit returns list for episodes like S01E01E02
   - What's unclear: How to handle arbitrary-length episode ranges
   - Recommendation: Support first/last episode extraction. Store episode_start and episode_end in ParsedFilename.

3. **Encoding Issues in Filenames**
   - What we know: guessit handles UTF-8, some filesystems have encoding issues
   - What's unclear: How to handle files with broken encoding
   - Recommendation: Try UTF-8 first, fall back to latin-1, log warning if issues.

## Sources

### Primary (HIGH confidence)
- [guessit GitHub](https://github.com/guessit-io/guessit) - API, options, examples
- [guessit Documentation](https://guessit-io.github.io/guessit/) - Properties list, CLI
- [pymediainfo ReadTheDocs](https://pymediainfo.readthedocs.io/en/stable/) - API reference
- [pymediainfo GitHub](https://github.com/sbraz/pymediainfo) - Version 7.0.1, examples
- [PyPI guessit](https://pypi.org/project/guessit/) - Version 3.8.0, Python 3.7-3.11

### Secondary (MEDIUM confidence)
- [PyPI pymediainfo](https://pypi.org/project/pymediainfo/) - Version 7.0.1, Python 3.9+
- [Python pathlib docs](https://docs.python.org/3/library/pathlib.html) - rglob, iterdir

### Tertiary (LOW confidence)
- WebSearch findings on guessit edge cases (verified against GitHub issues)
- Community patterns for type detection (verified against guessit source)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Both libraries verified on PyPI, widely used in media automation
- Architecture: HIGH - Patterns follow Phase 1 hexagonal structure
- Pitfalls: HIGH - Documented in library issues and official docs
- Code examples: HIGH - Verified against official documentation

**Research date:** 2026-01-27
**Valid until:** 2026-02-27 (30 days - stable libraries)
