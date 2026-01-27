---
phase: 03-clients-api
plan: 03
subsystem: api
tags: [tvdb, jwt, httpx, async, caching, rate-limiting]

# Dependency graph
requires:
  - phase: 03-01
    provides: IMediaAPIClient interface, SearchResult, MediaDetails dataclasses
  - phase: 03-04
    provides: APICache with TTL, RateLimitError, request_with_retry
provides:
  - TVDBClient implementing IMediaAPIClient for TV series
  - JWT authentication with automatic token refresh
  - Cache-first pattern for search and details
  - Rate limiting with automatic retry on 429
affects: [04-scoring-validation, 05-renaming-organisation]

# Tech tracking
tech-stack:
  added: []  # httpx, tenacity, diskcache already added in 03-04
  patterns:
    - JWT authentication with proactive token refresh (29-day expiry, refresh on use)
    - Cache-first pattern: cache.get() BEFORE any HTTP request

key-files:
  created:
    - src/adapters/api/tvdb_client.py
    - tests/unit/adapters/api/test_tvdb_client.py
    - tests/fixtures/tvdb_responses.py
  modified:
    - src/adapters/api/__init__.py

key-decisions:
  - "29-day token expiry (TVDB tokens valid 1 month, refresh 1 day early)"
  - "series endpoint uses /extended for full details including genres"
  - "duration_seconds is None for series (no single runtime)"

patterns-established:
  - "JWT auth: _ensure_token() called before each API request, token stored in instance"
  - "TVDB search uses /search?type=series endpoint with 'q' parameter"

# Metrics
duration: 5min
completed: 2026-01-27
---

# Phase 3 Plan 3: TVDBClient Summary

**TVDB API v4 client with JWT authentication, cache-first pattern, and automatic retry on rate limiting**

## Performance

- **Duration:** 5 min
- **Started:** 2026-01-27T17:52:34Z
- **Completed:** 2026-01-27T17:57:20Z
- **Tasks:** 2 (TDD: RED + GREEN phases)
- **Files modified:** 4

## Accomplishments

- TVDBClient implementing IMediaAPIClient for TV series metadata
- JWT authentication: token obtained via /login, auto-refreshed before expiry
- Cache-first pattern: cache checked BEFORE any HTTP request
- Rate limiting: 429 responses trigger automatic retry with exponential backoff
- 94% test coverage (exceeds 90% requirement)

## Task Commits

Each task was committed atomically:

1. **Task: RED phase (failing tests)** - `4b61f63` (test)
   - TVDB mock response fixtures
   - 16 comprehensive tests for TVDBClient

2. **Task: GREEN phase (implementation)** - `1c1a754` (feat)
   - TVDBClient with JWT auth, search, get_details
   - All 16 tests passing

_Note: TDD approach with RED-GREEN phases_

## Files Created/Modified

- `src/adapters/api/tvdb_client.py` - TVDB API client implementation
- `tests/unit/adapters/api/test_tvdb_client.py` - Comprehensive test suite (16 tests)
- `tests/fixtures/tvdb_responses.py` - Mock API responses (login, search, details)
- `src/adapters/api/__init__.py` - Export TVDBClient

## Decisions Made

1. **29-day token expiry** - TVDB tokens valid 1 month, refresh 1 day early to avoid edge cases
2. **Use /series/{id}/extended** - Extended endpoint provides full details including genres
3. **duration_seconds is None** - Series don't have a single runtime like movies
4. **Cache-first pattern** - Same as TMDBClient: check cache BEFORE any HTTP request

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - implementation followed research patterns from 03-RESEARCH.md.

## User Setup Required

**External services require manual configuration.** TVDB API key required:

1. Register at https://thetvdb.com/subscribe
2. Create a project under API Access
3. Copy Project API Key
4. Set environment variable: `CINEORG_TVDB_API_KEY=<your-key>`

Verification:
```bash
# Test with real API (requires valid key)
python -c "
import asyncio
from src.adapters.api import TVDBClient, APICache
import os

async def test():
    cache = APICache('.cache/test')
    client = TVDBClient(api_key=os.environ['CINEORG_TVDB_API_KEY'], cache=cache)
    results = await client.search('Breaking Bad')
    print(f'Found {len(results)} results')
    await client.close()
    cache.close()

asyncio.run(test())
"
```

## Next Phase Readiness

- TVDB client ready for TV series metadata retrieval
- Both TMDB and TVDB clients now available
- Ready for scoring/validation phase (04)

---
*Phase: 03-clients-api*
*Completed: 2026-01-27*
