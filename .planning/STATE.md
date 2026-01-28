# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-26)

**Core value:** Architecture propre avec separation claire entre logique metier et interfaces
**Current focus:** MILESTONE v1 COMPLETE

## Current Position

Phase: 8 of 8 (Import et Maintenance)
Plan: 2 of 2 in current phase (COMPLETE)
Status: MILESTONE v1 COMPLETE - All 8 phases verified
Last activity: 2026-01-28 - Phase 8 verified and complete

Progress: [████████████████████] 100%

## Performance Metrics

**Velocity:**
- Total plans completed: 17
- Average duration: 4.8 min
- Total execution time: 84 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-fondations-architecture | 2 | 6 min | 3 min |
| 02-parsing-et-scan | 2 | 13 min | 6.5 min |
| 03-clients-api | 4 | 17 min | 4.25 min |
| 04-persistance | 2 | 6 min | 3 min |
| 05-organisation-fichiers | 2 | 11 min | 5.5 min |
| 06-validation | 2 | 12 min | 6 min |
| 07-cli-principale | 1 | 7 min | 7 min |
| 08-import-et-maintenance | 2 | 12 min | 6 min |

**Recent Trend:**
- Last 5 plans: 08-02 (7 min), 08-01 (5 min), 07-01 (7 min), 06-02 (8 min), 06-01 (4 min)
- Trend: Stable

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Architecture hexagonale choisie pour eviter le couplage CLI/metier de la v1
- CLI avant Web pour valider le coeur metier d'abord
- Used @dataclass(frozen=True) for value objects to guarantee immutability
- Used ABC with @abstractmethod for ports to enforce interface contracts
- Async methods for IMediaAPIClient to support httpx async client
- API keys (TMDB/TVDB) are optional - features disabled via tmdb_enabled/tvdb_enabled properties
- Logging dual output: colored console for real-time, JSON file with rotation for historical analysis
- DI wiring done explicitly in main.py instead of auto-wiring to avoid import cycles
- MediaType.UNKNOWN n'est jamais considere mal place (pas de deplacement sans certitude)
- ScannerService now takes IMediaInfoExtractor parameter (implemented in 02-02)
- corrected_location est un FLAG (detection seulement, pas de deplacement)
- Type hint from directory overrides guessit auto-detection (Films/ -> MOVIE)
- Duration converted from milliseconds to seconds (pymediainfo returns ms)
- ScannerService calls extractor.extract() directly (separation of concerns)
- token_sort_ratio with processor for case-insensitive word-order-independent matching
- Year tolerance: +/-1 = 100%, -25% per additional year
- Duration tolerance: +/-10% = 100%, -50% per additional 10%
- API SearchResult lacks duration, so score_results max for movies = 75%
- diskcache for persistence (file-based, no external server needed)
- Async cache via run_in_executor (non-blocking despite sync diskcache)
- Cache TTL: 24h for search results, 7 days for media details
- wait_random_exponential for retry jitter (avoids thundering herd)
- Cache key format: "tmdb:search:{query}:{year}" and "tmdb:details:{media_id}"
- French genres: API response (fr-FR) with TMDB_GENRE_MAPPING fallback
- Duration: TMDB runtime (minutes) * 60 = duration_seconds
- TVDB JWT: 29-day token expiry (1 month valid, refresh 1 day early)
- TVDB search: /search?type=series with 'q' parameter
- TVDB details: /series/{id}/extended for full details including genres
- Series duration_seconds: None (no single runtime for TV series)
- check_same_thread=False pour SQLite multi-thread/async
- Properties getter/setter pour serialisation JSON transparente (genres, languages, candidates)
- entity_metadata au lieu de metadata pour eviter conflit avec SQLModel.metadata
- Index compose sur (series_id, season_number, episode_number) pour episodes
- xxhash pour hash rapide (echantillons debut/fin/taille au lieu de fichier complet)
- Factory provider pour repositories (session fraiche a chaque appel)
- Conversion tuple <-> JSON pour genres/languages dans repositories
- Ellipsis placeholder: caractere Unicode U+2026 pour preserver les ... en fin de chaine
- Priority genre: premier genre de GENRE_HIERARCHY trouve dans les genres du film
- Multi-audio scoring: meilleur score parmi toutes les pistes
- Protocol instead of ABC imports: TransfererService uses typing.Protocol for IAtomicFileSystem
- os.path.relpath for relative symlinks: Python 3.11 compatible (walk_up requires 3.12)
- THRESHOLD = 85 pour auto-validation (coherent avec MatcherService.MATCH_THRESHOLD)
- Clients API optionnels (None) - geres gracieusement avec retour liste vide
- list_validated utilise acces direct session pour filtrer par status
- determine_is_series() via candidate.source + filename patterns (pas de media_info.guessed)
- Series info extraction from filename (SxxExx pattern) since guessit data not persisted
- validate file as subcommand (not direct command) to avoid namespace conflict
- database.init() is synchronous - removed erroneous await calls
- pending sorted by max candidate score descending for priority display
- Hash-first duplicate detection: check by hash before path for import
- Dry-run mode via constructor injection for testability
- Generator pattern for scan_library to support progress streaming
- Rate limiting 0.25s entre requetes API (4 req/s pour TMDB 40/10s)
- MAX_RETRIES=3 avec backoff simple pour les erreurs transientes
- Symlinks orphelins deplaces vers trash/orphans avec timestamp si conflit
- Rapport integrite avec format texte structure par defaut, --json optionnel

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-01-28T20:02:33Z
Stopped at: Completed 08-02-PLAN.md - Project complete
Resume file: None
