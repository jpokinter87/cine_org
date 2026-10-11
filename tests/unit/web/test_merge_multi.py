"""Tests : fusion de plus de deux fiches séries en une seule opération.

Avant, seules deux fiches pouvaient être fusionnées : trois doublons
(« Calls », « The Shrink Next Door », « Æon Flux ») imposaient deux fusions
successives. La route accepte désormais N fiches absorbées, fusionnées
l'une après l'autre dans la fiche conservée.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.testclient import TestClient

from src.infrastructure.persistence.models import SeriesModel
from src.services.series_merge import MergePreview, MergeResult


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    return eng


class _FakeMergeService:
    def __init__(self, fail_on=None):
        self.merged = []
        self.previewed = []
        self.fail_on = fail_on

    def merge(self, recipient_id, absorbed_id):
        if absorbed_id == self.fail_on:
            raise ValueError("Fiche introuvable.")
        self.merged.append((recipient_id, absorbed_id))
        return MergeResult(recipient_id, 3, 0, 3, True)

    def preview(self, recipient_id, absorbed_id):
        self.previewed.append((recipient_id, absorbed_id))
        return MergePreview(
            recipient_id=recipient_id,
            absorbed_id=absorbed_id,
            recipient_title="Calls",
            absorbed_title="Calls",
            episodes_to_attach=2,
            target_series_folder="Calls (2017)",
        )


def _client(engine, monkeypatch, service):
    from src.web.routes.library import merge as merge_mod

    def _fake_get_session():
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(merge_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(merge_mod, "_build_service", lambda s, c: service)
    monkeypatch.setattr(merge_mod, "_LOCAL_HOSTS", {"testclient"})

    app = FastAPI()
    app.include_router(merge_mod.router, prefix="/library")
    app.state.container = MagicMock()
    return TestClient(app)


def _series(engine, title, created_at) -> int:
    with Session(engine) as s:
        series = SeriesModel(
            title=title, year=2017, tmdb_id=75718, created_at=created_at
        )
        s.add(series)
        s.commit()
        s.refresh(series)
        return series.id


def test_merge_apply_absorbs_several_series(engine, monkeypatch):
    service = _FakeMergeService()
    client = _client(engine, monkeypatch, service)

    resp = client.post("/library/series/10/merge", data={"absorbed_id": ["11", "12"]})

    assert resp.status_code == 200
    assert service.merged == [(10, 11), (10, 12)]
    assert resp.headers["HX-Redirect"] == "/library/series/10"


def test_merge_apply_single_absorbed_still_works(engine, monkeypatch):
    service = _FakeMergeService()
    client = _client(engine, monkeypatch, service)

    resp = client.post("/library/series/10/merge", data={"absorbed_id": "11"})

    assert resp.status_code == 200
    assert service.merged == [(10, 11)]


def test_merge_apply_reports_partial_failure(engine, monkeypatch):
    """Un échec en cours de route est signalé avec le nombre de fusions déjà
    effectuées (chaque fusion est validée indépendamment)."""
    service = _FakeMergeService(fail_on=12)
    client = _client(engine, monkeypatch, service)

    resp = client.post("/library/series/10/merge", data={"absorbed_id": ["11", "12"]})

    assert resp.status_code == 400
    assert service.merged == [(10, 11)]
    assert "1 fusion" in resp.json()["error"]


def test_overlay_lists_all_selected_series_with_oldest_as_recipient(
    engine, monkeypatch
):
    newest = _series(engine, "Calls nouvelle", datetime(2026, 5, 22))
    oldest = _series(engine, "Calls ancienne", datetime(2026, 2, 23))
    middle = _series(engine, "Calls milieu", datetime(2026, 3, 1))
    service = _FakeMergeService()
    client = _client(engine, monkeypatch, service)

    resp = client.get(
        "/library/merge/overlay", params={"ids": [newest, oldest, middle]}
    )

    assert resp.status_code == 200
    for title in ("Calls nouvelle", "Calls ancienne", "Calls milieu"):
        assert title in resp.text
    assert sorted(service.previewed) == sorted([(oldest, newest), (oldest, middle)])


def test_overlay_honours_explicit_recipient(engine, monkeypatch):
    a = _series(engine, "A", datetime(2026, 2, 23))
    b = _series(engine, "B", datetime(2026, 5, 22))
    service = _FakeMergeService()
    client = _client(engine, monkeypatch, service)

    resp = client.get("/library/merge/overlay", params={"ids": [a, b], "keep": b})

    assert resp.status_code == 200
    assert service.previewed == [(b, a)]


def test_overlay_requires_at_least_two_series(engine, monkeypatch):
    a = _series(engine, "A", datetime(2026, 2, 23))
    client = _client(engine, monkeypatch, _FakeMergeService())

    resp = client.get("/library/merge/overlay", params={"ids": [a]})

    assert resp.status_code == 400
