"""Tests P5 — routes /library/collections incluent les collections locales."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.testclient import TestClient

from src.infrastructure.persistence.models import (
    LocalCollectionModel,
    MovieModel,
    SeriesModel,
)
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


@pytest.fixture
def batch_client(engine, tmp_path, monkeypatch):
    """Client /collection-batch : container stub + hôte de test autorisé."""
    from src.web.routes.library import collections as collections_module

    def _get_session():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(collections_module, "get_session", _get_session)
    monkeypatch.setattr(
        collections_module,
        "_LOCAL_HOSTS",
        {"testclient", "127.0.0.1", "::1", "localhost"},
    )

    video_dir = tmp_path / "video"
    video_dir.mkdir()
    settings = SimpleNamespace(
        video_dir=video_dir,
        short_film_duration_threshold_seconds=900,
    )
    app = FastAPI()
    app.state.container = SimpleNamespace(config=lambda: settings)
    app.include_router(collections_router, prefix="/library")
    return TestClient(app), video_dir


class TestCollectionBatch:
    def test_requires_local_host(self, client, engine):
        # La fixture 'client' n'autorise pas l'hôte 'testclient' → 403
        r = client.post(
            "/library/collection-batch",
            json={"collection_name": "Looney Tunes", "items": []},
        )
        assert r.status_code == 403

    def test_creates_collection_and_assigns(self, batch_client, engine):
        test_client, _ = batch_client
        with Session(engine) as session:
            m1 = MovieModel(title="A", year=1958, is_short=True)
            m2 = MovieModel(title="B", year=1959, is_short=True)
            session.add(m1)
            session.add(m2)
            session.commit()
            session.refresh(m1)
            session.refresh(m2)
            ids = [m1.id, m2.id]

        r = test_client.post(
            "/library/collection-batch",
            json={
                "collection_name": "Looney Tunes",
                "items": [
                    {"type": "movie", "id": ids[0]},
                    {"type": "movie", "id": ids[1]},
                ],
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["assigned"] == 2
        assert data["collection_id"] is not None

        with Session(engine) as session:
            coll = session.exec(
                select(LocalCollectionModel).where(
                    LocalCollectionModel.name == "Looney Tunes"
                )
            ).first()
            assert coll is not None
            movies = session.exec(
                select(MovieModel).where(MovieModel.id.in_(ids))
            ).all()
            assert all(m.local_collection_id == coll.id for m in movies)

    def test_reuses_existing_collection(self, batch_client, engine):
        test_client, _ = batch_client
        with Session(engine) as session:
            coll = LocalCollectionModel(name="Looney Tunes")
            session.add(coll)
            m = MovieModel(title="A", year=1958, is_short=True)
            session.add(m)
            session.commit()
            session.refresh(coll)
            session.refresh(m)
            coll_id, movie_id = coll.id, m.id

        r = test_client.post(
            "/library/collection-batch",
            json={
                "collection_name": "Looney Tunes",
                "items": [{"type": "movie", "id": movie_id}],
            },
        )
        assert r.status_code == 200
        assert r.json()["collection_id"] == coll_id

        with Session(engine) as session:
            count = len(
                session.exec(
                    select(LocalCollectionModel).where(
                        LocalCollectionModel.name == "Looney Tunes"
                    )
                ).all()
            )
            assert count == 1

    def test_ignores_series_items(self, batch_client, engine):
        test_client, _ = batch_client
        with Session(engine) as session:
            s = SeriesModel(title="Ma Serie", year=2015)
            m = MovieModel(title="A", year=1958, is_short=True)
            session.add(s)
            session.add(m)
            session.commit()
            session.refresh(s)
            session.refresh(m)
            series_id, movie_id = s.id, m.id

        r = test_client.post(
            "/library/collection-batch",
            json={
                "collection_name": "Looney Tunes",
                "items": [
                    {"type": "series", "id": series_id},
                    {"type": "movie", "id": movie_id},
                ],
            },
        )
        assert r.status_code == 200
        assert r.json()["assigned"] == 1  # série ignorée

    def test_moves_symlink_to_franchise_folder(self, batch_client, engine):
        test_client, video_dir = batch_client
        storage = video_dir.parent / "storage"
        storage.mkdir()
        target = storage / "bunny.mkv"
        target.write_text("x")
        divers = video_dir / "Films" / "Courts" / "Divers"
        divers.mkdir(parents=True)
        link = divers / "Court Bunny (1958).mkv"
        link.symlink_to(target)

        with Session(engine) as session:
            m = MovieModel(
                title="Court Bunny",
                year=1958,
                duration_seconds=420,
                is_short=True,
                symlink_path=str(link),
            )
            session.add(m)
            session.commit()
            session.refresh(m)
            movie_id = m.id

        r = test_client.post(
            "/library/collection-batch",
            json={
                "collection_name": "Looney Tunes",
                "items": [{"type": "movie", "id": movie_id}],
            },
        )
        assert r.status_code == 200
        assert r.json()["moved"] == 1

        new_link = (
            video_dir / "Films" / "Courts" / "Looney Tunes" / "Court Bunny (1958).mkv"
        )
        assert new_link.is_symlink()
        assert not link.exists()
        with Session(engine) as session:
            m = session.get(MovieModel, movie_id)
            assert m.symlink_path == str(new_link)
