# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-26)

**Core value:** Architecture propre avec separation claire entre logique metier et interfaces
**Current focus:** Phase 4 - Persistance (ready to plan)

## Current Position

Phase: 4 of 8 (Persistance)
Plan: 0 of 2 in current phase
Status: Ready to plan
Last activity: 2026-01-27 - Phase 3 verified and complete

Progress: [████████░░] 37.5%

## Performance Metrics

**Velocity:**
- Total plans completed: 8
- Average duration: 4.5 min
- Total execution time: 36 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-fondations-architecture | 2 | 6 min | 3 min |
| 02-parsing-et-scan | 2 | 13 min | 6.5 min |
| 03-clients-api | 4 | 17 min | 4.25 min |

**Recent Trend:**
- Last 5 plans: 03-04 (4 min), 03-01 (4 min), 03-02 (4 min), 03-03 (5 min)
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

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-01-27T17:57:20Z
Stopped at: Completed 03-03-PLAN.md
Resume file: None
