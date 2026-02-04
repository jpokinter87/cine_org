"""
Mock TMDB API responses for testing.

Contains realistic responses from the TMDB API for search and movie details endpoints.
These fixtures are used with respx to mock httpx calls in tests.
"""

# Search response for "Avatar" query
# GET /search/movie?query=Avatar&language=fr-FR
TMDB_SEARCH_RESPONSE = {
    "page": 1,
    "results": [
        {
            "adult": False,
            "backdrop_path": "/s3TBrRGB1iav7gFOCNx3H31MoES.jpg",
            "genre_ids": [28, 12, 14, 878],
            "id": 19995,
            "original_language": "en",
            "original_title": "Avatar",
            "overview": "L'histoire d'un ancien marine paraplégique...",
            "popularity": 456.92,
            "poster_path": "/jRXYjXNq0Cs2TcJjLkki24MLp7u.jpg",
            "release_date": "2009-12-15",
            "title": "Avatar",
            "video": False,
            "vote_average": 7.6,
            "vote_count": 27000,
        },
        {
            "adult": False,
            "backdrop_path": "/7BIwGH0WAEN3tQsB1X5HnVjj2bR.jpg",
            "genre_ids": [28, 12, 878],
            "id": 76600,
            "original_language": "en",
            "original_title": "Avatar: The Way of Water",
            "overview": "Se déroulant plus d'une décennie après les événements...",
            "popularity": 234.56,
            "poster_path": "/t6HIqrRAclMCA60NsSmeqe9RmNV.jpg",
            "release_date": "2022-12-14",
            "title": "Avatar: La Voie de l'eau",
            "video": False,
            "vote_average": 7.7,
            "vote_count": 12000,
        },
    ],
    "total_pages": 1,
    "total_results": 2,
}

# Search response with year filter for "Avatar" 2009
# GET /search/movie?query=Avatar&year=2009&language=fr-FR
TMDB_SEARCH_RESPONSE_WITH_YEAR = {
    "page": 1,
    "results": [
        {
            "adult": False,
            "backdrop_path": "/s3TBrRGB1iav7gFOCNx3H31MoES.jpg",
            "genre_ids": [28, 12, 14, 878],
            "id": 19995,
            "original_language": "en",
            "original_title": "Avatar",
            "overview": "L'histoire d'un ancien marine paraplégique...",
            "popularity": 456.92,
            "poster_path": "/jRXYjXNq0Cs2TcJjLkki24MLp7u.jpg",
            "release_date": "2009-12-15",
            "title": "Avatar",
            "video": False,
            "vote_average": 7.6,
            "vote_count": 27000,
        },
    ],
    "total_pages": 1,
    "total_results": 1,
}

# Empty search response
TMDB_SEARCH_EMPTY_RESPONSE = {
    "page": 1,
    "results": [],
    "total_pages": 0,
    "total_results": 0,
}

# Movie details for Avatar (id=19995)
# GET /movie/19995?language=fr-FR&append_to_response=credits
TMDB_MOVIE_DETAILS_RESPONSE = {
    "adult": False,
    "backdrop_path": "/s3TBrRGB1iav7gFOCNx3H31MoES.jpg",
    "belongs_to_collection": {
        "id": 87096,
        "name": "Avatar - Saga",
        "poster_path": "/uO2yU3QiGHvVp0L5e5IatTVRkYk.jpg",
        "backdrop_path": "/iaEsDbQPE45hQU2EGiNjXD2KWuF.jpg",
    },
    "budget": 237000000,
    "genres": [
        {"id": 28, "name": "Action"},
        {"id": 12, "name": "Aventure"},
        {"id": 14, "name": "Fantastique"},
        {"id": 878, "name": "Science-Fiction"},
    ],
    "homepage": "https://www.avatar.com",
    "id": 19995,
    "imdb_id": "tt0499549",
    "original_language": "en",
    "original_title": "Avatar",
    "overview": "Malgré sa paralysie, Jake Sully, un ancien marine immobilisé dans un fauteuil roulant, est resté un combattant au plus profond de son être...",
    "popularity": 456.92,
    "poster_path": "/jRXYjXNq0Cs2TcJjLkki24MLp7u.jpg",
    "production_companies": [
        {
            "id": 574,
            "logo_path": "/iB6GjNVHs5hOqcEYt2rcjBqIjki.png",
            "name": "Lightstorm Entertainment",
            "origin_country": "US",
        }
    ],
    "production_countries": [
        {"iso_3166_1": "US", "name": "United States of America"}
    ],
    "release_date": "2009-12-15",
    "revenue": 2923706026,
    "runtime": 162,  # minutes
    "spoken_languages": [
        {"english_name": "English", "iso_639_1": "en", "name": "English"},
        {"english_name": "Spanish", "iso_639_1": "es", "name": "Español"},
    ],
    "status": "Released",
    "tagline": "Entrez dans un nouveau monde.",
    "title": "Avatar",
    "video": False,
    "vote_average": 7.6,
    "vote_count": 27000,
    "credits": {
        "cast": [
            {"id": 17647, "name": "Sam Worthington", "character": "Jake Sully", "order": 0},
            {"id": 8691, "name": "Zoe Saldana", "character": "Neytiri", "order": 1},
            {"id": 10205, "name": "Sigourney Weaver", "character": "Dr. Grace Augustine", "order": 2},
            {"id": 32747, "name": "Stephen Lang", "character": "Colonel Miles Quaritch", "order": 3},
        ],
        "crew": [
            {"id": 2710, "name": "James Cameron", "job": "Director", "department": "Directing"},
            {"id": 2710, "name": "James Cameron", "job": "Writer", "department": "Writing"},
        ],
    },
}

# External IDs for Avatar (id=19995)
# GET /movie/19995/external_ids
TMDB_EXTERNAL_IDS_RESPONSE = {
    "id": 19995,
    "imdb_id": "tt0499549",
    "wikidata_id": "Q24817",
    "facebook_id": "officialavatar",
    "instagram_id": "avatar",
    "twitter_id": "officialavatar",
}

# Inception movie details for additional test cases
TMDB_MOVIE_DETAILS_INCEPTION = {
    "adult": False,
    "backdrop_path": "/8ZTVqvKDQ8emSGUEMjsS4yHAwrp.jpg",
    "budget": 160000000,
    "genres": [
        {"id": 28, "name": "Action"},
        {"id": 878, "name": "Science-Fiction"},
        {"id": 12, "name": "Aventure"},
    ],
    "homepage": "https://www.warnerbros.com/inception",
    "id": 27205,
    "imdb_id": "tt1375666",
    "original_language": "en",
    "original_title": "Inception",
    "overview": "Dom Cobb est un voleur expérimenté, le meilleur qui soit dans l'art périlleux de l'extraction...",
    "popularity": 156.78,
    "poster_path": "/9gk7adHYeDvHkCSEqAvQNLV5Uge.jpg",
    "release_date": "2010-07-16",
    "revenue": 836836967,
    "runtime": 148,  # minutes
    "status": "Released",
    "tagline": "Votre esprit est la scène du crime.",
    "title": "Inception",
    "video": False,
    "vote_average": 8.4,
    "vote_count": 32000,
}
