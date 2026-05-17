"""Tests P5 — routes /library/collections incluent les collections locales."""

import pytest
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.testclient import TestClient

from src.infrastructure.persistence.models import LocalCollectionModel, MovieModel
from src.web.routes.library.collections import router as collections_router


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
    """TestClient FastAPI avec get_session monkey-patché vers l'engine in-memory."""
    from src.web.routes.library import collections as collections_module

    def _get_session():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(collections_module, "get_session", _get_session)

    app = FastAPI()
    app.include_router(collections_router, prefix="/library")
    return TestClient(app)


def _add_tmdb_movie(
    session: Session, title: str, collection_id: int, collection_name: str
) -> None:
    session.add(
        MovieModel(
            title=title,
            year=2000,
            collection_id=collection_id,
            collection_name=collection_name,
            poster_path="/poster.jpg",
        )
    )


def _add_local_collection(session: Session, name: str) -> int:
    coll = LocalCollectionModel(name=name)
    session.add(coll)
    session.commit()
    session.refresh(coll)
    return coll.id


def _add_local_short(
    session: Session,
    title: str,
    local_collection_id: int,
) -> None:
    session.add(
        MovieModel(
            title=title,
            year=1958,
            duration_seconds=420,
            is_short=True,
            local_collection_id=local_collection_id,
            poster_path="/poster.jpg",
        )
    )


class TestCollectionsIndexIncludesLocal:
    """L'index /library/collections doit lister TMDB + locales."""

    def test_tmdb_only(self, client, engine) -> None:
        with Session(engine) as session:
            _add_tmdb_movie(session, "Star Wars IV", 10, "Star Wars Collection")
            _add_tmdb_movie(session, "Star Wars V", 10, "Star Wars Collection")
            session.commit()

        r = client.get("/library/collections")
        assert r.status_code == 200
        assert "Star Wars Collection" in r.text

    def test_local_only_shown_in_index(self, client, engine) -> None:
        with Session(engine) as session:
            coll_id = _add_local_collection(session, "Looney Tunes")
            _add_local_short(session, "Hare-Way to the Stars", coll_id)
            _add_local_short(session, "Knighty Knight Bugs", coll_id)
            session.commit()

        r = client.get("/library/collections")
        assert r.status_code == 200
        assert "Looney Tunes" in r.text
        # La carte locale doit pointer vers la route detail locale
        assert "/library/collections/local/" in r.text

    def test_tmdb_and_local_listed_together(self, client, engine) -> None:
        with Session(engine) as session:
            _add_tmdb_movie(session, "Star Wars IV", 10, "Star Wars Collection")
            _add_tmdb_movie(session, "Star Wars V", 10, "Star Wars Collection")
            coll_id = _add_local_collection(session, "Looney Tunes")
            _add_local_short(session, "Hare-Way", coll_id)
            _add_local_short(session, "Knighty Knight Bugs", coll_id)
            session.commit()

        r = client.get("/library/collections")
        assert r.status_code == 200
        assert "Star Wars Collection" in r.text
        assert "Looney Tunes" in r.text

    def test_empty_local_collection_is_hidden(self, client, engine) -> None:
        """Une collection locale sans aucun film ne doit pas apparaître."""
        with Session(engine) as session:
            _add_local_collection(session, "Vide")
            session.commit()

        r = client.get("/library/collections")
        assert r.status_code == 200
        assert "Vide" not in r.text


class TestLocalCollectionDetail:
    """Détail d'une collection locale via /library/collections/local/{id}."""

    def test_detail_lists_attached_movies(self, client, engine) -> None:
        with Session(engine) as session:
            coll_id = _add_local_collection(session, "Looney Tunes")
            _add_local_short(session, "Hare-Way to the Stars", coll_id)
            _add_local_short(session, "Knighty Knight Bugs", coll_id)
            session.commit()

        r = client.get(f"/library/collections/local/{coll_id}")
        assert r.status_code == 200
        assert "Looney Tunes" in r.text
        assert "Hare-Way to the Stars" in r.text
        assert "Knighty Knight Bugs" in r.text

    def test_detail_unknown_id_returns_404(self, client, engine) -> None:
        r = client.get("/library/collections/local/99999")
        assert r.status_code == 404
