"""
Service de sandbox pour les fichiers orphelins.

Permet d'isoler les fichiers orphelins (non ciblés par un symlink)
dans un répertoire dédié pour revue avant décision (supprimer ou réintégrer).
"""

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger


@dataclass
class SandboxedFile:
    """Fichier présent dans le sandbox."""

    path: Path
    name: str
    size: int
    modified: datetime
    original_path: Path


class SandboxService:
    """Gestion du sandbox pour les fichiers orphelins.

    Args:
        sandbox_dir: Répertoire racine du sandbox.
        storage_dir: Répertoire storage de la vidéothèque.
        downloads_dir: Répertoire des téléchargements (cible de réinjection).
    """

    def __init__(
        self,
        sandbox_dir: Path,
        storage_dir: Path,
        downloads_dir: Path,
    ) -> None:
        self._sandbox_dir = sandbox_dir
        self._storage_dir = storage_dir
        self._downloads_dir = downloads_dir
        self._orphans_dir = sandbox_dir / "orphans"

    def sandbox_orphans(
        self,
        orphan_paths: list[Path],
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> int:
        """Déplace les fichiers orphelins vers le sandbox.

        Préserve l'arborescence relative à storage_dir.

        Args:
            orphan_paths: Liste des fichiers orphelins à sandboxer.
            on_progress: Callback optionnel (moved, total, filename) par fichier.

        Returns:
            Nombre de fichiers déplacés.
        """
        total = len(orphan_paths)
        moved = 0
        for src in orphan_paths:
            if not src.exists():
                logger.warning("Fichier introuvable, ignoré : {}", src)
                if on_progress:
                    on_progress(moved, total, src.name)
                continue
            try:
                relative = src.relative_to(self._storage_dir)
            except ValueError:
                # Fichier hors du storage — utiliser le nom seul
                relative = Path(src.name)

            dest = self._orphans_dir / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            moved += 1
            logger.info("Sandboxé : {} → {}", src, dest)
            if on_progress:
                on_progress(moved, total, src.name)

        # Nettoyer les répertoires vides laissés dans storage
        self._cleanup_empty_parents(orphan_paths)
        return moved

    def list_sandboxed(self) -> list[SandboxedFile]:
        """Liste les fichiers présents dans le sandbox.

        Returns:
            Liste de SandboxedFile avec métadonnées.
        """
        if not self._orphans_dir.exists():
            return []

        files: list[SandboxedFile] = []
        for entry in sorted(self._orphans_dir.rglob("*")):
            if entry.is_dir() or entry.is_symlink():
                continue
            try:
                relative = entry.relative_to(self._orphans_dir)
            except ValueError:
                continue

            stat = entry.stat()
            original = self._storage_dir / relative
            files.append(
                SandboxedFile(
                    path=entry,
                    name=entry.name,
                    size=stat.st_size,
                    modified=datetime.fromtimestamp(stat.st_mtime),
                    original_path=original,
                )
            )
        return files

    def delete_files(self, paths: list[Path]) -> int:
        """Supprime définitivement des fichiers du sandbox.

        Nettoie les répertoires vides remontant après suppression.

        Returns:
            Nombre de fichiers supprimés.
        """
        deleted = 0
        for path in paths:
            if not path.exists():
                logger.warning("Fichier déjà absent : {}", path)
                continue
            if not self._is_inside_sandbox(path):
                logger.error("Tentative de suppression hors sandbox : {}", path)
                continue
            path.unlink()
            deleted += 1
            logger.info("Supprimé définitivement : {}", path)

        self._cleanup_empty_parents(paths, root=self._orphans_dir)
        return deleted

    def reinject_files(self, paths: list[Path]) -> int:
        """Réinjecte des fichiers du sandbox vers le répertoire downloads.

        Les fichiers seront traités au prochain scan workflow.

        Returns:
            Nombre de fichiers réinjectés.
        """
        reinjected = 0
        self._downloads_dir.mkdir(parents=True, exist_ok=True)

        for path in paths:
            if not path.exists():
                logger.warning("Fichier introuvable : {}", path)
                continue
            if not self._is_inside_sandbox(path):
                logger.error("Tentative de réinjection hors sandbox : {}", path)
                continue

            # Conserver le sous-répertoire de type (Films/ ou Series/) pour
            # que le scan workflow détecte correctement le type de contenu
            try:
                relative = path.relative_to(self._orphans_dir)
                # Premier segment = Films, Series, Documentaires...
                type_dir = relative.parts[0] if relative.parts else ""
            except ValueError:
                type_dir = ""

            if type_dir:
                dest_dir = self._downloads_dir / type_dir
            else:
                dest_dir = self._downloads_dir
            dest_dir.mkdir(parents=True, exist_ok=True)

            dest = dest_dir / path.name
            # Éviter l'écrasement
            if dest.exists():
                stem = dest.stem
                suffix = dest.suffix
                counter = 1
                while dest.exists():
                    dest = dest_dir / f"{stem} ({counter}){suffix}"
                    counter += 1

            shutil.move(str(path), str(dest))
            reinjected += 1
            logger.info("Réinjecté : {} → {}", path, dest)

        self._cleanup_empty_parents(paths, root=self._orphans_dir)
        return reinjected

    def _is_inside_sandbox(self, path: Path) -> bool:
        """Vérifie qu'un chemin est bien à l'intérieur du sandbox."""
        try:
            path.resolve().relative_to(self._sandbox_dir.resolve())
            return True
        except ValueError:
            return False

    def _cleanup_empty_parents(
        self, paths: list[Path], root: Path | None = None
    ) -> None:
        """Nettoie les répertoires vides en remontant vers root."""
        stop = (root or self._storage_dir).resolve()
        seen: set[Path] = set()

        for path in paths:
            parent = path.parent.resolve()
            while parent != stop and parent not in seen and parent != parent.parent:
                seen.add(parent)
                if parent.exists() and parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
                    logger.debug("Répertoire vide supprimé : {}", parent)
                    parent = parent.parent.resolve()
                else:
                    break
