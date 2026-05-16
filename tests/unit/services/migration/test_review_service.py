"""Tests pour MigrationReviewService — orchestrateur de la review."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.services.migration.dataclasses import (
    Bucket,
    MatchInfo,
    MigrationItem,
    MigrationPlan,
    MigrationStats,
    RatingDecision,
)
from src.services.migration.decisions import Decision, DecisionStatus
from src.services.migration.review_service import MigrationReviewService
from src.services.migration.state_store import MigrationStateStore


def _item(item_id: str, bucket: Bucket, **overrides) -> MigrationItem:
    base = dict(
        item_id=item_id,
        bucket=bucket,
        symlink_path=Path(f"/old/{item_id}.mkv"),
        source_path=Path(f"/old/{item_id}.mkv"),
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1000,
        rating=RatingDecision(),
        match=MatchInfo(),
        is_symlink_source=False,
    )
    base.update(overrides)
    return MigrationItem(**base)


def _plan(items) -> MigrationPlan:
    return MigrationPlan(
        version=1,
        source_root=Path("/src"),
        destination_root=Path("/dst"),
        threshold=6.0,
        stats=MigrationStats(),
        items=items,
    )


@pytest.fixture
def store(tmp_path):
    return MigrationStateStore(tmp_path / "s.sqlite")


def test_iter_pending_yields_review_buckets_only(store):
    plan = _plan([
        _item("m1", Bucket.MIGRATE),
        _item("nv1", Bucket.NEEDS_VALIDATION),
        _item("u1", Bucket.UNRATED),
        _item("lr1", Bucket.LOW_RATED),
        _item("ail1", Bucket.ALREADY_IN_LIBRARY),
        _item("br1", Bucket.BROKEN),
    ])
    service = MigrationReviewService(
        plan=plan,
        state_store=store,
        tmdb_client=MagicMock(),
        tvdb_client=MagicMock(),
        matcher=MagicMock(),
        duplicate_detector=MagicMock(),
    )
    pending = list(service.iter_pending())
    ids = [it.item_id for it in pending]
    assert set(ids) == {"nv1", "u1", "lr1", "ail1"}
    assert "m1" not in ids
    assert "br1" not in ids  # BROKEN exclu (sans solution review)


def test_iter_pending_filters_by_bucket(store):
    plan = _plan([
        _item("nv1", Bucket.NEEDS_VALIDATION),
        _item("u1", Bucket.UNRATED),
    ])
    service = MigrationReviewService(
        plan=plan,
        state_store=store,
        tmdb_client=MagicMock(),
        tvdb_client=MagicMock(),
        matcher=MagicMock(),
        duplicate_detector=MagicMock(),
    )
    pending = list(service.iter_pending(bucket=Bucket.NEEDS_VALIDATION))
    assert [it.item_id for it in pending] == ["nv1"]


def test_iter_pending_resume_skips_decided(store):
    plan = _plan([
        _item("nv1", Bucket.NEEDS_VALIDATION),
        _item("nv2", Bucket.NEEDS_VALIDATION),
    ])
    store.save_decision(
        Decision(
            item_id="nv1",
            bucket_origin="needs_validation",
            decision=DecisionStatus.SKIPPED,
            decided_at=datetime.now(timezone.utc),
            decided_via="cli",
        )
    )
    service = MigrationReviewService(
        plan=plan,
        state_store=store,
        tmdb_client=MagicMock(),
        tvdb_client=MagicMock(),
        matcher=MagicMock(),
        duplicate_detector=MagicMock(),
    )
    pending = list(service.iter_pending(resume=True))
    assert [it.item_id for it in pending] == ["nv2"]


def test_iter_pending_no_resume_yields_all(store):
    plan = _plan([_item("nv1", Bucket.NEEDS_VALIDATION)])
    store.save_decision(
        Decision(
            item_id="nv1",
            bucket_origin="needs_validation",
            decision=DecisionStatus.SKIPPED,
            decided_at=datetime.now(timezone.utc),
            decided_via="cli",
        )
    )
    service = MigrationReviewService(
        plan=plan,
        state_store=store,
        tmdb_client=MagicMock(),
        tvdb_client=MagicMock(),
        matcher=MagicMock(),
        duplicate_detector=MagicMock(),
    )
    pending = list(service.iter_pending(resume=False))
    assert [it.item_id for it in pending] == ["nv1"]
