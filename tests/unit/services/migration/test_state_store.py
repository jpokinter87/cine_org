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

from datetime import datetime, timezone
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
from src.services.migration.decisions import (
    Decision,
    DecisionStatus,
    DuplicateAction,
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


# ---- Décisions de review (phase 44.1) -----------------------------------


def _decision(item_id: str = "abc", **overrides) -> Decision:
    base = dict(
        item_id=item_id,
        bucket_origin="needs_validation",
        decision=DecisionStatus.APPROVED,
        chosen_tmdb_id=19995,
        chosen_title="Avatar",
        chosen_year=2009,
        chosen_score=95.0,
        decided_at=datetime.now(timezone.utc),
        decided_via="cli",
    )
    base.update(overrides)
    return Decision(**base)


def test_save_decision_persists(tmp_path):
    store = MigrationStateStore(tmp_path / "s.sqlite")
    store.save_decision(_decision("item-1"))
    loaded = store.get_decision("item-1")
    assert loaded is not None
    assert loaded.chosen_tmdb_id == 19995
    assert loaded.decision == DecisionStatus.APPROVED


def test_save_decision_idempotent_overwrites(tmp_path):
    store = MigrationStateStore(tmp_path / "s.sqlite")
    store.save_decision(_decision("item-1"))
    store.save_decision(
        _decision("item-1", decision=DecisionStatus.SKIPPED, chosen_tmdb_id=None)
    )
    loaded = store.get_decision("item-1")
    assert loaded.decision == DecisionStatus.SKIPPED
    assert loaded.chosen_tmdb_id is None


def test_get_decision_returns_none_when_absent(tmp_path):
    store = MigrationStateStore(tmp_path / "s.sqlite")
    assert store.get_decision("missing") is None


def test_load_decisions_returns_dict_keyed_by_item_id(tmp_path):
    store = MigrationStateStore(tmp_path / "s.sqlite")
    store.save_decision(_decision("a"))
    store.save_decision(_decision("b", decision=DecisionStatus.SKIPPED))
    decisions = store.load_decisions()
    assert set(decisions.keys()) == {"a", "b"}
    assert decisions["b"].decision == DecisionStatus.SKIPPED


def test_decision_summary_groups_by_status(tmp_path):
    store = MigrationStateStore(tmp_path / "s.sqlite")
    store.save_decision(_decision("a", decision=DecisionStatus.APPROVED))
    store.save_decision(_decision("b", decision=DecisionStatus.APPROVED))
    store.save_decision(_decision("c", decision=DecisionStatus.SKIPPED))
    summary = store.decision_summary()
    assert summary[DecisionStatus.APPROVED] == 2
    assert summary[DecisionStatus.SKIPPED] == 1


def test_save_decision_with_duplicate_action(tmp_path):
    store = MigrationStateStore(tmp_path / "s.sqlite")
    store.save_decision(
        _decision(
            "dup-1",
            bucket_origin="already_in_library",
            duplicate_action=DuplicateAction.REPLACE_DEST,
        )
    )
    loaded = store.get_decision("dup-1")
    assert loaded.duplicate_action == DuplicateAction.REPLACE_DEST


def test_save_decision_with_delete_source_after(tmp_path):
    store = MigrationStateStore(tmp_path / "s.sqlite")
    store.save_decision(
        _decision(
            "low-1",
            bucket_origin="low_rated",
            delete_source_after=True,
        )
    )
    loaded = store.get_decision("low-1")
    assert loaded.delete_source_after is True
