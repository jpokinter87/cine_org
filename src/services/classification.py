"""Classification dynamique d'un fichier vidéo en MOVIE, SHORT ou SERIES.

La règle est volontairement minimale :

1. Si le chemin contient un segment ``Séries`` ou ``Series`` (insensible à la
   casse), le fichier est considéré comme un épisode de série et reste
   ``MediaType.SERIES`` quelle que soit sa durée. C'est la priorité absolue,
   pour ne jamais reclasser un épisode court en court-métrage.
2. Sinon, si la durée est connue et inférieure ou égale au seuil configuré,
   le fichier est un court-métrage (``MediaType.SHORT``).
3. Sinon, c'est un long-métrage (``MediaType.MOVIE``). C'est aussi le
   comportement par défaut quand la durée est inconnue.

Le seuil par défaut est ``900`` secondes (15 minutes), configuré via
``Settings.short_film_duration_threshold_seconds``.
"""

from pathlib import Path

from src.core.value_objects import MediaInfo, MediaType

_SERIES_DIR_SEGMENTS = frozenset({"séries", "series"})


def _is_under_series_dir(file_path: Path) -> bool:
    """Vrai si l'un des segments du chemin est ``Séries`` ou ``Series``."""
    return any(part.lower() in _SERIES_DIR_SEGMENTS for part in file_path.parts)


def classify_media(
    file_path: Path,
    media_info: MediaInfo,
    threshold_seconds: int,
) -> MediaType:
    """Classifie un fichier vidéo en MOVIE, SHORT ou SERIES.

    Args:
        file_path: Chemin du fichier (storage ou downloads).
        media_info: Métadonnées techniques (la durée est seule consultée ici).
        threshold_seconds: Durée seuil (incluse) en dessous de laquelle un
            fichier hors ``Séries/`` est considéré comme un court-métrage.

    Returns:
        Le ``MediaType`` retenu pour ce fichier.
    """
    if _is_under_series_dir(file_path):
        return MediaType.SERIES

    duration = media_info.duration_seconds
    if duration is not None and duration <= threshold_seconds:
        return MediaType.SHORT

    return MediaType.MOVIE
