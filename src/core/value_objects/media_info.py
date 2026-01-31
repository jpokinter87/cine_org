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
        """
        Retourne le libelle de resolution base sur la largeur et hauteur.

        Prend en compte les formats cinematographiques (2.35:1, 2.40:1)
        ou la hauteur est reduite mais la largeur reste standard.
        Utilise des seuils tolerants pour gerer les variations mineures
        (ex: 1916 pixels au lieu de 1920).
        """
        # 4K: 3840x2160 ou plus (seuil tolerant: 3800 pour cinema)
        if self.height >= 2160 or self.width >= 3800:
            return "4K"
        # 1080p: 1920x1080 ou plus (seuil tolerant: 1900 pour cinema)
        elif self.height >= 1080 or self.width >= 1900:
            return "1080p"
        # 720p: 1280x720 ou plus (seuil tolerant: 1260 pour cinema)
        elif self.height >= 720 or self.width >= 1260:
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
