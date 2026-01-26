"""
Objets valeur immutables représentant des concepts du domaine sans identité.

Les objets valeur sont définis par leurs attributs plutôt que par une identité.
Ils sont immutables et peuvent être librement partagés et comparés par valeur.

Exports :
- Resolution : Résolution vidéo (largeur x hauteur)
- VideoCodec : Informations sur le codec vidéo (HEVC, H.264, etc.)
- AudioCodec : Informations sur le codec audio avec canaux
- Language : Langue avec code ISO et nom complet
- MediaInfo : Composite de toutes les informations techniques média
"""

from src.core.value_objects.media_info import (
    Resolution,
    VideoCodec,
    AudioCodec,
    Language,
    MediaInfo,
)

__all__ = [
    "Resolution",
    "VideoCodec",
    "AudioCodec",
    "Language",
    "MediaInfo",
]
