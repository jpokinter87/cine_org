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
├── main.py                  # CLI entry point (Typer)
├── config.py                # Configuration (variables d'environnement)
├── container.py             # Injection de dépendances (dependency-injector)
├── core/                    # Domaine métier
│   ├── entities/            # Entités (Movie, Series, Episode, VideoFile)
│   ├── ports/               # Interfaces (repositories, API clients, parser)
│   └── value_objects/       # Objets valeur (ParsedInfo, MediaInfo)
├── adapters/                # Adaptateurs
│   ├── api/                 # Clients API externes
│   │   ├── tmdb_client.py   #   TMDB (films)
│   │   ├── tvdb_client.py   #   TVDB (séries)
│   │   ├── cache.py         #   Cache disque des réponses API
│   │   └── retry.py         #   Retry avec backoff exponentiel
│   ├── cli/                 # Interface CLI
│   │   ├── commands/        #   Commandes Typer (1 fichier par commande)
│   │   │   ├── workflow_commands.py    # process, pending
│   │   │   ├── validate_commands.py    # validate auto/manual/batch/file
│   │   │   ├── import_commands.py      # import, enrich, populate-movies
│   │   │   ├── enrichment_commands.py  # enrich-ratings, enrich-imdb-ids
│   │   │   ├── imdb_commands.py        # imdb import/sync/stats
│   │   │   ├── repair_command.py       # repair-links
│   │   │   ├── cleanup_command.py      # cleanup
│   │   │   ├── consolidate_command.py  # consolidate
│   │   │   ├── check_command.py        # check
│   │   │   └── regroup_command.py      # regroup
│   │   ├── validation/      #   Validation interactive
│   │   │   ├── candidate_display.py    # Affichage des candidats paginés
│   │   │   ├── interactive_loop.py     # Boucle de validation manuelle
│   │   │   └── batch_display.py        # Résumé batch et conflits
│   │   ├── repair/          #   Réparation interactive des symlinks
│   │   │   ├── auto_repair.py          # Réparation automatique
│   │   │   ├── interactive_repair.py   # Réparation interactive
│   │   │   ├── title_resolver.py       # Résolution alternative de titres
│   │   │   ├── custom_search.py        # Recherche personnalisée
│   │   │   └── helpers.py              # Utilitaires d'affichage
│   │   ├── helpers.py       #   Utilitaires CLI partagés
│   │   ├── cleanup_helpers.py          # Affichage rapport cleanup
│   │   ├── consolidation_helpers.py    # Affichage consolidation
│   │   ├── auto_validator.py           # Validation automatique
│   │   └── batch_builder.py            # Construction des batchs
│   ├── imdb/                # Import datasets IMDb
│   ├── parsing/             # Parsing (guessit, mediainfo)
│   └── file_system.py       # Opérations fichiers
├── services/                # Services métier
│   ├── workflow/            #   Pipeline de traitement (scan → match → transfer)
│   │   ├── workflow_service.py   # Orchestration principale
│   │   ├── scan_step.py          # Scan des téléchargements
│   │   ├── matching_step.py      # Matching TMDB/TVDB + scoring
│   │   ├── transfer_step.py      # Transfert et création symlinks
│   │   └── dataclasses.py        # WorkflowConfig, WorkflowResult, etc.
│   ├── repair/              #   Réparation de symlinks
│   │   ├── repair_service.py     # Orchestration réparation
│   │   ├── file_indexer.py       # Index des fichiers storage
│   │   ├── filename_analyzer.py  # Normalisation et extraction de titres
│   │   └── similarity_matcher.py # Recherche floue de candidats
│   ├── cleanup/             #   Nettoyage et réorganisation video/
│   │   ├── cleanup_service.py    # Orchestration cleanup
│   │   ├── analyzers.py          # 5 analyseurs (_scan_*)
│   │   ├── executors.py          # 6 correcteurs
│   │   ├── subdivision_algorithm.py  # Algorithme de subdivision alphabétique
│   │   ├── dataclasses.py        # CleanupReport, BrokenSymlink, etc.
│   │   └── report_cache.py       # Cache du rapport d'analyse
│   ├── integrity.py         # Vérification d'intégrité (IntegrityChecker)
│   ├── matcher.py           # Scoring et matching API
│   ├── organizer.py         # Structure des répertoires
│   ├── renamer.py           # Génération des noms de fichiers
│   ├── scanner.py           # Scan des répertoires
│   ├── transferer.py        # Déplacement + création symlinks
│   ├── importer.py          # Import vidéothèque existante
│   ├── enricher.py          # Enrichissement API
│   ├── consolidation.py     # Consolidation volumes externes
│   └── prefix_grouper.py    # Regroupement par préfixe de titre
├── infrastructure/          # Persistance
│   └── persistence/
│       ├── database.py      # Gestion SQLite
│       ├── models.py        # Modèles SQLModel
│       ├── hash_service.py  # Calcul de hash SHA-256
│       └── repositories/    # Implémentation des ports
└── utils/
    ├── constants.py         # Extensions vidéo, hiérarchie genres, codecs
    └── helpers.py           # Fonctions utilitaires
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

## Bonnes pratiques post-implémentation

Après chaque nouvelle fonctionnalité intégrée (nouvelle commande CLI, nouveau service, changement de comportement visible), **mettre à jour le README.md** : documenter la commande/fonctionnalité (usage, options, exemples, explication du fonctionnement). Ajouter une entrée dans la table des matières si pertinent, et mentionner la fonctionnalité dans la section Dépannage si applicable.

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
