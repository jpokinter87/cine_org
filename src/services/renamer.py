"""
Service de renommage des fichiers médias.

Ce module fournit les fonctions de génération de noms de fichiers
standardisés pour les films et séries TV.

Format films : Titre (Année) Langue Codec Résolution.ext
Format séries : Titre (Année) - SxxExx - TitreEpisode - Langue Codec Résolution.ext
"""

import unicodedata
from typing import Optional

from pathvalidate import sanitize_filename

from src.core.entities.media import Movie, Series, Episode
from src.core.value_objects.media_info import MediaInfo


# Longueur maximale du nom de fichier (hors extension)
MAX_FILENAME_LENGTH = 200

# Caractères spéciaux à remplacer par un tiret
# Note: pathvalidate gère déjà / \ : * " < > |
# Mais on veut un remplacement explicite par tiret
SPECIAL_CHARS_TO_DASH = frozenset({":", "/", "\\", "*", '"', "<", ">", "|"})

# Placeholder temporaire pour préserver les points de suspension
# Utilise des caractères Unicode rares qui ne seront pas dans un nom de fichier
_ELLIPSIS_PLACEHOLDER = "\u2026"  # Caractère ellipse Unicode ...


def _normalize_ligatures(text: str) -> str:
    """
    Normalise les ligatures françaises.

    Remplace:
    - œ (U+0153) par 'oe'
    - Œ (U+0152) par 'Oe'
    - æ (U+00E6) par 'ae'
    - Æ (U+00C6) par 'Ae'

    Args:
        text: Texte à normaliser.

    Returns:
        Texte avec ligatures remplacées.
    """
    # Remplacement des ligatures avant normalisation NFKC
    # (NFKC ne fait pas ces remplacements)
    replacements = {
        "\u0153": "oe",  # œ -> oe
        "\u0152": "Oe",  # Œ -> Oe
        "\u00e6": "ae",  # æ -> ae
        "\u00c6": "Ae",  # Æ -> Ae
    }
    for ligature, replacement in replacements.items():
        text = text.replace(ligature, replacement)
    return text


def sanitize_for_filesystem(text: str) -> str:
    """
    Nettoie une chaîne pour l'utiliser comme nom de fichier.

    Transformations appliquées :
    - Normalisation Unicode NFKC
    - Remplacement des ligatures (œ->oe, æ->ae)
    - Caractères spéciaux (: / \\ * " < > |) -> tiret
    - Point d'interrogation (?) -> points de suspension (...)
    - Troncature à 200 caractères maximum

    Args:
        text: Texte à nettoyer.

    Returns:
        Texte valide pour un nom de fichier.
    """
    if not text:
        return ""

    # Normalisation Unicode NFKC (compatibilité)
    text = unicodedata.normalize("NFKC", text)

    # Normalisation des ligatures françaises
    text = _normalize_ligatures(text)

    # Remplacement des caractères spéciaux par tiret
    for char in SPECIAL_CHARS_TO_DASH:
        text = text.replace(char, "-")

    # Remplacement du point d'interrogation par placeholder ellipse
    # (pour éviter que pathvalidate supprime les points finaux)
    text = text.replace("?", _ELLIPSIS_PLACEHOLDER)

    # Utilisation de pathvalidate pour le reste (nettoyage plateforme universelle)
    # replacement_text="" car on a déjà fait nos remplacements
    text = sanitize_filename(text, platform="universal", replacement_text="")

    # Restauration des ellipses (placeholder -> ...)
    text = text.replace(_ELLIPSIS_PLACEHOLDER, "...")

    # Troncature à la longueur maximale
    if len(text) > MAX_FILENAME_LENGTH:
        text = text[:MAX_FILENAME_LENGTH]

    return text


def format_language_code(languages: tuple[str, ...]) -> str:
    """
    Formate les codes de langue pour le nom de fichier.

    Règles :
    - Vide -> ""
    - Une langue -> code ISO en majuscules (FR, EN, DE)
    - Plusieurs langues -> "MULTi"

    Args:
        languages: Tuple des codes de langue ISO 639-1.

    Returns:
        Code formaté ou chaîne vide.
    """
    if not languages:
        return ""

    if len(languages) == 1:
        return languages[0].upper()

    return "MULTi"


def _build_tech_suffix(media_info: Optional[MediaInfo]) -> str:
    """
    Construit le suffixe technique (Langue Codec Résolution).

    Args:
        media_info: Informations techniques du fichier.

    Returns:
        Suffixe technique ou chaîne vide si pas d'infos.
    """
    if media_info is None:
        return ""

    parts: list[str] = []

    # Langue(s) audio
    if media_info.audio_languages:
        lang_codes = tuple(lang.code for lang in media_info.audio_languages)
        lang_str = format_language_code(lang_codes)
        if lang_str:
            parts.append(lang_str)

    # Codec vidéo
    if media_info.video_codec:
        parts.append(media_info.video_codec.name)

    # Résolution
    if media_info.resolution:
        parts.append(media_info.resolution.label)

    if not parts:
        return ""

    return " ".join(parts)


def generate_movie_filename(
    movie: Movie,
    media_info: Optional[MediaInfo],
    extension: str,
) -> str:
    """
    Génère le nom de fichier standardisé pour un film.

    Format : Titre (Année) Langue Codec Résolution.ext

    Chaque élément est omis s'il est absent.

    Args:
        movie: Métadonnées du film.
        media_info: Informations techniques du fichier (optionnel).
        extension: Extension du fichier (avec le point).

    Returns:
        Nom de fichier formaté et nettoyé.
    """
    parts: list[str] = []

    # Titre (nettoyé)
    title = sanitize_for_filesystem(movie.title)
    parts.append(title)

    # Année
    if movie.year:
        parts.append(f"({movie.year})")

    # Suffixe technique
    tech_suffix = _build_tech_suffix(media_info)
    if tech_suffix:
        parts.append(tech_suffix)

    # Assemblage
    filename_base = " ".join(parts)

    # Ajout de l'extension
    return f"{filename_base}{extension}"


def generate_series_filename(
    series: Series,
    episode: Episode,
    media_info: Optional[MediaInfo],
    extension: str,
) -> str:
    """
    Génère le nom de fichier standardisé pour un épisode de série.

    Format : Titre (Année) - SxxExx - TitreEpisode - Langue Codec Résolution.ext

    Les éléments absents (année, titre d'épisode) sont omis.

    Args:
        series: Métadonnées de la série.
        episode: Métadonnées de l'épisode.
        media_info: Informations techniques du fichier (optionnel).
        extension: Extension du fichier (avec le point).

    Returns:
        Nom de fichier formaté et nettoyé.
    """
    parts: list[str] = []

    # Titre de la série (nettoyé)
    title = sanitize_for_filesystem(series.title)
    parts.append(title)

    # Année
    if series.year:
        parts.append(f"({series.year})")

    # Séparateur
    parts.append("-")

    # Numéro d'épisode (SxxExx)
    episode_code = f"S{episode.season_number:02d}E{episode.episode_number:02d}"
    parts.append(episode_code)

    # Titre de l'épisode
    if episode.title:
        episode_title = sanitize_for_filesystem(episode.title)
        parts.append("-")
        parts.append(episode_title)

    # Suffixe technique
    tech_suffix = _build_tech_suffix(media_info)
    if tech_suffix:
        parts.append("-")
        parts.append(tech_suffix)

    # Assemblage
    filename_base = " ".join(parts)

    # Ajout de l'extension
    return f"{filename_base}{extension}"


class RenamerService:
    """
    Service de renommage des fichiers médias.

    Fournit les méthodes de haut niveau pour générer les noms
    de fichiers standardisés pour films et séries.

    Ce service est sans état et peut être utilisé comme singleton.
    """

    def generate_movie_filename(
        self,
        movie: Movie,
        media_info: Optional[MediaInfo],
        extension: str,
    ) -> str:
        """
        Génère le nom de fichier pour un film.

        Voir generate_movie_filename() pour les détails.
        """
        return generate_movie_filename(movie, media_info, extension)

    def generate_series_filename(
        self,
        series: Series,
        episode: Episode,
        media_info: Optional[MediaInfo],
        extension: str,
    ) -> str:
        """
        Génère le nom de fichier pour un épisode de série.

        Voir generate_series_filename() pour les détails.
        """
        return generate_series_filename(series, episode, media_info, extension)
