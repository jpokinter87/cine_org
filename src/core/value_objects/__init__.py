"""
Objets valeur immutables representant des concepts du domaine sans identite.

Les objets valeur sont definis par leurs attributs plutot que par une identite.
Ils sont immutables et peuvent etre librement partages et compares par valeur.

Exports :
- Resolution : Resolution video (largeur x hauteur)
- VideoCodec : Informations sur le codec video (HEVC, H.264, etc.)
- AudioCodec : Informations sur le codec audio avec canaux
- Language : Langue avec code ISO et nom complet
- MediaInfo : Composite de toutes les informations techniques media
- MediaType : Type de media (MOVIE, SERIES, UNKNOWN)
- ParsedFilename : Informations extraites du parsing d'un nom de fichier
"""

from src.core.value_objects.media_info import (
    Resolution,
    VideoCodec,
    AudioCodec,
    Language,
    MediaInfo,
)
from src.core.value_objects.parsed_info import (
    MediaType,
    ParsedFilename,
)

__all__ = [
    "Resolution",
    "VideoCodec",
    "AudioCodec",
    "Language",
    "MediaInfo",
    "MediaType",
    "ParsedFilename",
]
