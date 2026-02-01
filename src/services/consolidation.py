"""
Service de consolidation de la videotheque.

Detecte et rapatrie les fichiers stockes sur des volumes externes
via des symlinks dans la zone de stockage principale.
"""

import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Generator, Optional

from loguru import logger

from src.adapters.file_system import VIDEO_EXTENSIONS


class ConsolidationStatus(Enum):
    """Statut d'un symlink externe."""

    ACCESSIBLE = "accessible"  # Cible accessible, peut etre rapatrie
    INACCESSIBLE = "inaccessible"  # Cible inaccessible (volume non monte)
    CONSOLIDATED = "consolidated"  # Fichier rapatrie avec succes
    ERROR = "error"  # Erreur lors du rapatriement
    SKIPPED = "skipped"  # Ignore (symlink interne ou non-video)


@dataclass
class ExternalSymlink:
    """
    Un symlink dans storage pointant vers un volume externe.

    Attributs:
        symlink_path: Chemin du symlink dans storage
        target_path: Chemin de la cible (sur volume externe)
        target_volume: Volume racine de la cible
        status: Statut du symlink
        size_bytes: Taille du fichier cible (si accessible)
        error_message: Message d'erreur (si applicable)
    """

    symlink_path: Path
    target_path: Path
    target_volume: str
    status: ConsolidationStatus
    size_bytes: Optional[int] = None
    error_message: Optional[str] = None


@dataclass
class ConsolidationResult:
    """
    Resultat d'une operation de consolidation.

    Attributs:
        symlink: Le symlink traite
        new_path: Nouveau chemin du fichier (si consolide)
        status: Statut final
        error_message: Message d'erreur (si applicable)
    """

    symlink: ExternalSymlink
    new_path: Optional[Path] = None
    status: ConsolidationStatus = ConsolidationStatus.SKIPPED
    error_message: Optional[str] = None


class ConsolidationService:
    """
    Service de consolidation de la videotheque.

    Detecte les symlinks dans storage qui pointent vers des volumes externes
    et permet de rapatrier les fichiers dans la zone de stockage principale.
    """

    def __init__(
        self,
        storage_dir: Path,
        dry_run: bool = False,
    ) -> None:
        """
        Initialise le service de consolidation.

        Args:
            storage_dir: Repertoire de stockage principal
            dry_run: Si True, ne pas modifier les fichiers
        """
        self._storage_dir = storage_dir
        self._dry_run = dry_run

    def _is_external_target(self, symlink_path: Path, target_path: Path) -> bool:
        """
        Verifie si la cible d'un symlink est externe a storage_dir.

        Args:
            symlink_path: Chemin du symlink
            target_path: Chemin de la cible resolue

        Returns:
            True si la cible est en dehors de storage_dir
        """
        try:
            # Verifier si la cible est sous storage_dir
            target_path.relative_to(self._storage_dir)
            return False  # Cible interne
        except ValueError:
            return True  # Cible externe

    def _get_volume_root(self, path: Path) -> str:
        """
        Extrait le volume racine d'un chemin.

        Ex: /media/NAS/volume5/... -> /media/NAS/volume5

        Args:
            path: Chemin a analyser

        Returns:
            Chemin du volume racine
        """
        parts = path.parts
        # Chercher /media/XXX/YYY comme volume
        if len(parts) >= 4 and parts[1] == "media":
            return "/".join(parts[:4])
        return str(path.parent)

    def scan_external_symlinks(self) -> Generator[ExternalSymlink, None, None]:
        """
        Scanne storage_dir pour trouver les symlinks vers des volumes externes.

        Yields:
            ExternalSymlink pour chaque symlink externe trouve
        """
        for path in self._storage_dir.rglob("*"):
            # Ne traiter que les symlinks
            if not path.is_symlink():
                continue

            # Verifier que c'est un fichier video
            if path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue

            # Lire la cible du symlink
            try:
                target = path.resolve()
            except OSError:
                # Symlink casse - on ne peut pas le resoudre
                target = Path(str(path.readlink()))

            # Verifier si c'est externe
            if not self._is_external_target(path, target):
                continue

            # Determiner le volume
            volume = self._get_volume_root(target)

            # Verifier si la cible est accessible
            try:
                if target.exists():
                    size = target.stat().st_size
                    yield ExternalSymlink(
                        symlink_path=path,
                        target_path=target,
                        target_volume=volume,
                        status=ConsolidationStatus.ACCESSIBLE,
                        size_bytes=size,
                    )
                else:
                    yield ExternalSymlink(
                        symlink_path=path,
                        target_path=target,
                        target_volume=volume,
                        status=ConsolidationStatus.INACCESSIBLE,
                        error_message="Cible introuvable",
                    )
            except PermissionError:
                yield ExternalSymlink(
                    symlink_path=path,
                    target_path=target,
                    target_volume=volume,
                    status=ConsolidationStatus.INACCESSIBLE,
                    error_message="Permission refusee",
                )
            except OSError as e:
                yield ExternalSymlink(
                    symlink_path=path,
                    target_path=target,
                    target_volume=volume,
                    status=ConsolidationStatus.INACCESSIBLE,
                    error_message=str(e),
                )

    def consolidate(self, symlink: ExternalSymlink) -> ConsolidationResult:
        """
        Rapatrie un fichier externe dans storage.

        Copie le fichier cible a l'emplacement du symlink,
        puis supprime le symlink et le remplace par le fichier.

        Args:
            symlink: Le symlink externe a consolider

        Returns:
            ConsolidationResult avec le statut de l'operation
        """
        if symlink.status != ConsolidationStatus.ACCESSIBLE:
            return ConsolidationResult(
                symlink=symlink,
                status=ConsolidationStatus.SKIPPED,
                error_message="Cible non accessible",
            )

        symlink_path = symlink.symlink_path
        target_path = symlink.target_path

        # Le nouveau chemin sera le meme que le symlink (on remplace)
        new_path = symlink_path

        if self._dry_run:
            return ConsolidationResult(
                symlink=symlink,
                new_path=new_path,
                status=ConsolidationStatus.CONSOLIDATED,
            )

        try:
            # Creer un fichier temporaire pour la copie
            temp_path = symlink_path.with_suffix(symlink_path.suffix + ".tmp")

            # Copier le fichier
            logger.info(f"Copie de {target_path} vers {temp_path}")
            shutil.copy2(target_path, temp_path)

            # Verifier que la copie a la bonne taille
            if temp_path.stat().st_size != symlink.size_bytes:
                temp_path.unlink()
                return ConsolidationResult(
                    symlink=symlink,
                    status=ConsolidationStatus.ERROR,
                    error_message="Taille du fichier copie incorrecte",
                )

            # Supprimer le symlink
            symlink_path.unlink()

            # Renommer le fichier temporaire
            temp_path.rename(symlink_path)

            logger.info(f"Consolide: {symlink_path}")

            return ConsolidationResult(
                symlink=symlink,
                new_path=new_path,
                status=ConsolidationStatus.CONSOLIDATED,
            )

        except PermissionError as e:
            return ConsolidationResult(
                symlink=symlink,
                status=ConsolidationStatus.ERROR,
                error_message=f"Permission refusee: {e}",
            )
        except OSError as e:
            return ConsolidationResult(
                symlink=symlink,
                status=ConsolidationStatus.ERROR,
                error_message=str(e),
            )
        except Exception as e:
            return ConsolidationResult(
                symlink=symlink,
                status=ConsolidationStatus.ERROR,
                error_message=f"Erreur inattendue: {e}",
            )

    def get_summary(
        self, symlinks: list[ExternalSymlink]
    ) -> dict[str, dict[str, int | str]]:
        """
        Genere un resume par volume des symlinks externes.

        Args:
            symlinks: Liste des symlinks externes

        Returns:
            Dictionnaire {volume: {count, accessible, inaccessible, total_size}}
        """
        summary: dict[str, dict[str, int | str]] = {}

        for s in symlinks:
            volume = s.target_volume
            if volume not in summary:
                summary[volume] = {
                    "count": 0,
                    "accessible": 0,
                    "inaccessible": 0,
                    "total_size": 0,
                }

            summary[volume]["count"] += 1

            if s.status == ConsolidationStatus.ACCESSIBLE:
                summary[volume]["accessible"] += 1
                if s.size_bytes:
                    summary[volume]["total_size"] += s.size_bytes
            else:
                summary[volume]["inaccessible"] += 1

        return summary
