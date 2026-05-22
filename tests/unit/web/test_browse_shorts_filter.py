"""Tests — filtre « Courts » dans la grille (browse.py)."""

import pytest
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.testclient import TestClient

from src.infrastructure.persistence.models import MovieModel, SeriesModel
from src.web.routes.library.browse import router as browse_router

HX = {"HX-Request": "true"}


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
    from src.web.routes.library import browse as browse_module

    def _get_session():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(browse_module, "get_session", _get_session)
    app = FastAPI()
    app.include_router(browse_router, prefix="/library")
    return TestClient(app)


def _seed(engine):
    with Session(engine) as session:
        session.add(MovieModel(title="Long Film", year=2010, is_short=False))
        session.add(MovieModel(title="Court Bunny", year=1958, is_short=True))
        session.add(SeriesModel(title="Ma Serie", year=2015))
        session.commit()


def test_all_excludes_shorts(client, engine):
    _seed(engine)
    r = client.get("/library/?type=all", headers=HX)
    assert r.status_code == 200
    assert "Long Film" in r.text
    assert "Ma Serie" in r.text
    assert "Court Bunny" not in r.text


def test_movie_excludes_shorts(client, engine):
    _seed(engine)
    r = client.get("/library/?type=movie", headers=HX)
    assert "Long Film" in r.text
    assert "Court Bunny" not in r.text
    assert "Ma Serie" not in r.text


def test_courts_shows_only_shorts(client, engine):
    _seed(engine)
    r = client.get("/library/?type=courts", headers=HX)
    assert "Court Bunny" in r.text
    assert "Long Film" not in r.text
    assert "Ma Serie" not in r.text


def test_courts_option_present(client, engine):
    _seed(engine)
    r = client.get("/library/?type=all", headers=HX)
    assert 'value="courts"' in r.text
