"""Tests pour les routes /migration/review."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.container import Container
from src.services.migration.dataclasses import (
    Bucket,
    MatchInfo,
    MigrationItem,
    MigrationPlan,
    MigrationStats,
    RatingDecision,
)
from src.services.migration.plan_builder import serialize_plan
from src.web.routes.migration import router as migration_router


@pytest.fixture
def client_with_plan(tmp_path):
    """Crée un plan minimal et un client FastAPI configuré avec le router migration."""
    item = MigrationItem(
        item_id="nv1",
        bucket=Bucket.NEEDS_VALIDATION,
        symlink_path=Path("/old/Wrong.mkv"),
        source_path=Path("/old/Wrong.mkv"),
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1_500_000_000,
        rating=RatingDecision(),
        match=MatchInfo(top_candidates=[
            {"title": "Wrong", "year": 2012, "score": 67.0,
             "tmdb_id": 83186, "source": "tmdb"}
        ]),
        is_symlink_source=False,
    )
    plan = MigrationPlan(
        version=1, source_root=Path("/s"), destination_root=Path("/d"),
        threshold=6.0, stats=MigrationStats(), items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "plan.json.state.sqlite"

    app = FastAPI()
    app.include_router(migration_router)
    app.state.container = Container()

    return TestClient(app), plan_path, state_path


def test_review_list_renders(client_with_plan):
    client, plan_path, _ = client_with_plan
    response = client.get(
        "/migration/review", params={"plan": str(plan_path)}
    )
    assert response.status_code == 200
    assert "Wrong.mkv" in response.text
    assert "needs_validation" in response.text.lower()


def test_review_list_validates_plan_path_missing(client_with_plan, tmp_path):
    """Plan inexistant → 400 (pas un traceback)."""
    client, _, _ = client_with_plan
    response = client.get(
        "/migration/review",
        params={"plan": str(tmp_path / "does_not_exist.json")},
    )
    assert response.status_code == 400


def test_review_list_validates_plan_path_wrong_suffix(client_with_plan, tmp_path):
    """Plan avec mauvais suffixe → 400."""
    client, _, _ = client_with_plan
    bad_plan = tmp_path / "etc.txt"
    bad_plan.write_text("nope")
    response = client.get(
        "/migration/review",
        params={"plan": str(bad_plan)},
    )
    assert response.status_code == 400


def test_review_list_renders_includes_pending_count(client_with_plan):
    """Vérifie que le résumé pending=1 apparaît dans le rendu."""
    client, plan_path, _ = client_with_plan
    response = client.get(
        "/migration/review", params={"plan": str(plan_path)}
    )
    assert response.status_code == 200
    # 1 NV item, pas de décision → pending=1
    assert "En attente : 1" in response.text
