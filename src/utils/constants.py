"""
Constantes globales pour CineOrg.

Ce module contient toutes les constantes utilisees dans l'application:
- Extensions video supportees
- Patterns a ignorer lors du scan
- Hierarchie des genres (priorite pour le classement)
- Articles a ignorer pour le tri alphabetique
- Mapping des IDs de genre TMDB vers noms francais
"""

# Extensions video reconnues
VIDEO_EXTENSIONS = frozenset({
    ".mkv",
    ".mp4",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".ts",
    ".vob",
})

# Patterns a ignorer (sample, trailers, extras)
IGNORED_PATTERNS = frozenset({
    "sample",
    "trailer",
    "preview",
    "extras",
    "behind the scenes",
    "deleted scenes",
    "featurette",
    "interview",
    "bonus",
})

# Hierarchie des genres (ordre de priorite pour le classement)
# Animation > Science-Fiction > Fantastique > Horreur > Action > ...
GENRE_HIERARCHY = (
    "Animation",
    "Science-Fiction",
    "Fantastique",
    "Horreur",
    "Action",
    "Aventure",
    "Comedie",
    "Drame",
    "Thriller",
    "Crime",
    "Mystere",
    "Romance",
    "Guerre",
    "Histoire",
    "Musique",
    "Documentaire",
    "Famille",
    "Western",
    "Telefilm",
)

# Articles a ignorer pour le tri alphabetique (fr/en/de/es)
IGNORED_ARTICLES = frozenset({
    # Francais
    "le",
    "la",
    "les",
    "l'",
    "un",
    "une",
    "des",
    # Anglais
    "the",
    "a",
    "an",
    # Allemand
    "der",
    "die",
    "das",
    "ein",
    "eine",
    # Espagnol
    "el",
    "los",
    "las",
})

# Mapping des IDs de genre TMDB vers noms francais
# Source: https://api.themoviedb.org/3/genre/movie/list?language=fr-FR
# Ces mappings sont utilises comme fallback si l'API ne retourne pas
# les noms en francais (edge cases)
TMDB_GENRE_MAPPING = {
    28: "Action",
    12: "Aventure",
    16: "Animation",
    35: "Comedie",
    80: "Crime",
    99: "Documentaire",
    18: "Drame",
    10751: "Famille",
    14: "Fantastique",
    36: "Histoire",
    27: "Horreur",
    10402: "Musique",
    9648: "Mystere",
    10749: "Romance",
    878: "Science-Fiction",
    10770: "Telefilm",
    53: "Thriller",
    10752: "Guerre",
    37: "Western",
}
