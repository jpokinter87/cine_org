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

# Mapping des genres TMDB/internes vers les noms de repertoires existants
# Permet de matcher les genres retournes par l'API avec la structure de dossiers
GENRE_FOLDER_MAPPING = {
    # Genres TMDB en francais
    "action": "Action & Aventure",
    "aventure": "Action & Aventure",
    "animation": "Animation",
    "comédie": "Comédie",
    "comedie": "Comédie",
    "crime": "Policier",
    "documentaire": "Documentaire",
    "drame": "Drame",
    "famille": "Films pour enfants",
    "fantastique": "Fantastique",
    "histoire": "Historique",
    "horreur": "Horreur",
    "musique": "Comédie dramatique",
    "mystère": "Thriller",
    "mystere": "Thriller",
    "romance": "Comédie dramatique",
    "science-fiction": "SF",
    "téléfilm": "Drame",
    "telefilm": "Drame",
    "thriller": "Thriller",
    "guerre": "Guerre & espionnage",
    "western": "Western",
    # Genres TMDB en anglais (fallback)
    "action & adventure": "Action & Aventure",
    "sci-fi & fantasy": "SF",
    "science fiction": "SF",
    "war": "Guerre & espionnage",
    "war & politics": "Guerre & espionnage",
    "mystery": "Thriller",
    "horror": "Horreur",
    "comedy": "Comédie",
    "drama": "Drame",
    "fantasy": "Fantastique",
    "kids": "Films pour enfants",
    "family": "Films pour enfants",
    "history": "Historique",
    "documentary": "Documentaire",
    # Valeur par defaut
    "divers": "Drame",
}
