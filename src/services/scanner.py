"""
Service de scan des repertoires de telechargements.

Orchestre le scan des fichiers video en coordonnant le systeme de fichiers
et le parser de noms de fichiers.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from src.config import Settings
from src.core.entities.video import VideoFile
from src.core.ports.file_system import IFileSystem
from src.core.ports.parser import IFilenameParser, IMediaInfoExtractor
from src.core.value_objects import MediaInfo, MediaType, ParsedFilename


@dataclass
class ScanResult:
    """
    Resultat du scan d'un fichier video.

    Contient toutes les informations extraites du scan:
    - Le fichier video avec ses metadonnees de base
    - Les informations parsees du nom de fichier
    - Le type detecte et la source (Films/Series)
    - Un flag indiquant si le fichier est mal place

    Attributs:
        video_file: Entite VideoFile avec path, filename, size_bytes
        parsed_info: Informations extraites du parsing du nom
        detected_type: Type de media detecte (MOVIE, SERIES, UNKNOWN)
        source_directory: Nom du repertoire source ("Films" ou "Series")
        corrected_location: True si le type detecte != type attendu du repertoire.
                           C'est un FLAG pour Phase 5 (transferer) qui effectuera
                           le deplacement physique.
        media_info: Metadonnees techniques (None dans ce plan, peuple dans Plan 02-02)
    """

    video_file: VideoFile
    parsed_info: ParsedFilename
    detected_type: MediaType
    source_directory: str
    corrected_location: bool
    media_info: Optional[MediaInfo] = None


class ScannerService:
    """
    Service orchestrant le scan des repertoires de telechargements.

    Coordonne:
    - Le systeme de fichiers (IFileSystem) pour lister les fichiers video
    - Le parser de noms (IFilenameParser) pour extraire les informations
    - L'extracteur mediainfo (IMediaInfoExtractor) pour les metadonnees techniques
    """

    def __init__(
        self,
        file_system: IFileSystem,
        filename_parser: IFilenameParser,
        media_info_extractor: IMediaInfoExtractor,
        settings: Settings,
    ) -> None:
        """
        Initialise le service de scan.

        Args:
            file_system: Implementation de IFileSystem pour les operations fichiers
            filename_parser: Implementation de IFilenameParser pour le parsing
            media_info_extractor: Implementation de IMediaInfoExtractor pour mediainfo
            settings: Configuration de l'application
        """
        self._file_system = file_system
        self._filename_parser = filename_parser
        self._media_info_extractor = media_info_extractor
        self._settings = settings

    def scan_downloads(self) -> Iterator[ScanResult]:
        """
        Scanne les repertoires de telechargements (Films et Series).

        Parcourt downloads_dir/Films et downloads_dir/Series,
        et yield un ScanResult pour chaque fichier video trouve.

        Yields:
            ScanResult pour chaque fichier video valide trouve
        """
        downloads = self._settings.downloads_dir
        subdirs_with_hints: list[tuple[list[str], MediaType]] = [
            (["Films"], MediaType.MOVIE),
            (["Séries", "Series"], MediaType.SERIES),  # Supporte les deux variantes
        ]

        for subdir_variants, type_hint in subdirs_with_hints:
            for subdir_name in subdir_variants:
                source_dir = downloads / subdir_name
                if source_dir.exists():
                    yield from self._scan_directory(source_dir, subdir_name, type_hint)
                    break  # Ne scanner qu'une seule variante

    def _scan_directory(
        self,
        directory: Path,
        source_name: str,
        type_hint: MediaType,
    ) -> Iterator[ScanResult]:
        """
        Scanne un repertoire specifique.

        Args:
            directory: Chemin du repertoire a scanner
            source_name: Nom du repertoire source ("Films" ou "Series")
            type_hint: Type de media attendu dans ce repertoire

        Yields:
            ScanResult pour chaque fichier video valide trouve
        """
        # Calculer la taille minimale en octets
        min_size_bytes = self._settings.min_file_size_mb * 1024 * 1024

        # Utiliser list_video_files si disponible, sinon scan basique
        if hasattr(self._file_system, "list_video_files"):
            # FileSystemAdapter avec methode utilitaire
            video_files = self._file_system.list_video_files(  # type: ignore[attr-defined]
                directory, min_size_bytes
            )
        else:
            # Fallback pour les mocks sans list_video_files
            video_files = self._list_video_files_fallback(directory, min_size_bytes)

        for file_path in video_files:
            yield self._process_file(file_path, source_name, type_hint)

    def _list_video_files_fallback(
        self,
        directory: Path,
        min_size_bytes: int,
    ) -> Iterator[Path]:
        """
        Fallback pour lister les fichiers video quand list_video_files n'est pas disponible.

        Utilise seulement les methodes de IFileSystem.
        """
        from src.adapters.file_system import IGNORED_PATTERNS, VIDEO_EXTENSIONS

        for path in directory.rglob("*"):
            if path.is_dir():
                continue
            if path.is_symlink():
                continue
            if path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            filename_lower = path.name.lower()
            if any(pattern in filename_lower for pattern in IGNORED_PATTERNS):
                continue
            if self._file_system.get_size(path) < min_size_bytes:
                continue
            yield path

    def _process_file(
        self,
        file_path: Path,
        source_name: str,
        type_hint: MediaType,
    ) -> ScanResult:
        """
        Traite un fichier video et cree un ScanResult.

        Args:
            file_path: Chemin du fichier video
            source_name: Nom du repertoire source
            type_hint: Type de media attendu

        Returns:
            ScanResult avec toutes les informations extraites
        """
        # Creer VideoFile avec les infos de base
        video_file = VideoFile(
            path=file_path,
            filename=file_path.name,
            size_bytes=self._file_system.get_size(file_path),
        )

        # Parser le nom de fichier avec le type hint
        parsed_info = self._filename_parser.parse(file_path.name, type_hint)

        # Extraire les metadonnees techniques via mediainfo
        media_info = self._media_info_extractor.extract(file_path)

        # Determiner si le fichier est mal place
        # corrected_location = True si le type detecte != type attendu du repertoire
        detected_type = parsed_info.media_type
        corrected_location = self._is_misplaced(detected_type, type_hint)

        return ScanResult(
            video_file=video_file,
            parsed_info=parsed_info,
            detected_type=detected_type,
            source_directory=source_name,
            corrected_location=corrected_location,
            media_info=media_info,
        )

    def _is_misplaced(self, detected_type: MediaType, type_hint: MediaType) -> bool:
        """
        Determine si un fichier est mal place dans le repertoire.

        Un fichier est considere mal place si:
        - Le type detecte est SERIES mais il est dans Films/
        - Le type detecte est MOVIE mais il est dans Series/

        Un fichier avec type UNKNOWN n'est pas considere mal place
        car on ne peut pas determiner avec certitude ou il devrait etre.

        Args:
            detected_type: Type de media detecte par le parser
            type_hint: Type attendu selon le repertoire source

        Returns:
            True si le fichier est mal place
        """
        # Si le type n'est pas determine, on ne peut pas dire qu'il est mal place
        if detected_type == MediaType.UNKNOWN:
            return False

        # Verifier si le type detecte correspond au type attendu
        return detected_type != type_hint
