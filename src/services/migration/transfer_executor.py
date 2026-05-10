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
5. Si VERIFIED : finalisation selon le mode :
   - Mode symlinks (`is_symlink_source=True`) : swap atomique du symlink
     (os.rename via os.replace) vers la nouvelle destination. Source intacte.
   - Mode raw (`is_symlink_source=False`) : delegation a un `RawItemFinalizer`
     qui insere le VideoFile en DB, cree le symlink dans video/ canonique,
     et supprime la source physique apres verify.
6. Marque COMMITTED.

Important : rsync est invoqué SANS `--remove-source-files`. En mode symlinks,
la source reste intacte. En mode raw, la suppression source explicite est
faite par le finalizer apres verify hash, donc atomiquement non blocante.
"""

from __future__ import annotations

import os
import re
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


# 0 = pas de limite (vitesse max disque/réseau). Si rsync échoue (timeout
# réseau, peer reset…), on retombe sur des paliers dégressifs pour
# accommoder un lien saturé. Pour un transfert local rapide (cas usuel
# de la migration depuis un disque externe), le 1er essai sans bwlimit
# fait le job en quelques secondes au lieu de quelques minutes.
_DEFAULT_BANDWIDTH_STEPS_MBPS: tuple[int, ...] = (0, 50, 25, 10, 5)


@dataclass
class RsyncResult:
    """Résultat d'un appel rsync."""

    success: bool
    error: Optional[str] = None


class RsyncProgress(Protocol):
    """Callback invoqué pendant rsync à chaque ligne de progression.

    Args:
        bytes_done: Octets transférés à ce point.
        percent: Pourcentage (0-100).
        speed: Vitesse formattée (ex: "42.05MB/s").
    """

    def __call__(self, bytes_done: int, percent: int, speed: str) -> None: ...


class RsyncRunner(Protocol):
    """Interface minimale pour lancer un rsync. Injectable pour tests."""

    def run(
        self,
        source: Path,
        destination: Path,
        bwlimit_mbps: int,
        on_progress: Optional[RsyncProgress] = None,
    ) -> RsyncResult: ...


class RawItemFinalizer(Protocol):
    """
    Finalise un item raw (fichier physique) apres verify hash.

    `prepare` est appele avant rsync : il doit retourner le chemin de
    destination canonique sur le nouveau storage. Cela inclut typiquement
    l'insert/upsert Movie/Series en DB pour pouvoir calculer le chemin via
    OrganizerService + RenamerService.

    `finalize` est appele apres verify hash succes : il insere le
    VideoFileModel en DB, cree le symlink dans video/ canonique, et
    supprime le fichier source physique. Doit etre idempotent (appel
    repete sur un item deja finalise = no-op silencieux).
    """

    def prepare(self, item: MigrationItem) -> Optional[Path]: ...

    def finalize(self, item: MigrationItem, destination: Path) -> None: ...


# rsync --info=progress2 produit des lignes type :
#   "      87,121,920  10%   42.05MB/s    0:00:11  (xfr#1, to-chk=0/1)"
# Locale-dependent : selon la locale système, les milliers peuvent être
# séparés par "," (en_US, C) ou "." (fr_FR, de_DE…). Idem pour la
# virgule/point décimal de la vitesse. On accepte les deux dans la
# capture du nombre d'octets, et on nettoie les séparateurs avant int().
# Ces lignes sont séparées par \r (carriage return) pour overwrite la
# même ligne au terminal.
_PROGRESS2_LINE = re.compile(
    r"^\s*([\d.,]+)\s+(\d+)%\s+(\S+)"
)


class _SubprocessRsyncRunner:
    """Runner par défaut : appelle l'exécutable `rsync` du système.

    Utilise `rsync --info=progress2` pour extraire bytes/percent/vitesse en
    temps réel et les transmettre via le callback `on_progress` (utile pour
    actualiser une barre Rich pendant les transferts longs).
    """

    def run(
        self,
        source: Path,
        destination: Path,
        bwlimit_mbps: int,
        on_progress: Optional[RsyncProgress] = None,
    ) -> RsyncResult:
        destination.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["rsync", "-a", "--partial", "--inplace", "--info=progress2"]
        if bwlimit_mbps > 0:
            cmd.append(f"--bwlimit={bwlimit_mbps}M")
        cmd.extend([str(source), str(destination)])
        try:
            # stderr=STDOUT : merge stderr dans stdout pour éviter le
            # blocage classique de Popen quand stderr remplit son buffer
            # OS (~64 KB) sans qu'on le consomme. Les éventuels messages
            # d'erreur rsync atterrissent dans le même flux que progress2 ;
            # le parser regex ignore silencieusement les lignes non-progress.
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
            )
        except FileNotFoundError as exc:
            return RsyncResult(success=False, error=str(exc))

        # Stream stdout, parser chaque \r ou \n comme une ligne potentielle
        # (rsync --info=progress2 émet du \r pour overwrite la même ligne).
        buffer = bytearray()
        last_line = ""  # Conservée pour le diagnostic en cas d'échec
        assert process.stdout is not None
        while True:
            chunk = process.stdout.read(64)
            if not chunk:
                break
            for byte in chunk:
                if byte in (10, 13):  # \n or \r
                    if buffer:
                        decoded = buffer.decode("utf-8", errors="replace")
                        last_line = decoded
                        if on_progress is not None:
                            _parse_and_emit_progress(decoded, on_progress)
                    buffer.clear()
                else:
                    buffer.append(byte)
        if buffer:
            decoded = buffer.decode("utf-8", errors="replace")
            last_line = decoded
            if on_progress is not None:
                _parse_and_emit_progress(decoded, on_progress)

        process.wait()
        if process.returncode == 0:
            return RsyncResult(success=True)
        return RsyncResult(
            success=False,
            error=(last_line or "").strip() or f"rsync rc={process.returncode}",
        )


def _parse_and_emit_progress(line: str, on_progress: RsyncProgress) -> None:
    """Parse une ligne rsync --info=progress2 et invoque le callback si match."""
    match = _PROGRESS2_LINE.match(line)
    if match is None:
        return
    # Nettoie les séparateurs de milliers : "," (locale en_US/C) ou "."
    # (locale fr_FR/de_DE/…). int() ne tolère ni l'un ni l'autre.
    raw = match.group(1).replace(",", "").replace(".", "").replace(" ", "")
    try:
        bytes_done = int(raw)
        percent = int(match.group(2))
    except ValueError:
        return
    speed = match.group(3)
    try:
        on_progress(bytes_done, percent, speed)
    except Exception:  # noqa: BLE001 — UI ne doit jamais casser le transfert
        pass


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
        raw_finalizer: Optional[RawItemFinalizer] = None,
        on_event: Optional[Callable[[MigrationItem, str], None]] = None,
        on_rsync_progress: Optional[
            Callable[[MigrationItem, int, int, str], None]
        ] = None,
        verify_hash: bool = True,
    ) -> None:
        self._plan = plan
        self._store = state_store
        self._rsync = rsync_runner or _SubprocessRsyncRunner()
        self._bandwidth_steps = tuple(bandwidth_steps_mbps)
        self._hash_fn = hash_fn
        self._raw_finalizer = raw_finalizer
        self._on_event = on_event
        self._on_rsync_progress = on_rsync_progress
        # Si False : skip xxh3_64 source+dest (gain de ~2 lectures complètes
        # par fichier). Les checksums internes de rsync (rolling hash MD5)
        # restent actifs et garantissent l'intégrité du transfert. La reprise
        # se base alors sur la taille du fichier au lieu du hash.
        self._verify_hash = verify_hash

    def _emit(self, item: MigrationItem, phase: str) -> None:
        """Notifie un changement de phase (utile pour la barre de progression CLI)."""
        if self._on_event is not None:
            try:
                self._on_event(item, phase)
            except Exception:  # noqa: BLE001 — UI ne doit jamais casser le transfert
                pass

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
        """Transfère un item complet (copy + verify + finalize + commit)."""
        if self._store.get_status(item.item_id) == TransferStatus.COMMITTED:
            outcome = self._store.get_outcome(item.item_id)
            assert outcome is not None
            return outcome

        self._emit(item, "start")

        if item.source_path is None:
            self._store.update_status(
                item.item_id,
                TransferStatus.FAILED_OTHER,
                error_message="source_path manquant",
            )
            return self._outcome_or_synthetic(item.item_id, TransferStatus.FAILED_OTHER)

        # Mode raw : la destination canonique est calculee a l'apply via le
        # finalizer (pas presente dans le plan).
        destination = item.destination_path
        if destination is None:
            if not item.is_symlink_source and self._raw_finalizer is not None:
                self._emit(item, "preparing")
                try:
                    destination = self._raw_finalizer.prepare(item)
                except Exception as exc:  # noqa: BLE001 — le finalizer remonte
                    self._store.update_status(
                        item.item_id,
                        TransferStatus.FAILED_OTHER,
                        error_message=f"prepare raw destination échoué: {exc}",
                    )
                    return self._outcome_or_synthetic(
                        item.item_id, TransferStatus.FAILED_OTHER
                    )
            if destination is None:
                self._store.update_status(
                    item.item_id,
                    TransferStatus.FAILED_OTHER,
                    error_message="destination_path manquant",
                )
                return self._outcome_or_synthetic(
                    item.item_id, TransferStatus.FAILED_OTHER
                )

        source = item.source_path

        if self._verify_hash:
            self._emit(item, "hashing_source")
            try:
                source_hash: Optional[str] = self._hash_fn(source)
            except OSError as exc:
                self._store.update_status(
                    item.item_id,
                    TransferStatus.FAILED_OTHER,
                    error_message=f"lecture source impossible: {exc}",
                )
                return self._outcome_or_synthetic(
                    item.item_id, TransferStatus.FAILED_OTHER
                )
        else:
            source_hash = None

        # Reprise : destination déjà présente
        if destination.exists():
            if self._verify_hash:
                self._emit(item, "hashing_existing")
                try:
                    existing_hash: Optional[str] = self._hash_fn(destination)
                except OSError:
                    existing_hash = None
                if existing_hash == source_hash:
                    return self._finalize(
                        item, source_hash or "", existing_hash, destination
                    )
            else:
                # Mode --fast : reprise basée sur la taille (suppose qu'un
                # rsync précédent a achevé le transfert si tailles match).
                try:
                    if (
                        destination.stat().st_size == source.stat().st_size
                        and source.stat().st_size > 0
                    ):
                        return self._finalize(item, "", "", destination)
                except OSError:
                    pass

        # Copie via rsync avec retry sur paliers de bande passante.
        last_error: Optional[str] = None
        copied = False

        def _rsync_progress_for_item(
            bytes_done: int, percent: int, speed: str
        ) -> None:
            if self._on_rsync_progress is not None:
                try:
                    self._on_rsync_progress(item, bytes_done, percent, speed)
                except Exception:  # noqa: BLE001
                    pass

        for bwlimit in self._bandwidth_steps:
            self._store.update_status(item.item_id, TransferStatus.COPYING)
            self._emit(item, f"copying_{bwlimit}mbps")
            destination.parent.mkdir(parents=True, exist_ok=True)
            result = self._rsync.run(
                source,
                destination,
                bwlimit,
                on_progress=_rsync_progress_for_item,
            )
            if result.success:
                copied = True
                break
            last_error = result.error
            # Notifie l'erreur pour que l'utilisateur voie pourquoi on retente
            # (au prochain palier) — utile pour debug.
            if last_error:
                truncated = last_error[:120].replace("\n", " ")
                self._emit(item, f"rsync_error:{truncated}")

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

        if self._verify_hash:
            self._emit(item, "verifying")
            try:
                dest_hash: Optional[str] = self._hash_fn(destination)
            except OSError as exc:
                self._store.update_status(
                    item.item_id,
                    TransferStatus.FAILED_OTHER,
                    error_message=f"lecture destination impossible: {exc}",
                )
                return self._outcome_or_synthetic(
                    item.item_id, TransferStatus.FAILED_OTHER
                )

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
                return self._outcome_or_synthetic(
                    item.item_id, TransferStatus.FAILED_VERIFY
                )
        else:
            # Mode --fast : on fait confiance aux checksums internes de rsync
            # (rolling MD5) qui ont déjà validé le transfert bloc par bloc.
            dest_hash = None

        return self._finalize(
            item,
            source_hash or "",
            dest_hash or "",
            destination,
        )

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
        self._emit(item, "finalizing")

        try:
            if item.is_symlink_source:
                _swap_symlink(item.symlink_path, destination)
            else:
                if self._raw_finalizer is None:
                    raise RuntimeError(
                        "raw_finalizer requis pour finaliser un item raw"
                    )
                self._raw_finalizer.finalize(item, destination)
        except (OSError, RuntimeError) as exc:
            self._store.update_status(
                item.item_id,
                TransferStatus.FAILED_OTHER,
                error_message=f"finalisation impossible: {exc}",
            )
            return self._outcome_or_synthetic(item.item_id, TransferStatus.FAILED_OTHER)

        self._store.update_status(item.item_id, TransferStatus.COMMITTED)
        self._emit(item, "committed")
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
