---
phase: 02-parsing-et-scan
plan: 02
subsystem: parsing-adapters
tags: [guessit, pymediainfo, parsing, DI, TDD]

dependency-graph:
  requires: ["02-01"]
  provides: ["GuessitFilenameParser", "MediaInfoExtractor", "scanner-with-mediainfo"]
  affects: ["03-matching"]

tech-stack:
  added: ["guessit>=3.8.0", "pymediainfo>=7.0.1"]
  patterns: ["adapter-pattern", "TDD-red-green-refactor"]

file-tracking:
  key-files:
    created:
      - src/adapters/parsing/__init__.py
      - src/adapters/parsing/guessit_parser.py
      - src/adapters/parsing/mediainfo_extractor.py
      - tests/unit/test_guessit_parser.py
      - tests/unit/test_mediainfo_extractor.py
      - tests/integration/__init__.py
      - tests/integration/test_scanner_integration.py
    modified:
      - src/adapters/__init__.py
      - src/container.py
      - src/services/scanner.py
      - src/main.py
      - tests/conftest.py
      - tests/unit/test_scanner.py
      - requirements.txt

decisions:
  - id: guessit-type-hint-respected
    choice: "Type hint from directory overrides guessit auto-detection"
    rationale: "User's organization (Films/ vs Series/) is source of truth"
  - id: mediainfo-duration-seconds
    choice: "Duration converted from milliseconds to seconds"
    rationale: "pymediainfo returns ms, but seconds is more practical for display"
  - id: scanner-calls-extractor-directly
    choice: "ScannerService calls media_info_extractor.extract() directly"
    rationale: "Separation of concerns - mediainfo extraction is not a filesystem operation"

metrics:
  duration: "~7 min"
  completed: "2026-01-27"
---

# Phase 02 Plan 02: Parsing Adapters Implementation Summary

GuessitFilenameParser and MediaInfoExtractor implementing ports from Plan 01, integrated into DI container and ScannerService.

## What Was Built

### GuessitFilenameParser (TDD)

Implements `IFilenameParser` interface using guessit library.

**Key features:**
- Parses title, year, season, episode from filenames
- Respects type_hint from directory (Films/ -> MOVIE, Series/ -> SERIES)
- Detects double episodes (S01E01E02 -> episode=1, episode_end=2)
- Extracts technical info from filename (codecs, resolution, source)
- Maps Babelfish Language to alpha2 code (fr, en, etc.)

**Test coverage:** 18 unit tests covering movies, series, type hints, technical info, edge cases.

### MediaInfoExtractor

Implements `IMediaInfoExtractor` interface using pymediainfo library.

**Key features:**
- Extracts resolution (width/height) with label (1080p, 4K)
- Normalizes video codecs (HEVC -> x265, AVC -> x264)
- Normalizes audio codecs (AC-3 -> AC3, DTS-HD MA -> DTS-HD)
- Formats audio channels (6 -> 5.1, 8 -> 7.1)
- Maps language codes to French names
- **CRITICAL:** Converts duration from milliseconds to seconds

**Test coverage:** 11 unit tests covering resolution, codecs, duration, languages, error handling.

### DI Container Integration

Updated `Container` class with:
- `file_system`: Singleton FileSystemAdapter
- `filename_parser`: Singleton GuessitFilenameParser
- `media_info_extractor`: Singleton MediaInfoExtractor
- `scanner_service`: Factory ScannerService with all dependencies

### ScannerService Update

Added `media_info_extractor` parameter to constructor. `_process_file()` now calls `extractor.extract(file_path)` to populate `ScanResult.media_info`.

### CLI scan Command

New command: `python -m src.main scan`
- Lists video files in downloads/Films and downloads/Series
- Displays parsed info (title, year, season/episode)
- Displays media info (resolution, codec, duration)
- Warns about misplaced files

## Test Results

```
52 tests passed in 0.31s
- 18 unit tests for GuessitFilenameParser
- 11 unit tests for MediaInfoExtractor
- 15 unit tests for ScannerService
- 8 integration tests for full flow
```

## Key Implementation Details

### Type Hint Behavior

When guessit receives a type_hint (e.g., MOVIE from Films/ directory), it respects it even if the filename pattern suggests otherwise. This is intentional - the directory structure is the source of truth.

### Duration Conversion

pymediainfo returns duration in milliseconds. The extractor divides by 1000 to provide seconds, which is more practical for display (minutes calculation).

### Codec Normalization

Codecs are normalized to common names:
- Video: AVC/H.264 -> x264, HEVC/H.265 -> x265
- Audio: AC-3 -> AC3, DTS-HD Master Audio -> DTS-HD

## Commits

| Hash | Message |
|------|---------|
| 5efe574 | feat(02-02): add GuessitFilenameParser with TDD tests |
| db43fe8 | feat(02-02): add MediaInfoExtractor with unit tests |
| bc3829f | feat(02-02): integrate DI container, ScannerService and CLI scan command |

## Dependencies Added

```
guessit>=3.8.0
pymediainfo>=7.0.1
```

## Deviations from Plan

None - plan executed exactly as written.

## Next Phase Readiness

Phase 02 (Parsing et Scan) is now complete. All parsing and scanning infrastructure is ready:
- Value objects for parsed info and media info
- Ports (interfaces) for filename parsing and media info extraction
- Adapters implementing those ports with real libraries
- ScannerService orchestrating the full scan flow
- DI container providing all dependencies
- CLI command for manual testing

Ready for Phase 03: API Matching (TMDB/TVDB integration).
