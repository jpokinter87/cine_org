"""
Service d'organisation des fichiers médias.

Ce module fournit les fonctions de calcul des chemins de destination
pour les films et séries TV en naviguant dans la structure existante.

La logique principale est de DESCENDRE dans l'arborescence existante
pour trouver le répertoire approprié, plutôt que de construire un chemin
théorique. Cela garantit la compatibilité avec la structure en place.

Structure films : video/Films/Genre/[subdivisions lettres]/
Structure séries : video/Séries/{Type}/[subdivision lettres]/Titre (Annee)/Saison XX/
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.core.entities.media import Movie, Series
from src.utils.constants import GENRE_HIERARCHY, GENRE_FOLDER_MAPPING
from src.utils.helpers import strip_article as _strip_article  # noqa: F401


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


def _strip_invisible_chars(text: str) -> str:
    """
    Retire les caractères Unicode invisibles d'une chaîne.

    Supprime les caractères de contrôle, les marques directionnelles,
    et autres caractères invisibles qui peuvent provenir des APIs.

    Args:
        text: Texte potentiellement contaminé par des caractères invisibles.

    Returns:
        Texte nettoyé.
    """
    import unicodedata

    result = []
    for char in text:
        category = unicodedata.category(char)
        # Filtrer les catégories de caractères invisibles :
        # Cf = Format (LRM, RLM, BOM, etc.)
        # Cc = Control
        # Mn = Nonspacing Mark (certains accents combinants indésirables seuls)
        # Zs = Space Separator (mais on garde l'espace normal U+0020)
        if category in ("Cf", "Cc"):
            continue
        # Soft hyphen (U+00AD) est en catégorie Cf, déjà filtré
        result.append(char)
    return "".join(result)


def get_sort_letter(title: str) -> str:
    """
    Extrait la lettre de tri d'un titre.

    Ignore les articles (Le, La, The, etc.) et retourne
    la première lettre significative en majuscule.
    Les titres commençant par un chiffre ou caractère spécial
    retournent '#'.

    Nettoie également les caractères Unicode invisibles qui peuvent
    provenir des APIs (LRM, RLM, BOM, etc.).

    Args:
        title: Titre du film ou de la série.

    Returns:
        Lettre de tri en majuscule, ou '#' pour les numériques/spéciaux.
    """
    if not title:
        return "#"

    # Nettoyer les caractères invisibles Unicode
    title = _strip_invisible_chars(title)

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


def _map_genre_to_folder(genre: str) -> str:
    """
    Mappe un genre TMDB vers le nom de répertoire existant.

    Args:
        genre: Genre retourné par TMDB (en français ou anglais).

    Returns:
        Nom du répertoire correspondant dans la structure existante.
    """
    genre_lower = genre.lower()
    return GENRE_FOLDER_MAPPING.get(genre_lower, "Drame")


def _is_range_dir(name: str) -> bool:
    """
    Vérifie si un nom de répertoire est une plage alphabétique.

    Reconnaît les formats : A-G, Ba-Bi, Mab-Man, etc.
    Exclut les mots composés (Au-delà), les lettres simples (A),
    et les noms sans tiret (American).

    Args:
        name: Nom du répertoire.

    Returns:
        True si le nom est une plage alphabétique.
    """
    if "-" not in name:
        return False
    parts = name.split("-")
    if len(parts) != 2:
        return False
    return all(len(p) <= 3 and p.isalpha() for p in parts)


def _title_matches_prefix_dir(title: str, dir_name: str) -> bool:
    """
    Vérifie si un titre correspond à un répertoire de regroupement par préfixe.

    Exclut les lettres simples (A, B) et les plages alphabétiques (Ba-Bi).
    Strippe l'article du titre avant comparaison.

    Args:
        title: Titre complet du film/série.
        dir_name: Nom du répertoire candidat.

    Returns:
        True si le titre strippé commence par dir_name.
    """
    if not title or not dir_name:
        return False

    # Exclure les lettres simples
    if len(dir_name) <= 1:
        return False

    # Exclure les plages alphabétiques
    if _is_range_dir(dir_name):
        return False

    # Stripper l'article du titre
    stripped = _strip_article(title).strip()
    if not stripped:
        return False

    # Comparaison insensible à la casse
    return stripped.upper().startswith(dir_name.upper())


def _letter_matches_range(letter: str, range_name: str) -> bool:
    """
    Vérifie si une lettre correspond à une plage de répertoire.

    Gère UNIQUEMENT les formats de lettres simples :
    - Lettre simple : "A", "B", "#"
    - Plage de lettres simples : "A-I", "J-Z", "Sa-So", "Di-Dz"

    NE GÈRE PAS les plages de préfixes (Mab-Man, Mo-My, etc.)
    qui doivent être traitées par _title_matches_range().

    Args:
        letter: Lettre de tri du titre (majuscule).
        range_name: Nom du répertoire (ex: "A-I", "Sa-So", "B").

    Returns:
        True si la lettre est dans la plage de lettres simples.
    """
    if not range_name:
        return False

    # Cas spécial : # pour les numériques
    if letter == "#":
        return range_name == "#"

    range_upper = range_name.upper()
    letter_upper = letter.upper()

    # Lettre simple exacte
    if len(range_upper) == 1:
        return letter_upper == range_upper

    # Plage de lettres simples (A-I, J-Z, Sa-So, Di-Dz, etc.)
    # NE PAS matcher les plages de préfixes (Mab-Man, Mo-My, etc.)
    if "-" in range_name:
        parts = range_upper.split("-")
        if len(parts) == 2:
            start_part, end_part = parts[0], parts[1]
            # Une plage de lettres simples a des parties de 1-2 caractères max
            # Si une partie a plus de 2 caractères, c'est une plage de préfixes
            # -> ne pas matcher ici, laisser _title_matches_range() gérer
            if len(start_part) > 2 or len(end_part) > 2:
                return False
            # Extraire la première lettre de chaque partie
            # Sa-So -> S à S, Di-Dz -> D à D
            start_letter = start_part[0] if start_part else ""
            end_letter = end_part[0] if end_part else ""
            # Vérifier que les parties sont alphabétiques
            if not (start_letter.isalpha() and end_letter.isalpha()):
                return False
            # Plage de lettres simples (ex: A-I, Sa-So)
            return start_letter <= letter_upper <= end_letter

    return False


def _title_matches_range(title: str, range_name: str) -> bool:
    """
    Vérifie si un titre correspond à une plage de répertoire.

    Gère les préfixes de plusieurs lettres (Ba-Bi, Me-My, etc.)
    et les mots-clés (Amour, Homme, etc.).

    Args:
        title: Titre complet (après suppression de l'article).
        range_name: Nom du répertoire.

    Returns:
        True si le titre correspond à la plage.
    """
    if not title or not range_name:
        return False

    # Nettoyer les caractères invisibles Unicode (LRM, RLM, BOM, etc.)
    title = _strip_invisible_chars(title)

    title_stripped = _strip_article(title).strip()
    if not title_stripped:
        return False

    title_upper = title_stripped.upper()
    range_upper = range_name.upper()

    # Cas spécial : # pour les numériques/spéciaux
    if range_name == "#":
        first_char = title_upper[0] if title_upper else ""
        return not first_char.isalpha()

    # Plage de préfixes (Ba-Bi, Me-My, Sh-Sy)
    if "-" in range_name and len(range_name) > 3:
        parts = range_upper.split("-")
        if len(parts) == 2:
            start_prefix = parts[0]
            end_prefix = parts[1]
            # Le titre doit commencer par un préfixe dans la plage
            # Utiliser la longueur max pour gérer les plages asymétriques (A-Ami)
            prefix_len = max(len(start_prefix), len(end_prefix))
            title_prefix = title_upper[:prefix_len]
            return start_prefix <= title_prefix <= end_prefix + "Z" * 10

    # Lettre ou plage simple
    first_letter = title_upper[0] if title_upper else ""
    return _letter_matches_range(first_letter, range_name)


def _find_matching_subdir(parent: Path, title: str) -> Optional[Path]:
    """
    Trouve le sous-répertoire correspondant à un titre.

    Parcourt les sous-répertoires du parent et retourne celui
    qui correspond au titre (par lettre ou plage).
    Préfère les plages (Sa-So) aux lettres simples (S) pour
    naviguer jusqu'aux feuilles de l'arborescence.

    Args:
        parent: Répertoire parent à explorer.
        title: Titre pour le matching.

    Returns:
        Chemin du sous-répertoire correspondant, ou None si non trouvé.
    """
    if not parent.exists() or not parent.is_dir():
        return None

    letter = get_sort_letter(title)

    # Premier passage : chercher les plages (plus spécifiques)
    for subdir in sorted(parent.iterdir()):
        if not subdir.is_dir():
            continue

        # Préférer les plages de préfixes (Sa-So, Di-Dz, etc.)
        if _title_matches_range(title, subdir.name):
            return subdir

    # Deuxième passage : chercher les répertoires de préfixe de titre
    for subdir in sorted(parent.iterdir()):
        if not subdir.is_dir():
            continue

        if _title_matches_prefix_dir(title, subdir.name):
            return subdir

    # Troisième passage : chercher les lettres simples (fallback)
    for subdir in sorted(parent.iterdir()):
        if not subdir.is_dir():
            continue

        # Lettre simple exacte (S, D, etc.)
        if _letter_matches_range(letter, subdir.name):
            return subdir

    return None


def _navigate_to_leaf(start_dir: Path, title: str) -> Path:
    """
    Navigue dans l'arborescence jusqu'au répertoire feuille.

    Descend récursivement dans les sous-répertoires en matchant
    le titre jusqu'à trouver un répertoire sans sous-répertoire
    de subdivision (feuille).

    Args:
        start_dir: Répertoire de départ.
        title: Titre pour guider la navigation.

    Returns:
        Chemin du répertoire feuille approprié.
    """
    current = start_dir

    while True:
        # Chercher un sous-répertoire correspondant
        matching = _find_matching_subdir(current, title)

        if matching is None:
            # Aucun sous-répertoire ne correspond, on est à la feuille
            # ou le répertoire n'existe pas encore
            break

        # Vérifier si on est entré dans un répertoire de contenu (films/séries)
        #而不是 un répertoire de subdivision (lettres/plages)
        # Un répertoire de contenu a généralement un nom long (titre)
        # et peut contenir des fichiers médias
        has_media_files = any(
            f.suffix.lower() in (".mkv", ".mp4", ".avi", ".mov", ".m4v")
            for f in matching.iterdir() if f.is_file()
        )

        # Heuristique : si le nom ressemble à un titre de film/série
        # (long, sans tiret de plage), on s'arrête
        name_looks_like_content = (
            len(matching.name) > 10  # Titres généralement plus longs que "A-C" ou "Di-Dz"
            and "-" not in matching.name[:10]  # Pas de plage au début
        )

        if name_looks_like_content or has_media_files:
            # On est dans un répertoire de contenu, pas une subdivision
            current = matching
            break

        current = matching

    return current


def get_movie_destination(movie: Movie, storage_dir: Path, video_dir: Path) -> Path:
    """
    Calcule le chemin de destination pour un film dans storage.

    La structure est dictée par la zone symlinks (video_dir).
    On navigue dans video_dir pour trouver le chemin correct,
    puis on retourne l'équivalent dans storage_dir.

    Structure : storage/Films/Genre/[subdivisions lettres]/

    Args:
        movie: Métadonnées du film.
        storage_dir: Répertoire racine de stockage.
        video_dir: Répertoire racine des symlinks (structure maître).

    Returns:
        Chemin de destination (répertoire, pas le fichier).
    """
    # Naviguer dans video_dir pour déterminer le chemin
    video_path = get_movie_video_destination(movie, video_dir)

    # Convertir le chemin video en chemin storage
    # video_path est relatif à video_dir, on le transpose vers storage_dir
    relative_path = video_path.relative_to(video_dir)
    return storage_dir / relative_path


def get_movie_video_destination(movie: Movie, video_dir: Path) -> Path:
    """
    Calcule le chemin de symlink pour un film.

    Navigue dans la structure existante :
    video/Films/Genre/[subdivisions lettres]/

    Args:
        movie: Métadonnées du film (avec genres).
        video_dir: Répertoire racine des symlinks.

    Returns:
        Chemin de destination pour le symlink.
    """
    # Genre prioritaire et mapping vers nom de dossier
    priority_genre = get_priority_genre(movie.genres)
    genre_folder = _map_genre_to_folder(priority_genre)

    # Point de départ : video/Films/Genre
    genre_dir = video_dir / "Films" / genre_folder

    # Si le répertoire genre n'existe pas, le créer avec la lettre
    if not genre_dir.exists():
        letter = get_sort_letter(movie.title)
        return genre_dir / letter

    # Naviguer dans les subdivisions jusqu'à la feuille
    return _navigate_to_leaf(genre_dir, movie.title)


def get_series_type(genres: tuple[str, ...]) -> str:
    """
    Determine le type de serie selon les genres.

    Classification:
    - "Anime" dans les genres -> "Mangas" (animation japonaise)
    - "Animation" dans les genres -> "Animation" (animation occidentale)
    - Autre -> "Séries TV"

    Args:
        genres: Tuple des genres de la serie.

    Returns:
        Type de serie: "Mangas", "Animation" ou "Séries TV"
    """
    if not genres:
        return "Séries TV"

    # Normaliser les genres en minuscules pour la comparaison
    genres_lower = [g.lower() for g in genres]

    # Anime (japonais) -> Mangas
    if "anime" in genres_lower:
        return "Mangas"

    # Animation (occidentale) -> Animation
    if "animation" in genres_lower:
        return "Animation"

    # Tout le reste -> Séries TV
    return "Séries TV"


def get_series_destination(
    series: Series,
    season_number: int,
    storage_dir: Path,
    video_dir: Path,
) -> Path:
    """
    Calcule le chemin de destination pour un épisode de série dans storage.

    La structure est dictée par la zone symlinks (video_dir).
    On navigue dans video_dir pour trouver le chemin correct,
    puis on retourne l'équivalent dans storage_dir.

    Structure : storage/Séries/{Type}/[subdivision lettres]/Titre (Annee)/Saison XX/

    Args:
        series: Métadonnées de la série.
        season_number: Numéro de saison.
        storage_dir: Répertoire racine de stockage.
        video_dir: Répertoire racine des symlinks (structure maître).

    Returns:
        Chemin de destination (répertoire, pas le fichier).
    """
    # Naviguer dans video_dir pour déterminer le chemin
    video_path = get_series_video_destination(series, season_number, video_dir)

    # Convertir le chemin video en chemin storage
    relative_path = video_path.relative_to(video_dir)
    return storage_dir / relative_path


def get_series_video_destination(
    series: Series,
    season_number: int,
    video_dir: Path,
) -> Path:
    """
    Calcule le chemin de symlink pour un épisode de série.

    Navigue dans la structure existante :
    video/Séries/{Type}/[subdivision lettres]/Titre (Annee)/Saison XX/

    Args:
        series: Métadonnées de la série (avec genres).
        season_number: Numéro de saison.
        video_dir: Répertoire racine des symlinks.

    Returns:
        Chemin de destination pour le symlink.
    """
    # Type de série basé sur les genres
    series_type = get_series_type(series.genres)

    # Dossier de la série
    if series.year:
        series_folder = f"{series.title} ({series.year})"
    else:
        series_folder = series.title

    # Dossier de la saison
    season_folder = f"Saison {season_number:02d}"

    # Point de départ : video/Séries/Type
    type_dir = video_dir / "Séries" / series_type

    # Si le répertoire type n'existe pas, utiliser la lettre simple
    if not type_dir.exists():
        letter = get_sort_letter(series.title)
        return type_dir / letter / series_folder / season_folder

    # Naviguer récursivement jusqu'à la bonne subdivision
    letter_dir = _navigate_to_leaf(type_dir, series.title)

    # Retourner le chemin complet
    return letter_dir / series_folder / season_folder


class OrganizerService:
    """
    Service d'organisation des fichiers médias.

    Fournit les méthodes de haut niveau pour calculer les chemins
    de destination des films et séries.

    Ce service est sans état et peut être utilisé comme singleton.
    """

    def get_movie_destination(self, movie: Movie, storage_dir: Path, video_dir: Path) -> Path:
        """
        Calcule le chemin de destination pour un film dans storage.

        Voir get_movie_destination() pour les détails.
        """
        return get_movie_destination(movie, storage_dir, video_dir)

    def get_movie_video_destination(self, movie: Movie, video_dir: Path) -> Path:
        """
        Calcule le chemin de symlink pour un film.

        Voir get_movie_video_destination() pour les détails.
        """
        return get_movie_video_destination(movie, video_dir)

    def get_series_destination(
        self,
        series: Series,
        season_number: int,
        storage_dir: Path,
        video_dir: Path,
    ) -> Path:
        """
        Calcule le chemin de destination pour un épisode de série.

        Voir get_series_destination() pour les détails.
        """
        return get_series_destination(series, season_number, storage_dir, video_dir)

    def get_series_video_destination(
        self,
        series: Series,
        season_number: int,
        video_dir: Path,
    ) -> Path:
        """
        Calcule le chemin de symlink pour un épisode de série.

        Voir get_series_video_destination() pour les détails.
        """
        return get_series_video_destination(series, season_number, video_dir)

    def get_series_type(self, genres: tuple[str, ...]) -> str:
        """
        Détermine le type de série selon les genres.

        Voir get_series_type() pour les détails.
        """
        return get_series_type(genres)

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
