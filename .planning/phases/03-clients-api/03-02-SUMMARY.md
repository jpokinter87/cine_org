---
phase: 03-clients-api
plan: 02
subsystem: api-clients
tags: [tmdb, api, http, cache, retry]
dependency-graph:
  requires: [03-01]
  provides: [TMDBClient, TMDB_GENRE_MAPPING]
  affects: [03-03, 04-01]
tech-stack:
  added: []
  patterns: [cache-first, retry-with-backoff, interface-implementation]
key-files:
  created:
    - src/adapters/api/tmdb_client.py
    - src/utils/__init__.py
    - src/utils/constants.py
    - tests/fixtures/__init__.py
    - tests/fixtures/tmdb_responses.py
    - tests/unit/adapters/api/test_tmdb_client.py
  modified:
    - src/adapters/api/__init__.py
decisions:
  - id: "cache-key-format"
    choice: "tmdb:search:{query}:{year} and tmdb:details:{media_id}"
    reason: "Clear namespace separation, includes all query parameters"
  - id: "french-genre-source"
    choice: "API response (fr-FR language param) with TMDB_GENRE_MAPPING fallback"
    reason: "API provides French names directly, mapping is backup for edge cases"
  - id: "duration-conversion"
    choice: "runtime (minutes) * 60 = duration_seconds"
    reason: "TMDB returns minutes, MediaDetails expects seconds"
metrics:
  duration: 4 min
  completed: 2026-01-27
---

# Phase 03 Plan 02: TMDBClient Summary

TMDB API client implementing IMediaAPIClient with cache-first pattern, 24h search cache, 7-day details cache, automatic retry on 429.

## What Was Built

### TMDBClient (`src/adapters/api/tmdb_client.py`)

Full implementation of TMDB API client:

```python
class TMDBClient(IMediaAPIClient):
    async def search(query, year=None) -> list[SearchResult]
    async def get_details(media_id) -> MediaDetails | None
    @property
    def source -> str  # Returns "tmdb"
    async def close() -> None
```

Key features:
- **Cache-first pattern**: `cache.get()` called BEFORE any HTTP request
- **Bearer auth**: Uses TMDB v4 Read Access Token
- **French language**: Requests with `language=fr-FR`
- **Retry on 429**: Uses `request_with_retry` from 03-01

### TMDB Genre Mapping (`src/utils/constants.py`)

19 genre ID to French name mappings:

```python
TMDB_GENRE_MAPPING = {
    28: "Action",
    878: "Science-Fiction",
    14: "Fantastique",
    # ... 16 more entries
}
```

### Test Fixtures (`tests/fixtures/tmdb_responses.py`)

Realistic mock responses for:
- `TMDB_SEARCH_RESPONSE` - Avatar search results (2 movies)
- `TMDB_SEARCH_RESPONSE_WITH_YEAR` - Avatar 2009 only
- `TMDB_SEARCH_EMPTY_RESPONSE` - No results
- `TMDB_MOVIE_DETAILS_RESPONSE` - Avatar full details

## TDD Execution

### RED Phase (commit: 639003f)

14 failing tests created:
- Interface compliance (2 tests)
- Search functionality (6 tests)
- Get details functionality (4 tests)
- Retry behavior (1 test)
- Lifecycle management (1 test)

### GREEN Phase (commit: 6b20493)

All 14 tests passing with 97% coverage.

## Tests Added

| Test Class | Tests | Coverage |
|------------|-------|----------|
| TestTMDBClientInterface | 2 | Interface + source |
| TestTMDBSearch | 6 | search(), caching, cache-first |
| TestTMDBGetDetails | 4 | get_details(), 404, caching |
| TestTMDBRetry | 1 | 429 retry behavior |
| TestTMDBClientLifecycle | 1 | close() cleanup |

## Verification Results

1. All 14 tests pass
2. Import works: `from src.adapters.api.tmdb_client import TMDBClient`
3. Interface: `isinstance(TMDBClient(...), IMediaAPIClient)` = True
4. Coverage: 97% (65 statements, 2 missed in edge cases)

## Deviations from Plan

None - plan executed exactly as written.

## Cache Key Patterns

| Operation | Cache Key Format | TTL |
|-----------|------------------|-----|
| Search | `tmdb:search:{query}:{year}` | 24h |
| Details | `tmdb:details:{media_id}` | 7 days |

## Next Phase Readiness

**Provides for 03-03 (TVDB Client):**
- Pattern to follow for TVDBClient
- Constants module structure for TVDB_GENRE_MAPPING if needed

**Provides for 04-01 (Orchestrator):**
- TMDBClient ready for dependency injection
- Interface compliant for polymorphic usage
