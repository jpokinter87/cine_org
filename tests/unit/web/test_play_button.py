"""Rendu du bouton « Visionner » côté Python (_play_button_html).

Doit rester cohérent avec le template library/_play_btn.html.
"""

import src.web.routes.library.player as player


def _profiles(*items):
    """items : tuples (name, type, target)."""
    return {
        "active": "Local",
        "profiles": [{"name": n, "type": t, "target": tg} for (n, t, tg) in items],
    }


def test_un_seul_profil_bouton_direct(monkeypatch):
    monkeypatch.setattr(
        player, "load_profiles", lambda: _profiles(("Local", "mpv", "local"))
    )
    html = player._play_button_html("movies", 5)
    assert 'hx-post="/library/movies/5/play"' in html
    assert "play-profile-popover" not in html


def test_plusieurs_profils_bouton_scinde(monkeypatch):
    monkeypatch.setattr(
        player,
        "load_profiles",
        lambda: _profiles(("Local", "mpv", "local"), ("Willow", "mpv", "remote")),
    )
    html = player._play_button_html("movies", 5)
    assert 'hx-post="/library/movies/5/play"' in html
    assert "play-btn-launch" in html
    assert "play-popover-trigger" in html
    assert "play-profile-popover" in html
    assert "/library/movies/5/play?profile=Willow" in html


def test_popover_liste_dunehd(monkeypatch):
    monkeypatch.setattr(
        player,
        "load_profiles",
        lambda: _profiles(("Local", "mpv", "local"), ("Salon", "dunehd", "remote")),
    )
    html = player._play_button_html("movies", 7)
    assert "/library/movies/7/play?profile=Salon" in html
    assert "mediacenter" in html
