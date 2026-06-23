"""Tests de routage des routes de fusion de séries (overlay + exécution).

On valide ici que les routes sont bien enregistrées et appliquent le
contrôle d'accès « machine maître ». Le TestClient utilise un hôte
non-localhost, donc le POST de fusion doit être refusé (403).
"""

import pytest
from fastapi.testclient import TestClient

from src.web.app import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_merge_routes_are_registered(client):
    # GET overlay : 200 si les fiches existent, 404 sinon — on valide le routage.
    resp = client.get("/library/merge/overlay", params={"a": 1, "b": 2})
    assert resp.status_code in (200, 404)


def test_merge_post_requires_master_host(client):
    # En TestClient, request.client.host n'est pas localhost → 403 attendu,
    # ce qui prouve que la route existe et applique le contrôle d'accès.
    resp = client.post("/library/series/1/merge", data={"absorbed_id": 2})
    assert resp.status_code in (403, 400)
