from src.web.deps import templates


def _render(items, is_local=True):
    tmpl = templates.env.get_template("maintenance/_sandbox_section.html")
    return tmpl.render(
        sandbox_items=items,
        sandbox_count=len(items),
        sandbox_total_size="1.0 Go",
        is_local=is_local,
    )


def test_section_shows_category_badge_and_kept_indicator():
    items = [
        {
            "path": "/sb/rejets_doublons/Films/Heat (1995)/h.mkv",
            "name": "h.mkv",
            "size": "1.0 Go",
            "size_bytes": 1073741824,
            "modified": "25/05/2026",
            "original_path": "Films/Heat (1995)/h.mkv",
            "category": "rejet_doublon",
            "kept_version": "Films/Heat (1995)",
        },
        {
            "path": "/sb/orphans/Films/X (2000)/x.mkv",
            "name": "x.mkv",
            "size": "2.0 Go",
            "size_bytes": 2147483648,
            "modified": "25/05/2026",
            "original_path": "Films/X (2000)/x.mkv",
            "category": "orphelin",
            "kept_version": None,
        },
    ]
    html = _render(items)
    # Badges de catégorie
    assert "sandbox-badge-rejet_doublon" in html
    assert "Doublon rejeté" in html
    assert "sandbox-badge-orphelin" in html
    # Indicateurs version conservée
    assert "sandbox-kept-yes" in html
    assert "sandbox-kept-no" in html
    # data-attributs pour le filtre / récap
    assert 'data-category="rejet_doublon"' in html
    assert 'data-kept="yes"' in html
    assert 'data-kept="no"' in html
    # Barre de filtre
    assert "sandbox-filter" in html


def test_section_renders_without_checkboxes_when_not_local():
    items = [{
        "path": "/sb/orphans/Films/X (2000)/x.mkv", "name": "x.mkv",
        "size": "2.0 Go", "size_bytes": 2147483648, "modified": "25/05/2026",
        "original_path": "Films/X (2000)/x.mkv", "category": "orphelin",
        "kept_version": None,
    }]
    html = _render(items, is_local=False)
    # Pas de cases à cocher en non-local, mais le badge et l'indicateur restent
    assert "sandbox-cb" not in html
    assert "sandbox-badge-orphelin" in html
