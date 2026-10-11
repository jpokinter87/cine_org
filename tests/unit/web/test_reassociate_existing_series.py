"""Tests : ré-associer une série vers une fiche TMDB déjà présente en base.

Cas « Spider-Noir » : la fiche fantôme (sans fichier) « Noire » a été
ré-associée vers Spider-Noir, que la bibliothèque possédait déjà sous une
autre fiche. Résultat : deux fiches Spider-Noir, dont une « incomplète »
listant comme manquants des épisodes présents sur l'autre fiche.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.testclient import TestClient

from src.infrastructure.persistence.models import (
    EpisodeModel,
    SeriesModel,
    TrashModel,
)

TARGET_TMDB_ID = 220102


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def client(engine, monkeypatch):
    from src.web.routes.library import reassociate as mod

    def _fake_get_session():
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(mod, "get_session", _fake_get_session)
    monkeypatch.setattr(mod, "_remove_from_quality_cache", lambda *a: None)

    tmdb = MagicMock()
    tmdb.get_tv_details = AsyncMock(
        return_value=SimpleNamespace(
            title="Spider-Noir",
            original_title="Spider-Noir",
            year=2026,
            genres=(),
            overview="",
            poster_url=None,
            director=None,
            cast=(),
            vote_average=7.5,
            vote_count=100,
        )
    )
    tmdb.get_tv_external_ids = AsyncMock(return_value={"imdb_id": "tt30460310"})

    app = FastAPI()
    app.include_router(mod.router, prefix="/library")
    container = MagicMock()
    container.tmdb_client.return_value = tmdb
    container.file_system.return_value = MagicMock()
    app.state.container = container
    return TestClient(app)


def _series(engine, title, tmdb_id, *, filed: bool) -> int:
    with Session(engine) as s:
        series = SeriesModel(title=title, year=2026, tmdb_id=tmdb_id)
        s.add(series)
        s.commit()
        s.refresh(series)
        s.add(
            EpisodeModel(
                series_id=series.id,
                season_number=1,
                episode_number=1,
                title="E1",
                file_path=f"/storage/{title}/s01e01.mkv" if filed else None,
            )
        )
        s.commit()
        return series.id


def test_phantom_reassociated_to_existing_series_is_trashed(client, engine):
    existing_id = _series(engine, "Spider-Noir", TARGET_TMDB_ID, filed=True)
    phantom_id = _series(engine, "Noire", 111, filed=False)

    resp = client.post(
        f"/library/series/{phantom_id}/reassociate",
        data={"tmdb_id": str(TARGET_TMDB_ID)},
    )

    assert resp.status_code == 200
    assert resp.headers["HX-Redirect"] == f"/library/series/{existing_id}"
    with Session(engine) as s:
        assert s.get(SeriesModel, phantom_id) is None
        assert s.get(SeriesModel, existing_id) is not None
        trashed = s.exec(select(TrashModel)).all()
        assert any(
            t.entity_type == "series" and t.original_id == phantom_id for t in trashed
        )


def test_series_with_files_reassociated_to_existing_series_is_refused(client, engine):
    existing_id = _series(engine, "Spider-Noir", TARGET_TMDB_ID, filed=True)
    other_id = _series(engine, "Noire", 111, filed=True)

    resp = client.post(
        f"/library/series/{other_id}/reassociate",
        data={"tmdb_id": str(TARGET_TMDB_ID)},
    )

    assert "HX-Redirect" not in resp.headers
    assert f"/library/series/{existing_id}" in resp.text
    with Session(engine) as s:
        unchanged = s.get(SeriesModel, other_id)
        assert unchanged.title == "Noire"
        assert unchanged.tmdb_id == 111
