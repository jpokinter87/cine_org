"""
Mock TVDB API v3 responses for testing.

These fixtures simulate the TVDB API v3 responses for authentication,
search, and series details endpoints.

Reference: https://api.thetvdb.com/swagger (legacy v3 API)
"""

# POST /login response - JWT token (API v3: token at root level)
TVDB_LOGIN_RESPONSE = {
    "token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJhZ2UiOiIiLCJhcGlrZXkiOiJ0ZXN0LWFwaS1rZXkiLCJjb21tdW5pdHlfc3VwcG9ydGVkIjpmYWxzZSwiZXhwIjoxNzAwMDAwMDAwLCJnZW5kZXIiOiIiLCJoaXRzX3Blcl9kYXkiOjEwMDAwMDAwMCwiaGl0c19wZXJfbW9udGgiOjEwMDAwMDAwMDAsImlkIjoiMTIzNDU2Nzg5MCIsImlzX21vZCI6ZmFsc2UsImlzX3N5c3RlbV9rZXkiOmZhbHNlLCJpc190cnVzdGVkIjpmYWxzZSwicGluIjoiIiwidGhlbWUiOiIifQ.test-signature"
}

# GET /search/series?name=Breaking%20Bad response (API v3 format)
TVDB_SEARCH_RESPONSE = {
    "data": [
        {
            "id": 81189,
            "seriesName": "Breaking Bad",
            "aliases": ["Ruptura Total"],
            "banner": "banners/graphical/81189-g10.jpg",
            "firstAired": "2008-01-20",
            "network": "AMC",
            "overview": "Walter White, a high school chemistry teacher...",
            "seriesId": "81189",
            "slug": "breaking-bad",
            "status": "Ended"
        },
        {
            "id": 273181,
            "seriesName": "Metastasis",
            "aliases": ["Breaking Bad (Metastasis)"],
            "banner": "banners/graphical/273181-g.jpg",
            "firstAired": "2014-06-09",
            "network": "Univision",
            "overview": "Colombian adaptation of Breaking Bad...",
            "seriesId": "273181",
            "slug": "metastasis",
            "status": "Ended"
        }
    ]
}

# GET /search/series?name=NonexistentSeries response (empty results)
TVDB_SEARCH_EMPTY_RESPONSE = {
    "data": []
}

# GET /series/81189 response (API v3 format)
TVDB_SERIES_DETAILS_RESPONSE = {
    "data": {
        "id": 81189,
        "seriesName": "Breaking Bad",
        "aliases": ["Ruptura Total"],
        "banner": "banners/graphical/81189-g10.jpg",
        "firstAired": "2008-01-20",
        "genre": ["Crime", "Drama", "Thriller"],
        "imdbId": "tt0903747",
        "lastUpdated": 1630000000,
        "network": "AMC",
        "networkId": "20",
        "overview": "Walter White, a struggling high school chemistry teacher, is diagnosed with inoperable lung cancer...",
        "poster": "/banners/posters/81189-10.jpg",
        "rating": "TV-MA",
        "runtime": "47",
        "seriesId": "81189",
        "slug": "breaking-bad",
        "status": "Ended",
        "added": "2008-01-20 00:00:00",
        "addedBy": 1,
        "airsDayOfWeek": "Sunday",
        "airsTime": "9:00 PM",
        "siteRating": 9.4,
        "siteRatingCount": 500000
    }
}

# GET /series/81189/episodes/query?airedSeason=1 response (13 episodes, single page)
TVDB_SEASON_EPISODES_RESPONSE = {
    "links": {
        "first": 1,
        "last": 1,
        "next": None,
        "prev": None,
    },
    "data": [
        {"id": i, "airedSeason": 1, "airedEpisodeNumber": i, "episodeName": f"Episode {i}"}
        for i in range(1, 14)  # 13 episodes
    ],
}

# GET /series/81189/episodes/query?airedSeason=5 response (page 1 sur 2, 100 episodes)
TVDB_SEASON_EPISODES_PAGE1_RESPONSE = {
    "links": {
        "first": 1,
        "last": 2,
        "next": 2,
        "prev": None,
    },
    "data": [
        {"id": i, "airedSeason": 5, "airedEpisodeNumber": i, "episodeName": f"Episode {i}"}
        for i in range(1, 101)  # 100 episodes (page 1)
    ],
}

# GET /series/81189/episodes/query?airedSeason=5&page=2 response (page 2 sur 2, 20 episodes)
TVDB_SEASON_EPISODES_PAGE2_RESPONSE = {
    "links": {
        "first": 1,
        "last": 2,
        "next": None,
        "prev": 1,
    },
    "data": [
        {"id": 100 + i, "airedSeason": 5, "airedEpisodeNumber": 100 + i, "episodeName": f"Episode {100 + i}"}
        for i in range(1, 21)  # 20 episodes (page 2)
    ],
}

# GET /series/99999999 response (not found - 404)
TVDB_SERIES_NOT_FOUND_RESPONSE = {
    "Error": "Resource not found"
}
