"""
Exécuteur de transferts pour la migration NAS.

Pour chaque MigrationItem du bucket MIGRATE non encore COMMITTED dans le
state store :

1. Calcule le hash xxh3_64 (échantillonné) de la source.
2. Si la destination existe déjà avec le même hash (reprise d'une session
   interrompue), saute directement à la finalisation.
3. Sinon lance rsync avec retry après pause (par défaut 3 essais espacés
   de 30 s) — `--inplace --partial` reprend où le précédent s'est arrêté.
4. Vérifie le hash xxh3_64 (échantillonné) de la destination. En cas de
   mismatch, supprime la destination et marque FAILED_VERIFY (source intacte).
5. Si VERIFIED : finalisation selon le mode :
   - Mode symlinks (`is_symlink_source=True`) : swap atomique du symlink
     (os.rename via os.replace) vers la nouvelle destination. Source intacte.
   - Mode raw (`is_symlink_source=False`) : delegation a un `RawItemFinalizer`
     qui insere le VideoFile en DB, cree le symlink dans video/ canonique,
     et supprime la source physique apres verify.
6. Marque COMMITTED.

⚠️  Limites du hash xxh3_64
---------------------------
`compute_file_hash` (dans `src/infrastructure/persistence/hash_service.py`)
est un hash **échantillonné** : 1 Mo en tête + 1 Mo en queue + taille du
fichier (pas le contenu complet). Sa fonction principale est la **détection
de doublons rapide**, pas la garantie d'intégrité bit-à-bit.

Conséquence pour la migration : un flip de bit dans la partie centrale d'un
fichier multi-Go passerait inaperçu pour ce hash. Le vrai filet de sécurité
est le **checksum rolling MD5 interne de rsync** (calculé bloc par bloc
pendant le transfert), qui valide réellement le contenu intégral. Le hash
xxh3_64 échantillonné reste utile pour :
- détecter une corruption catastrophique (taille différente, header altéré),
- accélérer la reprise (skip si destination identique d'une session précédente).

Pour un transfert réseau fiable + filesystem journalisé, c'est suffisant en
pratique. Pour des transferts entre disques peu fiables, envisager d'ajouter
une vérification SHA-256 streaming complète post-transfert.

Important : rsync est invoqué SANS `--remove-source-files`. En mode symlinks,
la source reste intacte. En mode raw, la suppression source explicite est
faite par le finalizer apres verify hash, donc atomiquement non blocante.
"""

from __future__ import annotations

import os
import re
import time
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Protocol

from loguru import logger

from src.infrastructure.persistence.hash_service import compute_file_hash
from src.services.migration.dataclasses import (
    Bucket,
    MigrationItem,
    MigrationPlan,
    TransferOutcome,
    TransferStatus,
)
from src.services.migration.state_store import MigrationStateStore


# Stratégie retry simple : le rsync tourne sans bwlimit (vitesse max). En
# cas d'échec on retente N fois avec une pause entre chaque (le NAS de
# destination a souvent besoin d'une fenêtre pour évacuer son cache write
# avant d'accepter une nouvelle session). Plus pertinent qu'une cascade
# de paliers dégressifs : la grande majorité des échecs réseau/NAS sont
# transitoires (timeout NFS, fsync long), pas une saturation de débit.
_DEFAULT_MAX_RETRIES: int = 3
_DEFAULT_RETRY_PAUSE_SECONDS: int = 30
# Timeout rsync en secondes : déconnecte si aucun paquet pendant N sec.
# Évite les hangs lors d'un fsync long côté NAS — l'erreur est propagée,
# le retry suivant tente sa chance.
_DEFAULT_RSYNC_TIMEOUT_SECONDS: int = 300


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
        on_progress: Optional[RsyncProgress] = None,
    ) -> RsyncResult:
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Wrappe le callback : le `bytes_done` extrait de --info=progress2
        # est le compteur volatile de CETTE instance rsync, qui repart à 0
        # à chaque nouvelle invocation (retry, reprise après interruption).
        # On remplace par la taille réelle du fichier dest sur disque, qui
        # reflète l'état persistent via --inplace --partial.
        rsync_cb = on_progress
        if on_progress is not None:
            def _stat_wrapper(_bytes_done: int, percent: int, speed: str) -> None:
                try:
                    real = destination.stat().st_size
                except OSError:
                    real = _bytes_done
                on_progress(real, percent, speed)
            rsync_cb = _stat_wrapper

        # Pas de `-a` (= -rlptgoD) : sur un NAS NFS, la préservation owner/
        # group/perms échoue souvent (mapping uid foireux, ACL refusées) et
        # rsync sort en rc=23 même quand le contenu est intégralement copié.
        # Pour notre cas (migration 1 fichier vers NAS qui gère ses propres
        # permissions), on n'a besoin de rien de tout cela.
        cmd = [
            "rsync",
            "--partial",
            "--inplace",
            "--info=progress2",
            f"--timeout={_DEFAULT_RSYNC_TIMEOUT_SECONDS}",
            str(source),
            str(destination),
        ]
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
        # try/finally garantit qu'un Ctrl-C ne laisse pas de processus rsync
        # zombie : --inplace peut laisser un fichier partiel sur disque, le
        # prochain run reprendra via la branche "destination existe".
        buffer = bytearray()
        last_line = ""  # Conservée pour le diagnostic en cas d'échec
        assert process.stdout is not None
        try:
            while True:
                chunk = process.stdout.read(64)
                if not chunk:
                    break
                for byte in chunk:
                    if byte in (10, 13):  # \n or \r
                        if buffer:
                            decoded = buffer.decode("utf-8", errors="replace")
                            last_line = decoded
                            if rsync_cb is not None:
                                _parse_and_emit_progress(decoded, rsync_cb)
                        buffer.clear()
                    else:
                        buffer.append(byte)
            if buffer:
                decoded = buffer.decode("utf-8", errors="replace")
                last_line = decoded
                if rsync_cb is not None:
                    _parse_and_emit_progress(decoded, rsync_cb)

            process.wait()
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
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
    except Exception as exc:  # noqa: BLE001 — UI ne doit jamais casser le transfert
        logger.warning("Callback rsync progress a levé une exception : {}", exc)


class MigrationTransferExecutor:
    """
    Orchestre les transferts d'un MigrationPlan.

    Args:
        plan: Plan source des items à transférer.
        state_store: Journal SQLite reprenable.
        rsync_runner: Implémentation rsync (par défaut : subprocess).
        max_retries: Nombre total d'essais rsync par fichier en cas
            d'échec (1 = pas de retry).
        retry_pause_seconds: Pause entre deux essais (laisse au NAS le
            temps d'évacuer son cache write avant la nouvelle session).
        hash_fn: Fonction de hash. Par défaut compute_file_hash (xxh3_64).
        sleep_fn: time.sleep par défaut. Injectable pour les tests.
    """

    def __init__(
        self,
        plan: MigrationPlan,
        state_store: MigrationStateStore,
        rsync_runner: Optional[RsyncRunner] = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_pause_seconds: int = _DEFAULT_RETRY_PAUSE_SECONDS,
        hash_fn: Callable[[Path], str] = compute_file_hash,
        raw_finalizer: Optional[RawItemFinalizer] = None,
        on_event: Optional[Callable[[MigrationItem, str], None]] = None,
        on_rsync_progress: Optional[
            Callable[[MigrationItem, int, int, str], None]
        ] = None,
        verify_hash: bool = True,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._plan = plan
        self._store = state_store
        self._rsync = rsync_runner or _SubprocessRsyncRunner()
        self._max_retries = max(1, int(max_retries))
        self._retry_pause_seconds = max(0, int(retry_pause_seconds))
        self._sleep = sleep_fn
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
            except Exception as exc:  # noqa: BLE001 — UI ne doit jamais casser le transfert
                logger.warning(
                    "Callback on_event(phase={!r}) a levé une exception : {}",
                    phase,
                    exc,
                )

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

        # Copie via rsync : un essai à plein débit, puis N-1 retries après
        # pause si échec. Avec --inplace --partial chaque retry reprend où
        # le précédent s'est arrêté (pas de re-transfert depuis zéro).
        last_error: Optional[str] = None
        copied = False

        def _rsync_progress_for_item(
            bytes_done: int, percent: int, speed: str
        ) -> None:
            if self._on_rsync_progress is not None:
                try:
                    self._on_rsync_progress(item, bytes_done, percent, speed)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Callback on_rsync_progress a levé une exception : {}",
                        exc,
                    )

        for attempt in range(1, self._max_retries + 1):
            self._store.update_status(item.item_id, TransferStatus.COPYING)
            self._emit(item, f"copying_attempt_{attempt}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            result = self._rsync.run(
                source,
                destination,
                on_progress=_rsync_progress_for_item,
            )
            if result.success:
                copied = True
                break
            last_error = result.error
            if last_error:
                truncated = last_error[:120].replace("\n", " ")
                self._emit(item, f"rsync_error:{truncated}")
            # Pause avant le prochain essai (NAS récupère son cache).
            if attempt < self._max_retries and self._retry_pause_seconds > 0:
                self._emit(
                    item, f"retry_pause_{self._retry_pause_seconds}s"
                )
                self._sleep(self._retry_pause_seconds)

        if not copied:
            self._store.update_status(
                item.item_id,
                TransferStatus.FAILED_COPY,
                error_message=(
                    last_error
                    or f"rsync a échoué après {self._max_retries} essai(s)"
                ),
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

        # Post-commit cleanup : honor tag delete_source_after_commit
        # (posé par run_apply depuis Decision.delete_source_after).
        if "delete_source_after_commit" in item.tags:
            self._post_commit_delete_source(item)

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

    def _post_commit_delete_source(self, item: MigrationItem) -> None:
        """Supprime la source physique après COMMITTED.

        Honore le tag `delete_source_after_commit` posé par
        `_apply_decisions_to_plan` depuis `Decision.delete_source_after`.
        Idempotent (FileNotFoundError ignoré). Logue toujours, n'échoue jamais
        le transfert (OSError → warning).
        """
        if item.source_path is None:
            return
        try:
            item.source_path.unlink()
            logger.info(
                "Source supprimée post-commit (delete_source_after_commit) : {}",
                item.source_path,
            )
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning(
                "Échec suppression source post-commit pour {} : {}",
                item.source_path, exc,
            )

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
