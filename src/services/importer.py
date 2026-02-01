"""
Service d'import de videotheque existante.

Orchestre l'import de fichiers video existants dans la base de donnees,
avec detection des doublons par hash et creation des entrees PendingValidation.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Generator, Optional

from src.core.entities.video import PendingValidation, VideoFile
from src.core.ports.file_system import IFileSystem
from src.core.ports.parser import IFilenameParser, IMediaInfoExtractor
from src.core.ports.repositories import IVideoFileRepository


class ImportDecision(Enum):
    """Decision prise pour un fichier lors de l'import."""

    IMPORT = "import"  # Nouveau fichier a importer
    SKIP_KNOWN = "skip_known"  # Fichier deja connu (meme hash)
    UPDATE_PATH = "update_path"  # Fichier connu mais path different
    ERROR = "error"  # Erreur lors du traitement


@dataclass
class ImportResult:
    """
    Resultat de l'import d'un fichier.

    Attributs:
        filename: Nom du fichier traite
        decision: Decision prise (IMPORT, SKIP_KNOWN, UPDATE_PATH, ERROR)
        error_message: Message d'erreur si decision == ERROR
    """

    filename: str
    decision: ImportDecision
    error_message: Optional[str] = None


class ImporterService:
    """
    Service d'import de videotheque existante.

    Scanne un repertoire de stockage et importe les fichiers video
    dans la base de donnees. Les fichiers deja connus (par hash)
    sont ignores silencieusement.

    Attributs injectes:
        file_system: Interface pour les operations fichiers
        filename_parser: Parser de noms de fichiers
        media_info_extractor: Extracteur de metadonnees techniques
        video_file_repo: Repository des fichiers video
        pending_repo: Repository des validations en attente
        compute_hash_fn: Fonction de calcul de hash de fichier
    """

    def __init__(
        self,
        file_system: IFileSystem,
        filename_parser: IFilenameParser,
        media_info_extractor: IMediaInfoExtractor,
        video_file_repo: IVideoFileRepository,
        pending_repo: "SQLModelPendingValidationRepository",
        compute_hash_fn: Callable[[Path], str],
        dry_run: bool = False,
    ) -> None:
        """
        Initialise le service d'import.

        Args:
            file_system: Implementation de IFileSystem
            filename_parser: Implementation de IFilenameParser
            media_info_extractor: Implementation de IMediaInfoExtractor
            video_file_repo: Repository des fichiers video
            pending_repo: Repository des validations en attente
            compute_hash_fn: Fonction de calcul de hash (ex: compute_file_hash)
            dry_run: Si True, ne pas modifier la BDD
        """
        self._file_system = file_system
        self._filename_parser = filename_parser
        self._media_info_extractor = media_info_extractor
        self._video_file_repo = video_file_repo
        self._pending_repo = pending_repo
        self._compute_hash_fn = compute_hash_fn
        self._dry_run = dry_run

    def scan_library(
        self, storage_dir: Path
    ) -> Generator[ImportResult, None, None]:
        """
        Scanne un repertoire de stockage et importe les fichiers video.

        Parcourt recursivement le repertoire et yield un ImportResult
        pour chaque fichier video trouve.

        Args:
            storage_dir: Repertoire de stockage a scanner

        Yields:
            ImportResult pour chaque fichier traite
        """
        from src.adapters.file_system import IGNORED_PATTERNS, VIDEO_EXTENSIONS

        # Parcourir recursivement le repertoire
        for file_path in storage_dir.rglob("*"):
            # Ignorer les repertoires et symlinks
            if file_path.is_dir() or file_path.is_symlink():
                continue

            # Verifier que c'est un fichier video
            if file_path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue

            # Verifier les patterns ignores
            filename_lower = file_path.name.lower()
            if any(pattern in filename_lower for pattern in IGNORED_PATTERNS):
                continue

            # Traiter le fichier
            yield self._process_file(file_path)

    def _process_file(self, file_path: Path) -> ImportResult:
        """
        Traite un fichier video et determine l'action a effectuer.

        Args:
            file_path: Chemin du fichier a traiter

        Returns:
            ImportResult avec la decision prise
        """
        try:
            # Determiner la decision
            decision, existing = self._should_import(file_path)

            if decision == ImportDecision.SKIP_KNOWN:
                return ImportResult(
                    filename=file_path.name,
                    decision=ImportDecision.SKIP_KNOWN,
                )

            if decision == ImportDecision.UPDATE_PATH:
                # Mettre a jour le path du fichier existant
                if not self._dry_run and existing:
                    existing.path = file_path
                    self._video_file_repo.save(existing)
                return ImportResult(
                    filename=file_path.name,
                    decision=ImportDecision.UPDATE_PATH,
                )

            # Nouveau fichier - creer VideoFile et PendingValidation
            return self._import_file(file_path)

        except Exception as e:
            return ImportResult(
                filename=file_path.name,
                decision=ImportDecision.ERROR,
                error_message=str(e),
            )

    def _should_import(
        self, file_path: Path
    ) -> tuple[ImportDecision, Optional[VideoFile]]:
        """
        Determine si un fichier doit etre importe.

        Verifie par hash d'abord, puis par path.

        Args:
            file_path: Chemin du fichier a verifier

        Returns:
            Tuple (decision, existing_video_file)
        """
        # Calculer le hash du fichier
        file_hash = self._compute_hash_fn(file_path)

        # Verifier si le hash existe deja
        existing_by_hash = self._video_file_repo.get_by_hash(file_hash)
        if existing_by_hash:
            # Fichier connu par hash - verifier si path a change
            if existing_by_hash.path != file_path:
                return ImportDecision.UPDATE_PATH, existing_by_hash
            return ImportDecision.SKIP_KNOWN, existing_by_hash

        # Verifier si le path existe avec un hash different
        existing_by_path = self._video_file_repo.get_by_path(file_path)
        if existing_by_path:
            # Meme path mais hash different -> fichier modifie, re-importer
            return ImportDecision.IMPORT, None

        # Nouveau fichier
        return ImportDecision.IMPORT, None

    def _import_file(self, file_path: Path) -> ImportResult:
        """
        Importe un nouveau fichier dans la base de donnees.

        Cree un VideoFile et un PendingValidation.

        Args:
            file_path: Chemin du fichier a importer

        Returns:
            ImportResult avec decision IMPORT
        """
        # Calculer le hash
        file_hash = self._compute_hash_fn(file_path)

        # Extraire les metadonnees techniques
        media_info = self._media_info_extractor.extract(file_path)

        # Detecter le type (Films ou Series)
        import_type = self._detect_import_type(file_path)

        # Creer le VideoFile
        video_file = VideoFile(
            path=file_path,
            filename=file_path.name,
            size_bytes=self._file_system.get_size(file_path),
            file_hash=file_hash,
            media_info=media_info,
        )

        if not self._dry_run:
            # Sauvegarder le VideoFile
            saved_vf = self._video_file_repo.save(video_file)

            # Creer le PendingValidation avec metadata
            pending = PendingValidation(
                video_file=saved_vf,
                candidates=[],
            )
            # Note: entity_metadata serait stocke si le modele le supporte
            # Pour l'instant on utilise le path pour detecter le type
            self._pending_repo.save(pending)

        return ImportResult(
            filename=file_path.name,
            decision=ImportDecision.IMPORT,
        )

    def _detect_import_type(self, file_path: Path) -> str:
        """
        Detecte le type de media depuis le chemin du fichier.

        Parcourt les parents du fichier pour detecter "Films" ou "Series".

        Args:
            file_path: Chemin du fichier

        Returns:
            "movie" si dans Films/, "series" si dans Series/, "unknown" sinon
        """
        for parent in file_path.parents:
            parent_name = parent.name.lower()
            if parent_name == "films":
                return "movie"
            if parent_name in ("series", "séries"):
                return "series"
        return "unknown"

    def scan_from_symlinks(
        self, video_dir: Path
    ) -> Generator[ImportResult, None, None]:
        """
        Import inverse : scanne les symlinks et importe leurs cibles.

        Parcourt recursivement le repertoire des symlinks, resout chaque
        symlink vers son fichier physique cible, et importe les deux chemins
        (symlink + cible) dans la base de donnees.

        Args:
            video_dir: Repertoire des symlinks a scanner

        Yields:
            ImportResult pour chaque symlink traite
        """
        from src.adapters.file_system import IGNORED_PATTERNS, VIDEO_EXTENSIONS

        # Parcourir recursivement le repertoire
        for symlink_path in video_dir.rglob("*"):
            # Ignorer les repertoires
            if symlink_path.is_dir():
                continue

            # On ne traite QUE les symlinks
            if not symlink_path.is_symlink():
                continue

            # Verifier que c'est un fichier video
            if symlink_path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue

            # Verifier les patterns ignores
            filename_lower = symlink_path.name.lower()
            if any(pattern in filename_lower for pattern in IGNORED_PATTERNS):
                continue

            # Traiter le symlink
            yield self._process_symlink(symlink_path)

    def _process_symlink(self, symlink_path: Path) -> ImportResult:
        """
        Traite un symlink et importe sa cible.

        Args:
            symlink_path: Chemin du symlink a traiter

        Returns:
            ImportResult avec la decision prise
        """
        try:
            # Resoudre le symlink vers sa cible
            try:
                target_path = symlink_path.resolve()
            except OSError as e:
                return ImportResult(
                    filename=symlink_path.name,
                    decision=ImportDecision.ERROR,
                    error_message=f"Symlink casse: {e}",
                )

            # Verifier que la cible existe
            if not target_path.exists():
                return ImportResult(
                    filename=symlink_path.name,
                    decision=ImportDecision.ERROR,
                    error_message=f"Cible introuvable: {target_path}",
                )

            # Verifier que la cible n'est pas un symlink (eviter les boucles)
            if target_path.is_symlink():
                return ImportResult(
                    filename=symlink_path.name,
                    decision=ImportDecision.ERROR,
                    error_message="Cible est aussi un symlink",
                )

            # Determiner la decision
            decision, existing = self._should_import(target_path)

            if decision == ImportDecision.SKIP_KNOWN:
                # Fichier connu - verifier si on doit mettre a jour le symlink_path
                if existing and not existing.symlink_path:
                    if not self._dry_run:
                        existing.symlink_path = symlink_path
                        self._video_file_repo.save(existing)
                    return ImportResult(
                        filename=symlink_path.name,
                        decision=ImportDecision.UPDATE_PATH,
                    )
                return ImportResult(
                    filename=symlink_path.name,
                    decision=ImportDecision.SKIP_KNOWN,
                )

            if decision == ImportDecision.UPDATE_PATH:
                # Mettre a jour le path du fichier existant + symlink
                if not self._dry_run and existing:
                    existing.path = target_path
                    existing.symlink_path = symlink_path
                    self._video_file_repo.save(existing)
                return ImportResult(
                    filename=symlink_path.name,
                    decision=ImportDecision.UPDATE_PATH,
                )

            # Nouveau fichier - creer VideoFile avec symlink
            return self._import_symlink(symlink_path, target_path)

        except Exception as e:
            return ImportResult(
                filename=symlink_path.name,
                decision=ImportDecision.ERROR,
                error_message=str(e),
            )

    def _import_symlink(self, symlink_path: Path, target_path: Path) -> ImportResult:
        """
        Importe un nouveau fichier depuis un symlink.

        Cree un VideoFile avec le path physique ET le symlink_path.

        Args:
            symlink_path: Chemin du symlink
            target_path: Chemin du fichier physique cible

        Returns:
            ImportResult avec decision IMPORT
        """
        # Calculer le hash du fichier cible
        file_hash = self._compute_hash_fn(target_path)

        # Extraire les metadonnees techniques du fichier cible
        media_info = self._media_info_extractor.extract(target_path)

        # Creer le VideoFile avec les deux chemins
        video_file = VideoFile(
            path=target_path,
            symlink_path=symlink_path,
            filename=target_path.name,
            size_bytes=self._file_system.get_size(target_path),
            file_hash=file_hash,
            media_info=media_info,
        )

        if not self._dry_run:
            # Sauvegarder le VideoFile
            saved_vf = self._video_file_repo.save(video_file)

            # Creer le PendingValidation
            pending = PendingValidation(
                video_file=saved_vf,
                candidates=[],
            )
            self._pending_repo.save(pending)

        return ImportResult(
            filename=symlink_path.name,
            decision=ImportDecision.IMPORT,
        )
