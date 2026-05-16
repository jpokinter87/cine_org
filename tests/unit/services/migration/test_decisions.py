"""Tests pour Decision dataclass + DecisionStatus enum."""

from datetime import datetime, timezone

from src.services.migration.decisions import (
    Decision,
    DecisionStatus,
    DuplicateAction,
)


def test_decision_status_values():
    assert DecisionStatus.APPROVED.value == "approved"
    assert DecisionStatus.REJECTED.value == "rejected"
    assert DecisionStatus.SKIPPED.value == "skipped"
    assert DecisionStatus.DEFERRED_TO_WEB.value == "deferred_to_web"


def test_duplicate_action_values():
    assert DuplicateAction.KEEP_DEST.value == "keep_dest"
    assert DuplicateAction.REPLACE_DEST.value == "replace_dest"
    assert DuplicateAction.DELETE_SOURCE.value == "delete_source"


def test_decision_minimal_construction():
    d = Decision(
        item_id="abc123",
        bucket_origin="needs_validation",
        decision=DecisionStatus.SKIPPED,
        decided_at=datetime.now(timezone.utc),
        decided_via="cli",
    )
    assert d.item_id == "abc123"
    assert d.decision == DecisionStatus.SKIPPED
    assert d.chosen_tmdb_id is None
    assert d.delete_source_after is False


def test_decision_approved_with_match():
    d = Decision(
        item_id="abc123",
        bucket_origin="needs_validation",
        decision=DecisionStatus.APPROVED,
        chosen_tmdb_id=19995,
        chosen_title="Avatar",
        chosen_year=2009,
        chosen_score=95.0,
        decided_at=datetime.now(timezone.utc),
        decided_via="cli",
    )
    assert d.chosen_tmdb_id == 19995
    assert d.chosen_score == 95.0
