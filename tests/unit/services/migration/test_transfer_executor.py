"""
Tests pour MigrationTransferExecutor.

L'executor consomme un MigrationPlan et un MigrationStateStore : pour chaque
item MIGRATE non encore COMMITTED il copie via rsync (sans
--remove-source-files), vérifie l'intégrité via xxh3_64 source/dest, swappe
atomiquement le symlink vers la nouvelle destination, et met à jour le
state_store à chaque transition.

Le RsyncRunner est injecté pour les tests : on simule les succès/échecs
et on copie réellement le fichier dans `on_run` quand on veut un test
d'intégrité réaliste (vrais hashes via compute_file_hash).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import pytest

from src.services.migration.dataclasses import (
    Bucket,
    MigrationItem,
    MigrationPlan,
    MigrationStats,
    RatingDecision,
    TransferStatus,
)
from src.services.migration.state_store import MigrationStateStore
from src.services.migration.transfer_executor import (
    MigrationTransferExecutor,
    RsyncResult,
)


# ---- Fakes ---------------------------------------------------------------


@dataclass
class _Behavior:
    success: bool
    error: Optional[str] = None
    # Callable(source, destination) appelé avant le retour quand success=True
    on_success: Optional[Callable[[Path, Path], None]] = None


class FakeRsync:
    """RsyncRunner factice qui suit un script de comportements par appel."""

    def __init__(self, behaviors: list[_Behavior]) -> None:
        self.calls: list[tuple[Path, Path]] = []
        self._behaviors = list(behaviors)

    def run(
        self,
        source: Path,
        destination: Path,
        on_progress=None,
    ) -> RsyncResult:
        self.calls.append((source, destination))
        if not self._behaviors:
            raise AssertionError("FakeRsync: appel inattendu")
        b = self._behaviors.pop(0)
        if b.success and b.on_success:
            b.on_success(source, destination)
        return RsyncResult(success=b.success, error=b.error)


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _corrupt_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"corrupted-" + source.read_bytes()[:5])


# ---- Fixtures ------------------------------------------------------------


@pytest.fixture
def layout(tmp_path):
    """
    Arborescence test :

      tmp_path/
        old_storage/avatar.mkv     (vraie source, contenu binaire)
        old_video/Films/A/avatar.mkv  -> old_storage/avatar.mkv  (symlink)
        new_storage/                  (cible des copies)
    """
    old_storage = tmp_path / "old_storage"
    old_video = tmp_path / "old_video" / "Films" / "A"
    new_storage = tmp_path / "new_storage"
    old_storage.mkdir(parents=True)
    old_video.mkdir(parents=True)
    new_storage.mkdir(parents=True)

    source_file = old_storage / "avatar.mkv"
    source_file.write_bytes(b"AVATAR_CONTENT_BIN" * 100)

    symlink = old_video / "avatar.mkv"
    symlink.symlink_to(source_file)

    return {
        "old_storage": old_storage,
        "new_storage": new_storage,
        "source_file": source_file,
        "symlink": symlink,
        "destination": new_storage / "Films" / "SF" / "A" / "avatar.mkv",
    }


def _migrate_item(layout, item_id: str = "abc123") -> MigrationItem:
    return MigrationItem(
        item_id=item_id,
        bucket=Bucket.MIGRATE,
        symlink_path=layout["symlink"],
        source_path=layout["source_file"],
        destination_path=layout["destination"],
        media_root="Films",
        relative_category="SF/A",
        size_bytes=layout["source_file"].stat().st_size,
        rating=RatingDecision(value=8.0, source="imdb"),
    )


def _plan(items: list[MigrationItem], layout) -> MigrationPlan:
    return MigrationPlan(
        version=1,
        source_root=Path("/old_video"),
        destination_root=layout["new_storage"],
        threshold=6.0,
        stats=MigrationStats(),
        items=items,
    )


@pytest.fixture
def store(tmp_path):
    return MigrationStateStore(tmp_path / "state.sqlite")


# ---- Happy path ----------------------------------------------------------


def test_executes_one_item_end_to_end(layout, store):
    item = _migrate_item(layout)
    plan = _plan([item], layout)
    store.init_from_plan(plan)
    rsync = FakeRsync([_Behavior(success=True, on_success=_copy_file)])

    executor = MigrationTransferExecutor(
        plan=plan, state_store=store, rsync_runner=rsync
    )
    outcome = executor.execute_one(item)

    assert outcome.status == TransferStatus.COMMITTED
    assert outcome.source_hash == outcome.destination_hash
    assert outcome.source_hash is not None
    assert outcome.bytes_transferred == layout["source_file"].stat().st_size

    # Le state store a bien été mis à jour
    assert store.get_status(item.item_id) == TransferStatus.COMMITTED

    # Le fichier destination existe et a le bon contenu
    assert layout["destination"].exists()
    assert layout["destination"].read_bytes() == layout["source_file"].read_bytes()

    # Le symlink pointe maintenant vers la nouvelle destination (swap atomique)
    assert layout["symlink"].is_symlink()
    assert layout["symlink"].resolve() == layout["destination"].resolve()

    # La source originale est intacte (pas de --remove-source-files)
    assert layout["source_file"].exists()

    # Un seul appel rsync (succès au 1er essai)
    assert len(rsync.calls) == 1


# ---- Retry sur erreur réseau --------------------------------------------


def test_retries_after_rsync_failure_with_pause(layout, store):
    """En cas d'échec rsync, retry jusqu'à max_retries avec pause entre.
    Pause respectée via sleep_fn injectable."""
    item = _migrate_item(layout)
    plan = _plan([item], layout)
    store.init_from_plan(plan)

    rsync = FakeRsync(
        [
            _Behavior(success=False, error="connection reset"),
            _Behavior(success=False, error="connection reset"),
            _Behavior(success=True, on_success=_copy_file),
        ]
    )
    sleep_calls: list[float] = []

    executor = MigrationTransferExecutor(
        plan=plan,
        state_store=store,
        rsync_runner=rsync,
        max_retries=3,
        retry_pause_seconds=30,
        sleep_fn=sleep_calls.append,
    )
    outcome = executor.execute_one(item)

    assert outcome.status == TransferStatus.COMMITTED
    assert len(rsync.calls) == 3
    # 2 pauses entre les 3 essais (pas après le succès final).
    assert sleep_calls == [30, 30]


def test_marks_failed_copy_when_all_retries_fail(layout, store):
    item = _migrate_item(layout)
    plan = _plan([item], layout)
    store.init_from_plan(plan)

    rsync = FakeRsync([_Behavior(success=False, error="fail")] * 3)

    executor = MigrationTransferExecutor(
        plan=plan,
        state_store=store,
        rsync_runner=rsync,
        max_retries=3,
        retry_pause_seconds=0,  # tests rapides
    )
    outcome = executor.execute_one(item)

    assert outcome.status == TransferStatus.FAILED_COPY
    assert "fail" in (outcome.error_message or "")
    assert len(rsync.calls) == 3
    assert store.get_status(item.item_id) == TransferStatus.FAILED_COPY

    # La source est intacte, pas de symlink swap
    assert layout["source_file"].exists()
    assert layout["symlink"].resolve() == layout["source_file"].resolve()
    # Pas de fichier destination orphelin
    assert not layout["destination"].exists()


# ---- Mismatch hash → FAILED_VERIFY + suppression dest -------------------


def test_failed_verify_removes_destination_and_keeps_source_intact(layout, store):
    item = _migrate_item(layout)
    plan = _plan([item], layout)
    store.init_from_plan(plan)

    rsync = FakeRsync([_Behavior(success=True, on_success=_corrupt_copy)])

    executor = MigrationTransferExecutor(
        plan=plan, state_store=store, rsync_runner=rsync
    )
    outcome = executor.execute_one(item)

    assert outcome.status == TransferStatus.FAILED_VERIFY
    assert outcome.source_hash != outcome.destination_hash
    assert outcome.error_message is not None and "hash" in outcome.error_message.lower()

    # Destination supprimée
    assert not layout["destination"].exists()
    # Source intacte
    assert layout["source_file"].exists()
    # Symlink inchangé
    assert layout["symlink"].resolve() == layout["source_file"].resolve()


# ---- Reprise -------------------------------------------------------------


def test_skips_already_committed_item(layout, store):
    item = _migrate_item(layout)
    plan = _plan([item], layout)
    store.init_from_plan(plan)
    store.update_status(item.item_id, TransferStatus.COMMITTED)

    rsync = FakeRsync([])  # ne doit pas être appelé
    executor = MigrationTransferExecutor(
        plan=plan, state_store=store, rsync_runner=rsync
    )
    outcome = executor.execute_one(item)

    assert outcome.status == TransferStatus.COMMITTED
    assert rsync.calls == []


def test_resume_when_destination_already_exists_with_matching_hash(layout, store):
    """Reprise : le fichier a été copié dans une session précédente mais le
    state store n'a pas été mis à jour (crash). On revérifie le hash, et si
    OK on swap directement sans relancer rsync."""
    item = _migrate_item(layout)
    plan = _plan([item], layout)
    store.init_from_plan(plan)

    # Pré-remplit la destination avec le bon contenu
    layout["destination"].parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(layout["source_file"], layout["destination"])

    rsync = FakeRsync([])  # ne doit pas être appelé
    executor = MigrationTransferExecutor(
        plan=plan, state_store=store, rsync_runner=rsync
    )
    outcome = executor.execute_one(item)

    assert outcome.status == TransferStatus.COMMITTED
    assert rsync.calls == []
    assert layout["symlink"].resolve() == layout["destination"].resolve()


def test_resume_when_destination_exists_with_bad_hash_recopies(layout, store):
    """Si la destination existe mais corrompue, on relance rsync."""
    item = _migrate_item(layout)
    plan = _plan([item], layout)
    store.init_from_plan(plan)

    # Pré-remplit la destination avec contenu CORROMPU
    layout["destination"].parent.mkdir(parents=True, exist_ok=True)
    layout["destination"].write_bytes(b"junk")

    rsync = FakeRsync([_Behavior(success=True, on_success=_copy_file)])
    executor = MigrationTransferExecutor(
        plan=plan, state_store=store, rsync_runner=rsync
    )
    outcome = executor.execute_one(item)

    assert outcome.status == TransferStatus.COMMITTED
    assert len(rsync.calls) == 1


# ---- Cas dégénéré : destination_path None -------------------------------


def test_failed_other_when_destination_path_missing(layout, store):
    item = _migrate_item(layout)
    item.destination_path = None  # mauvais plan
    plan = _plan([item], layout)
    store.init_from_plan(plan)

    rsync = FakeRsync([])
    executor = MigrationTransferExecutor(
        plan=plan, state_store=store, rsync_runner=rsync
    )
    outcome = executor.execute_one(item)

    assert outcome.status == TransferStatus.FAILED_OTHER


# ---- execute_all --------------------------------------------------------


def test_execute_all_processes_pending_items_only(layout, store, tmp_path):
    # Deux items : un déjà COMMITTED, un PENDING
    src_b = layout["old_storage"] / "b.mkv"
    src_b.write_bytes(b"BBBB" * 50)
    sym_b = layout["old_storage"].parent / "old_video" / "Films" / "A" / "b.mkv"
    sym_b.parent.mkdir(parents=True, exist_ok=True)
    sym_b.symlink_to(src_b)

    item_a = _migrate_item(layout, item_id="aaa")
    item_b = MigrationItem(
        item_id="bbb",
        bucket=Bucket.MIGRATE,
        symlink_path=sym_b,
        source_path=src_b,
        destination_path=layout["new_storage"] / "Films" / "B" / "b.mkv",
        media_root="Films",
        relative_category="B",
        size_bytes=src_b.stat().st_size,
        rating=RatingDecision(value=7.5),
    )
    plan = _plan([item_a, item_b], layout)
    store.init_from_plan(plan)

    # item_a déjà fait
    store.update_status("aaa", TransferStatus.COMMITTED)

    rsync = FakeRsync([_Behavior(success=True, on_success=_copy_file)])
    executor = MigrationTransferExecutor(
        plan=plan, state_store=store, rsync_runner=rsync
    )
    outcomes = executor.execute_all()

    assert len(outcomes) == 1
    assert outcomes[0].item_id == "bbb"
    assert outcomes[0].status == TransferStatus.COMMITTED
    assert len(rsync.calls) == 1


# ---- Mode raw : RawItemFinalizer (étape 4a) ------------------------------


class _FakeRawFinalizer:
    """RawItemFinalizer factice : enregistre les appels prepare/finalize."""

    def __init__(
        self,
        prepare_destination: Optional[Path] = None,
        prepare_raises: Optional[Exception] = None,
        finalize_raises: Optional[Exception] = None,
    ) -> None:
        self.prepare_calls: list[MigrationItem] = []
        self.finalize_calls: list[tuple[MigrationItem, Path]] = []
        self._destination = prepare_destination
        self._prepare_raises = prepare_raises
        self._finalize_raises = finalize_raises

    def prepare(self, item: MigrationItem) -> Optional[Path]:
        self.prepare_calls.append(item)
        if self._prepare_raises is not None:
            raise self._prepare_raises
        return self._destination

    def finalize(self, item: MigrationItem, destination: Path) -> None:
        self.finalize_calls.append((item, destination))
        if self._finalize_raises is not None:
            raise self._finalize_raises


def _raw_item(layout, item_id: str = "raw1") -> MigrationItem:
    """MigrationItem en mode raw : is_symlink_source=False, destination_path=None."""
    return MigrationItem(
        item_id=item_id,
        bucket=Bucket.MIGRATE,
        symlink_path=layout["source_file"],  # = source physique elle-même
        source_path=layout["source_file"],
        destination_path=None,  # calculée à l'apply via prepare()
        media_root="Films",
        relative_category="",
        size_bytes=layout["source_file"].stat().st_size,
        rating=RatingDecision(value=8.0, source="tmdb"),
        is_symlink_source=False,
    )


def test_raw_item_calls_prepare_then_finalize(layout, store):
    item = _raw_item(layout)
    plan = _plan([item], layout)
    store.init_from_plan(plan)

    canonical_dest = layout["new_storage"] / "Films" / "SF" / "A" / "Avatar.mkv"
    finalizer = _FakeRawFinalizer(prepare_destination=canonical_dest)
    rsync = FakeRsync([_Behavior(success=True, on_success=_copy_file)])

    executor = MigrationTransferExecutor(
        plan=plan,
        state_store=store,
        rsync_runner=rsync,
        raw_finalizer=finalizer,
    )
    outcome = executor.execute_one(item)

    assert outcome.status == TransferStatus.COMMITTED
    # prepare appelé une fois avec l'item raw, retour utilisé comme destination
    assert len(finalizer.prepare_calls) == 1
    assert finalizer.prepare_calls[0] is item
    # finalize appelé une fois avec l'item + destination retournée par prepare
    assert len(finalizer.finalize_calls) == 1
    finalize_item, finalize_dest = finalizer.finalize_calls[0]
    assert finalize_item is item
    assert finalize_dest == canonical_dest
    # Le fichier a bien été copié
    assert canonical_dest.exists()


def test_raw_item_without_finalizer_fails(layout, store):
    """Un item raw sans raw_finalizer → FAILED_OTHER (destination manquante)."""
    item = _raw_item(layout)
    plan = _plan([item], layout)
    store.init_from_plan(plan)

    executor = MigrationTransferExecutor(
        plan=plan, state_store=store, rsync_runner=FakeRsync([])
    )  # pas de raw_finalizer
    outcome = executor.execute_one(item)
    assert outcome.status == TransferStatus.FAILED_OTHER


def test_raw_prepare_failure_marks_failed_other(layout, store):
    item = _raw_item(layout)
    plan = _plan([item], layout)
    store.init_from_plan(plan)

    finalizer = _FakeRawFinalizer(prepare_raises=RuntimeError("DB indisponible"))
    rsync = FakeRsync([])
    executor = MigrationTransferExecutor(
        plan=plan,
        state_store=store,
        rsync_runner=rsync,
        raw_finalizer=finalizer,
    )

    outcome = executor.execute_one(item)
    assert outcome.status == TransferStatus.FAILED_OTHER
    # rsync n'a jamais été appelé : on s'arrête avant la copie.
    assert rsync.calls == []
    assert finalizer.finalize_calls == []


def test_raw_finalize_failure_marks_failed_other(layout, store):
    item = _raw_item(layout)
    plan = _plan([item], layout)
    store.init_from_plan(plan)

    canonical_dest = layout["new_storage"] / "Films" / "SF" / "A" / "Avatar.mkv"
    finalizer = _FakeRawFinalizer(
        prepare_destination=canonical_dest,
        finalize_raises=OSError("permission denied on video/"),
    )
    rsync = FakeRsync([_Behavior(success=True, on_success=_copy_file)])

    executor = MigrationTransferExecutor(
        plan=plan,
        state_store=store,
        rsync_runner=rsync,
        raw_finalizer=finalizer,
    )
    outcome = executor.execute_one(item)

    assert outcome.status == TransferStatus.FAILED_OTHER
    # Le rsync + verify ont eu lieu (canonical_dest existe), mais finalize a explosé.
    assert canonical_dest.exists()
    assert len(finalizer.finalize_calls) == 1


def test_symlink_mode_unchanged_when_no_finalizer_provided(layout, store):
    """Garde-fou : un item symlinks classique reste intact sans raw_finalizer."""
    item = _migrate_item(layout)  # is_symlink_source default True
    plan = _plan([item], layout)
    store.init_from_plan(plan)

    rsync = FakeRsync([_Behavior(success=True, on_success=_copy_file)])
    executor = MigrationTransferExecutor(
        plan=plan, state_store=store, rsync_runner=rsync
    )  # pas de raw_finalizer
    outcome = executor.execute_one(item)

    assert outcome.status == TransferStatus.COMMITTED
    # Le symlink a bien été swappé vers la nouvelle destination.
    assert layout["symlink"].is_symlink()
    assert layout["symlink"].resolve() == layout["destination"].resolve()


# ---- Mode --fast : verify_hash=False -------------------------------------


def test_fast_mode_skips_source_and_dest_hashing(layout, store):
    """Mode --fast : aucun hash n'est calculé, on fait confiance à rsync."""
    item = _migrate_item(layout)
    plan = _plan([item], layout)
    store.init_from_plan(plan)

    # hash_fn qui lève si appelé : prouve qu'il n'est jamais invoqué.
    def _hash_must_not_be_called(_path):
        raise AssertionError("hash_fn ne doit pas être appelé en mode --fast")

    rsync = FakeRsync([_Behavior(success=True, on_success=_copy_file)])
    executor = MigrationTransferExecutor(
        plan=plan,
        state_store=store,
        rsync_runner=rsync,
        verify_hash=False,
        hash_fn=_hash_must_not_be_called,
    )
    outcome = executor.execute_one(item)

    assert outcome.status == TransferStatus.COMMITTED
    # source_hash et destination_hash restent vides (pas de verify)
    assert outcome.source_hash == ""
    assert outcome.destination_hash == ""
    # Mais le fichier est bien copié et le symlink swappé
    assert layout["destination"].exists()
    assert layout["symlink"].resolve() == layout["destination"].resolve()


def test_fast_mode_resume_skips_when_destination_size_matches(layout, store):
    """Mode --fast : si destination existe avec la même taille, on saute rsync."""
    item = _migrate_item(layout)
    plan = _plan([item], layout)
    store.init_from_plan(plan)

    # Pré-remplit la destination avec un fichier de MÊME taille (contenu peu importe
    # en mode --fast, c'est la taille qui sert d'indicateur de reprise).
    layout["destination"].parent.mkdir(parents=True, exist_ok=True)
    source_size = layout["source_file"].stat().st_size
    layout["destination"].write_bytes(b"X" * source_size)

    rsync = FakeRsync([])  # ne doit pas être appelé
    executor = MigrationTransferExecutor(
        plan=plan,
        state_store=store,
        rsync_runner=rsync,
        verify_hash=False,
    )
    outcome = executor.execute_one(item)

    assert outcome.status == TransferStatus.COMMITTED
    assert rsync.calls == []  # reprise sans nouveau transfert
    assert layout["symlink"].resolve() == layout["destination"].resolve()


# ---- Tag delete_source_after_commit --------------------------------------


def test_delete_source_after_commit_tag_removes_source_post_commit(
    layout, store, tmp_path
):
    """Tag 'delete_source_after_commit' → source supprimée après COMMITTED."""
    item = _migrate_item(layout)
    item.tags = ["delete_source_after_commit"]
    plan = _plan([item], layout)
    store.init_from_plan(plan)
    rsync = FakeRsync([_Behavior(success=True, on_success=_copy_file)])

    executor = MigrationTransferExecutor(
        plan=plan, state_store=store, rsync_runner=rsync,
    )
    outcome = executor.execute_one(item)
    assert outcome.status == TransferStatus.COMMITTED
    # Source supprimée
    assert not layout["source_file"].exists()
    # Mais destination intacte
    assert layout["destination"].exists()


def test_no_tag_keeps_source_intact(layout, store):
    """Sans tag, comportement standard : source intacte."""
    item = _migrate_item(layout)
    plan = _plan([item], layout)
    store.init_from_plan(plan)
    rsync = FakeRsync([_Behavior(success=True, on_success=_copy_file)])

    executor = MigrationTransferExecutor(
        plan=plan, state_store=store, rsync_runner=rsync,
    )
    executor.execute_one(item)
    assert layout["source_file"].exists()  # intacte (mode symlinks default)
