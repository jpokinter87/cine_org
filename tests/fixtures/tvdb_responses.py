"""
Mock TVDB API v4 responses for testing.

These fixtures simulate the TVDB API responses for authentication,
search, and series details endpoints.

Reference: https://thetvdb.github.io/v4-api/
"""

# POST /login response - JWT token
TVDB_LOGIN_RESPONSE = {
    "status": "success",
    "data": {
        "token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJhZ2UiOiIiLCJhcGlrZXkiOiJ0ZXN0LWFwaS1rZXkiLCJjb21tdW5pdHlfc3VwcG9ydGVkIjpmYWxzZSwiZXhwIjoxNzAwMDAwMDAwLCJnZW5kZXIiOiIiLCJoaXRzX3Blcl9kYXkiOjEwMDAwMDAwMCwiaGl0c19wZXJfbW9udGgiOjEwMDAwMDAwMDAsImlkIjoiMTIzNDU2Nzg5MCIsImlzX21vZCI6ZmFsc2UsImlzX3N5c3RlbV9rZXkiOmZhbHNlLCJpc190cnVzdGVkIjpmYWxzZSwicGluIjoiIiwidGhlbWUiOiIifQ.test-signature"
    }
}

# GET /search?type=series&q=Breaking%20Bad response
TVDB_SEARCH_RESPONSE = {
    "status": "success",
    "data": [
        {
            "objectID": "series-81189",
            "id": "81189",
            "name": "Breaking Bad",
            "slug": "breaking-bad",
            "aliases": [
                "Breaking Bad",
                "Ruptura Total"
            ],
            "country": "usa",
            "first_air_time": "2008-01-20",
            "image_url": "https://artworks.thetvdb.com/banners/posters/81189-10.jpg",
            "year": "2008",
            "type": "series",
            "primary_language": "eng",
            "primary_type": "series",
            "overview": "Walter White, a high school chemistry teacher...",
            "network": "AMC",
            "status": "Ended",
            "genres": ["Crime", "Drama", "Thriller"]
        },
        {
            "objectID": "series-273181",
            "id": "273181",
            "name": "Metastasis",
            "slug": "metastasis",
            "aliases": ["Breaking Bad (Metastasis)"],
            "country": "col",
            "first_air_time": "2014-06-09",
            "image_url": "https://artworks.thetvdb.com/banners/posters/273181-1.jpg",
            "year": "2014",
            "type": "series",
            "primary_language": "spa",
            "primary_type": "series",
            "overview": "Colombian adaptation of Breaking Bad...",
            "network": "Univision",
            "status": "Ended",
            "genres": ["Crime", "Drama"]
        }
    ]
}

# GET /search?type=series&q=NonexistentSeries response (empty results)
TVDB_SEARCH_EMPTY_RESPONSE = {
    "status": "success",
    "data": []
}

# GET /series/81189/extended response
TVDB_SERIES_DETAILS_RESPONSE = {
    "status": "success",
    "data": {
        "id": 81189,
        "name": "Breaking Bad",
        "slug": "breaking-bad",
        "image": "https://artworks.thetvdb.com/banners/posters/81189-10.jpg",
        "nameTranslations": ["fra", "eng", "deu", "spa"],
        "overviewTranslations": ["fra", "eng", "deu", "spa"],
        "aliases": [
            {"language": "fra", "name": "Breaking Bad"},
            {"language": "spa", "name": "Ruptura Total"}
        ],
        "firstAired": "2008-01-20",
        "lastAired": "2013-09-29",
        "nextAired": "",
        "score": 11989,
        "status": {
            "id": 2,
            "name": "Ended",
            "recordType": "series",
            "keepUpdated": False
        },
        "originalCountry": "usa",
        "originalLanguage": "eng",
        "originalNetwork": {
            "id": 20,
            "name": "AMC",
            "slug": "amc",
            "abbreviation": "AMC",
            "country": "usa"
        },
        "year": "2008",
        "overview": "Walter White, a struggling high school chemistry teacher, is diagnosed with inoperable lung cancer...",
        "genres": [
            {"id": 1, "name": "Crime", "slug": "crime"},
            {"id": 2, "name": "Drama", "slug": "drama"},
            {"id": 3, "name": "Thriller", "slug": "thriller"}
        ],
        "averageRuntime": 47,
        "seasons": [
            {"id": 30272, "seriesId": 81189, "type": {"id": 1, "name": "Aired Order"}, "number": 1},
            {"id": 30273, "seriesId": 81189, "type": {"id": 1, "name": "Aired Order"}, "number": 2},
            {"id": 30274, "seriesId": 81189, "type": {"id": 1, "name": "Aired Order"}, "number": 3},
            {"id": 30275, "seriesId": 81189, "type": {"id": 1, "name": "Aired Order"}, "number": 4},
            {"id": 30276, "seriesId": 81189, "type": {"id": 1, "name": "Aired Order"}, "number": 5}
        ],
        "translations": {
            "nameTranslations": [
                {"language": "fra", "name": "Breaking Bad", "isPrimary": True},
                {"language": "eng", "name": "Breaking Bad", "isPrimary": True}
            ],
            "overviewTranslations": [
                {
                    "language": "fra",
                    "overview": "Walter White est un professeur de chimie dans un lycee du Nouveau-Mexique...",
                    "isPrimary": False
                },
                {
                    "language": "eng",
                    "overview": "Walter White, a struggling high school chemistry teacher...",
                    "isPrimary": True
                }
            ]
        }
    }
}

# GET /series/99999999/extended response (not found - 404)
TVDB_SERIES_NOT_FOUND_RESPONSE = {
    "status": "failure",
    "message": "Record not found",
    "data": None
}
