"""
Tests pour MigrationStateStore.

Le state store persiste l'état d'avancement de la migration dans une base
SQLite locale (séparée de la DB CineOrg principale). Il permet de reprendre
une migration interrompue en sautant les items déjà COMMITTED, et de relancer
les items en échec après diagnostic.

Seuls les items du bucket MIGRATE sont enregistrés (les autres buckets sont
informatifs et n'ont pas vocation à être transférés).
"""

from __future__ import annotations

from pathlib import Path

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


# ---- Fixtures -----------------------------------------------------------


def _migrate_item(item_id: str, name: str = "x.mkv") -> MigrationItem:
    return MigrationItem(
        item_id=item_id,
        bucket=Bucket.MIGRATE,
        symlink_path=Path(f"/old/{name}"),
        source_path=Path(f"/old_storage/{name}"),
        destination_path=Path(f"/new_storage/{name}"),
        media_root="Films",
        relative_category="Drame/X",
        size_bytes=1000,
        rating=RatingDecision(value=8.0, source="imdb"),
    )


def _broken_item(item_id: str) -> MigrationItem:
    return MigrationItem(
        item_id=item_id,
        bucket=Bucket.BROKEN,
        symlink_path=Path("/old/missing.mkv"),
        source_path=None,
        destination_path=None,
        media_root="Films",
        relative_category="X",
        size_bytes=None,
        rating=RatingDecision(),
    )


def _plan(items: list[MigrationItem]) -> MigrationPlan:
    return MigrationPlan(
        version=1,
        source_root=Path("/old"),
        destination_root=Path("/new"),
        threshold=6.0,
        stats=MigrationStats(),
        items=items,
    )


@pytest.fixture
def store(tmp_path):
    return MigrationStateStore(tmp_path / "state.sqlite")


# ---- init_from_plan ------------------------------------------------------


def test_init_from_plan_inserts_migrate_items_as_pending(store):
    plan = _plan([_migrate_item("a"), _migrate_item("b", "y.mkv")])
    store.init_from_plan(plan)

    assert store.get_status("a") == TransferStatus.PENDING
    assert store.get_status("b") == TransferStatus.PENDING


def test_init_from_plan_skips_non_migrate_items(store):
    plan = _plan([_migrate_item("a"), _broken_item("b")])
    store.init_from_plan(plan)

    assert store.get_status("a") == TransferStatus.PENDING
    assert store.get_status("b") is None


def test_init_from_plan_is_idempotent(store):
    plan = _plan([_migrate_item("a")])
    store.init_from_plan(plan)
    store.update_status("a", TransferStatus.COMMITTED)

    # Re-init ne doit pas écraser le statut existant
    store.init_from_plan(plan)
    assert store.get_status("a") == TransferStatus.COMMITTED


def test_init_from_plan_adds_new_items_on_replan(store):
    """Un re-plan qui ajoute de nouveaux items doit les insérer en PENDING."""
    store.init_from_plan(_plan([_migrate_item("a")]))
    store.update_status("a", TransferStatus.COMMITTED)

    store.init_from_plan(_plan([_migrate_item("a"), _migrate_item("b", "y.mkv")]))
    assert store.get_status("a") == TransferStatus.COMMITTED
    assert store.get_status("b") == TransferStatus.PENDING


# ---- get_status / get_outcome -------------------------------------------


def test_get_status_returns_none_for_unknown_item(store):
    assert store.get_status("inconnu") is None


def test_get_outcome_returns_none_for_unknown_item(store):
    assert store.get_outcome("inconnu") is None


def test_get_outcome_after_update_returns_full_record(store):
    plan = _plan([_migrate_item("a")])
    store.init_from_plan(plan)
    store.update_status(
        "a",
        TransferStatus.VERIFIED,
        source_hash="cafebabe",
        destination_hash="cafebabe",
        bytes_transferred=1024,
    )

    outcome = store.get_outcome("a")
    assert outcome is not None
    assert outcome.item_id == "a"
    assert outcome.status == TransferStatus.VERIFIED
    assert outcome.source_hash == "cafebabe"
    assert outcome.destination_hash == "cafebabe"
    assert outcome.bytes_transferred == 1024
    assert outcome.error_message is None


# ---- update_status ------------------------------------------------------


def test_update_status_overwrites_previous_status(store):
    plan = _plan([_migrate_item("a")])
    store.init_from_plan(plan)

    store.update_status("a", TransferStatus.COPYING)
    assert store.get_status("a") == TransferStatus.COPYING

    store.update_status("a", TransferStatus.COPIED)
    assert store.get_status("a") == TransferStatus.COPIED


def test_update_status_records_error_message_for_failures(store):
    plan = _plan([_migrate_item("a")])
    store.init_from_plan(plan)

    store.update_status(
        "a",
        TransferStatus.FAILED_VERIFY,
        error_message="hash mismatch source/dest",
    )
    outcome = store.get_outcome("a")
    assert outcome is not None
    assert outcome.status == TransferStatus.FAILED_VERIFY
    assert outcome.error_message == "hash mismatch source/dest"


def test_update_status_creates_row_if_missing(store):
    """Tolérant : si l'item n'a pas été inséré par init_from_plan
    (ex. ajout dynamique), update_status le crée."""
    store.update_status("orphan", TransferStatus.COMMITTED)
    assert store.get_status("orphan") == TransferStatus.COMMITTED


# ---- pending_items ------------------------------------------------------


def test_pending_items_excludes_committed(store):
    plan = _plan(
        [
            _migrate_item("a"),
            _migrate_item("b", "b.mkv"),
            _migrate_item("c", "c.mkv"),
        ]
    )
    store.init_from_plan(plan)
    store.update_status("b", TransferStatus.COMMITTED)

    pending = sorted(store.pending_items())
    assert pending == ["a", "c"]


def test_pending_items_includes_failures_for_retry(store):
    """Les items FAILED_* doivent rester dans pending_items pour permettre
    la reprise après diagnostic / correction."""
    plan = _plan([_migrate_item("a"), _migrate_item("b", "b.mkv")])
    store.init_from_plan(plan)
    store.update_status("a", TransferStatus.FAILED_COPY, error_message="disk full")
    store.update_status("b", TransferStatus.COMMITTED)

    assert sorted(store.pending_items()) == ["a"]


def test_pending_items_empty_when_all_committed(store):
    plan = _plan([_migrate_item("a")])
    store.init_from_plan(plan)
    store.update_status("a", TransferStatus.COMMITTED)
    assert list(store.pending_items()) == []


# ---- summary ------------------------------------------------------------


def test_summary_groups_by_status(store):
    plan = _plan(
        [
            _migrate_item("a"),
            _migrate_item("b", "b.mkv"),
            _migrate_item("c", "c.mkv"),
            _migrate_item("d", "d.mkv"),
        ]
    )
    store.init_from_plan(plan)
    store.update_status("b", TransferStatus.COMMITTED)
    store.update_status("c", TransferStatus.COMMITTED)
    store.update_status("d", TransferStatus.FAILED_VERIFY, error_message="x")

    summary = store.summary()
    assert summary[TransferStatus.PENDING] == 1
    assert summary[TransferStatus.COMMITTED] == 2
    assert summary[TransferStatus.FAILED_VERIFY] == 1
    assert summary.get(TransferStatus.COPYING, 0) == 0


# ---- Persistance disque -------------------------------------------------


def test_state_persists_across_store_instances(tmp_path):
    db_path = tmp_path / "state.sqlite"
    store1 = MigrationStateStore(db_path)
    store1.init_from_plan(_plan([_migrate_item("a")]))
    store1.update_status("a", TransferStatus.COMMITTED)
    store1.close()

    store2 = MigrationStateStore(db_path)
    assert store2.get_status("a") == TransferStatus.COMMITTED
