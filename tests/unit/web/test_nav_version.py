"""Test : le numéro de version figure dans le bandeau de navigation.

La version vit dans pyproject.toml (source unique, cf. src/version.py). Elle
est affichée à côté du sigle CinéOrg pour vérifier d'un coup d'œil quelle
version tourne réellement après un déploiement.
"""

from __future__ import annotations

from src.version import get_version
from src.web.deps import templates


def test_nav_shows_version_number():
    """Le bandeau rend « vX.Y.Z » à côté du sigle."""
    html = templates.get_template("base.html").render(
        request=None,
        get_personal_profiles=lambda: [],
    )
    assert 'class="nav-version"' in html
    assert f"v{get_version()}" in html.split("</nav>")[0]


def test_version_globals_share_the_same_source():
    """Les deux globals dérivent de la même version."""
    version = get_version()
    assert templates.env.globals["app_version_number"] == version
    assert templates.env.globals["app_version"] == f"CineOrg v{version}"
