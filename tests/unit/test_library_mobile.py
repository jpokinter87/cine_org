"""Consultation de la bibliothèque depuis un téléphone (Wi-Fi local).

Sur petit écran, les filtres occupaient tout le premier écran : un bouton
« Filtres » les replie et affiche le nombre de filtres actifs. Un manifest
permet d'ajouter CineOrg à l'écran d'accueil du téléphone.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from src.web.app import app
from tests.unit.test_browse_incomplete_filter import isolated_db  # noqa: F401

STATIC = Path(__file__).resolve().parents[2] / "src" / "web" / "static"


def _toggle(html: str) -> str:
    start = html.index('class="lib-filters-mobile-toggle"')
    return html[start : html.index("</button>", start)]


def test_filters_toggle_without_active_filter(isolated_db):  # noqa: F811
    with TestClient(app) as client:
        resp = client.get("/library/")
    assert "lib-tech-badge" not in _toggle(resp.text)


def test_filters_toggle_counts_active_filters(isolated_db):  # noqa: F811
    with TestClient(app) as client:
        resp = client.get("/library/?type=movie&genre=Drame&unwatched=1")
    assert '<span class="lib-tech-badge">3</span>' in _toggle(resp.text)


def test_manifest_is_declared_and_valid(isolated_db):  # noqa: F811
    with TestClient(app) as client:
        page = client.get("/library/")
        manifest = client.get("/static/manifest.json")
    assert '<link rel="manifest" href="/static/manifest.json">' in page.text
    assert manifest.status_code == 200
    data = manifest.json()
    assert data["start_url"] == "/library/"
    assert data["display"] == "standalone"
    for icon in data["icons"]:
        assert (STATIC / icon["src"].removeprefix("/static/")).is_file()
    assert {i["sizes"] for i in data["icons"]} >= {"192x192", "512x512"}
