# Phase 3: Clients API - Research

**Researched:** 2026-01-27
**Domain:** HTTP API clients (TMDB/TVDB), caching, rate limiting, string similarity
**Confidence:** HIGH

## Summary

This phase implements API clients for TMDB (movies) and TVDB (TV series) to search and retrieve metadata, with caching and rate limiting. The research confirms:

1. **TMDB API** is straightforward REST with bearer token auth, ~40 req/s rate limit, returns 429 on excess
2. **TVDB API v4** uses JWT authentication (token valid 1 month), rate limits not explicitly documented
3. **httpx** is the async HTTP client already in the stack, version 0.28.1
4. **tenacity** is the standard library for retry with exponential backoff, supports async natively
5. **diskcache** provides SQLite-backed persistent caching with TTL per key, thread-safe
6. **rapidfuzz** is the modern, fast replacement for fuzzywuzzy for title similarity scoring

The existing `IMediaAPIClient` interface from Phase 1 defines async `search()` and `get_details()` methods. Implementations will use httpx AsyncClient with tenacity decorators for retry logic.

**Primary recommendation:** Use httpx + tenacity for HTTP with retry, diskcache for persistent caching, rapidfuzz for title similarity scoring.

## Standard Stack

The established libraries for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | 0.28.1 | Async HTTP client | Already in project stack, full async support, connection pooling |
| tenacity | 9.0+ | Retry with backoff | De facto standard for Python retries, native async support |
| diskcache | 5.6.1 | Persistent cache | SQLite-backed, thread-safe, per-key TTL, survives restarts |
| rapidfuzz | 3.10+ | String similarity | MIT license, 10x faster than fuzzywuzzy, pure C++ implementation |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| httpx.Timeout | built-in | Fine-grained timeouts | Configure connect/read/write timeouts separately |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| diskcache | SQLite direct | diskcache handles TTL, eviction, thread-safety automatically |
| tenacity | httpx-retries | tenacity more flexible, better async support, widely adopted |
| rapidfuzz | thefuzz (fuzzywuzzy) | rapidfuzz is MIT licensed, 10x faster, drop-in compatible |
| tvdb-v4-official | custom httpx client | Official lib is sync-only, custom client allows async |

**Installation:**
```bash
pip install httpx tenacity diskcache rapidfuzz
```

## Architecture Patterns

### Recommended Project Structure
```
src/
├── adapters/
│   └── api/
│       ├── __init__.py
│       ├── tmdb_client.py      # TMDB implementation of IMediaAPIClient
│       ├── tvdb_client.py      # TVDB implementation of IMediaAPIClient
│       ├── cache.py            # APICache wrapper around diskcache
│       └── retry.py            # Tenacity retry decorators for 429 handling
├── core/
│   └── ports/
│       └── api_clients.py      # IMediaAPIClient interface (exists)
└── services/
    └── matcher.py              # Scoring service using rapidfuzz
```

### Pattern 1: Async Client with Shared Session
**What:** Maintain a single httpx.AsyncClient instance per API client
**When to use:** Always - connection pooling requires client reuse
**Example:**
```python
# Source: https://www.python-httpx.org/async/
class TMDBClient(IMediaAPIClient):
    def __init__(self, api_key: str, cache: APICache):
        self._api_key = api_key
        self._cache = cache
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url="https://api.themoviedb.org/3",
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
```

### Pattern 2: Tenacity Retry Decorator for 429
**What:** Wrap API calls with exponential backoff on rate limit errors
**When to use:** All external API calls
**Example:**
```python
# Source: https://tenacity.readthedocs.io/
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)
import httpx

class RateLimitError(Exception):
    """Raised when API returns 429."""
    def __init__(self, retry_after: Optional[int] = None):
        self.retry_after = retry_after

@retry(
    retry=retry_if_exception_type(RateLimitError),
    wait=wait_random_exponential(multiplier=1, min=1, max=60),
    stop=stop_after_attempt(5),
)
async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs
) -> httpx.Response:
    response = await client.request(method, url, **kwargs)
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        raise RateLimitError(int(retry_after) if retry_after else None)
    response.raise_for_status()
    return response
```

### Pattern 3: Cache with Different TTLs
**What:** Use diskcache with per-key expiration for search vs details
**When to use:** All API responses
**Example:**
```python
# Source: https://grantjenks.com/docs/diskcache/tutorial.html
import asyncio
from diskcache import Cache
from functools import partial

class APICache:
    SEARCH_TTL = 24 * 60 * 60   # 24 hours
    DETAILS_TTL = 7 * 24 * 60 * 60  # 7 days

    def __init__(self, cache_dir: str = ".cache/api"):
        self._cache = Cache(cache_dir)

    async def get(self, key: str) -> Optional[Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._cache.get, key)

    async def set(self, key: str, value: Any, ttl: int) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, partial(self._cache.set, key, value, expire=ttl)
        )

    async def clear(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._cache.clear)
```

### Pattern 4: Scoring with RapidFuzz
**What:** Calculate title similarity using token_sort_ratio for word-order invariance
**When to use:** Matching API results to parsed filenames
**Example:**
```python
# Source: https://github.com/rapidfuzz/RapidFuzz
from rapidfuzz import fuzz, utils

def calculate_title_score(query: str, candidate: str) -> float:
    """
    Calculate title similarity score (0-100).
    Uses token_sort_ratio for word-order independence.
    """
    # Normalize: lowercase, strip whitespace, remove punctuation
    q_normalized = utils.default_process(query)
    c_normalized = utils.default_process(candidate)
    return fuzz.token_sort_ratio(q_normalized, c_normalized)
```

### Anti-Patterns to Avoid
- **Creating new AsyncClient per request:** Wastes connection pool, creates overhead
- **Synchronous diskcache in async code:** Block event loop - use run_in_executor
- **Immediate retry without backoff:** Overwhelms API, extends rate limit window
- **Caching error responses:** Store only successful results
- **Hardcoding API URLs:** Use base_url on client, relative paths in requests

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Retry logic | Custom while loops with sleep | tenacity | Handles jitter, backoff curves, async, stop conditions |
| String similarity | Levenshtein from scratch | rapidfuzz | C++ optimized, handles unicode, provides multiple algorithms |
| Disk caching | SQLite schema + TTL logic | diskcache | Thread-safe, automatic expiration, tested edge cases |
| HTTP client | requests + asyncio.to_thread | httpx | Native async, connection pooling, same API sync/async |
| JWT handling | Manual token refresh | Store expiry, refresh proactively | TVDB tokens last 1 month, simple check suffices |

**Key insight:** API client code is 90% boilerplate around retry, caching, and error handling. Libraries handle the edge cases (connection drops, partial responses, race conditions) that you will miss.

## Common Pitfalls

### Pitfall 1: Connection Exhaustion
**What goes wrong:** Creating AsyncClient in each request exhausts connections
**Why it happens:** AsyncClient maintains connection pool, creating many wastes resources
**How to avoid:** Create one client per API, reuse across requests, close on shutdown
**Warning signs:** "Too many open files" errors, slow requests after many calls

### Pitfall 2: Blocking Event Loop with Cache
**What goes wrong:** Calling diskcache.get() directly blocks async event loop
**Why it happens:** diskcache uses SQLite which is synchronous
**How to avoid:** Always use `await loop.run_in_executor(None, cache.get, key)`
**Warning signs:** Slow async performance, high latency on cache operations

### Pitfall 3: Rate Limit Retry Storm
**What goes wrong:** All retries happen at same time after backoff
**Why it happens:** Fixed backoff without jitter causes synchronized retries
**How to avoid:** Use `wait_random_exponential` not `wait_exponential`
**Warning signs:** Repeated 429 errors even with retry logic

### Pitfall 4: TVDB JWT Token Expiry
**What goes wrong:** Requests fail with 401 after token expires
**Why it happens:** JWT token valid for 1 month, not refreshed
**How to avoid:** Store token with expiry timestamp, refresh proactively (e.g., 1 day before expiry)
**Warning signs:** 401 errors after long periods without TVDB calls

### Pitfall 5: Genre ID vs Genre Name Confusion
**What goes wrong:** Storing genre IDs instead of names, breaking organization logic
**Why it happens:** TMDB returns `genre_ids` in search, `genres` array in details
**How to avoid:** Always fetch details for genre names, or use genre list endpoint
**Warning signs:** Numbers where genre names expected, organization by ID not name

### Pitfall 6: Missing Year Tolerance
**What goes wrong:** Good matches rejected because year is off by 1
**Why it happens:** Release dates vary by country, encoded dates differ
**How to avoid:** Accept +/-1 year tolerance as specified in CONTEXT.md
**Warning signs:** Obviously correct matches scoring below threshold

## Code Examples

Verified patterns from official sources:

### TMDB Movie Search
```python
# Source: https://developer.themoviedb.org/reference/search-movie
async def search_movies(self, query: str, year: Optional[int] = None) -> list[SearchResult]:
    cache_key = f"tmdb:search:{query}:{year}"
    cached = await self._cache.get(cache_key)
    if cached:
        return cached

    params = {"query": query, "language": "fr-FR"}
    if year:
        params["year"] = str(year)

    response = await self._request_with_retry("GET", "/search/movie", params=params)
    data = response.json()

    results = [
        SearchResult(
            id=str(r["id"]),
            title=r["title"],
            year=int(r["release_date"][:4]) if r.get("release_date") else None,
            source="tmdb",
        )
        for r in data.get("results", [])
    ]

    await self._cache.set(cache_key, results, APICache.SEARCH_TTL)
    return results
```

### TMDB Movie Details
```python
# Source: https://developer.themoviedb.org/reference/movie-details
async def get_movie_details(self, movie_id: str) -> Optional[MediaDetails]:
    cache_key = f"tmdb:details:{movie_id}"
    cached = await self._cache.get(cache_key)
    if cached:
        return cached

    response = await self._request_with_retry("GET", f"/movie/{movie_id}", params={"language": "fr-FR"})
    data = response.json()

    details = MediaDetails(
        id=str(data["id"]),
        title=data["title"],
        original_title=data.get("original_title"),
        year=int(data["release_date"][:4]) if data.get("release_date") else None,
        genres=tuple(g["name"] for g in data.get("genres", [])),
        duration_seconds=data.get("runtime", 0) * 60 if data.get("runtime") else None,
        overview=data.get("overview"),
        poster_url=f"https://image.tmdb.org/t/p/w500{data['poster_path']}" if data.get("poster_path") else None,
    )

    await self._cache.set(cache_key, details, APICache.DETAILS_TTL)
    return details
```

### TVDB Authentication
```python
# Source: https://thetvdb.github.io/v4-api/
class TVDBClient(IMediaAPIClient):
    BASE_URL = "https://api4.thetvdb.com/v4"

    def __init__(self, api_key: str, cache: APICache):
        self._api_key = api_key
        self._cache = cache
        self._token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None

    async def _ensure_token(self) -> str:
        if self._token and self._token_expiry and datetime.now() < self._token_expiry:
            return self._token

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/login",
                json={"apikey": self._api_key},
            )
            response.raise_for_status()
            data = response.json()
            self._token = data["data"]["token"]
            # Token valid for 1 month, refresh 1 day early
            self._token_expiry = datetime.now() + timedelta(days=29)
            return self._token
```

### Scoring Implementation
```python
# Based on CONTEXT.md requirements
from rapidfuzz import fuzz, utils

def calculate_movie_score(
    query_title: str,
    query_year: Optional[int],
    query_duration: Optional[int],  # seconds
    candidate_title: str,
    candidate_year: Optional[int],
    candidate_duration: Optional[int],  # seconds
) -> float:
    """
    Calculate match score: 50% title + 25% year + 25% duration.
    Returns 0-100.
    """
    # Title: 50%
    title_score = fuzz.token_sort_ratio(
        utils.default_process(query_title),
        utils.default_process(candidate_title),
    )

    # Year: 25% (full score if within +/-1 year)
    year_score = 0.0
    if query_year and candidate_year:
        year_diff = abs(query_year - candidate_year)
        if year_diff == 0:
            year_score = 100.0
        elif year_diff == 1:
            year_score = 100.0  # Tolerance per CONTEXT.md
        else:
            year_score = max(0, 100 - (year_diff - 1) * 25)

    # Duration: 25% (full score if within +/-10%)
    duration_score = 0.0
    if query_duration and candidate_duration:
        ratio = query_duration / candidate_duration
        if 0.9 <= ratio <= 1.1:
            duration_score = 100.0  # Within 10% tolerance
        else:
            deviation = abs(1 - ratio)
            duration_score = max(0, 100 - (deviation - 0.1) * 500)

    return title_score * 0.5 + year_score * 0.25 + duration_score * 0.25
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| requests + threading | httpx async | 2020 | Native async, better performance |
| fuzzywuzzy | rapidfuzz | 2021 | MIT license, 10x faster |
| TVDB API v2/v3 | TVDB API v4 | 2021 | JWT auth, cleaner endpoints |
| custom retry loops | tenacity | Standard since 2018 | Declarative, handles edge cases |
| in-memory caching | diskcache | Mature since 2016 | Persists across restarts |

**Deprecated/outdated:**
- **fuzzywuzzy:** GPL license issues, slow pure-Python, use rapidfuzz instead
- **TVDB API v2/v3:** v4 is current, older versions being deprecated
- **requests for async:** Use httpx for unified sync/async API

## Open Questions

Things that couldn't be fully resolved:

1. **TVDB exact rate limits**
   - What we know: No explicit documentation found, community uses ~1-2 req/s self-imposed
   - What's unclear: Official limit, if any
   - Recommendation: Implement same retry/backoff as TMDB, observe 429 responses

2. **TMDB exact rate limit**
   - What we know: "~40 requests per second range", may change
   - What's unclear: Whether limit is per IP or per API key, exact headers
   - Recommendation: Implement exponential backoff on 429, don't optimize to the limit

3. **Genre mapping completeness**
   - What we know: TMDB provides French translations via language=fr-FR
   - What's unclear: Whether all genres have French translations
   - Recommendation: Fetch genre list endpoint once, cache indefinitely, fallback to English

## Sources

### Primary (HIGH confidence)
- TMDB API official docs - https://developer.themoviedb.org/reference/search-movie
- TMDB rate limiting - https://developer.themoviedb.org/docs/rate-limiting
- TVDB API v4 Swagger - https://thetvdb.github.io/v4-api/
- httpx documentation - https://www.python-httpx.org/async/
- tenacity documentation - https://tenacity.readthedocs.io/
- diskcache tutorial - https://grantjenks.com/docs/diskcache/tutorial.html
- rapidfuzz GitHub - https://github.com/rapidfuzz/RapidFuzz

### Secondary (MEDIUM confidence)
- httpx-retries usage - https://will-ockmore.github.io/httpx-retries/
- TVDB Python official lib - https://github.com/thetvdb/tvdb-v4-python
- Tenacity 429 handling example - https://github.com/alexwlchan/handling-http-429-with-tenacity

### Tertiary (LOW confidence)
- TVDB rate limit community practices - forum discussions indicate ~1-2 req/s as safe

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries are well-documented, widely used
- Architecture: HIGH - Patterns from official httpx and tenacity docs
- Pitfalls: HIGH - Common issues documented in library docs and community
- TVDB rate limits: LOW - No official documentation found

**Research date:** 2026-01-27
**Valid until:** 2026-02-27 (30 days - stable libraries, APIs versioned)
