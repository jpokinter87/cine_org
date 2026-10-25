"""Test : sélecteur de thème (Nuit ambrée par défaut, trois thèmes optionnels).

Le thème est mémorisé par navigateur (localStorage), comme « Vous regardez
sur » ; un script de <head> l'applique avant le premier rendu. Les thèmes
redéfinissent les variables CSS : aucune couleur d'accent ne doit rester en
dur dans la feuille de style.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.web.deps import templates

CSS = (
    Path(__file__).resolve().parents[3] / "src" / "web" / "static" / "css" / "style.css"
).read_text(encoding="utf-8")

THEMES = ("nuit", "cinematheque", "velours", "kodachrome")


def _render() -> str:
    return templates.get_template("base.html").render(
        request=None, get_player_profiles=lambda: {"profiles": [{"name": "Local"}]}
    )


def test_theme_select_offers_four_themes():
    nav = _render().split("</nav>")[0]
    assert 'id="theme-select"' in nav
    assert '<label for="theme-select"' in nav
    for theme in THEMES:
        assert f'<option value="{theme}">' in nav


def test_theme_applied_in_head_before_render():
    head = _render().split("</head>")[0]
    assert "cineorg.theme" in head
    assert "data-theme" in head


def test_stylesheet_defines_each_optional_theme():
    for theme in THEMES[1:]:
        assert f'[data-theme="{theme}"]' in CSS


def test_brand_accent_is_separate_from_warning():
    root = CSS.split(":root {", 1)[1].split("}", 1)[0]
    assert "--accent:" in root
    assert "--accent-amber:" in root


def test_no_hardcoded_accent_or_white_rgba():
    # Ambre, émeraude, rose, bleu et blanc translucides doivent passer par color-mix()
    forbidden = re.compile(
        r"rgba\(\s*(232,\s*168,\s*73|78,\s*203,\s*141|232,\s*93,\s*117"
        r"|91,\s*141,\s*239|255,\s*255,\s*255)\s*,"
    )
    assert forbidden.findall(CSS) == []


def _rule(selector: str) -> str:
    return CSS.split("\n" + selector + " {", 1)[1].split("}", 1)[0]


def test_play_buttons_follow_brand_accent():
    # « Visionner » prend la couleur de marque du thème, plus le vert « lecture »
    for selector in (
        ".lib-detail-poster-actions .play-btn",
        ".action-btn-play",
        ".suggest-play-btn",
    ):
        rule = _rule(selector)
        assert "var(--accent)" in rule
        assert "accent-emerald" not in rule
    # Variables jamais définies : la couleur prévue ne s'appliquait pas
    assert "var(--accent-warm)" not in CSS
    assert "var(--bg-primary)" not in CSS
