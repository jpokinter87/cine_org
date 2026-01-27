"""
Objets valeur pour les informations de parsing de noms de fichiers.

Objets valeur immutables representant les informations extraites du parsing
de noms de fichiers video (guessit) et la classification du type de media.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MediaType(Enum):
    """Type de media detecte depuis le nom de fichier ou le repertoire source.

    Valeurs:
        MOVIE: Film (long-metrage)
        SERIES: Serie TV (avec saison/episode)
        UNKNOWN: Type non determine
    """

    MOVIE = "movie"
    SERIES = "series"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ParsedFilename:
    """
    Informations extraites du parsing d'un nom de fichier video.

    Objet valeur immutable contenant toutes les informations
    pouvant etre extraites d'un nom de fichier via guessit.

    Attributs:
        title: Titre extrait (obligatoire)
        year: Annee de sortie (optionnel)
        media_type: Type de media detecte (MOVIE, SERIES, UNKNOWN)
        season: Numero de saison pour les series
        episode: Numero d'episode pour les series
        episode_end: Numero d'episode de fin pour les doubles episodes (ex: S01E01-E02)
        episode_title: Titre de l'episode
        video_codec: Codec video (ex: "H.264", "HEVC", "AV1")
        audio_codec: Codec audio (ex: "AAC", "DTS", "TrueHD")
        resolution: Resolution video (ex: "1080p", "4K", "720p")
        source: Source du fichier (ex: "BluRay", "WEB-DL", "HDTV")
        release_group: Groupe de release
        language: Langue principale detectee
    """

    title: str
    year: Optional[int] = None
    media_type: MediaType = MediaType.UNKNOWN
    season: Optional[int] = None
    episode: Optional[int] = None
    episode_end: Optional[int] = None
    episode_title: Optional[str] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    resolution: Optional[str] = None
    source: Optional[str] = None
    release_group: Optional[str] = None
    language: Optional[str] = None
