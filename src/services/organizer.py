"""
Service d'organisation des fichiers médias.

Ce module fournit les fonctions de calcul des chemins de destination
pour les films et séries TV selon leur structure organisationnelle.

Structure films : stockage/Films/Genre/Lettre/
Structure séries : stockage/Series/Lettre/Titre (Annee)/Saison XX/
"""

from dataclasses import dataclass
from pathlib import Path

from src.core.entities.media import Movie, Series
from src.utils.constants import IGNORED_ARTICLES, GENRE_HIERARCHY


@dataclass(frozen=True)
class SubdivisionRange:
    """
    Plage de subdivision alphabétique.

    Représente une plage de lettres pour subdiviser les répertoires
    contenant trop de fichiers (ex: A-C, D-F).

    Attributs :
        start: Première lettre de la plage.
        end: Dernière lettre de la plage.
    """

    start: str
    end: str

    @property
    def label(self) -> str:
        """Retourne le libellé de la plage (ex: 'A-C')."""
        return f"{self.start}-{self.end}"


def _strip_article(title: str) -> str:
    """
    Retire l'article initial d'un titre.

    Gère les articles français, anglais, allemands et espagnols.
    Gère également l'apostrophe (L'Odyssée -> Odyssée).

    Args:
        title: Titre complet.

    Returns:
        Titre sans l'article initial.
    """
    if not title:
        return title

    # Conversion en minuscules pour la comparaison
    title_lower = title.lower()

    # Cas spécial de l'apostrophe (L'Odyssée, L'Amour, etc.)
    for article in IGNORED_ARTICLES:
        if article.endswith("'"):
            # Articles avec apostrophe (l', d')
            if title_lower.startswith(article):
                rest = title[len(article):]
                if rest:  # S'assurer qu'il reste quelque chose
                    return rest

    # Articles standards (séparés par espace)
    words = title.split(None, 1)  # Split en max 2 parties
    if len(words) >= 2:
        first_word = words[0].lower()
        if first_word in IGNORED_ARTICLES:
            return words[1]

    # Pas d'article trouvé, retourner le titre original
    return title


def get_sort_letter(title: str) -> str:
    """
    Extrait la lettre de tri d'un titre.

    Ignore les articles (Le, La, The, etc.) et retourne
    la première lettre significative en majuscule.
    Les titres commençant par un chiffre ou caractère spécial
    retournent '#'.

    Args:
        title: Titre du film ou de la série.

    Returns:
        Lettre de tri en majuscule, ou '#' pour les numériques/spéciaux.
    """
    if not title:
        return "#"

    # Retirer l'article initial
    stripped = _strip_article(title)

    # Si le titre est maintenant vide (titre = article seul), utiliser l'original
    if not stripped:
        stripped = title

    # Première lettre après suppression des espaces initiaux
    first_char = stripped.lstrip()[0] if stripped.strip() else "#"

    # Vérifier si c'est une lettre
    if first_char.isalpha():
        return first_char.upper()

    # Chiffres et caractères spéciaux -> #
    return "#"


def get_priority_genre(genres: tuple[str, ...]) -> str:
    """
    Sélectionne le genre prioritaire selon la hiérarchie.

    La hiérarchie est définie dans GENRE_HIERARCHY (constants.py) :
    Animation > Science-Fiction > Fantastique > Horreur > Action > ...

    Args:
        genres: Tuple des genres du film.

    Returns:
        Genre prioritaire ou 'Divers' si vide.
    """
    if not genres:
        return "Divers"

    # Chercher le premier genre dans la hiérarchie
    for priority_genre in GENRE_HIERARCHY:
        if priority_genre in genres:
            return priority_genre

    # Aucun genre de la hiérarchie trouvé, retourner le premier
    return genres[0]


def get_movie_destination(movie: Movie, storage_dir: Path) -> Path:
    """
    Calcule le chemin de destination pour un film.

    Structure : stockage/Films/Genre/Lettre/

    Args:
        movie: Métadonnées du film.
        storage_dir: Répertoire racine de stockage.

    Returns:
        Chemin de destination (répertoire, pas le fichier).
    """
    # Genre prioritaire
    genre = get_priority_genre(movie.genres)

    # Lettre de tri
    letter = get_sort_letter(movie.title)

    # Construction du chemin
    return storage_dir / "Films" / genre / letter


def get_series_destination(
    series: Series,
    season_number: int,
    storage_dir: Path,
) -> Path:
    """
    Calcule le chemin de destination pour un épisode de série.

    Structure : stockage/Series/Lettre/Titre (Annee)/Saison XX/

    Args:
        series: Métadonnées de la série.
        season_number: Numéro de saison.
        storage_dir: Répertoire racine de stockage.

    Returns:
        Chemin de destination (répertoire, pas le fichier).
    """
    # Lettre de tri
    letter = get_sort_letter(series.title)

    # Dossier de la série
    if series.year:
        series_folder = f"{series.title} ({series.year})"
    else:
        series_folder = series.title

    # Dossier de la saison
    season_folder = f"Saison {season_number:02d}"

    # Construction du chemin
    return storage_dir / "Series" / letter / series_folder / season_folder


class OrganizerService:
    """
    Service d'organisation des fichiers médias.

    Fournit les méthodes de haut niveau pour calculer les chemins
    de destination des films et séries.

    Ce service est sans état et peut être utilisé comme singleton.
    """

    def get_movie_destination(self, movie: Movie, storage_dir: Path) -> Path:
        """
        Calcule le chemin de destination pour un film.

        Voir get_movie_destination() pour les détails.
        """
        return get_movie_destination(movie, storage_dir)

    def get_series_destination(
        self,
        series: Series,
        season_number: int,
        storage_dir: Path,
    ) -> Path:
        """
        Calcule le chemin de destination pour un épisode de série.

        Voir get_series_destination() pour les détails.
        """
        return get_series_destination(series, season_number, storage_dir)

    def get_sort_letter(self, title: str) -> str:
        """
        Extrait la lettre de tri d'un titre.

        Voir get_sort_letter() pour les détails.
        """
        return get_sort_letter(title)

    def get_priority_genre(self, genres: tuple[str, ...]) -> str:
        """
        Sélectionne le genre prioritaire.

        Voir get_priority_genre() pour les détails.
        """
        return get_priority_genre(genres)
