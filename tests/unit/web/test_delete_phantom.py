"""Tests : suppression d'une fiche fantôme depuis le détail (demande n°2).

Une fiche « fantôme » est une fiche sans fichiers réels (série dont aucun
épisode n'a de ``file_path``, film sans ``file_path``). Le bouton de
suppression ne doit agir que sur ces fiches : le endpoint refuse (400)
une fiche porteuse de fichiers, garde-fou côté serveur indépendant de
l'affichage du bouton.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.testclient import TestClient

from src.infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    SeriesModel,
)


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
    from src.infrastructure.persistence import database as db_mod
    from src.web.routes.library import delete as delete_mod

    def _fake_get_session():
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(db_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(delete_mod, "get_session", _fake_get_session)
    # Autoriser le client de test (sinon garde-fou « machine maître »).
    monkeypatch.setattr(delete_mod, "_LOCAL_HOSTS", {"testclient"})

    app = FastAPI()
    app.include_router(delete_mod.router, prefix="/library")
    container = MagicMock()
    container.file_system.return_value = MagicMock()
    app.state.container = container
    return TestClient(app)


def _phantom_series(engine) -> int:
    with Session(engine) as s:
        series = SeriesModel(title="Sous ses yeux", year=2026, tmdb_id=280511)
        s.add(series)
        s.commit()
        s.refresh(series)
        sid = series.id
        for ep_num in (1, 2, 3):
            s.add(
                EpisodeModel(
                    series_id=sid,
                    season_number=1,
                    episode_number=ep_num,
                    title=f"Épisode {ep_num}",
                )
            )
        s.commit()
    return sid


def _real_series(engine) -> int:
    with Session(engine) as s:
        series = SeriesModel(title="Vraie série", year=2026, tvdb_id=457481)
        s.add(series)
        s.commit()
        s.refresh(series)
        sid = series.id
        s.add(
            EpisodeModel(
                series_id=sid,
                season_number=1,
                episode_number=1,
                title="Épisode 1",
                file_path="/media/NAS64/Series/TV/S01E01.mkv",
            )
        )
        s.commit()
    return sid


def _make_movie(engine, **kwargs) -> int:
    with Session(engine) as s:
        defaults = dict(title="Film", year=2020, tmdb_id=1)
        defaults.update(kwargs)
        m = MovieModel(**defaults)
        s.add(m)
        s.commit()
        s.refresh(m)
        return m.id


def _series_exists(engine, sid: int) -> bool:
    with Session(engine) as s:
        return s.get(SeriesModel, sid) is not None


def _episodes_count(engine, sid: int) -> int:
    with Session(engine) as s:
        return len(
            s.exec(select(EpisodeModel).where(EpisodeModel.series_id == sid)).all()
        )


def _movie_exists(engine, mid: int) -> bool:
    with Session(engine) as s:
        return s.get(MovieModel, mid) is not None


# ─── Séries ────────────────────────────────────────────────────────────────


def test_supprime_serie_fantome(client, engine):
    sid = _phantom_series(engine)
    r = client.post(f"/library/series/{sid}/delete-phantom")
    assert r.status_code == 200
    assert r.headers.get("HX-Redirect") == "/library/"
    assert not _series_exists(engine, sid)
    assert _episodes_count(engine, sid) == 0


def test_refuse_serie_avec_fichiers(client, engine):
    sid = _real_series(engine)
    r = client.post(f"/library/series/{sid}/delete-phantom")
    assert r.status_code == 400
    assert _series_exists(engine, sid)


def test_serie_inconnue_404(client):
    r = client.post("/library/series/99999/delete-phantom")
    assert r.status_code == 404


# ─── Films ───────────────────────────────────────────────────────────────────


def test_supprime_film_fantome(client, engine):
    mid = _make_movie(engine, title="Film fantôme")
    r = client.post(f"/library/movies/{mid}/delete-phantom")
    assert r.status_code == 200
    assert not _movie_exists(engine, mid)


def test_refuse_film_avec_fichier(client, engine):
    mid = _make_movie(engine, title="Vrai film", file_path="/media/x.mkv")
    r = client.post(f"/library/movies/{mid}/delete-phantom")
    assert r.status_code == 400
    assert _movie_exists(engine, mid)
