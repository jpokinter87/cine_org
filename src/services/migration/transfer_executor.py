"""
Exécuteur de transferts pour la migration NAS.

Pour chaque MigrationItem du bucket MIGRATE non encore COMMITTED dans le
state store :

1. Calcule le hash xxh3_64 de la source.
2. Si la destination existe déjà avec le même hash (reprise d'une session
   interrompue), saute directement à la finalisation.
3. Sinon lance rsync avec retry sur paliers de bande passante décroissants
   (par défaut 25 → 20 → 15 → 10 → 5 MB/s).
4. Vérifie le hash xxh3_64 de la destination. En cas de mismatch, supprime
   la destination et marque FAILED_VERIFY (la source reste intacte).
5. Si VERIFIED : swap atomique du symlink (os.rename via os.replace) vers
   la nouvelle destination, puis marque COMMITTED.

Important : rsync est invoqué SANS `--remove-source-files`. La source reste
intacte ; le réordonnancement des fichiers se fait uniquement par swap des
symlinks. La suppression effective de la source relève d'une étape
ultérieure (post-validation) et n'est pas du ressort de cet exécuteur.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Protocol

from src.infrastructure.persistence.hash_service import compute_file_hash
from src.services.migration.dataclasses import (
    Bucket,
    MigrationItem,
    MigrationPlan,
    TransferOutcome,
    TransferStatus,
)
from src.services.migration.state_store import MigrationStateStore


_DEFAULT_BANDWIDTH_STEPS_MBPS: tuple[int, ...] = (25, 20, 15, 10, 5)


@dataclass
class RsyncResult:
    """Résultat d'un appel rsync."""

    success: bool
    error: Optional[str] = None


class RsyncRunner(Protocol):
    """Interface minimale pour lancer un rsync. Injectable pour tests."""

    def run(
        self, source: Path, destination: Path, bwlimit_mbps: int
    ) -> RsyncResult: ...


class _SubprocessRsyncRunner:
    """Runner par défaut : appelle l'exécutable `rsync` du système."""

    def run(
        self, source: Path, destination: Path, bwlimit_mbps: int
    ) -> RsyncResult:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                [
                    "rsync",
                    "-a",
                    "--partial",
                    "--inplace",
                    f"--bwlimit={bwlimit_mbps}M",
                    str(source),
                    str(destination),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            return RsyncResult(success=False, error=str(exc))
        if result.returncode == 0:
            return RsyncResult(success=True)
        return RsyncResult(
            success=False,
            error=result.stderr.strip() or f"rsync rc={result.returncode}",
        )


class MigrationTransferExecutor:
    """
    Orchestre les transferts d'un MigrationPlan.

    Args:
        plan: Plan source des items à transférer.
        state_store: Journal SQLite reprenable.
        rsync_runner: Implémentation rsync (par défaut : subprocess).
        bandwidth_steps_mbps: Paliers de bande passante essayés en cas
            d'échec rsync (ordre = ordre des essais).
        hash_fn: Fonction de hash. Par défaut compute_file_hash (xxh3_64).
    """

    def __init__(
        self,
        plan: MigrationPlan,
        state_store: MigrationStateStore,
        rsync_runner: Optional[RsyncRunner] = None,
        bandwidth_steps_mbps: tuple[int, ...] = _DEFAULT_BANDWIDTH_STEPS_MBPS,
        hash_fn: Callable[[Path], str] = compute_file_hash,
    ) -> None:
        self._plan = plan
        self._store = state_store
        self._rsync = rsync_runner or _SubprocessRsyncRunner()
        self._bandwidth_steps = tuple(bandwidth_steps_mbps)
        self._hash_fn = hash_fn

    def execute_all(self) -> list[TransferOutcome]:
        """Itère sur les items pending (non COMMITTED) du plan et les transfère."""
        pending_ids = set(self._store.pending_items())
        outcomes: list[TransferOutcome] = []
        for item in self._plan.items:
            if item.bucket != Bucket.MIGRATE:
                continue
            if item.item_id not in pending_ids:
                continue
            outcomes.append(self.execute_one(item))
        return outcomes

    def execute_one(self, item: MigrationItem) -> TransferOutcome:
        """Transfère un item complet (copy + verify + swap + commit)."""
        if self._store.get_status(item.item_id) == TransferStatus.COMMITTED:
            outcome = self._store.get_outcome(item.item_id)
            assert outcome is not None
            return outcome

        if item.destination_path is None or item.source_path is None:
            self._store.update_status(
                item.item_id,
                TransferStatus.FAILED_OTHER,
                error_message="destination_path ou source_path manquant",
            )
            return self._outcome_or_synthetic(item.item_id, TransferStatus.FAILED_OTHER)

        source = item.source_path
        destination = item.destination_path

        try:
            source_hash = self._hash_fn(source)
        except OSError as exc:
            self._store.update_status(
                item.item_id,
                TransferStatus.FAILED_OTHER,
                error_message=f"lecture source impossible: {exc}",
            )
            return self._outcome_or_synthetic(item.item_id, TransferStatus.FAILED_OTHER)

        # Reprise : destination déjà présente avec le bon hash → finalize direct.
        if destination.exists():
            try:
                existing_hash = self._hash_fn(destination)
            except OSError:
                existing_hash = None
            if existing_hash == source_hash:
                return self._finalize(item, source_hash, existing_hash, destination)

        # Copie via rsync avec retry sur paliers de bande passante.
        last_error: Optional[str] = None
        copied = False
        for bwlimit in self._bandwidth_steps:
            self._store.update_status(item.item_id, TransferStatus.COPYING)
            destination.parent.mkdir(parents=True, exist_ok=True)
            result = self._rsync.run(source, destination, bwlimit)
            if result.success:
                copied = True
                break
            last_error = result.error

        if not copied:
            self._store.update_status(
                item.item_id,
                TransferStatus.FAILED_COPY,
                error_message=last_error or "rsync a échoué sur tous les paliers",
            )
            return self._outcome_or_synthetic(item.item_id, TransferStatus.FAILED_COPY)

        # Vérification d'intégrité.
        bytes_transferred = self._safe_size(destination)
        self._store.update_status(
            item.item_id,
            TransferStatus.COPIED,
            bytes_transferred=bytes_transferred,
        )

        try:
            dest_hash = self._hash_fn(destination)
        except OSError as exc:
            self._store.update_status(
                item.item_id,
                TransferStatus.FAILED_OTHER,
                error_message=f"lecture destination impossible: {exc}",
            )
            return self._outcome_or_synthetic(item.item_id, TransferStatus.FAILED_OTHER)

        if dest_hash != source_hash:
            try:
                destination.unlink()
            except OSError:
                pass
            self._store.update_status(
                item.item_id,
                TransferStatus.FAILED_VERIFY,
                source_hash=source_hash,
                destination_hash=dest_hash,
                error_message="hash mismatch source/destination",
            )
            return self._outcome_or_synthetic(item.item_id, TransferStatus.FAILED_VERIFY)

        return self._finalize(item, source_hash, dest_hash, destination)

    # ---- Helpers --------------------------------------------------------

    def _finalize(
        self,
        item: MigrationItem,
        source_hash: str,
        dest_hash: str,
        destination: Path,
    ) -> TransferOutcome:
        self._store.update_status(
            item.item_id,
            TransferStatus.VERIFIED,
            source_hash=source_hash,
            destination_hash=dest_hash,
            bytes_transferred=self._safe_size(destination),
        )
        try:
            _swap_symlink(item.symlink_path, destination)
        except OSError as exc:
            self._store.update_status(
                item.item_id,
                TransferStatus.FAILED_OTHER,
                error_message=f"swap symlink impossible: {exc}",
            )
            return self._outcome_or_synthetic(item.item_id, TransferStatus.FAILED_OTHER)

        self._store.update_status(item.item_id, TransferStatus.COMMITTED)
        outcome = self._store.get_outcome(item.item_id)
        assert outcome is not None
        return outcome

    def _outcome_or_synthetic(
        self, item_id: str, fallback_status: TransferStatus
    ) -> TransferOutcome:
        existing = self._store.get_outcome(item_id)
        if existing is not None:
            return existing
        return TransferOutcome(item_id=item_id, status=fallback_status)

    @staticmethod
    def _safe_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0


def _swap_symlink(symlink_path: Path, new_target: Path) -> None:
    """
    Remplace le symlink existant par un lien vers `new_target` de manière atomique.

    Implémentation : crée d'abord un symlink temporaire, puis utilise
    `os.replace` (rename atomique sur le même filesystem) pour le substituer
    à l'original. En cas d'erreur entre les deux étapes, l'ancien symlink
    reste intact.
    """
    tmp = symlink_path.with_name(symlink_path.name + ".tmp_swap")
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    os.symlink(new_target, tmp)
    os.replace(tmp, symlink_path)
