"""
Reponses TVDB API v4 simulees pour les tests.

Ces fixtures reproduisent la forme reelle des reponses de l'API v4
(enveloppe ``{"status": ..., "data": ...}``), capturees depuis l'API
de production pour la serie Breaking Bad (id 81189).

Reference API: https://thetvdb.github.io/v4-api/
"""

TVDB_LOGIN_RESPONSE = {
    "status": "success",
    "data": {
        "token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJhcGlrZXkiOiJ0ZXN0LWFwaS1rZXkifQ.test-signature"
    },
}

TVDB_SEARCH_RESPONSE = {
    "status": "success",
    "data": [
        {
            "objectID": "series-81189",
            "id": "series-81189",
            "tvdb_id": "81189",
            "name": "Breaking Bad",
            "name_translated": "Breaking Bad",
            "overview": "Walter White, a high school chemistry teacher...",
            "first_air_time": "2008-01-20",
            "year": "2008",
            "primary_language": "eng",
            "network": "AMC",
            "type": "series",
            "aliases": ["Ruptura Total"],
            "image_url": "https://artworks.thetvdb.com/banners/posters/81189-10.jpg",
        },
        {
            "objectID": "series-273181",
            "id": "series-273181",
            "tvdb_id": "273181",
            "name": "Metastasis",
            "name_translated": None,
            "overview": "Colombian adaptation of Breaking Bad...",
            "first_air_time": "2014-06-09",
            "year": "2014",
            "primary_language": "spa",
            "network": "Univision",
            "type": "series",
            "aliases": ["Breaking Bad (Metastasis)"],
            "image_url": "https://artworks.thetvdb.com/banners/posters/273181-1.jpg",
        },
    ],
}

TVDB_SEARCH_EMPTY_RESPONSE = {"status": "success", "data": []}

# Serie dont le titre francais differe du titre original : la traduction
# vit dans le dictionnaire ``translations`` (langue ISO-639-3 -> titre).
TVDB_SEARCH_TRANSLATED_RESPONSE = {
    "status": "success",
    "data": [
        {
            "objectID": "series-321239",
            "id": "series-321239",
            "tvdb_id": "321239",
            "name": "The Handmaid's Tale",
            "name_translated": None,
            "first_air_time": "2017-04-26",
            "year": "2017",
            "primary_language": "eng",
            "type": "series",
            "translations": {
                "eng": "The Handmaid's Tale",
                "fra": "The Handmaid's Tale : La Servante ecarlate",
                "deu": "The Handmaid's Tale - Der Report der Magd",
            },
        }
    ],
}

TVDB_SERIES_EXTENDED_RESPONSE = {
    "status": "success",
    "data": {
        "id": 81189,
        "name": "Breaking Bad",
        "slug": "breaking-bad",
        "image": "https://artworks.thetvdb.com/banners/posters/81189-10.jpg",
        "firstAired": "2008-01-20",
        "lastAired": "2013-09-29",
        "year": "2008",
        "originalLanguage": "eng",
        "originalCountry": "usa",
        "averageRuntime": 48,
        "defaultSeasonType": 1,
        "status": {"id": 2, "name": "Ended"},
        "genres": [
            {"id": 12, "name": "Drama", "slug": "drama"},
            {"id": 14, "name": "Crime", "slug": "crime"},
            {"id": 24, "name": "Thriller", "slug": "thriller"},
        ],
        "aliases": [
            {"language": "eng", "name": "Breaking Bad: Original Minisodes"},
            {"language": "ita", "name": "Breaking Bad - Reazioni collaterali"},
        ],
        "overview": "Walter White, a struggling high school chemistry teacher...",
        "nameTranslations": ["eng", "fra", "spa"],
        "overviewTranslations": ["eng", "fra"],
    },
}

TVDB_SERIES_TRANSLATION_FRA_RESPONSE = {
    "status": "success",
    "data": {
        "name": "Breaking Bad",
        "overview": (
            "La vie de Walter White, professeur de chimie dans un lycee, est "
            "bouleversee lorsqu'il apprend qu'il est atteint d'un cancer."
        ),
        "language": "fra",
    },
}

TVDB_SERIES_TRANSLATION_ENG_RESPONSE = {
    "status": "success",
    "data": {
        "name": "Breaking Bad",
        "overview": "Walter White, a struggling high school chemistry teacher...",
        "language": "eng",
    },
}

# Serie complete : 2 specials (saison 0) + 7 episodes saison 1 + 13 saison 2.
# Reproduit le fait que /episodes/{season-type}/{lang} renvoie TOUTES les
# saisons en une seule reponse, specials inclus.
TVDB_SERIES_EPISODES_FRA_RESPONSE = {
    "status": "success",
    "data": {
        "id": 81189,
        "name": "Breaking Bad",
        "episodes": [
            # Specials : titres non traduits en francais (name a None)
            {
                "id": 4130001,
                "seriesId": 81189,
                "name": None,
                "overview": None,
                "number": 1,
                "seasonNumber": 0,
                "aired": "2009-02-17",
            },
            {
                "id": 4130002,
                "seriesId": 81189,
                "name": None,
                "overview": None,
                "number": 2,
                "seasonNumber": 0,
                "aired": "2009-02-24",
            },
            # Saison 1 : 7 episodes traduits
            {
                "id": 349232,
                "seriesId": 81189,
                "name": "Chute libre",
                "overview": "Walter White apprend qu'il est atteint d'un cancer.",
                "number": 1,
                "seasonNumber": 1,
                "aired": "2008-01-20",
            },
            {
                "id": 349233,
                "seriesId": 81189,
                "name": "Le choix",
                "overview": "Walter et Jesse doivent se debarrasser des corps.",
                "number": 2,
                "seasonNumber": 1,
                "aired": "2008-01-27",
            },
            {
                "id": 349234,
                "seriesId": 81189,
                "name": "Derapage",
                "overview": None,
                "number": 3,
                "seasonNumber": 1,
                "aired": "2008-02-10",
            },
            {
                "id": 349235,
                "seriesId": 81189,
                "name": "Retour aux sources",
                "overview": None,
                "number": 4,
                "seasonNumber": 1,
                "aired": "2008-02-17",
            },
            {
                "id": 349236,
                "seriesId": 81189,
                "name": "Vivre ou survivre",
                "overview": None,
                "number": 5,
                "seasonNumber": 1,
                "aired": "2008-02-24",
            },
            {
                "id": 349237,
                "seriesId": 81189,
                "name": "Bluff",
                "overview": None,
                "number": 6,
                "seasonNumber": 1,
                "aired": "2008-03-02",
            },
            # Episode sans traduction francaise : doit basculer sur l'anglais
            {
                "id": 349238,
                "seriesId": 81189,
                "name": "",
                "overview": None,
                "number": 7,
                "seasonNumber": 1,
                "aired": "2008-03-09",
            },
        ]
        + [
            {
                "id": 349300 + i,
                "seriesId": 81189,
                "name": f"Episode {i}",
                "overview": None,
                "number": i,
                "seasonNumber": 2,
                "aired": "2009-03-08",
            }
            for i in range(1, 14)
        ],
    },
    "links": {
        "prev": None,
        "self": "https://api4.thetvdb.com/v4/series/81189/episodes/default/fra?page=0",
        "next": None,
        "total_items": 22,
        "page_size": 500,
    },
}

TVDB_SERIES_EPISODES_ENG_RESPONSE = {
    "status": "success",
    "data": {
        "id": 81189,
        "name": "Breaking Bad",
        "episodes": [
            {
                "id": 4130001,
                "seriesId": 81189,
                "name": "Good Cop / Bad Cop",
                "overview": "A minisode.",
                "number": 1,
                "seasonNumber": 0,
                "aired": "2009-02-17",
            },
            {
                "id": 4130002,
                "seriesId": 81189,
                "name": "Wedding Day",
                "overview": None,
                "number": 2,
                "seasonNumber": 0,
                "aired": "2009-02-24",
            },
        ]
        + [
            {
                "id": 349231 + i,
                "seriesId": 81189,
                "name": f"English title {i}",
                "overview": f"English overview {i}",
                "number": i,
                "seasonNumber": 1,
                "aired": "2008-01-20",
            }
            for i in range(1, 8)
        ]
        + [
            {
                "id": 349300 + i,
                "seriesId": 81189,
                "name": f"English S02 title {i}",
                "overview": None,
                "number": i,
                "seasonNumber": 2,
                "aired": "2009-03-08",
            }
            for i in range(1, 14)
        ],
    },
    "links": {
        "prev": None,
        "self": "https://api4.thetvdb.com/v4/series/81189/episodes/default/eng?page=0",
        "next": None,
        "total_items": 22,
        "page_size": 500,
    },
}

# Pagination : une serie dont les episodes s'etalent sur deux pages.
TVDB_SERIES_EPISODES_PAGE0_RESPONSE = {
    "status": "success",
    "data": {
        "id": 81189,
        "name": "Breaking Bad",
        "episodes": [
            {
                "id": 500000 + i,
                "seriesId": 81189,
                "name": f"Episode {i}",
                "overview": None,
                "number": i,
                "seasonNumber": 1,
                "aired": "2008-01-20",
            }
            for i in range(1, 501)
        ],
    },
    "links": {
        "prev": None,
        "self": "https://api4.thetvdb.com/v4/series/81189/episodes/default/fra?page=0",
        "next": "https://api4.thetvdb.com/v4/series/81189/episodes/default/fra?page=1",
        "total_items": 520,
        "page_size": 500,
    },
}

TVDB_SERIES_EPISODES_PAGE1_RESPONSE = {
    "status": "success",
    "data": {
        "id": 81189,
        "name": "Breaking Bad",
        "episodes": [
            {
                "id": 500500 + i,
                "seriesId": 81189,
                "name": f"Episode {500 + i}",
                "overview": None,
                "number": 500 + i,
                "seasonNumber": 1,
                "aired": "2008-01-20",
            }
            for i in range(1, 21)
        ],
    },
    "links": {
        "prev": "https://api4.thetvdb.com/v4/series/81189/episodes/default/fra?page=0",
        "self": "https://api4.thetvdb.com/v4/series/81189/episodes/default/fra?page=1",
        "next": None,
        "total_items": 520,
        "page_size": 500,
    },
}

TVDB_REMOTE_ID_RESPONSE = {
    "status": "success",
    "data": [
        {
            "series": {
                "id": 81189,
                "name": "Breaking Bad",
                "slug": "breaking-bad",
                "year": "2008",
            }
        }
    ],
}

TVDB_REMOTE_ID_EMPTY_RESPONSE = {"status": "success", "data": []}

TVDB_NOT_FOUND_RESPONSE = {
    "status": "failure",
    "message": "Resource not found",
    "data": None,
}

# Alias historique conserve : plusieurs tests referencent encore ce nom.
TVDB_SERIES_NOT_FOUND_RESPONSE = TVDB_NOT_FOUND_RESPONSE
