"""Test : le sélecteur « Vous regardez sur » propose aussi la DuneHD.

Depuis un téléphone, le bouton « Visionner » lançait la lecture sur le profil
« Local » (mpv sur le serveur) : la DuneHD n'était accessible que par le
chevron ▾, à chaque lecture. L'identité étant mémorisée par navigateur, le
téléphone peut désormais choisir la DuneHD une fois pour toutes.
"""

from __future__ import annotations

from src.web.deps import templates

PROFILES = {
    "active": "Local",
    "profiles": [
        {"name": "Local", "type": "mpv", "target": "local"},
        {"name": "Willow", "type": "mpv", "target": "remote"},
        {"name": "DuneHD", "type": "dunehd", "target": "remote"},
    ],
}


def _nav() -> str:
    html = templates.get_template("base.html").render(
        request=None, get_player_profiles=lambda: PROFILES
    )
    return html.split("</nav>")[0]


def test_viewer_select_offers_dunehd():
    nav = _nav()
    assert 'id="viewer-select"' in nav
    for name in ("Local", "Willow", "DuneHD"):
        assert f'<option value="{name}">' in nav


def test_viewer_select_hidden_with_single_profile():
    html = templates.get_template("base.html").render(
        request=None,
        get_player_profiles=lambda: {"profiles": [{"name": "Local"}]},
    )
    assert 'id="viewer-select"' not in html.split("</nav>")[0]
