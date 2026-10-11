"""La bibliothèque ne doit jamais être resservie depuis le cache navigateur.

Après une fusion (ou une suppression), le retour arrière réaffichait la copie
en cache de la bibliothèque : la fiche absorbée y figurait encore et menait à
« Série introuvable ».
"""

import pytest
from fastapi.testclient import TestClient

from src.web.app import app
from tests.unit.test_browse_incomplete_filter import isolated_db  # noqa: F401


@pytest.mark.parametrize("hx", [False, True])
def test_library_response_is_not_stored(isolated_db, hx):  # noqa: F811
    headers = {"HX-Request": "true"} if hx else {}
    with TestClient(app) as client:
        resp = client.get("/library/", headers=headers)
    assert resp.status_code == 200
    assert "no-store" in resp.headers.get("cache-control", "")
