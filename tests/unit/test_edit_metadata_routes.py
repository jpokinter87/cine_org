"""
Tests des routes d'edition manuelle des metadonnees (phase 42-02, tache 2).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.templating import Jinja2Templates
from starlette.testclient import TestClient

from src.infrastructure.persistence.models import MovieModel, SeriesModel


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


@pytest.fixture
def storage_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def client(engine, storage_dir, monkeypatch):
    """TestClient FastAPI minimal : router edit_metadata + DB patchee."""
    from src.web.routes.library import edit_metadata
    from src.infrastructure.persistence import database as db_mod

    # Brancher la DB in-memory
    def _fake_get_session():
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(db_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(edit_metadata, "get_session", _fake_get_session)

    # Brancher le storage_dir via Settings
    monkeypatch.setattr(
        edit_metadata, "_get_storage_dir", lambda: storage_dir
    )

    # Stubber templates : la route GET renvoie un template, on se
    # concentre sur le JSON-like (on veut juste verifier status 200 et
    # contexte). Remplacement par un template minimal.
    def _fake_template_response(request, name, ctx, **kwargs):
        # Renvoyer les donnees pertinentes sous forme HTML simple
        from fastapi.responses import HTMLResponse
        body = (
            f"<form data-type='{ctx.get('entity_type')}' "
            f"data-id='{ctx.get('entity_id')}' "
            f"data-overview='{ctx.get('current_overview')}' "
            f"data-preserve='{ctx.get('preserve_overrides')}' "
            f"data-has-override='{ctx.get('has_override')}'>"
            f"{json.dumps(ctx.get('current_cast', []))}"
            f"</form>"
        )
        return HTMLResponse(body)

    monkeypatch.setattr(edit_metadata.templates, "TemplateResponse", _fake_template_response)

    app = FastAPI()
    app.include_router(edit_metadata.router, prefix="/library")
    return TestClient(app)


def _create_movie(session, **kwargs) -> int:
    defaults = dict(title="Film Test", year=2020, tmdb_id=42)
    defaults.update(kwargs)
    m = MovieModel(**defaults)
    session.add(m)
    session.commit()
    session.refresh(m)
    return m.id


def _create_series(session, **kwargs) -> int:
    defaults = dict(title="Série Test", year=2020, tvdb_id=42)
    defaults.update(kwargs)
    s = SeriesModel(**defaults)
    session.add(s)
    session.commit()
    session.refresh(s)
    return s.id


# ─── GET edit form ────────────────────────────────────────────────────────


def test_get_edit_form_pre_fills_api_values(client, session):
    movie_id = _create_movie(session, overview="Synopsis API", cast_json='["Alice","Bob"]')
    r = client.get(f"/library/movies/{movie_id}/edit")
    assert r.status_code == 200
    assert "Synopsis API" in r.text
    assert "Alice" in r.text
    assert "data-preserve='False'" in r.text
    assert "data-has-override='False'" in r.text


def test_get_edit_form_pre_fills_overrides(client, session):
    movie_id = _create_movie(
        session,
        overview="Old API",
        overview_override="My override",
        cast_override_json='[{"name":"X","role":"Lead"}]',
        preserve_overrides=True,
    )
    r = client.get(f"/library/movies/{movie_id}/edit")
    assert r.status_code == 200
    assert "My override" in r.text
    assert "Lead" in r.text
    assert "data-preserve='True'" in r.text
    assert "data-has-override='True'" in r.text


def test_get_edit_form_returns_404_for_unknown(client):
    r = client.get("/library/movies/9999/edit")
    assert r.status_code == 404


# ─── POST edit : upload ───────────────────────────────────────────────────


def test_post_upload_writes_poster(client, session, storage_dir):
    movie_id = _create_movie(session)
    files = {"poster_file": ("cover.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")}
    data = {"poster_mode": "upload", "overview_override": ""}
    r = client.post(f"/library/movies/{movie_id}/edit", data=data, files=files)
    assert r.status_code == 200
    assert r.headers.get("hx-redirect", "").endswith(f"/library/movies/{movie_id}")

    expected = storage_dir / ".metadata" / "posters" / f"movie-{movie_id}.jpg"
    assert expected.exists()

    # DB : poster_override pointe sur ce fichier, preserve auto-active
    session.expire_all()
    movie = session.get(MovieModel, movie_id)
    assert movie.poster_override == str(expected)
    assert movie.preserve_overrides is True  # auto : un override existe


def test_post_upload_rejects_bad_extension(client, session):
    movie_id = _create_movie(session)
    files = {"poster_file": ("notes.txt", b"data", "text/plain")}
    data = {"poster_mode": "upload", "overview_override": ""}
    r = client.post(f"/library/movies/{movie_id}/edit", data=data, files=files)
    assert r.status_code == 400
    assert "edit-error" in r.text


# ─── POST edit : URL ──────────────────────────────────────────────────────


@respx.mock
def test_post_url_downloads_poster(client, session, storage_dir):
    movie_id = _create_movie(session)
    respx.get("https://example.com/p.jpg").mock(
        return_value=httpx.Response(
            200, content=b"FAKE", headers={"content-type": "image/jpeg"}
        )
    )
    data = {
        "poster_mode": "url",
        "poster_url": "https://example.com/p.jpg",
        "overview_override": "",
    }
    r = client.post(f"/library/movies/{movie_id}/edit", data=data)
    assert r.status_code == 200

    expected = storage_dir / ".metadata" / "posters" / f"movie-{movie_id}.jpg"
    assert expected.exists()

    session.expire_all()
    movie = session.get(MovieModel, movie_id)
    assert movie.poster_override == str(expected)


# ─── POST edit : keep / clear ─────────────────────────────────────────────


def test_post_keep_does_not_touch_poster(client, session):
    movie_id = _create_movie(session, poster_override="/old/path.jpg")
    data = {
        "poster_mode": "keep",
        "overview_override": "New overview",
    }
    r = client.post(f"/library/movies/{movie_id}/edit", data=data)
    assert r.status_code == 200

    session.expire_all()
    movie = session.get(MovieModel, movie_id)
    assert movie.poster_override == "/old/path.jpg"  # inchange
    assert movie.overview_override == "New overview"


def test_post_clear_removes_poster_override(client, session):
    movie_id = _create_movie(session, poster_override="/old/path.jpg")
    data = {"poster_mode": "clear", "overview_override": ""}
    r = client.post(f"/library/movies/{movie_id}/edit", data=data)
    assert r.status_code == 200

    session.expire_all()
    movie = session.get(MovieModel, movie_id)
    assert movie.poster_override is None


# ─── POST edit : casting ──────────────────────────────────────────────────


def test_post_cast_pairs_names_and_roles(client, session):
    movie_id = _create_movie(session)
    data = {
        "poster_mode": "keep",
        "overview_override": "",
        "cast_names[]": ["Alice", "Bob"],
        "cast_roles[]": ["Héroïne", "Méchant"],
    }
    r = client.post(f"/library/movies/{movie_id}/edit", data=data)
    assert r.status_code == 200

    session.expire_all()
    movie = session.get(MovieModel, movie_id)
    assert movie.cast_override == [
        {"name": "Alice", "role": "Héroïne"},
        {"name": "Bob", "role": "Méchant"},
    ]


def test_post_empty_cast_clears_override(client, session):
    movie_id = _create_movie(
        session, cast_override_json='[{"name":"X","role":"Y"}]'
    )
    data = {"poster_mode": "keep", "overview_override": ""}
    r = client.post(f"/library/movies/{movie_id}/edit", data=data)
    assert r.status_code == 200

    session.expire_all()
    movie = session.get(MovieModel, movie_id)
    assert movie.cast_override_json is None


# ─── POST edit : préservation ────────────────────────────────────────────


def test_post_preserve_auto_true_when_overview_override(client, session):
    """preserve_overrides est True automatiquement quand un override existe."""
    movie_id = _create_movie(session)
    data = {"poster_mode": "keep", "overview_override": "Mon synopsis"}
    r = client.post(f"/library/movies/{movie_id}/edit", data=data)
    assert r.status_code == 200

    session.expire_all()
    movie = session.get(MovieModel, movie_id)
    assert movie.overview_override == "Mon synopsis"
    assert movie.preserve_overrides is True  # auto


def test_post_preserve_auto_false_when_all_cleared(client, session):
    """preserve revient à False quand tous les overrides ont été effacés."""
    movie_id = _create_movie(
        session,
        overview_override="Old override",
        preserve_overrides=True,
    )
    # Effacer overview + clear poster + cast vide => plus d'override
    data = {"poster_mode": "clear", "overview_override": ""}
    r = client.post(f"/library/movies/{movie_id}/edit", data=data)
    assert r.status_code == 200

    session.expire_all()
    movie = session.get(MovieModel, movie_id)
    assert movie.overview_override is None
    assert movie.poster_override is None
    assert movie.cast_override_json is None
    assert movie.preserve_overrides is False  # auto : tout effacé


def test_post_preserve_auto_true_when_cast_override(client, session):
    movie_id = _create_movie(session)
    data = {
        "poster_mode": "keep",
        "overview_override": "",
        "cast_names[]": ["Alice"],
        "cast_roles[]": ["Lead"],
    }
    r = client.post(f"/library/movies/{movie_id}/edit", data=data)
    assert r.status_code == 200

    session.expire_all()
    movie = session.get(MovieModel, movie_id)
    assert movie.preserve_overrides is True


# ─── Series ───────────────────────────────────────────────────────────────


def test_post_series_edit_works(client, session):
    series_id = _create_series(session)
    data = {"poster_mode": "keep", "overview_override": "Série override"}
    r = client.post(f"/library/series/{series_id}/edit", data=data)
    assert r.status_code == 200

    session.expire_all()
    series = session.get(SeriesModel, series_id)
    assert series.overview_override == "Série override"
    assert series.preserve_overrides is True  # auto


# ─── Route /metadata/posters/{filename} ───────────────────────────────────


def test_serve_poster_returns_file(client, storage_dir):
    posters_dir = storage_dir / ".metadata" / "posters"
    posters_dir.mkdir(parents=True)
    (posters_dir / "movie-99.jpg").write_bytes(b"IMAGE")

    r = client.get("/library/metadata/posters/movie-99.jpg")
    assert r.status_code == 200
    assert r.content == b"IMAGE"


def test_serve_poster_rejects_traversal(client):
    r = client.get("/library/metadata/posters/..%2Fsecret.jpg")
    assert r.status_code in (400, 404)


def test_serve_poster_404_when_missing(client, storage_dir):
    r = client.get("/library/metadata/posters/nonexistent.jpg")
    assert r.status_code == 404
