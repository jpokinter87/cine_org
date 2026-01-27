---
phase: 02-parsing-et-scan
plan: 01
subsystem: parsing
tags: [scanner, filesystem, hexagonal, value-objects, ports]

# Dependency graph
requires:
  - phase: 01-fondations-architecture
    provides: IFileSystem interface, Settings config, MediaInfo value objects
provides:
  - IFilenameParser and IMediaInfoExtractor port interfaces
  - ParsedFilename and MediaType value objects
  - FileSystemAdapter implementing IFileSystem with video filtering
  - ScannerService orchestrating scan and parsing
  - Unit tests for scanner with mocks
affects: [02-02, phase-3-matching, phase-5-transferer]

# Tech tracking
tech-stack:
  added: [pytest]
  patterns: [hexagonal-architecture, dependency-injection, value-objects]

key-files:
  created:
    - src/core/ports/parser.py
    - src/core/value_objects/parsed_info.py
    - src/adapters/file_system.py
    - src/services/scanner.py
    - tests/conftest.py
    - tests/unit/test_scanner.py
  modified:
    - src/core/value_objects/__init__.py

key-decisions:
  - "MediaType.UNKNOWN n'est jamais considere mal place (pas de deplacement sans certitude)"
  - "ScannerService ne prend pas IMediaInfoExtractor - sera ajoute dans Plan 02-02"
  - "Hash SHA-256 sur premiers 10MB seulement pour performance"
  - "corrected_location est un FLAG (detection seulement, pas de deplacement)"

patterns-established:
  - "Ports comme ABC avec @abstractmethod pour contrats d'interface"
  - "Value objects avec @dataclass(frozen=True) pour immutabilite"
  - "Services utilisent injection de dependances (pas d'instanciation directe)"
  - "Tests unitaires avec mocks des interfaces (pas de vrais fichiers)"

# Metrics
duration: 6min
completed: 2026-01-27
---

# Phase 2 Plan 1: Scanning Infrastructure Summary

**Ports IFilenameParser/IMediaInfoExtractor, value objects ParsedFilename/MediaType, FileSystemAdapter avec filtrage video, ScannerService orchestrant scan avec detection de fichiers mal places**

## Performance

- **Duration:** 6 min
- **Started:** 2026-01-27T16:04:43Z
- **Completed:** 2026-01-27T16:10:34Z
- **Tasks:** 3
- **Files created:** 6
- **Files modified:** 1

## Accomplishments

- Ports IFilenameParser et IMediaInfoExtractor definissent les contrats pour le parsing
- Value objects ParsedFilename et MediaType immutables exportes depuis le module
- FileSystemAdapter implemente IFileSystem avec filtrage par extension, taille, symlinks, patterns ignores
- ScannerService orchestre le scan avec detection corrected_location pour fichiers mal places
- 15 tests unitaires passent avec mocks complets

## Task Commits

Each task was committed atomically:

1. **Task 1: Ports et value objects pour le parsing** - `1c01d33` (feat)
2. **Task 2: FileSystemAdapter et ScannerService** - `af9cf62` (feat)
3. **Task 3: Tests unitaires du scanner** - `cc0403c` (test)

## Files Created/Modified

- `src/core/ports/parser.py` - Interfaces IFilenameParser et IMediaInfoExtractor (ABC)
- `src/core/value_objects/parsed_info.py` - MediaType enum et ParsedFilename dataclass
- `src/core/value_objects/__init__.py` - Export MediaType et ParsedFilename
- `src/adapters/file_system.py` - FileSystemAdapter avec list_video_files helper
- `src/services/scanner.py` - ScannerService et ScanResult dataclass
- `tests/conftest.py` - Fixtures mock_file_system, mock_filename_parser, test_settings
- `tests/unit/test_scanner.py` - 15 tests couvrant filtrage, type hint, corrected_location

## Decisions Made

1. **MediaType.UNKNOWN n'est pas mal place** - Un fichier avec type inconnu ne peut pas etre declare "mal place" avec certitude, donc corrected_location=False pour UNKNOWN.

2. **ScannerService sans IMediaInfoExtractor** - L'extracteur sera ajoute dans Plan 02-02 quand l'adaptateur guessit/mediainfo existera. Pour l'instant, media_info=None dans ScanResult.

3. **Hash sur premiers 10MB** - Pour performance sur gros fichiers video, le hash SHA-256 n'est calcule que sur les premiers 10MB du fichier.

4. **corrected_location est detection seulement** - C'est un flag pour indiquer qu'un fichier est dans le mauvais repertoire. Le deplacement physique sera effectue par le Transferer (Phase 5).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- **pytest non installe dans venv**: pip install pytest necessaire avant de lancer les tests.
- **Mocks avec side_effect vs return_value**: Les tests utilisant mock_filename_parser devaient soit definir side_effect, soit le clearer avant de definir return_value (side_effect prend precedence).
- **list_video_files appele pour Films et Series**: Les tests devaient mocker list_video_files avec side_effect pour retourner differents fichiers selon le repertoire scanne.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Ports et value objects prets pour implementation des adaptateurs guessit/mediainfo
- ScannerService pret pour ajout de IMediaInfoExtractor dans Plan 02-02
- Tests et fixtures prets pour extension dans les prochains plans

---
*Phase: 02-parsing-et-scan*
*Completed: 2026-01-27*
