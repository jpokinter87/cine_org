"""Tests — « Surprends-moi » exclut les courts-métrages (suggest.py)."""

import pytest
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.testclient import TestClient

from src.infrastructure.persistence.models import MovieModel
from src.web.routes.library.suggest import router as suggest_router


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
    from src.web.routes.library import suggest as suggest_module

    def _get_session():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(suggest_module, "get_session", _get_session)
    app = FastAPI()
    app.include_router(suggest_router, prefix="/library")
    return TestClient(app)


def test_short_only_yields_no_suggestion(client, engine):
    """Si le seul film est un court, aucune suggestion (courts exclus)."""
    with Session(engine) as session:
        session.add(
            MovieModel(title="Court Bunny", year=1958, duration_seconds=420, is_short=True)
        )
        session.commit()

    r = client.get("/library/suggest?type=movie")
    assert r.status_code == 200
    assert "Court Bunny" not in r.text


def test_short_never_chosen_among_movies(client, engine):
    """Avec un film normal + un court, seul le film normal est proposé."""
    with Session(engine) as session:
        session.add(MovieModel(title="Film Normal", year=2010, is_short=False))
        session.add(
            MovieModel(title="Court Bunny", year=1958, duration_seconds=420, is_short=True)
        )
        session.commit()

    # random.choice sur un pool d'un seul candidat (le court est exclu)
    for _ in range(5):
        r = client.get("/library/suggest?type=movie")
        assert r.status_code == 200
        assert "Court Bunny" not in r.text
        assert "Film Normal" in r.text
