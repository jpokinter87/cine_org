# « Visionner » en un clic avec identité par navigateur — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cliquer « Visionner » lance la vidéo en un seul clic sur la cible mémorisée dans le navigateur de chaque utilisateur, tout en gardant un chevron ▾ pour un choix ponctuel (autre profil, DuneHD).

**Architecture:** L'identité « qui regarde » est stockée côté client (`localStorage`), jamais côté serveur. Le bouton « Visionner » devient un *bouton scindé* : le corps lance directement (un écouteur JS global `htmx:configRequest` injecte `?profile=<identité>` dans la requête `/play`), le chevron ▾ rouvre le popover existant pour un lancement ponctuel. Un sélecteur d'identité dans l'en-tête (profils hors DuneHD) écrit l'identité dans `localStorage`.

**Tech Stack:** FastAPI + Jinja2 + HTMX (htmx 2.0.4), CSS maison, pytest (extra `dev`). Profils lecteur dans `player_profiles.json` via `src/player_profiles.py`.

---

## Contexte de code (lire avant de commencer)

- `src/player_profiles.py` : CRUD profils. `load_profiles()` renvoie `{"active": str, "profiles": [ {name, type, command, target, ...} ]}`. Le profil « Local » est protégé (toujours présent). Les profils DuneHD ont `type == "dunehd"`.
- `src/web/deps.py` : expose des globals aux templates Jinja (`get_player_profiles`).
- `src/web/templates/library/_play_btn.html` : partial du bouton, inclus depuis `movie_detail.html`, `series_detail.html`, `suggest.html`, `_detail_poster_actions.html`, `duplicates/_results.html`. Variables : `play_entity_type`, `play_entity_id`, `play_btn_class`, `play_show_label`.
- `src/web/routes/library/player.py` : endpoints `/play` (acceptent déjà `?profile=`) + `_play_button_html()` qui **reconstruit le même bouton** côté Python pour le restaurer après la fin de lecture (`/play-status`). **Duplication à maintenir en parallèle avec le template.**
- `src/web/templates/base.html` : `main-nav` (en-tête) + bloc `<script>` en bas avec `togglePlayPopover(...)`.
- CSS : `src/web/static/css/style.css` — `.play-btn` (≈6480), `.lib-episode-play-btn` (≈6499), `.play-wrapper` / `.play-profile-popover` (≈6527+), variante fiche détaillée `.lib-detail-poster-actions .play-btn` (≈9571, pleine largeur, vert emerald).

---

## Task 1 : `get_personal_profiles()` dans player_profiles.py

**Files:**
- Modify: `src/player_profiles.py`
- Test: `tests/unit/test_player_profiles.py`

- [ ] **Step 1 : Écrire le test qui échoue**

Ajouter à la fin de `tests/unit/test_player_profiles.py` :

```python
def test_get_personal_profiles_exclut_dunehd(tmp_path, monkeypatch):
    """get_personal_profiles ne renvoie que les profils personnes/écrans (hors DuneHD)."""
    import src.player_profiles as pp

    fake = {
        "active": "Local",
        "profiles": [
            {"name": "Local", "type": "mpv", "target": "local"},
            {"name": "Willow", "type": "mpv", "target": "remote"},
            {"name": "Salon", "type": "dunehd", "target": "remote"},
        ],
    }
    monkeypatch.setattr(pp, "load_profiles", lambda: fake)

    names = [p["name"] for p in pp.get_personal_profiles()]
    assert names == ["Local", "Willow"]
    assert "Salon" not in names
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `uv sync --extra dev && uv run pytest tests/unit/test_player_profiles.py::test_get_personal_profiles_exclut_dunehd -v`
Expected: FAIL avec `AttributeError: module 'src.player_profiles' has no attribute 'get_personal_profiles'`.

- [ ] **Step 3 : Implémenter**

Ajouter dans `src/player_profiles.py` (après `get_active_profile`, par ex.) :

```python
def get_personal_profiles() -> list[dict]:
    """Retourne les profils « personnes/écrans » (hors DuneHD).

    Sert au sélecteur d'identité de l'en-tête : on ne « devient » pas un DuneHD,
    qui reste une action ponctuelle « envoyer au mediacenter » dans le menu ▾.
    """
    data = load_profiles()
    return [p for p in data.get("profiles", []) if p.get("type") != "dunehd"]
```

- [ ] **Step 4 : Lancer le test, vérifier le succès**

Run: `uv run pytest tests/unit/test_player_profiles.py::test_get_personal_profiles_exclut_dunehd -v`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add src/player_profiles.py tests/unit/test_player_profiles.py
git commit -m "feat(player): get_personal_profiles() pour le sélecteur d'identité"
```

---

## Task 2 : Exposer get_personal_profiles aux templates

**Files:**
- Modify: `src/web/deps.py`

- [ ] **Step 1 : Implémenter**

Dans `src/web/deps.py`, remplacer le bloc d'import des profils (lignes ~30-33) :

```python
# Profils lecteur accessibles dans tous les templates (pour le sélecteur de profil)
from ..player_profiles import load_profiles as _load_profiles  # noqa: E402
```

par :

```python
# Profils lecteur accessibles dans tous les templates (sélecteur de profil + identité)
from ..player_profiles import (  # noqa: E402
    get_personal_profiles as _personal_profiles,
    load_profiles as _load_profiles,
)
```

Puis, juste après la ligne `templates.env.globals["get_player_profiles"] = _load_profiles`, ajouter :

```python
templates.env.globals["get_personal_profiles"] = _personal_profiles
```

- [ ] **Step 2 : Vérifier l'import (pas de régression)**

Run: `uv run python -c "import src.web.deps as d; print(d.templates.env.globals['get_personal_profiles'])"`
Expected: affiche `<function get_personal_profiles at 0x...>` sans erreur.

- [ ] **Step 3 : Commit**

```bash
git add src/web/deps.py
git commit -m "feat(player): exposer get_personal_profiles aux templates"
```

---

## Task 3 : Sélecteur d'identité + JS dans base.html

**Files:**
- Modify: `src/web/templates/base.html`

- [ ] **Step 1 : Ajouter le sélecteur dans l'en-tête**

Dans `src/web/templates/base.html`, juste **après** `</ul>` (fin de `nav-links`, ligne ~34) et **avant** `<button class="nav-toggle" ...>` (ligne ~35), insérer :

```html
        {% set _personal = get_personal_profiles() %}
        {% if _personal | length > 1 %}
        <div class="viewer-select-wrap">
            <label for="viewer-select" class="viewer-select-label">Vous regardez sur</label>
            <select id="viewer-select" class="viewer-select" onchange="setViewerProfile(this.value)">
                {% for p in _personal %}
                <option value="{{ p.name }}">{{ p.name }}</option>
                {% endfor %}
            </select>
        </div>
        {% endif %}
```

- [ ] **Step 2 : Ajouter le JS (identité + injection du profil)**

Dans le bloc `<script>` en bas de `base.html`, juste **après** la ligne `function togglePlayPopover(btn) { ... }` (après sa `}` de fermeture, ligne ~69), insérer :

```javascript
    /* Identité « qui regarde » mémorisée dans CE navigateur (jamais côté serveur) */
    var VIEWER_KEY = 'cineorg.viewer';
    function getViewerProfile() {
        try { return localStorage.getItem(VIEWER_KEY) || 'Local'; }
        catch (e) { return 'Local'; }
    }
    function setViewerProfile(name) {
        try { localStorage.setItem(VIEWER_KEY, name); } catch (e) {}
    }
    /* Initialiser le sélecteur depuis localStorage ; repli sur Local si profil disparu */
    document.addEventListener('DOMContentLoaded', function() {
        var sel = document.getElementById('viewer-select');
        if (!sel) return;
        var stored = getViewerProfile();
        var found = false;
        for (var i = 0; i < sel.options.length; i++) {
            if (sel.options[i].value === stored) { found = true; break; }
        }
        if (!found) { stored = 'Local'; setViewerProfile('Local'); }
        sel.value = stored;
    });
    /* « Visionner » en un clic : injecter l'identité dans les requêtes /play
       qui n'ont pas déjà un profil explicite (les options du ▾ en portent un). */
    document.body.addEventListener('htmx:configRequest', function(evt) {
        var path = evt.detail.path || '';
        if (evt.detail.verb === 'post' && /\/play(\?|$)/.test(path)
            && path.indexOf('profile=') === -1) {
            var sep = path.indexOf('?') === -1 ? '?' : '&';
            evt.detail.path = path + sep + 'profile=' + encodeURIComponent(getViewerProfile());
        }
    });
```

- [ ] **Step 3 : Vérifier que la page se rend (smoke test)**

Run: `uv run python -c "from src.web.deps import templates; print('viewer-select' in templates.get_template('base.html').render())"`
Expected: `True` si plusieurs profils personnels existent, sinon `False` (les deux sont acceptables — dépend de `player_profiles.json`). Le but est qu'aucune exception Jinja ne soit levée.

- [ ] **Step 4 : Commit**

```bash
git add src/web/templates/base.html
git commit -m "feat(player): sélecteur d'identité dans l'en-tête + injection profil HTMX"
```

---

## Task 4 : Bouton scindé dans le partial _play_btn.html

**Files:**
- Modify: `src/web/templates/library/_play_btn.html`

- [ ] **Step 1 : Remplacer tout le contenu du partial**

Remplacer **l'intégralité** de `src/web/templates/library/_play_btn.html` par :

```html
{#
  Bouton « Visionner » : lancement direct sur l'identité du navigateur (un clic)
  + chevron ▾ pour un choix ponctuel (autre profil, DuneHD).

  Variables attendues :
    - play_entity_type: "movies" | "movie-parts" | "episodes" | "series"
    - play_entity_id: int
    - play_btn_class: classe CSS du bouton (ex. "play-btn", "lib-episode-play-btn", "dup-btn-play")
    - play_show_label: true/false (afficher « Visionner » ou juste l'icône)
#}
{% set _pdata = get_player_profiles() %}
{% set _profiles = _pdata.get('profiles', []) %}
{% set _icon_sz = '14' if not play_show_label else '12' %}

{% if _profiles | length <= 1 %}
  {# Un seul profil : bouton direct #}
  <button class="{{ play_btn_class }}"
      hx-post="/library/{{ play_entity_type }}/{{ play_entity_id }}/play"
      hx-swap="outerHTML"
      title="Visionner">
      <svg width="{{ _icon_sz }}" height="{{ _icon_sz }}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
      {% if play_show_label %} Visionner{% endif %}
  </button>
{% else %}
  {# Plusieurs profils : bouton scindé (lancement direct + chevron popover) #}
  <span class="play-wrapper{% if 'episode' in play_btn_class %} play-wrapper-episode{% endif %}">
      <button class="{{ play_btn_class }} play-btn-launch"
          hx-post="/library/{{ play_entity_type }}/{{ play_entity_id }}/play"
          hx-swap="outerHTML" hx-target="closest .play-wrapper"
          title="Visionner sur votre profil">
          <svg width="{{ _icon_sz }}" height="{{ _icon_sz }}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          {% if play_show_label %} Visionner{% endif %}
      </button>
      <button class="{{ play_btn_class }} play-btn-caret play-popover-trigger"
          title="Choisir le lecteur" onclick="togglePlayPopover(this)">
          <svg class="play-caret-icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      <div class="play-profile-popover">
          {% for p in _profiles %}
          <button class="play-profile-option"
              hx-post="/library/{{ play_entity_type }}/{{ play_entity_id }}/play?profile={{ p.name | urlencode }}"
              hx-swap="outerHTML" hx-target="closest .play-wrapper"
              onclick="event.stopPropagation()">
              {% if p.type == 'dunehd' %}
              <svg class="play-profile-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 16.1A5 5 0 0 1 5.9 20M2 12.05A9 9 0 0 1 9.95 20M2 8V6a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-6"/><line x1="2" y1="20" x2="2.01" y2="20"/></svg>
              {% elif p.target == 'remote' %}
              <svg class="play-profile-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="15" rx="2"/><polyline points="17 2 12 7 7 2"/></svg>
              {% else %}
              <svg class="play-profile-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
              {% endif %}
              {{ p.name }}{% if p.type == 'dunehd' %} <span class="play-profile-default">→ mediacenter</span>{% endif %}
          </button>
          {% endfor %}
      </div>
  </span>
{% endif %}
```

- [ ] **Step 2 : Vérifier le rendu (smoke test)**

Run: `uv run python -c "from src.web.deps import templates; t=templates.get_template('library/_play_btn.html'); print(t.render(play_entity_type='movies', play_entity_id=1, play_btn_class='play-btn', play_show_label=True)[:200])"`
Expected: du HTML s'affiche sans exception Jinja.

- [ ] **Step 3 : Commit**

```bash
git add src/web/templates/library/_play_btn.html
git commit -m "feat(player): bouton « Visionner » scindé (lancement direct + chevron ▾)"
```

---

## Task 5 : Mettre _play_button_html (player.py) en cohérence

**Files:**
- Modify: `src/web/routes/library/player.py:151-250` (fonction `_play_button_html`)
- Test: `tests/unit/web/test_play_button.py` (créer)

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/unit/web/test_play_button.py` :

```python
"""Rendu du bouton « Visionner » côté Python (_play_button_html).

Doit rester cohérent avec le template library/_play_btn.html.
"""

import src.web.routes.library.player as player


def _profiles(*items):
    """items : tuples (name, type, target)."""
    return {
        "active": "Local",
        "profiles": [
            {"name": n, "type": t, "target": tg} for (n, t, tg) in items
        ],
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
    # Bouton principal : lancement direct SANS profile (injecté côté client)
    assert 'hx-post="/library/movies/5/play"' in html
    assert "play-btn-launch" in html
    # Chevron + popover présents
    assert "play-popover-trigger" in html
    assert "play-profile-popover" in html
    # Option ponctuelle avec profil explicite
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
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run: `uv run pytest tests/unit/web/test_play_button.py -v`
Expected: `test_plusieurs_profils_bouton_scinde` et `test_popover_liste_dunehd` échouent (l'ancien rendu n'a ni `play-btn-launch`, ni le bouton principal sans `profile=`, ni `mediacenter`). `test_un_seul_profil_bouton_direct` peut déjà passer.

- [ ] **Step 3 : Remplacer la fonction _play_button_html**

Dans `src/web/routes/library/player.py`, remplacer **toute** la fonction `_play_button_html` (de `def _play_button_html(` jusqu'à son `return ...` final, ~lignes 151-250) par :

```python
def _play_button_html(entity_type: str, entity_id: int) -> str:
    """Génère le bouton « Visionner » (bouton scindé) pour restaurer après lecture.

    Doit rester cohérent avec le template library/_play_btn.html : le corps lance
    directement (l'identité est injectée côté client), le chevron ▾ ouvre le popover
    pour un choix ponctuel (autre profil, DuneHD).
    """
    data = load_profiles()
    profiles = data.get("profiles", [])

    is_episode = entity_type == "episodes"
    btn_class = "lib-episode-play-btn" if is_episode else "play-btn"
    label = "" if is_episode else " Visionner"
    icon_sz = "14" if is_episode else "12"
    base = f"/library/{entity_type}/{entity_id}/play"

    play_icon = (
        f'<svg width="{icon_sz}" height="{icon_sz}" viewBox="0 0 24 24" fill="none"'
        f' stroke="currentColor" stroke-width="2">'
        f'<polygon points="5 3 19 12 5 21 5 3"/></svg>'
    )

    if len(profiles) <= 1:
        return (
            f'<button class="{btn_class}"'
            f' hx-post="{base}" hx-swap="outerHTML" title="Visionner">'
            f"{play_icon}{label}</button>"
        )

    caret = (
        '<svg class="play-caret-icon" width="11" height="11" viewBox="0 0 24 24"'
        ' fill="none" stroke="currentColor" stroke-width="2">'
        '<polyline points="6 9 12 15 18 9"/></svg>'
    )
    icon_local = (
        '<svg class="play-profile-icon" width="14" height="14" viewBox="0 0 24 24"'
        ' fill="none" stroke="currentColor" stroke-width="2">'
        '<rect x="2" y="3" width="20" height="14" rx="2"/>'
        '<line x1="8" y1="21" x2="16" y2="21"/>'
        '<line x1="12" y1="17" x2="12" y2="21"/></svg>'
    )
    icon_remote = (
        '<svg class="play-profile-icon" width="14" height="14" viewBox="0 0 24 24"'
        ' fill="none" stroke="currentColor" stroke-width="2">'
        '<rect x="2" y="7" width="20" height="15" rx="2"/>'
        '<polyline points="17 2 12 7 7 2"/></svg>'
    )
    icon_cast = (
        '<svg class="play-profile-icon" width="14" height="14" viewBox="0 0 24 24"'
        ' fill="none" stroke="currentColor" stroke-width="2">'
        '<path d="M2 16.1A5 5 0 0 1 5.9 20M2 12.05A9 9 0 0 1 9.95 20'
        'M2 8V6a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-6"/>'
        '<line x1="2" y1="20" x2="2.01" y2="20"/></svg>'
    )

    options_html = ""
    for p in profiles:
        name_esc = html.escape(p["name"])
        if p.get("type") == "dunehd":
            icon = icon_cast
            suffix = ' <span class="play-profile-default">→ mediacenter</span>'
        elif p.get("target") == "remote":
            icon = icon_remote
            suffix = ""
        else:
            icon = icon_local
            suffix = ""
        options_html += (
            f'<button class="play-profile-option"'
            f' hx-post="{base}?profile={name_esc}"'
            f' hx-swap="outerHTML" hx-target="closest .play-wrapper"'
            f' onclick="event.stopPropagation()">'
            f"{icon} {name_esc}{suffix}</button>"
        )

    wrapper_class = (
        "play-wrapper play-wrapper-episode" if is_episode else "play-wrapper"
    )
    return (
        f'<span class="{wrapper_class}">'
        f'<button class="{btn_class} play-btn-launch"'
        f' hx-post="{base}" hx-swap="outerHTML"'
        f' hx-target="closest .play-wrapper" title="Visionner sur votre profil">'
        f"{play_icon}{label}</button>"
        f'<button class="{btn_class} play-btn-caret play-popover-trigger"'
        f' title="Choisir le lecteur" onclick="togglePlayPopover(this)">'
        f"{caret}</button>"
        f'<div class="play-profile-popover">{options_html}</div>'
        f"</span>"
    )
```

- [ ] **Step 4 : Lancer les tests, vérifier le succès**

Run: `uv run pytest tests/unit/web/test_play_button.py -v`
Expected: les 3 tests PASS.

- [ ] **Step 5 : Non-régression des endpoints play**

Run: `uv run pytest tests/unit/web/test_movie_part_play.py tests/unit/test_player.py -v`
Expected: PASS (les endpoints `/play` acceptent toujours `?profile=`).

- [ ] **Step 6 : Commit**

```bash
git add src/web/routes/library/player.py tests/unit/web/test_play_button.py
git commit -m "feat(player): bouton scindé côté serveur (restauration après lecture)"
```

---

## Task 6 : CSS du bouton scindé + sélecteur d'en-tête

**Files:**
- Modify: `src/web/static/css/style.css`

- [ ] **Step 1 : Ajouter les styles du bouton scindé**

À la fin de la section sélecteur de profil (juste **après** la règle `.play-popover-trigger { position: relative; }`, ligne ~6634), ajouter :

```css
/* --- Bouton scindé : corps « Visionner » + chevron ▾ --- */
.play-btn-launch {
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
}
.play-btn-caret {
    border-top-left-radius: 0;
    border-bottom-left-radius: 0;
    padding-left: 0.3rem;
    padding-right: 0.4rem;
    gap: 0;
}
/* Variante .play-btn (avec bordure) : éviter la double bordure entre corps et chevron */
.play-btn.play-btn-caret {
    border-left-color: transparent;
}
.play-caret-icon {
    flex-shrink: 0;
    opacity: 0.75;
}
```

- [ ] **Step 2 : Ajouter les styles spécifiques à la fiche détaillée (bouton hero)**

Juste **après** la règle `.lib-detail-poster-actions .play-btn:hover { ... }` (ligne ~9595), ajouter :

```css
/* Bouton scindé dans la fiche détaillée : corps extensible + chevron compact */
.lib-detail-poster-actions .play-btn-launch {
    width: auto;
    flex: 1 1 auto;
}
.lib-detail-poster-actions .play-btn-caret {
    width: auto;
    flex: 0 0 auto;
    padding-left: 0.5rem;
    padding-right: 0.6rem;
}
.lib-detail-poster-actions .play-btn-caret svg {
    width: 13px;
    height: 13px;
}
```

- [ ] **Step 3 : Ajouter les styles du sélecteur d'en-tête**

À la fin de la section navigation (chercher la dernière règle `.nav-*` ou, à défaut, à la fin du fichier), ajouter :

```css
/* --- Sélecteur d'identité « qui regarde » (en-tête) --- */
.viewer-select-wrap {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    margin-left: auto;
    margin-right: 0.75rem;
}
.viewer-select-label {
    font-size: 0.72rem;
    color: var(--text-muted);
    white-space: nowrap;
}
.viewer-select {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.78rem;
    color: var(--text-primary);
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 0.25rem 0.45rem;
    cursor: pointer;
}
.viewer-select:hover {
    border-color: var(--accent-emerald);
}
```

> Note : si `margin-left: auto` sur `.viewer-select-wrap` ne pousse pas correctement le sélecteur à droite (selon le `display` de `.main-nav`), vérifier visuellement à l'étape suivante et ajuster (`.main-nav` est probablement `display:flex`). Ne pas modifier `.main-nav` sauf nécessité confirmée.

- [ ] **Step 4 : Vérification visuelle (manuelle)**

Lancer le serveur : `uv run uvicorn src.web.app:app --reload --host 0.0.0.0`
Ouvrir une fiche film. Vérifier :
- Le bouton « Visionner » apparaît scindé (corps + chevron accolé, sans double bordure).
- Le sélecteur « Vous regardez sur » apparaît à droite dans l'en-tête.

- [ ] **Step 5 : Commit**

```bash
git add src/web/static/css/style.css
git commit -m "style(player): bouton scindé + sélecteur d'identité dans l'en-tête"
```

---

## Task 7 : Vérification end-to-end manuelle + README

**Files:**
- Modify: `README.md`

- [ ] **Step 1 : Vérification fonctionnelle manuelle**

Serveur lancé (`uv run uvicorn src.web.app:app --reload --host 0.0.0.0`), avec au moins 2 profils personnels + 1 DuneHD dans `player_profiles.json`. Vérifier le scénario complet :

1. En-tête : régler « Vous regardez sur » sur un profil (ex. Willow).
2. Sur une fiche film, **un clic** sur le corps de « Visionner » → la lecture démarre sur Willow (le bandeau « Lecture en cours… (Willow) » apparaît), **sans** menu intermédiaire.
3. Ouvrir un **2ᵉ navigateur** (ou fenêtre privée), régler l'identité sur un autre profil → un clic lance sur cet autre profil, sans affecter le premier.
4. Cliquer le chevron ▾ → choisir DuneHD → l'ordre part au mediacenter ; l'identité de l'en-tête n'a pas changé.
5. Recharger la page : l'identité choisie est conservée (localStorage).

Confirmer dans les outils dev (onglet Réseau) que la requête `/play` du clic principal porte bien `?profile=<identité>`, et que l'option du ▾ porte le profil choisi.

- [ ] **Step 2 : Documenter dans le README**

Dans `README.md`, repérer la section décrivant le bouton « Visionner » / les profils lecteur (chercher « Visionner » ou « profil »). Mettre à jour / ajouter un paragraphe :

```markdown
### Visionner en un clic (identité par navigateur)

Chaque navigateur mémorise « qui regarde » via le sélecteur **« Vous regardez sur »**
de l'en-tête (stockage local, propre à chaque appareil — aucun réglage côté serveur,
donc plusieurs personnes peuvent regarder en même temps sans interférence).

- **Clic sur « Visionner »** : lance la vidéo directement sur votre profil, en un seul clic.
- **Chevron ▾** : choix ponctuel d'un autre lecteur ou envoi vers le mediacenter **DuneHD**,
  sans changer votre identité.

DuneHD n'apparaît pas dans le sélecteur d'identité (il *envoie* au mediacenter plutôt que
de « regarder ») : il reste accessible uniquement via le menu ▾.
```

(Ajouter une entrée à la table des matières si la section est nouvelle.)

- [ ] **Step 3 : Lint des fichiers modifiés**

Run: `uv run --extra dev ruff check src/player_profiles.py src/web/deps.py src/web/routes/library/player.py tests/unit/web/test_play_button.py tests/unit/test_player_profiles.py`
Expected: aucune nouvelle erreur (corriger le cas échéant). Puis :
Run: `uv run --extra dev ruff format src/player_profiles.py src/web/deps.py src/web/routes/library/player.py tests/unit/web/test_play_button.py`

- [ ] **Step 4 : Suite de tests ciblée**

Run: `uv sync --extra dev && uv run pytest tests/unit/web/ tests/unit/test_player.py tests/unit/test_player_profiles.py tests/unit/test_dunehd_player.py -v`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add README.md
git commit -m "docs: « Visionner » en un clic avec identité par navigateur"
```

---

## Self-review (couverture spec → plan)

- **Identité côté client (localStorage, défaut Local, repli si profil disparu)** → Task 3 (JS `getViewerProfile` + init sélecteur).
- **`active` serveur inerte pour le défaut** → plus utilisé pour piloter le clic (Task 3/5) ; conservé dans le fichier (hors périmètre, OK).
- **Sélecteur d'en-tête, profils personnels uniquement, masqué si ≤1** → Task 1 (`get_personal_profiles`), Task 2 (global), Task 3 (`{% if _personal|length > 1 %}`).
- **Clic = lancement direct via `htmx:configRequest`** → Task 3 (listener), Task 4 + Task 5 (bouton principal sans `profile=`).
- **Chevron ▾ = popover tous profils + DuneHD, lancement ponctuel** → Task 4 + Task 5 (options avec `?profile=`, DuneHD avec « → mediacenter »).
- **DuneHD jamais dans le sélecteur d'identité** → Task 1 (filtre `type != dunehd`).
- **Duplication `_play_btn.html` / `_play_button_html` maintenue en parallèle** → Task 4 + Task 5.
- **CSS bouton scindé + sélecteur** → Task 6.
- **Tests serveur (exclusion DuneHD, bouton sans popover forcé, ▾ liste tout)** → Task 1, Task 5.
- **README** → Task 7.
- **Vérif manuelle de la couche JS** → Task 6 step 4, Task 7 step 1.

Aucun placeholder. Signatures cohérentes (`get_personal_profiles`, `getViewerProfile`/`setViewerProfile`, classes `play-btn-launch`/`play-btn-caret`/`play-caret-icon`, clé `cineorg.viewer`) entre toutes les tâches.
```
