"""
Objets valeur pour les informations média.

Objets valeur immutables représentant les informations techniques des fichiers vidéo.
Tous les objets valeur utilisent @dataclass(frozen=True) pour garantir l'immutabilité.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Resolution:
    """
    Résolution vidéo (largeur x hauteur).

    Attributs :
        width : Résolution horizontale en pixels
        height : Résolution verticale en pixels

    Propriétés :
        label : Libellé lisible (4K, 1080p, 720p, SD)
    """

    width: int
    height: int

    @property
    def label(self) -> str:
        """Retourne le libellé de résolution basé sur la hauteur."""
        if self.height >= 2160:
            return "4K"
        elif self.height >= 1080:
            return "1080p"
        elif self.height >= 720:
            return "720p"
        else:
            return "SD"


@dataclass(frozen=True)
class VideoCodec:
    """
    Informations sur le codec vidéo.

    Attributs :
        name : Nom du codec (ex: "HEVC", "H.264", "AV1")
        profile : Profil optionnel du codec (ex: "Main 10", "High")
    """

    name: str
    profile: Optional[str] = None


@dataclass(frozen=True)
class AudioCodec:
    """
    Informations sur le codec audio avec configuration des canaux.

    Attributs :
        name : Nom du codec (ex: "AAC", "DTS-HD", "TrueHD")
        channels : Configuration optionnelle des canaux (ex: "5.1", "7.1", "2.0")
    """

    name: str
    channels: Optional[str] = None


@dataclass(frozen=True)
class Language:
    """
    Langue avec code ISO 639-1 et nom complet.

    Attributs :
        code : Code de langue ISO 639-1 (ex: "fr", "en")
        name : Nom complet de la langue (ex: "Français", "Anglais")
    """

    code: str
    name: str


@dataclass(frozen=True)
class MediaInfo:
    """
    Objet valeur composite contenant toutes les informations techniques média.

    Agrège résolution, codecs, langues et durée extraits
    d'un fichier vidéo via mediainfo.

    Attributs :
        resolution : Résolution vidéo (largeur x hauteur)
        video_codec : Informations sur le codec vidéo
        audio_codecs : Tuple des codecs audio (tuple pour l'immutabilité)
        audio_languages : Tuple des langues audio
        duration_seconds : Durée en secondes
    """

    resolution: Optional[Resolution] = None
    video_codec: Optional[VideoCodec] = None
    audio_codecs: tuple[AudioCodec, ...] = ()
    audio_languages: tuple[Language, ...] = ()
    duration_seconds: Optional[int] = None
