"""
Interfaces ports pour le parsing de noms de fichiers et extraction de metadonnees.

Interfaces abstraites (ports) definissant les contrats pour le parsing de noms
de fichiers video et l'extraction des metadonnees techniques via mediainfo.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from src.core.value_objects.media_info import MediaInfo
from src.core.value_objects.parsed_info import MediaType, ParsedFilename


class IFilenameParser(ABC):
    """
    Interface pour le parsing de noms de fichiers video.

    Definit le contrat pour extraire les informations structurees
    (titre, annee, saison, episode, codecs...) depuis un nom de fichier.
    L'implementation utilisera typiquement la bibliotheque guessit.
    """

    @abstractmethod
    def parse(
        self, filename: str, type_hint: Optional[MediaType] = None
    ) -> ParsedFilename:
        """
        Parse un nom de fichier video et extrait les informations structurees.

        Args:
            filename: Nom du fichier a parser (sans le chemin)
            type_hint: Indication du type de media attendu (depuis le repertoire source).
                       Aide a la detection quand le nom seul est ambigu.

        Retourne:
            ParsedFilename avec les informations extraites.
            Le champ title est toujours renseigne (au minimum le nom sans extension).
        """
        ...


class IMediaInfoExtractor(ABC):
    """
    Interface pour l'extraction des metadonnees techniques d'un fichier video.

    Definit le contrat pour extraire les informations techniques
    (resolution, codecs, langues, duree) via mediainfo.
    """

    @abstractmethod
    def extract(self, file_path: Path) -> Optional[MediaInfo]:
        """
        Extrait les metadonnees techniques d'un fichier video.

        Utilise mediainfo pour obtenir resolution, codecs video/audio,
        langues des pistes audio, et duree.

        Args:
            file_path: Chemin complet vers le fichier video

        Retourne:
            MediaInfo avec les metadonnees extraites, ou None si
            l'extraction echoue (fichier non video, corrompu, etc.)
        """
        ...
