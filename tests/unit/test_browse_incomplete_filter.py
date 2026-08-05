"""Test du filtre « séries incomplètes » de la bibliothèque.

Isolation : on bascule ``CINEORG_DATABASE_URL`` vers une base SQLite jetable
AVANT toute création de l'engine global (réinitialisé via
``database._engine = None``), de sorte que ni la vraie BDD ni les autres tests
ne soient touchés. L'app web étant montée sur ``get_session()`` (module global),
ce simple basculement suffit. On utilise ``with TestClient(app)`` pour déclencher
le lifespan (init du Container DI).
"""

import re

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


def _seed_granular():
    session = next(get_session())
    try:
        session.add(
            SeriesModel(
                title="ZZZ Eps Gap", completeness_status="incomplete",
                has_missing_episodes=True, has_missing_seasons=False,
            )
        )
        session.add(
            SeriesModel(
                title="ZZZ Season Gap", completeness_status="incomplete",
                has_missing_episodes=False, has_missing_seasons=True,
            )
        )
        session.add(
            SeriesModel(
                title="ZZZ Both Gap", completeness_status="incomplete",
                has_missing_episodes=True, has_missing_seasons=True,
            )
        )
        session.add(
            SeriesModel(
                title="ZZZ Full Show", completeness_status="complete",
                has_missing_episodes=False, has_missing_seasons=False,
            )
        )
        session.commit()
    finally:
        session.close()


def test_missing_episodes_filter(isolated_db):
    """missing_episodes=1 → séries avec trous d'épisodes (dont mixtes)."""
    _seed_granular()
    with TestClient(app) as client:
        resp = client.get("/library/?type=series&missing_episodes=1")
    assert resp.status_code == 200
    body = resp.text
    assert "ZZZ Eps Gap" in body
    assert "ZZZ Both Gap" in body
    assert "ZZZ Season Gap" not in body
    assert "ZZZ Full Show" not in body


def test_missing_seasons_filter(isolated_db):
    """missing_seasons=1 → séries avec saisons entières manquantes (dont mixtes)."""
    _seed_granular()
    with TestClient(app) as client:
        resp = client.get("/library/?type=series&missing_seasons=1")
    assert resp.status_code == 200
    body = resp.text
    assert "ZZZ Season Gap" in body
    assert "ZZZ Both Gap" in body
    assert "ZZZ Eps Gap" not in body
    assert "ZZZ Full Show" not in body


def test_both_filters_union(isolated_db):
    """Les deux cases cochées → union (toute série remplissant un critère)."""
    _seed_granular()
    with TestClient(app) as client:
        resp = client.get("/library/?type=series&missing_episodes=1&missing_seasons=1")
    assert resp.status_code == 200
    body = resp.text
    assert "ZZZ Eps Gap" in body
    assert "ZZZ Season Gap" in body
    assert "ZZZ Both Gap" in body
    assert "ZZZ Full Show" not in body


def test_granular_filter_excludes_movies(isolated_db):
    """Un filtre granulaire actif exclut les films (comme incomplete_series)."""
    _seed_granular()
    session = next(get_session())
    try:
        session.add(MovieModel(title="ZZZ Some Movie", year=2024))
        session.commit()
    finally:
        session.close()
    with TestClient(app) as client:
        resp = client.get("/library/?type=all&missing_seasons=1")
    assert resp.status_code == 200
    assert "ZZZ Some Movie" not in resp.text
    assert "ZZZ Season Gap" in resp.text


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


def test_pagination_links_keep_incomplete_filter(isolated_db):
    """Les liens de pagination conservent incomplete_series=1 — régression :
    passer à la page 2 retombait sur la bibliothèque non filtrée."""
    session = next(get_session())
    try:
        for i in range(30):
            session.add(
                SeriesModel(title=f"ZZZ Broken {i:02d}", completeness_status="incomplete")
            )
        session.commit()
    finally:
        session.close()

    with TestClient(app) as client:
        resp = client.get("/library/?type=series&incomplete_series=1")
    assert resp.status_code == 200

    page2_links = re.findall(r'href="([^"]*[?&]page=2[^"]*)"', resp.text)
    assert page2_links, "aucun lien vers la page 2 dans la pagination"
    for href in page2_links:
        assert "incomplete_series=1" in href


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
