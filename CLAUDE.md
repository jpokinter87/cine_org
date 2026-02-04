# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Langue / Language

**Français obligatoire** pour :
- Tous les échanges avec l'utilisateur
- Les docstrings et commentaires dans le code
- Les messages émis par le programme (logs, erreurs, CLI)
- La documentation générée (.md, README, etc.)

Les noms de variables, fonctions et classes restent en anglais (convention Python).

## Environnement Python

**IMPORTANT** : Ce projet utilise un environnement virtuel `.venv`. Pour toutes les commandes Python (pytest, python -m src.main, etc.), toujours activer le venv :

```bash
source .venv/bin/activate && pytest ...
source .venv/bin/activate && python -m src.main ...
```

Ne jamais essayer d'utiliser `python3` ou `pyenv` directement - pytest et les dépendances sont uniquement dans `.venv`.

## Project Overview

CineOrg is a personal video library management application that:
- Scans download directories for video files
- Extracts metadata via guessit and mediainfo
- Validates and enriches info via TMDB (movies) and TVDB (TV shows) APIs
- Renames files according to a standardized format
- Organizes files in structured directories (by genre for movies, alphabetically for TV shows)
- Creates symlinks for media centers

## Tech Stack

- **Python 3.11+**
- **FastAPI** - Web framework
- **Jinja2 + HTMX** - Templates and interactivity
- **Typer** - CLI framework
- **SQLModel** - ORM (SQLite)
- **guessit** - Filename parsing
- **pymediainfo** - Technical metadata extraction
- **httpx** - Async HTTP client

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
pytest

# Run tests with coverage
pytest --cov=src --cov-report=html --cov-report=term-missing

# Run a single test file
pytest tests/unit/test_parser.py -v

# Check minimum coverage (fails if < 90%)
pytest --cov=src --cov-fail-under=90

# Start dev server
uvicorn src.web.app:app --reload

# Run CLI
python -m src.main --help
```

## Code Architecture

### Directory Structure

```
src/
├── main.py              # CLI entry point
├── core/                # Business logic
│   ├── scanner.py       # Download directory scanning
│   ├── parser.py        # Metadata extraction (guessit + mediainfo)
│   ├── matcher.py       # Scoring and API matching
│   ├── renamer.py       # Formatted filename generation
│   ├── organizer.py     # Directory structure management
│   ├── transferer.py    # File moves + symlink creation
│   ├── importer.py      # Import existing library to DB
│   ├── enricher.py      # API enrichment (separate from import)
│   ├── repair.py        # Broken symlink repair
│   └── orchestrator.py  # Workflow coordination
├── api/                 # External API clients
│   ├── base.py          # Abstract interface (MediaAPIClient)
│   ├── tmdb.py          # TMDB client (movies only)
│   └── tvdb.py          # TVDB client (TV shows only)
├── db/                  # Data layer
│   ├── models.py        # SQLModel models
│   └── repository.py    # Data access
├── web/                 # Web interface
│   ├── app.py           # FastAPI app
│   └── routes/          # Route handlers
├── cli/                 # CLI interface
│   └── commands.py      # Typer commands
└── utils/
    ├── constants.py     # Video extensions, genre hierarchy, codecs
    └── helpers.py       # Utility functions
```

### Key Design Patterns

- **Extensible API clients**: `MediaAPIClient` interface for adding new providers (TMDB, TVDB, future AniDB)
- **Symlink-only reorganization**: Subdivision operations (>50 files) only affect `video/` symlinks, never `storage/` physical files
- **Separate import/enrichment**: Import scans existing library; API enrichment is a separate batch operation with rate limiting

### Scoring System

Movies: 50% title similarity + 25% year match + 25% duration match
- Auto-validation: score >= 85% AND unique result

TV Shows: 100% title similarity (no duration validation)

### File Naming Conventions

Movies: `{Title} ({Year}) {Language} {AudioCodec} {VideoCodec} {Resolution}.{ext}`
TV: `{Title} ({Year}) - {SxxExx} - {EpisodeTitle} - {Language} {AudioCodec} {VideoCodec} {Resolution}.{ext}`

### Directory Organization

- Movies: `storage/Films/{Genre}/{Letter}/{Subdivision}/`
- TV Shows: `storage/Séries/{Letter}/{Subdivision}/{Title} ({Year})/Saison XX/`
- Symlinks mirror this structure in `video/`

## Testing Strategy (TDD)

- Write tests BEFORE implementation code
- Mock all TMDB/TVDB API calls (use `respx` for httpx)
- Each test must be independent and isolated
- Target coverage: 90%+ overall, 95%+ for core modules (parser, matcher, renamer)

Test fixtures in `tests/fixtures/`: sample files, mocked API responses, pre-filled test databases.

## Configuration

Config file: `config/config.json`
- `paths`: downloads, storage, video, manual, trash directories
- `api`: TMDB and TVDB API keys
- `processing`: min_file_size_mb (100), max_files_per_subdir (50), match_score_threshold (85)

## Important Constants (src/utils/constants.py)

- `VIDEO_EXTENSIONS`: .mkv, .mp4, .avi, .mov, etc.
- `IGNORED_PATTERNS`: sample, trailer, preview, extras
- `GENRE_HIERARCHY`: Animation > Science-Fiction > Fantastique > ... (priority order)
- `IGNORED_ARTICLES`: fr/en/de/es articles stripped for alphabetical sorting
- `TMDB_GENRE_MAPPING`: TMDB genre IDs to French genre names
