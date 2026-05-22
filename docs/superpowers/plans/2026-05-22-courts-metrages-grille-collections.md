# Courts-métrages : grille + collection en masse — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Masquer les courts-métrages de la grille par défaut (les exposer via un type « Courts ») et permettre de sélectionner plusieurs films pour les ranger en masse dans une collection locale, avec déplacement immédiat des symlinks.

**Architecture:** Filtre `is_short` ajouté dans la route de navigation `browse.py` piloté par un 3ᵉ type « Courts ». Action de masse greffée sur le mode sélection existant (`delete.js` + barre flottante) via un nouvel endpoint `POST /library/collection-batch` qui réutilise `SQLModelLocalCollectionRepository` (find-or-create) puis `ShortReclassifier` (déplacement symlink). Aucune logique de chemin dupliquée.

**Tech Stack:** Python 3.11, FastAPI, SQLModel (SQLite), Jinja2/HTMX, JS vanilla, pytest. Toutes les commandes via `uv run`.

**Spec de référence:** `docs/superpowers/specs/2026-05-22-courts-metrages-grille-collections-design.md`

---

## Structure des fichiers

| Fichier | Responsabilité | Action |
| --- | --- | --- |
| `src/web/routes/library/browse.py` | filtre `is_short` selon `type` + contexte `local_collections` | Modifier |
| `src/web/templates/library/_filters.html` | option « Courts » + libellé du tag de filtre actif | Modifier |
| `src/web/templates/library/index.html` | bouton barre + overlay collection + `<datalist>` | Modifier |
| `src/web/static/css/style.css` | style bouton collection + champ nom | Modifier |
| `src/web/static/js/delete.js` | action « Ajouter à une collection » | Modifier |
| `src/web/routes/library/collections.py` | endpoint `POST /collection-batch` | Modifier |
| `tests/unit/web/test_browse_shorts_filter.py` | tests filtre « Courts » | Créer |
| `tests/unit/web/test_library_collections_routes.py` | tests endpoint + déplacement symlink | Modifier |
| `README.md` | documentation utilisateur | Modifier |

---

## Task 1 : Filtre « Courts » dans la grille

**Files:**
- Create: `tests/unit/web/test_browse_shorts_filter.py`
- Modify: `src/web/routes/library/browse.py` (bloc Films ~87-133)
- Modify: `src/web/templates/library/_filters.html` (sélecteur type + tag actif)

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/unit/web/test_browse_shorts_filter.py` :

```python
"""Tests — filtre « Courts » dans la grille (browse.py)."""

import pytest
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.testclient import TestClient

from src.infrastructure.persistence.models import MovieModel, SeriesModel
from src.web.routes.library.browse import router as browse_router

HX = {"HX-Request": "true"}


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def client(engine, monkeypatch):
    from src.web.routes.library import browse as browse_module

    def _get_session():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(browse_module, "get_session", _get_session)
    app = FastAPI()
    app.include_router(browse_router, prefix="/library")
    return TestClient(app)


def _seed(engine):
    with Session(engine) as session:
        session.add(MovieModel(title="Long Film", year=2010, is_short=False))
        session.add(MovieModel(title="Court Bunny", year=1958, is_short=True))
        session.add(SeriesModel(title="Ma Serie", year=2015))
        session.commit()


def test_all_excludes_shorts(client, engine):
    _seed(engine)
    r = client.get("/library/?type=all", headers=HX)
    assert r.status_code == 200
    assert "Long Film" in r.text
    assert "Ma Serie" in r.text
    assert "Court Bunny" not in r.text


def test_movie_excludes_shorts(client, engine):
    _seed(engine)
    r = client.get("/library/?type=movie", headers=HX)
    assert "Long Film" in r.text
    assert "Court Bunny" not in r.text
    assert "Ma Serie" not in r.text


def test_courts_shows_only_shorts(client, engine):
    _seed(engine)
    r = client.get("/library/?type=courts", headers=HX)
    assert "Court Bunny" in r.text
    assert "Long Film" not in r.text
    assert "Ma Serie" not in r.text


def test_courts_option_present(client, engine):
    _seed(engine)
    r = client.get("/library/?type=all", headers=HX)
    assert 'value="courts"' in r.text
```

- [ ] **Step 2 : Lancer le test pour vérifier l'échec**

Run: `uv sync --extra dev && uv run pytest tests/unit/web/test_browse_shorts_filter.py -v`
Expected: FAIL — `test_all_excludes_shorts` et `test_movie_excludes_shorts` échouent (« Court Bunny » présent car non filtré), `test_courts_shows_only_shorts` échoue (« Long Film » présent), `test_courts_option_present` échoue (option absente).

- [ ] **Step 3 : Implémenter le filtre dans `browse.py`**

Dans `src/web/routes/library/browse.py`, élargir la condition du bloc Films à `"courts"`. Remplacer :

```python
        # --- Films ---
        if type in ("all", "movie"):
```

par :

```python
        # --- Films ---
        if type in ("all", "movie", "courts"):
```

Puis, juste après le bloc `unwatched` et avant `movies = session.exec(movie_stmt).all()`, ajouter le filtre `is_short`. Remplacer :

```python
            if unwatched == "1":
                movie_stmt = movie_stmt.where(MovieModel.watched == False)  # noqa: E712

            movies = session.exec(movie_stmt).all()
```

par :

```python
            if unwatched == "1":
                movie_stmt = movie_stmt.where(MovieModel.watched == False)  # noqa: E712
            if type == "courts":
                movie_stmt = movie_stmt.where(MovieModel.is_short == True)  # noqa: E712
            else:
                movie_stmt = movie_stmt.where(MovieModel.is_short == False)  # noqa: E712

            movies = session.exec(movie_stmt).all()
```

Le bloc Séries reste conditionné à `type in ("all", "series")` : `"courts"` exclut donc nativement les séries (aucune modification du bloc Séries).

- [ ] **Step 4 : Implémenter l'option et le tag dans `_filters.html`**

Dans `src/web/templates/library/_filters.html`, ajouter l'option « Courts » au sélecteur de type. Remplacer :

```html
        <select name="type" class="lib-filter-select">
            <option value="all" {{ 'selected' if current_type == 'all' }}>Tous</option>
            <option value="movie" {{ 'selected' if current_type == 'movie' }}>Films</option>
            <option value="series" {{ 'selected' if current_type == 'series' }}>Series</option>
        </select>
```

par :

```html
        <select name="type" class="lib-filter-select">
            <option value="all" {{ 'selected' if current_type == 'all' }}>Tous</option>
            <option value="movie" {{ 'selected' if current_type == 'movie' }}>Films</option>
            <option value="series" {{ 'selected' if current_type == 'series' }}>Series</option>
            <option value="courts" {{ 'selected' if current_type == 'courts' }}>Courts</option>
        </select>
```

Puis corriger le libellé du tag de filtre actif (aujourd'hui binaire). Remplacer :

```html
            {{ 'Film' if current_type == 'movie' else 'Serie' }}
```

par :

```html
            {% if current_type == 'movie' %}Film{% elif current_type == 'courts' %}Court{% else %}Serie{% endif %}
```

- [ ] **Step 5 : Lancer le test pour vérifier le succès**

Run: `uv run pytest tests/unit/web/test_browse_shorts_filter.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6 : Lint + commit**

```bash
uv run ruff format src/web/routes/library/browse.py tests/unit/web/test_browse_shorts_filter.py
uv run ruff check src/web/routes/library/browse.py tests/unit/web/test_browse_shorts_filter.py
git add src/web/routes/library/browse.py src/web/templates/library/_filters.html tests/unit/web/test_browse_shorts_filter.py
git commit -m "feat(courts): filtre type « Courts » dans la grille (exclu de Tous/Films)"
```

---

## Task 2 : Contexte `local_collections` + UI barre/overlay

**Files:**
- Modify: `src/web/routes/library/browse.py` (imports + requête + contexte)
- Modify: `src/web/templates/library/index.html` (barre + overlay + datalist)
- Modify: `src/web/static/css/style.css` (après ligne 8345)

> Cette tâche est de l'UI (template/CSS) + une clé de contexte. Vérification manuelle en fin de tâche : pas de test automatisé (la barre est sous `{% if is_local %}`, non rendue pour l'hôte de test ; le comportement JS est validé en Task 4).

- [ ] **Step 1 : Exposer `local_collections` dans le contexte de `browse.py`**

Dans `src/web/routes/library/browse.py`, étendre l'import des modèles. Remplacer :

```python
from ....infrastructure.persistence.models import MovieModel, SeriesModel
```

par :

```python
from ....infrastructure.persistence.models import (
    LocalCollectionModel,
    MovieModel,
    SeriesModel,
)
```

Puis, dans le bloc `try` juste avant `finally: session.close()` (après la construction de `all_languages`), ajouter la requête des noms de collections locales :

```python
        local_collection_names = session.exec(
            select(LocalCollectionModel.name).order_by(LocalCollectionModel.name)
        ).all()
```

Enfin, ajouter la clé au dictionnaire `context` (à côté de `"languages": all_languages,`) :

```python
        "local_collections": local_collection_names,
```

- [ ] **Step 2 : Ajouter le bouton de barre et l'overlay dans `index.html`**

Dans `src/web/templates/library/index.html`, à l'intérieur du bloc `{% if is_local %}`, ajouter le bouton « Ajouter à une collection » dans la barre flottante. Remplacer :

```html
<div class="delete-bar" id="delete-bar">
    <div class="delete-bar-count"><span id="delete-count">0</span> sélectionné(s)</div>
    <button class="delete-bar-btn delete-bar-btn-danger" id="delete-confirm-btn">
```

par :

```html
<div class="delete-bar" id="delete-bar">
    <div class="delete-bar-count"><span id="delete-count">0</span> sélectionné(s)</div>
    <button class="delete-bar-btn delete-bar-btn-collection" id="collection-confirm-btn">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: -2px; margin-right: 3px;"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
        Ajouter à une collection
    </button>
    <button class="delete-bar-btn delete-bar-btn-danger" id="delete-confirm-btn">
```

Puis, juste après la fermeture du bloc `<!-- Dialogue de confirmation suppression -->` (la `</div>` qui ferme `#delete-overlay`) et avant `<script src="/static/js/delete.js"></script>`, ajouter l'overlay collection :

```html
<!-- Dialogue : ajout à une collection -->
<div class="delete-overlay" id="collection-overlay">
    <div class="delete-dialog">
        <div class="delete-dialog-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
        </div>
        <h3 class="delete-dialog-title">Ajouter <span id="collection-overlay-count">0</span> élément(s) à une collection</h3>
        <p class="delete-dialog-text">Saisissez un nom de collection : un nom existant est réutilisé, un nouveau nom crée la collection. Les courts sélectionnés seront déplacés vers <code>Films/Courts/{collection}/</code> (les séries sont ignorées).</p>
        <input type="text" id="collection-name-input" list="collection-names" class="collection-name-input" placeholder="Nom de la collection (ex. Looney Tunes)" autocomplete="off">
        <datalist id="collection-names">
            {% for name in local_collections %}
            <option value="{{ name }}"></option>
            {% endfor %}
        </datalist>
        <div class="delete-dialog-actions">
            <button class="reject-dialog-cancel" id="collection-overlay-cancel">Annuler</button>
            <button class="reject-dialog-confirm" id="collection-overlay-confirm">Ajouter à la collection</button>
        </div>
    </div>
</div>
```

- [ ] **Step 3 : Styler le bouton et le champ dans `style.css`**

Dans `src/web/static/css/style.css`, juste après le bloc `.delete-bar-btn-cancel:hover { ... }` (vers la ligne 8345), ajouter :

```css
.delete-bar-btn-collection {
    background: rgba(52, 211, 153, 0.15);
    color: var(--accent-emerald, #34d399);
    border: 1px solid rgba(52, 211, 153, 0.3);
}

.delete-bar-btn-collection:hover {
    background: rgba(52, 211, 153, 0.25);
    border-color: rgba(52, 211, 153, 0.5);
}

.collection-name-input {
    width: 100%;
    margin: 0.5rem 0 1rem;
    padding: 0.6rem 0.85rem;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    background: var(--bg-card);
    color: var(--text-primary);
    font-family: var(--font-body);
    font-size: 0.9rem;
}

.collection-name-input:focus {
    outline: none;
    border-color: rgba(52, 211, 153, 0.6);
}
```

- [ ] **Step 4 : Vérification manuelle**

```bash
uv run uvicorn src.web.app:app --reload
```

Ouvrir `http://127.0.0.1:8000/library/`, cliquer « Suppression » (mode sélection), cocher une jaquette : la barre flottante doit afficher **deux** boutons d'action (« Ajouter à une collection » en vert + « Supprimer la sélection » en rose) + « Annuler ». Cliquer « Ajouter à une collection » : l'overlay s'ouvre avec le champ texte et l'autocomplétion des collections existantes. (Le câblage du bouton de confirmation arrive en Task 4.)

- [ ] **Step 5 : Commit**

```bash
git add src/web/routes/library/browse.py src/web/templates/library/index.html src/web/static/css/style.css
git commit -m "feat(courts): barre + overlay « Ajouter à une collection » (UI)"
```

---

## Task 3 : Endpoint `POST /library/collection-batch`

**Files:**
- Modify: `src/web/routes/library/collections.py` (imports + garde + route)
- Modify: `tests/unit/web/test_library_collections_routes.py` (fixture + tests)

- [ ] **Step 1 : Écrire les tests d'assignation + garde (échouent)**

Dans `tests/unit/web/test_library_collections_routes.py`, étendre les imports en tête de fichier. Remplacer :

```python
import pytest
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.testclient import TestClient

from src.infrastructure.persistence.models import LocalCollectionModel, MovieModel
from src.web.routes.library.collections import router as collections_router
```

par :

```python
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.testclient import TestClient

from src.infrastructure.persistence.models import (
    LocalCollectionModel,
    MovieModel,
    SeriesModel,
)
from src.web.routes.library.collections import router as collections_router
```

Puis ajouter, à la fin du fichier, la fixture dédiée et la classe de tests :

```python
@pytest.fixture
def batch_client(engine, tmp_path, monkeypatch):
    """Client /collection-batch : container stub + hôte de test autorisé."""
    from src.web.routes.library import collections as collections_module

    def _get_session():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(collections_module, "get_session", _get_session)
    monkeypatch.setattr(
        collections_module,
        "_LOCAL_HOSTS",
        {"testclient", "127.0.0.1", "::1", "localhost"},
    )

    video_dir = tmp_path / "video"
    video_dir.mkdir()
    settings = SimpleNamespace(
        video_dir=video_dir,
        short_film_duration_threshold_seconds=900,
    )
    app = FastAPI()
    app.state.container = SimpleNamespace(config=lambda: settings)
    app.include_router(collections_router, prefix="/library")
    return TestClient(app), video_dir


class TestCollectionBatch:
    def test_requires_local_host(self, client, engine):
        # La fixture 'client' n'autorise pas l'hôte 'testclient' → 403
        r = client.post(
            "/library/collection-batch",
            json={"collection_name": "Looney Tunes", "items": []},
        )
        assert r.status_code == 403

    def test_creates_collection_and_assigns(self, batch_client, engine):
        test_client, _ = batch_client
        with Session(engine) as session:
            m1 = MovieModel(title="A", year=1958, is_short=True)
            m2 = MovieModel(title="B", year=1959, is_short=True)
            session.add(m1)
            session.add(m2)
            session.commit()
            session.refresh(m1)
            session.refresh(m2)
            ids = [m1.id, m2.id]

        r = test_client.post(
            "/library/collection-batch",
            json={
                "collection_name": "Looney Tunes",
                "items": [
                    {"type": "movie", "id": ids[0]},
                    {"type": "movie", "id": ids[1]},
                ],
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["assigned"] == 2
        assert data["collection_id"] is not None

        with Session(engine) as session:
            coll = session.exec(
                select(LocalCollectionModel).where(
                    LocalCollectionModel.name == "Looney Tunes"
                )
            ).first()
            assert coll is not None
            movies = session.exec(
                select(MovieModel).where(MovieModel.id.in_(ids))
            ).all()
            assert all(m.local_collection_id == coll.id for m in movies)

    def test_reuses_existing_collection(self, batch_client, engine):
        test_client, _ = batch_client
        with Session(engine) as session:
            coll = LocalCollectionModel(name="Looney Tunes")
            session.add(coll)
            m = MovieModel(title="A", year=1958, is_short=True)
            session.add(m)
            session.commit()
            session.refresh(coll)
            session.refresh(m)
            coll_id, movie_id = coll.id, m.id

        r = test_client.post(
            "/library/collection-batch",
            json={
                "collection_name": "Looney Tunes",
                "items": [{"type": "movie", "id": movie_id}],
            },
        )
        assert r.status_code == 200
        assert r.json()["collection_id"] == coll_id

        with Session(engine) as session:
            count = len(
                session.exec(
                    select(LocalCollectionModel).where(
                        LocalCollectionModel.name == "Looney Tunes"
                    )
                ).all()
            )
            assert count == 1

    def test_ignores_series_items(self, batch_client, engine):
        test_client, _ = batch_client
        with Session(engine) as session:
            s = SeriesModel(title="Ma Serie", year=2015)
            m = MovieModel(title="A", year=1958, is_short=True)
            session.add(s)
            session.add(m)
            session.commit()
            session.refresh(s)
            session.refresh(m)
            series_id, movie_id = s.id, m.id

        r = test_client.post(
            "/library/collection-batch",
            json={
                "collection_name": "Looney Tunes",
                "items": [
                    {"type": "series", "id": series_id},
                    {"type": "movie", "id": movie_id},
                ],
            },
        )
        assert r.status_code == 200
        assert r.json()["assigned"] == 1  # série ignorée
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

Run: `uv run pytest tests/unit/web/test_library_collections_routes.py::TestCollectionBatch -v`
Expected: FAIL — `404 Not Found` (route inexistante) sur tous les tests.

- [ ] **Step 3 : Implémenter l'endpoint (assignation, sans symlink)**

Dans `src/web/routes/library/collections.py`, étendre les imports et ajouter la garde + le modèle d'item. Remplacer le haut de fichier (des imports jusqu'à `router = APIRouter()` inclus) :

```python
import math
from typing import Optional

from fastapi import APIRouter, Request
from sqlalchemy import func
from sqlmodel import select

from ....infrastructure.persistence.database import get_session
from ....infrastructure.persistence.models import LocalCollectionModel, MovieModel
from ....utils.helpers import title_sort_key
from ...deps import templates
from .helpers import _best_rating, _parse_genres, _poster_url

COLLECTIONS_PER_PAGE = 24

router = APIRouter()
```

par :

```python
import math
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import select

from ....core.entities.local_collection import LocalCollection
from ....infrastructure.persistence.database import get_session
from ....infrastructure.persistence.models import LocalCollectionModel, MovieModel
from ....infrastructure.persistence.repositories.local_collection_repository import (
    SQLModelLocalCollectionRepository,
)
from ....services.short_reclassifier import ShortReclassifier
from ....utils.helpers import title_sort_key
from ...deps import templates
from .helpers import _best_rating, _parse_genres, _poster_url

COLLECTIONS_PER_PAGE = 24

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}

router = APIRouter()


class CollectionAssignItem(BaseModel):
    """Élément à rattacher à une collection locale."""

    type: str  # "movie" | "series"
    id: int
```

Puis, après la route `collection_detail_local` (avant `def _collect_tmdb_collections`), ajouter l'endpoint :

```python
@router.post("/collection-batch")
async def collection_batch(request: Request):
    """Rattache des films sélectionnés à une collection locale (find-or-create)
    et déplace les symlinks des courts vers ``Films/Courts/{collection}/``.

    Réservé à la machine maître (modification DB + filesystem). Les items
    ``series`` sont ignorés : seuls les films portent ``local_collection_id``.
    """
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return JSONResponse(
            {"error": "Action autorisée uniquement depuis la machine maître."},
            status_code=403,
        )

    body = await request.json()
    collection_name = (body.get("collection_name") or "").strip()
    if not collection_name:
        return JSONResponse({"error": "Nom de collection requis."}, status_code=400)

    items = [CollectionAssignItem(**it) for it in body.get("items", [])]
    movie_ids = [it.id for it in items if it.type == "movie"]
    if not movie_ids:
        return JSONResponse(
            {"assigned": 0, "moved": 0, "errors": [], "collection_id": None}
        )

    settings = request.app.state.container.config()
    session = next(get_session())
    try:
        repo = SQLModelLocalCollectionRepository(session)
        collection = repo.get_by_name(collection_name) or repo.save(
            LocalCollection(name=collection_name)
        )

        assigned = 0
        for movie_id in movie_ids:
            movie = session.get(MovieModel, movie_id)
            if movie is None:
                continue
            movie.local_collection_id = collection.id
            session.add(movie)
            assigned += 1
        session.commit()

        moved = 0
        errors: list[str] = []
        reclassifier = ShortReclassifier(
            session,
            settings.video_dir,
            settings.short_film_duration_threshold_seconds,
        )
        target_ids = set(movie_ids)
        for candidate in reclassifier.find_candidates():
            if candidate.model.id not in target_ids:
                continue
            result = reclassifier.apply(candidate)
            if result.moved:
                moved += 1
            elif result.error:
                errors.append(result.error)
    finally:
        session.close()

    return JSONResponse(
        {
            "assigned": assigned,
            "moved": moved,
            "errors": errors,
            "collection_id": collection.id,
        }
    )
```

> Le bloc `reclassifier` est inclus dès maintenant : il est inerte tant qu'aucun court avec symlink mal placé n'est dans la sélection (les tests de l'étape 1 créent des films sans `symlink_path`, donc `find_candidates()` les ignore). Le test de l'étape 5 le valide explicitement.

- [ ] **Step 4 : Lancer pour vérifier le succès**

Run: `uv run pytest tests/unit/web/test_library_collections_routes.py::TestCollectionBatch -v`
Expected: PASS (4 tests).

- [ ] **Step 5 : Écrire le test de déplacement de symlink (échoue d'abord)**

Ajouter cette méthode à la classe `TestCollectionBatch` :

```python
    def test_moves_symlink_to_franchise_folder(self, batch_client, engine):
        test_client, video_dir = batch_client
        storage = video_dir.parent / "storage"
        storage.mkdir()
        target = storage / "bunny.mkv"
        target.write_text("x")
        divers = video_dir / "Films" / "Courts" / "Divers"
        divers.mkdir(parents=True)
        link = divers / "Court Bunny (1958).mkv"
        link.symlink_to(target)

        with Session(engine) as session:
            m = MovieModel(
                title="Court Bunny",
                year=1958,
                duration_seconds=420,
                is_short=True,
                symlink_path=str(link),
            )
            session.add(m)
            session.commit()
            session.refresh(m)
            movie_id = m.id

        r = test_client.post(
            "/library/collection-batch",
            json={
                "collection_name": "Looney Tunes",
                "items": [{"type": "movie", "id": movie_id}],
            },
        )
        assert r.status_code == 200
        assert r.json()["moved"] == 1

        new_link = (
            video_dir / "Films" / "Courts" / "Looney Tunes" / "Court Bunny (1958).mkv"
        )
        assert new_link.is_symlink()
        assert not link.exists()
        with Session(engine) as session:
            m = session.get(MovieModel, movie_id)
            assert m.symlink_path == str(new_link)
```

- [ ] **Step 6 : Lancer pour vérifier**

Run: `uv run pytest tests/unit/web/test_library_collections_routes.py::TestCollectionBatch::test_moves_symlink_to_franchise_folder -v`
Expected: PASS — le `reclassifier` ajouté à l'étape 3 déplace le symlink de `Films/Courts/Divers/` vers `Films/Courts/Looney Tunes/`.

> Si ce test échoue (par ex. `moved == 0`), vérifier que `find_candidates()` capte bien le film : `duration_seconds=420 <= 900`, `symlink_path` non nul, chemin hors `Séries/`. Aucune logique à dupliquer — le service existant fait le déplacement.

- [ ] **Step 7 : Lint + suite complète du fichier + commit**

```bash
uv run ruff format src/web/routes/library/collections.py tests/unit/web/test_library_collections_routes.py
uv run ruff check src/web/routes/library/collections.py tests/unit/web/test_library_collections_routes.py
uv run pytest tests/unit/web/test_library_collections_routes.py -v
git add src/web/routes/library/collections.py tests/unit/web/test_library_collections_routes.py
git commit -m "feat(courts): endpoint POST /library/collection-batch (assign + move symlinks)"
```

---

## Task 4 : Action JS « Ajouter à une collection »

**Files:**
- Modify: `src/web/static/js/delete.js` (insérer le bloc collection ; remplacer le handler Escape)

> Pas de test unitaire JS (le projet n'en a pas pour `delete.js`). Vérification manuelle de bout en bout en fin de tâche.

- [ ] **Step 1 : Ajouter le bloc d'action collection**

Dans `src/web/static/js/delete.js`, insérer le bloc suivant **juste avant** le commentaire `// Ré-attacher les checkboxes après un swap HTMX` (vers la ligne 231) :

```javascript
    // --- Action : ajouter à une collection ---
    var collectionBtn = document.getElementById('collection-confirm-btn');
    var collectionOverlay = document.getElementById('collection-overlay');
    var collectionCount = document.getElementById('collection-overlay-count');
    var collectionInput = document.getElementById('collection-name-input');
    var collectionOverlayConfirm = document.getElementById('collection-overlay-confirm');
    var collectionOverlayCancel = document.getElementById('collection-overlay-cancel');

    if (collectionBtn) {
        collectionBtn.addEventListener('click', function () {
            if (selected.size === 0) return;
            if (collectionCount) collectionCount.textContent = selected.size;
            if (collectionInput) collectionInput.value = '';
            if (collectionOverlay) collectionOverlay.classList.add('active');
            if (collectionInput) setTimeout(function () { collectionInput.focus(); }, 50);
        });
    }

    if (collectionOverlayCancel) {
        collectionOverlayCancel.addEventListener('click', function () {
            if (collectionOverlay) collectionOverlay.classList.remove('active');
        });
    }

    if (collectionOverlay) {
        collectionOverlay.addEventListener('click', function (e) {
            if (e.target === collectionOverlay) collectionOverlay.classList.remove('active');
        });
    }

    if (collectionOverlayConfirm) {
        collectionOverlayConfirm.addEventListener('click', function () {
            var name = ((collectionInput && collectionInput.value) || '').trim();
            if (selected.size === 0 || !name) return;

            var items = [];
            selected.forEach(function (val) {
                items.push({ type: val.type, id: val.id });
            });

            collectionOverlayConfirm.disabled = true;
            collectionOverlayConfirm.textContent = 'Ajout...';

            fetch('/library/collection-batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ collection_name: name, items: items })
            })
                .then(function (res) {
                    if (res.status === 403) {
                        return res.json().then(function (data) {
                            alert(data.error || 'Accès refusé.');
                            throw new Error('forbidden');
                        });
                    }
                    return res.json();
                })
                .then(function (data) {
                    if (data && data.assigned !== undefined) {
                        clearState();
                        window.location.href = '/library/';
                    }
                })
                .catch(function (err) {
                    if (err.message !== 'forbidden') {
                        alert('Erreur lors de l\'ajout à la collection.');
                    }
                    collectionOverlayConfirm.disabled = false;
                    collectionOverlayConfirm.textContent = 'Ajouter à la collection';
                    if (collectionOverlay) collectionOverlay.classList.remove('active');
                });
        });
    }

```

- [ ] **Step 2 : Étendre le handler Escape pour fermer l'overlay collection**

Toujours dans `src/web/static/js/delete.js`, remplacer le handler Escape existant :

```javascript
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && selectMode) {
            if (overlay && overlay.classList.contains('active')) {
                overlay.classList.remove('active');
            } else {
                exitSelectMode();
            }
        }
    });
```

par :

```javascript
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && selectMode) {
            if (overlay && overlay.classList.contains('active')) {
                overlay.classList.remove('active');
            } else if (collectionOverlay && collectionOverlay.classList.contains('active')) {
                collectionOverlay.classList.remove('active');
            } else {
                exitSelectMode();
            }
        }
    });
```

- [ ] **Step 3 : Vérification manuelle de bout en bout**

```bash
uv run uvicorn src.web.app:app --reload
```

Sur `http://127.0.0.1:8000/library/` :
1. Type → **Courts** : seuls les courts apparaissent (ex. les Looney Tunes).
2. Cliquer « Suppression » (mode sélection), cocher 2-3 courts, cliquer « Ajouter à une collection ».
3. Saisir « Looney Tunes », confirmer. La page recharge.
4. Aller dans `/library/collections` : la collection « Looney Tunes » apparaît avec les films rattachés.
5. Vérifier les symlinks déplacés :

```bash
ls -l "$(uv run python -c 'from src.container import Container; c=Container(); print(c.config().video_dir)')/Films/Courts/Looney Tunes/"
```

Les symlinks des courts sélectionnés doivent s'y trouver.

- [ ] **Step 4 : Commit**

```bash
git add src/web/static/js/delete.js
git commit -m "feat(courts): action JS « Ajouter à une collection » (mode sélection étendu)"
```

---

## Task 5 : Documentation + portes qualité

**Files:**
- Modify: `README.md`

- [ ] **Step 1 : Documenter dans le README**

Dans `README.md`, ajouter (dans la section bibliothèque/web, près des filtres existants) :

```markdown
### Courts-métrages dans la bibliothèque

- **Filtre « Courts »** : le sélecteur de type de la grille propose désormais
  Tous / Films / Séries / **Courts**. Par défaut (Tous) et sous « Films », les
  courts-métrages (`is_short`) sont masqués ; ils n'apparaissent que via le
  type « Courts ».
- **Ranger des courts en collection (sélection en masse)** : activer le mode
  « Suppression » (qui est en réalité un mode sélection), cocher plusieurs
  jaquettes, puis cliquer **« Ajouter à une collection »**. Saisir un nom de
  collection (un nom existant est réutilisé, un nouveau nom la crée). Les courts
  sélectionnés sont rattachés à la collection locale et leurs symlinks sont
  déplacés vers `video/Films/Courts/{collection}/`. Action réservée à la machine
  maître (modification de la base et des symlinks).
```

- [ ] **Step 2 : Portes qualité complètes**

```bash
uv run ruff format src tests
uv run ruff check src tests
uv run pytest tests/unit/web/ -v
```

Expected: ruff sans erreur ; tests web verts.

- [ ] **Step 3 : Commit**

```bash
git add README.md
git commit -m "docs(courts): filtre « Courts » + ajout à une collection en masse"
```

---

## Notes de validation finale

- **Couverture spec** :
  - Volet 1 (filtre Courts) → Task 1.
  - Volet 2 (UI barre/overlay/datalist + contexte) → Task 2 + Task 4 (JS).
  - Volet 3 (endpoint + symlinks) → Task 3.
  - Volet 4 (tests) → Task 1 (filtre), Task 3 (endpoint + symlink).
  - Documentation → Task 5.
- **Hors périmètre** (rappel spec) : marquage manuel `is_short` pour les courts non détectés ; assignation de collection aux séries ; évolution du suggester par préfixe.
- **Restriction machine maître** : `/collection-batch` renvoie `403` hors `127.0.0.1/::1/localhost`, et le bouton/overlay sont sous `{% if is_local %}` (cohérent avec la suppression en masse).
