"""Test du filtre « séries incomplètes » de la bibliothèque.

Isolation : on bascule ``CINEORG_DATABASE_URL`` vers une base SQLite jetable
AVANT toute création de l'engine global (réinitialisé via
``database._engine = None``), de sorte que ni la vraie BDD ni les autres tests
ne soient touchés. L'app web étant montée sur ``get_session()`` (module global),
ce simple basculement suffit. On utilise ``with TestClient(app)`` pour déclencher
le lifespan (init du Container DI).
"""

import os

import pytest
from fastapi.testclient import TestClient

import src.infrastructure.persistence.database as db_module
from src.infrastructure.persistence.database import get_session, init_db
from src.infrastructure.persistence.models import MovieModel, SeriesModel
from src.web.app import app


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """Bascule l'engine global sur une BDD temporaire isolée."""
    db_file = tmp_path / "browse_filter.db"
    monkeypatch.setenv("CINEORG_DATABASE_URL", f"sqlite:///{db_file}")
    # Forcer la recréation de l'engine global avec la nouvelle URL.
    monkeypatch.setattr(db_module, "_engine", None)
    init_db()
    yield
    # Remettre l'engine global à None pour ne pas fuiter vers d'autres tests.
    db_module._engine = None


def _seed_series():
    session = next(get_session())
    try:
        session.add(
            SeriesModel(title="ZZZ Complete Show", completeness_status="complete")
        )
        session.add(
            SeriesModel(title="ZZZ Broken Show", completeness_status="incomplete")
        )
        session.add(SeriesModel(title="ZZZ Unknown Show", completeness_status=None))
        session.commit()
    finally:
        session.close()


def test_incomplete_filter_returns_only_incomplete(isolated_db):
    """incomplete_series=1 ne renvoie que les séries au statut 'incomplete'."""
    _seed_series()
    with TestClient(app) as client:
        resp = client.get("/library/?type=series&incomplete_series=1")
    assert resp.status_code == 200
    body = resp.text
    assert "ZZZ Broken Show" in body
    assert "ZZZ Complete Show" not in body
    assert "ZZZ Unknown Show" not in body


def test_incomplete_filter_excludes_movies_when_type_all(isolated_db):
    """incomplete_series=1 avec type=all n'affiche aucun film (le filtre est
    propre aux séries) — régression : les films passaient sans être filtrés."""
    _seed_series()
    session = next(get_session())
    try:
        session.add(MovieModel(title="ZZZ Some Movie", year=2024))
        session.commit()
    finally:
        session.close()
    with TestClient(app) as client:
        resp = client.get("/library/?type=all&incomplete_series=1")
    assert resp.status_code == 200
    body = resp.text
    assert "ZZZ Broken Show" in body
    assert "ZZZ Some Movie" not in body
    assert "ZZZ Complete Show" not in body


def test_no_incomplete_filter_returns_all_series(isolated_db):
    """Sans le filtre, toutes les séries restent visibles (non-régression)."""
    _seed_series()
    with TestClient(app) as client:
        resp = client.get("/library/?type=series")
    assert resp.status_code == 200
    body = resp.text
    assert "ZZZ Broken Show" in body
    assert "ZZZ Complete Show" in body
    assert "ZZZ Unknown Show" in body
