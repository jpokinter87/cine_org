"""
Service de sandbox pour les fichiers orphelins.

Permet d'isoler les fichiers orphelins (non ciblés par un symlink)
dans un répertoire dédié pour revue avant décision (supprimer ou réintégrer).
"""

import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger


#: Origine d'un fichier du sandbox
ORPHAN = "orphan"  # isolé par la détection d'orphelins (sous orphans/)
REPLACED_VERSION = "replaced_version"  # ancienne version écartée par un transfert


@dataclass
class SandboxedFile:
    """Fichier présent dans le sandbox.

    Attributs:
        origin: ORPHAN ou REPLACED_VERSION
        status: Statut d'audit (voir sandbox_audit) — REPLACED, MISSING, UNKNOWN
        replacement_path: Fichier vivant qui remplace celui-ci, si connu
        shares_inode: True si le fichier partage son inode (suppression sans gain)
        reclaimable_bytes: Espace réellement libéré par la suppression
    """

    path: Path
    name: str
    size: int
    modified: datetime
    original_path: Path
    origin: str = REPLACED_VERSION
    status: str = "unknown"
    replacement_path: Optional[Path] = None
    shares_inode: bool = False
    reclaimable_bytes: int = 0


@dataclass
class DeletionReport:
    """Compte rendu d'une suppression.

    Attributs:
        deleted: Nombre de fichiers effectivement supprimés
        refused: Couples (chemin, motif) des fichiers épargnés
        reclaimed_bytes: Espace disque réellement libéré
    """

    deleted: int = 0
    refused: list[tuple[Path, str]] = field(default_factory=list)
    reclaimed_bytes: int = 0


class SandboxService:
    """Gestion du sandbox pour les fichiers orphelins.

    Args:
        sandbox_dir: Répertoire racine du sandbox.
        storage_dir: Répertoire storage de la vidéothèque.
        downloads_dir: Répertoire des téléchargements (cible de réinjection).
        auditor: Auditeur confrontant chaque fichier à la vidéothèque. Sans
            lui, la suppression ne peut pas vérifier qu'un remplaçant existe.
    """

    def __init__(
        self,
        sandbox_dir: Path,
        storage_dir: Path,
        downloads_dir: Path,
        auditor: Optional[object] = None,
    ) -> None:
        self._sandbox_dir = sandbox_dir
        self._storage_dir = storage_dir
        self._downloads_dir = downloads_dir
        self._orphans_dir = sandbox_dir / "orphans"
        self._auditor = auditor

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
        """Liste tous les fichiers présents dans le sandbox.

        Couvre aussi bien les orphelins isolés (sous ``orphans/``) que les
        anciennes versions déposées par les transferts, qui reproduisent
        l'arborescence du storage à la racine du sandbox.

        Chaque entrée est confrontée à la vidéothèque quand un auditeur est
        configuré, afin de savoir si un remplaçant existe.

        Returns:
            Liste de SandboxedFile avec métadonnées et statut d'audit.
        """
        if not self._sandbox_dir.exists():
            return []

        files: list[SandboxedFile] = []
        for entry in sorted(self._sandbox_dir.rglob("*")):
            if entry.is_dir() or entry.is_symlink():
                continue

            try:
                relative_to_sandbox = entry.relative_to(self._sandbox_dir)
            except ValueError:
                continue

            if relative_to_sandbox.parts and relative_to_sandbox.parts[0] == "orphans":
                origin = ORPHAN
                relative = entry.relative_to(self._orphans_dir)
            else:
                origin = REPLACED_VERSION
                relative = relative_to_sandbox

            stat = entry.stat()
            audit = self._audit(entry)
            files.append(
                SandboxedFile(
                    path=entry,
                    name=entry.name,
                    size=stat.st_size,
                    modified=datetime.fromtimestamp(stat.st_mtime),
                    original_path=self._storage_dir / relative,
                    origin=origin,
                    status=audit.status if audit else "unknown",
                    replacement_path=audit.replacement_path if audit else None,
                    shares_inode=audit.shares_inode if audit else False,
                    reclaimable_bytes=audit.reclaimable_bytes if audit else 0,
                )
            )
        return files

    def _audit(self, path: Path):
        """Audite un fichier si un auditeur est configuré, sinon None."""
        if self._auditor is None:
            return None
        try:
            return self._auditor.audit(path)
        except Exception as exc:  # l'audit ne doit jamais bloquer l'affichage
            logger.warning("Audit impossible pour {} : {}", path, exc)
            return None

    def delete_files(
        self, paths: list[Path], allow_unknown: bool = False
    ) -> DeletionReport:
        """Supprime définitivement des fichiers du sandbox.

        Un fichier n'est supprimé que si l'audit confirme qu'un remplaçant
        vit dans la vidéothèque. Les fichiers dont le statut est indéterminé
        exigent ``allow_unknown``. Les fichiers sans remplaçant sont toujours
        refusés : le sandbox en détient la seule copie.

        Nettoie les répertoires vides remontant après suppression.

        Args:
            paths: Fichiers à supprimer
            allow_unknown: Autorise la suppression des statuts indéterminés

        Returns:
            DeletionReport (supprimés, refusés avec motif, espace libéré).
        """
        from src.services.sandbox_audit import MISSING, REPLACED, UNKNOWN

        report = DeletionReport()
        for path in paths:
            if not path.exists():
                logger.warning("Fichier déjà absent : {}", path)
                continue
            if not self._is_inside_sandbox(path):
                logger.error("Tentative de suppression hors sandbox : {}", path)
                report.refused.append((path, "hors du sandbox"))
                continue

            audit = self._audit(path)
            if audit is not None:
                if audit.status == MISSING:
                    logger.warning(
                        "Suppression refusée (aucun remplaçant en bibliothèque) : {}",
                        path,
                    )
                    report.refused.append((path, "aucun remplaçant en bibliothèque"))
                    continue
                if audit.status == UNKNOWN and not allow_unknown:
                    logger.info("Suppression refusée (statut indéterminé) : {}", path)
                    report.refused.append((path, "statut indéterminé"))
                    continue
                if audit.status not in (REPLACED, UNKNOWN):
                    report.refused.append((path, f"statut {audit.status}"))
                    continue
                gain = audit.reclaimable_bytes
            else:
                gain = path.stat().st_size

            path.unlink()
            report.deleted += 1
            report.reclaimed_bytes += gain
            logger.info("Supprimé définitivement : {}", path)

        self._cleanup_empty_parents(paths, root=self._sandbox_dir)
        return report

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
