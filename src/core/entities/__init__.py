"""
Entités métier représentant les concepts clés du domaine.

Les entités sont des objets mutables avec une identité qui persiste dans le temps.
Elles encapsulent les règles métier et le comportement.

Exports :
- VideoFile : Représente un fichier vidéo avec ses métadonnées
- PendingValidation : Un fichier vidéo en attente de validation utilisateur
- Movie : Métadonnées d'un film depuis TMDB
- Series : Métadonnées d'une série TV depuis TVDB
- Episode : Épisode individuel d'une série
"""

from src.core.entities.video import VideoFile, PendingValidation, ValidationStatus
from src.core.entities.media import Movie, Series, Episode

__all__ = [
    "VideoFile",
    "PendingValidation",
    "ValidationStatus",
    "Movie",
    "Series",
    "Episode",
]
