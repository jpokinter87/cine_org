"""
Tests des routes de ré-association TMDB (films + séries).

Couvre deux comportements :
- Le handler `apply` backfille la note IMDb (`imdb_rating`/`imdb_votes`)
  depuis le cache IMDb local, en plus de la note TMDB.
- Le partiel `_reassociate_results.html` rend un bouton « Rafraîchir »
  sur la carte de l'association actuelle (sinon impossible de relancer
  l'enrichissement sans passer par une fausse association).
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.testclient import TestClient

from src.infrastructure.persistence.models import (
    IMDbRatingModel,
    MovieModel,
    SeriesModel,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────


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
def session(engine):
    with Session(engine) as s:
        yield s


def _fake_details(**kwargs) -> SimpleNamespace:
    """Construit un faux MediaDetails avec les attributs lus par les handlers."""
    defaults = dict(
        id="999",
        title="Nouveau Titre",
        original_title="New Title",
        year=2020,
        genres=("Drame",),
        duration_seconds=5400,
        overview="Synopsis",
        poster_url="https://img/poster.jpg",
        director="Réalisateur",
        cast=("Acteur 1",),
        vote_average=7.8,
        vote_count=1234,
        collection_id=None,
        collection_name=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class _FakeTMDBClient:
    """Client TMDB minimal : renvoie toujours les mêmes détails + imdb_id."""

    def __init__(self, details: SimpleNamespace, imdb_id: str | None) -> None:
        self._details = details
        self._imdb_id = imdb_id
        self._api_key = "fake-key"

    async def get_details(self, tmdb_id):  # noqa: D102
        return self._details

    async def get_tv_details(self, tmdb_id):  # noqa: D102
        return self._details

    async def get_external_ids(self, tmdb_id):  # noqa: D102
        return {"imdb_id": self._imdb_id}

    async def get_tv_external_ids(self, tmdb_id):  # noqa: D102
        return {"imdb_id": self._imdb_id}


class _FakeContainer:
    """Container DI minimal : tmdb_client() + session()."""

    def __init__(self, client: _FakeTMDBClient, engine) -> None:
        self._client = client
        self._engine = engine

    def tmdb_client(self):  # noqa: D102
        return self._client

    def session(self):  # noqa: D102
        return Session(self._engine)


@pytest.fixture
def make_client(engine, monkeypatch):
    """Fabrique un TestClient branché sur la DB in-memory et un faux container."""
    from src.web.routes.library import reassociate
    from src.infrastructure.persistence import database as db_mod

    def _fake_get_session():
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(db_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(reassociate, "get_session", _fake_get_session)
    # Le cache qualité n'est pas le sujet ici : on neutralise l'effet de bord.
    monkeypatch.setattr(reassociate, "_remove_from_quality_cache", lambda *a, **k: None)

    def _factory(details: SimpleNamespace, imdb_id: str | None) -> TestClient:
        client = _FakeTMDBClient(details, imdb_id)
        app = FastAPI()
        app.include_router(reassociate.router, prefix="/library")
        app.state.container = _FakeContainer(client, engine)
        return TestClient(app)

    return _factory


def _seed_imdb_rating(session, tconst: str, rating: float, votes: int) -> None:
    session.add(
        IMDbRatingModel(
            tconst=tconst,
            average_rating=rating,
            num_votes=votes,
            last_updated=date(2024, 1, 1),
        )
    )
    session.commit()


# ─── Backend : backfill note IMDb sur apply (films) ───────────────────────


def test_movie_apply_backfills_imdb_rating_from_cache(make_client, session, engine):
    """Le POST apply film récupère la note IMDb du cache local après l'imdb_id."""
    movie = MovieModel(title="Ancien", year=2000, tmdb_id=1, file_path="/x/film.mkv")
    session.add(movie)
    session.commit()
    session.refresh(movie)
    movie_id = movie.id

    _seed_imdb_rating(session, "tt7777777", 8.3, 5000)

    client = make_client(_fake_details(), imdb_id="tt7777777")
    r = client.post(f"/library/movies/{movie_id}/reassociate", data={"tmdb_id": "999"})
    assert r.status_code == 200

    with Session(engine) as s:
        updated = s.get(MovieModel, movie_id)
        assert updated.tmdb_id == 999
        assert updated.vote_average == 7.8  # note TMDB (déjà géré avant)
        assert updated.imdb_rating == 8.3  # note IMDb (le correctif)
        assert updated.imdb_votes == 5000


def test_movie_apply_imdb_rating_none_when_absent_from_cache(
    make_client, session, engine
):
    """Si l'imdb_id n'est pas dans le cache local, imdb_rating reste None."""
    movie = MovieModel(
        title="Ancien",
        year=2000,
        tmdb_id=1,
        file_path="/x/film.mkv",
        imdb_rating=5.0,  # ancienne note (association précédente) : doit être purgée
        imdb_votes=10,
    )
    session.add(movie)
    session.commit()
    session.refresh(movie)
    movie_id = movie.id

    client = make_client(_fake_details(), imdb_id="tt0000000")
    r = client.post(f"/library/movies/{movie_id}/reassociate", data={"tmdb_id": "999"})
    assert r.status_code == 200

    with Session(engine) as s:
        updated = s.get(MovieModel, movie_id)
        assert updated.imdb_rating is None
        assert updated.imdb_votes is None


# ─── Backend : backfill note IMDb sur apply (séries) ──────────────────────


def test_series_apply_backfills_imdb_rating_from_cache(make_client, session, engine):
    """Le POST apply série récupère aussi la note IMDb du cache local."""
    series = SeriesModel(title="Ancienne Série", year=2010, tvdb_id=42)
    session.add(series)
    session.commit()
    session.refresh(series)
    series_id = series.id

    _seed_imdb_rating(session, "tt5555555", 9.1, 80000)

    client = make_client(_fake_details(), imdb_id="tt5555555")
    r = client.post(
        f"/library/series/{series_id}/reassociate", data={"tmdb_id": "999"}
    )
    assert r.status_code == 200

    with Session(engine) as s:
        updated = s.get(SeriesModel, series_id)
        assert updated.tmdb_id == 999
        assert updated.vote_average == 7.8
        assert updated.imdb_rating == 9.1
        assert updated.imdb_votes == 80000


# ─── Template : bouton « Rafraîchir » sur la carte courante ───────────────


def test_results_template_renders_refresh_button_for_current():
    """La carte « Association actuelle » expose un bouton de relance."""
    from src.web.deps import templates

    tmpl = templates.get_template("library/_reassociate_results.html")
    html = tmpl.render(
        candidates=[
            {
                "tmdb_id": "61828",
                "title": "Detectorists",
                "year": 2014,
                "original_title": "Detectorists",
                "overview": None,
                "poster_url": None,
                "director": None,
                "nb_seasons": 3,
                "nb_episodes": 19,
                "series_indicator": None,
                "is_current": True,
            }
        ],
        entity_type="series",
        entity_id=1,
        local_duration=None,
        local_duration_seconds=None,
        local_seasons=3,
        local_episodes=19,
    )
    assert 'data-refresh="1"' in html
    assert "Rafraîchir" in html


def test_results_template_non_current_keeps_select_button():
    """Un candidat différent de l'association courante garde « Sélectionner »."""
    from src.web.deps import templates

    tmpl = templates.get_template("library/_reassociate_results.html")
    html = tmpl.render(
        candidates=[
            {
                "tmdb_id": "12345",
                "title": "Autre Série",
                "year": 2020,
                "original_title": "Other",
                "overview": None,
                "poster_url": None,
                "director": None,
                "nb_seasons": 1,
                "nb_episodes": 8,
                "series_indicator": None,
                "is_current": False,
            }
        ],
        entity_type="series",
        entity_id=1,
        local_duration=None,
        local_duration_seconds=None,
        local_seasons=1,
        local_episodes=8,
    )
    assert "Sélectionner" in html
    assert 'data-refresh="1"' not in html
