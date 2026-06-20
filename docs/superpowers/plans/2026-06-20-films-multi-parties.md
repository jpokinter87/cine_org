# Films multi-parties — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre à un film d'avoir plusieurs parties (un seul fichier par partie), regroupées sous une seule fiche, accessibles individuellement comme les épisodes d'une mini-série, et faire en sorte que le workflow de transfert les regroupe automatiquement.

**Architecture:** Nouvelle table `movie_parts` (une-à-plusieurs vers `movies`, calquée sur `episodes`). La fiche `Movie` continue de porter la **Partie 1** (`file_path`/`symlink_path`) ; la table ne contient que les parties ≥ 2. Le workflow annote, dans `_fix_duplicate_filenames`, les parties non primaires d'un film, et `transfer_step` crée les lignes `MoviePart` correspondantes au lieu d'écraser le `file_path` du film. La fiche web affiche un bloc « Parties », un nouvel endpoint joue une partie, la suppression nettoie les parties, et une commande CLI `link-movie-parts` régularise les films multi-parties déjà transférés.

**Tech Stack:** Python 3.11+, SQLModel/SQLite, FastAPI + Jinja2/HTMX, Typer, pytest (`uv run --extra dev pytest`).

**Décision de simplification (vs spec) :** le code web (`detail.py`, `delete.py`, `player.py`) et `transfer_step` manipulent déjà les modèles SQLModel via des sessions directes. On suit ce style : **pas d'entité domaine `MoviePart` ni de méthodes ajoutées au port `IMovieRepository`** (elles seraient inutilisées → YAGNI). Tout passe par `MoviePartModel` + sessions directes. Le service `MoviePartLinker` (backfill) prend une session.

---

## Fichiers touchés

- **Créer** `src/services/movie_parts.py` — service `MoviePartLinker` (backfill).
- **Créer** `src/adapters/cli/commands/link_movie_parts_command.py` — commande CLI `link-movie-parts`.
- **Modifier** `src/infrastructure/persistence/models.py` — ajouter `MoviePartModel`.
- **Modifier** `src/adapters/cli/batch_builder.py` — annoter les parties dans `_fix_duplicate_filenames`.
- **Modifier** `src/services/workflow/transfer_step.py` — créer les `MoviePart` dans `_update_file_paths`.
- **Modifier** `src/web/routes/library/detail.py` — charger les parties pour la fiche film.
- **Modifier** `src/web/templates/library/movie_detail.html` — bloc « Parties ».
- **Modifier** `src/web/routes/library/player.py` — endpoint `POST /movie-parts/{id}/play`.
- **Modifier** `src/web/routes/library/delete.py` — cascade suppression des parties.
- **Modifier** `src/adapters/cli/commands/__init__.py` + `src/main.py` — enregistrer la commande.
- **Modifier** `README.md` — documenter la commande et le comportement multi-parties.
- **Tests** : voir chaque tâche.

> La table `movie_parts` est créée automatiquement par `init_db` (`SQLModel.metadata.create_all`, `src/infrastructure/persistence/database.py:122`) puisque c'est une **table neuve**. Aucune migration manuelle n'est nécessaire.

---

### Task 1 : Modèle `MoviePartModel`

**Files:**
- Modify: `src/infrastructure/persistence/models.py` (ajout après `EpisodeModel`, vers la ligne 244)
- Test: `tests/unit/infrastructure/persistence/test_movie_part_model.py`

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/unit/infrastructure/persistence/test_movie_part_model.py
"""Tests du modèle MoviePartModel (parties d'un film multi-parties)."""

from sqlmodel import SQLModel, Session, create_engine, select

from src.infrastructure.persistence.models import MovieModel, MoviePartModel


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_movie_part_persiste_et_se_relit():
    session = _session()
    movie = MovieModel(title="Nos meilleures années", year=2003, tmdb_id=11659)
    session.add(movie)
    session.commit()
    session.refresh(movie)

    part = MoviePartModel(
        movie_id=movie.id,
        part_number=2,
        file_path="/storage/Nos meilleures années (2003) Partie 2.mkv",
        symlink_path="/video/Nos meilleures années (2003) Partie 2.mkv",
    )
    session.add(part)
    session.commit()

    rows = session.exec(
        select(MoviePartModel).where(MoviePartModel.movie_id == movie.id)
    ).all()
    assert len(rows) == 1
    assert rows[0].part_number == 2
    assert rows[0].file_path.endswith("Partie 2.mkv")
    assert rows[0].symlink_path.endswith("Partie 2.mkv")
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `uv sync --extra dev && uv run --extra dev pytest tests/unit/infrastructure/persistence/test_movie_part_model.py -v`
Expected: FAIL avec `ImportError: cannot import name 'MoviePartModel'`

- [ ] **Step 3 : Implémenter le modèle**

Dans `src/infrastructure/persistence/models.py`, ajouter juste après la classe `EpisodeModel` (après sa ligne `self.languages_json = json.dumps(value)`, soit ~ligne 244) :

```python
class MoviePartModel(SQLModel, table=True):
    """
    Partie supplementaire d'un film multi-parties (ex. film en 2 parties).

    La Partie 1 reste portee par MovieModel (file_path/symlink_path).
    Cette table ne contient que les parties >= 2, liees au film via movie_id.
    """

    __tablename__ = "movie_parts"
    __table_args__ = (
        Index("ix_movie_parts_movie_part", "movie_id", "part_number"),
    )

    id: int | None = Field(default=None, primary_key=True)
    movie_id: int = Field(foreign_key="movies.id", index=True)
    part_number: int
    file_path: str | None = Field(default=None, index=True)
    symlink_path: str | None = Field(default=None, index=True)
    created_at: datetime | None = Field(default_factory=datetime.utcnow)
```

(`Index`, `Field`, `SQLModel`, `datetime` sont déjà importés en tête de fichier.)

- [ ] **Step 4 : Lancer le test pour vérifier qu'il passe**

Run: `uv run --extra dev pytest tests/unit/infrastructure/persistence/test_movie_part_model.py -v`
Expected: PASS

- [ ] **Step 5 : Commit**

```bash
git add src/infrastructure/persistence/models.py tests/unit/infrastructure/persistence/test_movie_part_model.py
git commit -m "feat(films): modele MoviePartModel pour films multi-parties"
```

---

### Task 2 : Annoter les parties d'un film dans `_fix_duplicate_filenames`

`_fix_duplicate_filenames` (`src/adapters/cli/batch_builder.py:785`) détecte déjà les transferts visant la même destination et en extrait les numéros de partie. On y ajoute, **pour les films** (`is_series` faux), une annotation : la partie de plus petit numéro reste primaire (porte la fiche), les autres reçoivent `t["movie_part_number"] = part_num`.

**Files:**
- Modify: `src/adapters/cli/batch_builder.py` (dans `_fix_duplicate_filenames`, ~lignes 838-899)
- Test: `tests/unit/adapters/cli/test_batch_builder_movie_parts.py`

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/unit/adapters/cli/test_batch_builder_movie_parts.py
"""Annotation des parties de films dans _fix_duplicate_filenames."""

from pathlib import Path
from types import SimpleNamespace

from src.adapters.cli.batch_builder import _fix_duplicate_filenames
from src.services.renamer import RenamerService


def _movie_transfer(filename: str, movie_id: int) -> dict:
    video_file = SimpleNamespace(filename=filename, media_info=None)
    pending = SimpleNamespace(video_file=video_file)
    return {
        "pending": pending,
        "source": Path(f"/dl/{filename}"),
        # Meme destination pour les deux parties (collision) -> declenche le fix
        "destination": Path("/storage/Nos meilleures annees (2003) MULTi x265 1080p.mkv"),
        "new_filename": "Nos meilleures annees (2003) MULTi x265 1080p.mkv",
        "symlink_destination": Path("/video/Nos meilleures annees (2003) MULTi x265 1080p.mkv"),
        "is_series": False,
        "title": "Nos meilleures annees",
        "year": 2003,
        "movie_id": movie_id,
    }


def test_film_multipartie_annote_les_parties_non_primaires():
    renamer = RenamerService()
    transfers = [
        _movie_transfer("Nos.meilleures.annees.2003.Part.1.MULTi.x265.1080p.mkv", 42),
        _movie_transfer("Nos.meilleures.annees.2003.Part.2.MULTi.x265.1080p.mkv", 42),
    ]

    result = _fix_duplicate_filenames(transfers, renamer)

    # Les noms sont desormais distincts (Partie 1 / Partie 2)
    by_part = {t["new_filename"]: t for t in result}
    p1 = next(t for t in result if "Partie 1" in t["new_filename"])
    p2 = next(t for t in result if "Partie 2" in t["new_filename"])

    # La partie 1 reste primaire (pas d'annotation), la partie 2 est annotee
    assert "movie_part_number" not in p1
    assert p2["movie_part_number"] == 2
    assert len(by_part) == 2
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `uv run --extra dev pytest tests/unit/adapters/cli/test_batch_builder_movie_parts.py -v`
Expected: FAIL avec `KeyError: 'movie_part_number'` (l'annotation n'existe pas encore)

- [ ] **Step 3 : Implémenter l'annotation**

Dans `src/adapters/cli/batch_builder.py`, fonction `_fix_duplicate_filenames`, juste après la boucle qui régénère les noms (après la ligne `console.print(f"    [green]✓[/green] {old_filename} → {new_filename}")`, ~ligne 899) et **avant** la fin de la boucle `for dest, indices in by_destination.items():`, ajouter l'annotation du groupe pour les films :

```python
        # Annoter les parties d'un film multi-parties : la plus petite partie
        # reste primaire (porte la fiche Movie), les autres deviennent des
        # MoviePart (cf. transfer_step._update_file_paths).
        film_parts = [
            (idx, part_num)
            for idx, part_num in parts_found
            if part_num is not None and not transfers[idx].get("is_series")
        ]
        if len(film_parts) >= 2:
            primary_idx = min(film_parts, key=lambda p: p[1])[0]
            for idx, part_num in film_parts:
                if idx != primary_idx:
                    transfers[idx]["movie_part_number"] = part_num
```

- [ ] **Step 4 : Lancer le test pour vérifier qu'il passe**

Run: `uv run --extra dev pytest tests/unit/adapters/cli/test_batch_builder_movie_parts.py -v`
Expected: PASS

- [ ] **Step 5 : Vérifier la non-régression séries**

Run: `uv run --extra dev pytest tests/unit/adapters/cli/ -q`
Expected: PASS (les transferts séries ne reçoivent jamais `movie_part_number`)

- [ ] **Step 6 : Commit**

```bash
git add src/adapters/cli/batch_builder.py tests/unit/adapters/cli/test_batch_builder_movie_parts.py
git commit -m "feat(workflow): annoter les parties non primaires des films multi-parties"
```

---

### Task 3 : Créer les `MoviePart` au transfert (`transfer_step`)

À l'exécution du transfert, `_update_file_paths` (`src/services/workflow/transfer_step.py:90-128`) met à jour `file_path`/`symlink_path` du `Movie`. On ajoute : si le transfert porte `movie_part_number`, on crée une ligne `MoviePartModel` au lieu d'écraser le `file_path` du film.

**Files:**
- Modify: `src/services/workflow/transfer_step.py` (dans `_update_file_paths`, ~lignes 92-128)
- Test: `tests/unit/services/workflow/test_transfer_movie_parts.py`
- Créer si besoin: `tests/unit/services/workflow/__init__.py` (fichier vide) si le dossier n'existe pas.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/unit/services/workflow/test_transfer_movie_parts.py
"""Creation des MoviePart a l'execution du transfert."""

from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine, select

from src.infrastructure.persistence.models import MovieModel, MoviePartModel
from src.services.workflow.transfer_step import TransferStepMixin


class _FakeContainer:
    def __init__(self, session):
        self._session = session

    def session(self):
        return self._session


class _Holder(TransferStepMixin):
    def __init__(self, container):
        self._container = container


def test_transfert_cree_les_movie_parts():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    session = Session(engine)

    movie = MovieModel(title="Nos meilleures années", year=2003, tmdb_id=11659)
    session.add(movie)
    session.commit()
    session.refresh(movie)

    holder = _Holder(_FakeContainer(session))

    transfers = [
        {  # Partie 1 : primaire
            "movie_id": movie.id,
            "destination": Path("/storage/Nos meilleures années (2003) Partie 1.mkv"),
            "symlink_destination": Path("/video/Nos meilleures années (2003) Partie 1.mkv"),
        },
        {  # Partie 2 : MoviePart
            "movie_id": movie.id,
            "movie_part_number": 2,
            "destination": Path("/storage/Nos meilleures années (2003) Partie 2.mkv"),
            "symlink_destination": Path("/video/Nos meilleures années (2003) Partie 2.mkv"),
        },
    ]
    results = [{"success": True}, {"success": True}]

    holder._update_file_paths(transfers, results)

    movie = session.get(MovieModel, movie.id)
    assert movie.file_path.endswith("Partie 1.mkv")  # primaire sur la fiche

    parts = session.exec(
        select(MoviePartModel).where(MoviePartModel.movie_id == movie.id)
    ).all()
    assert len(parts) == 1
    assert parts[0].part_number == 2
    assert parts[0].file_path.endswith("Partie 2.mkv")
    assert parts[0].symlink_path.endswith("Partie 2.mkv")
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `uv run --extra dev pytest tests/unit/services/workflow/test_transfer_movie_parts.py -v`
Expected: FAIL (la Partie 2 écrase `movie.file_path`, aucune ligne `MoviePartModel` n'est créée → assertions sur `parts` échouent)

- [ ] **Step 3 : Implémenter la création des parties**

Dans `src/services/workflow/transfer_step.py`, méthode `_update_file_paths` :

1. Ajouter `MoviePartModel` à l'import existant (ligne 92) :

```python
        from src.infrastructure.persistence.models import (
            EpisodeModel,
            MovieModel,
            MoviePartModel,
        )
```

2. Remplacer le bloc `movie_id = transfer.get("movie_id")` … (lignes 109-116) par :

```python
            movie_id = transfer.get("movie_id")
            part_number = transfer.get("movie_part_number")
            if movie_id and part_number is not None:
                # Partie non primaire : enregistrer une MoviePart, ne pas
                # ecraser le file_path de la fiche (porte par la Partie 1).
                existing_part = session.exec(
                    select(MoviePartModel).where(
                        MoviePartModel.movie_id == int(movie_id),
                        MoviePartModel.part_number == int(part_number),
                    )
                ).first()
                if existing_part:
                    existing_part.file_path = storage_str
                    existing_part.symlink_path = symlink_str
                    session.add(existing_part)
                else:
                    session.add(
                        MoviePartModel(
                            movie_id=int(movie_id),
                            part_number=int(part_number),
                            file_path=storage_str,
                            symlink_path=symlink_str,
                        )
                    )
                updated += 1
            elif movie_id:
                movie = session.get(MovieModel, int(movie_id))
                if movie:
                    movie.file_path = storage_str
                    movie.symlink_path = symlink_str
                    session.add(movie)
                    updated += 1
```

3. Ajouter l'import `select` en tête de la méthode (juste sous l'import des modèles) :

```python
        from sqlmodel import select
```

- [ ] **Step 4 : Lancer le test pour vérifier qu'il passe**

Run: `uv run --extra dev pytest tests/unit/services/workflow/test_transfer_movie_parts.py -v`
Expected: PASS

- [ ] **Step 5 : Commit**

```bash
git add src/services/workflow/transfer_step.py tests/unit/services/workflow/
git commit -m "feat(workflow): enregistrer les parties >=2 comme MoviePart au transfert"
```

---

### Task 4 : Charger les parties sur la fiche film (route)

**Files:**
- Modify: `src/web/routes/library/detail.py` (`movie_detail`, lignes 10-15 import + 34-93)
- Test: `tests/unit/web/test_movie_detail_parts.py`

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/unit/web/test_movie_detail_parts.py
"""La fiche film expose ses parties (MoviePart) au template."""

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

from src.infrastructure.persistence import database
from src.infrastructure.persistence.models import MovieModel, MoviePartModel
from src.web.app import app


def _setup_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    SQLModel.metadata.create_all(engine)
    database._engine = engine  # forcer get_session/get_engine sur la base de test
    with Session(engine) as s:
        movie = MovieModel(
            title="Nos meilleures années",
            year=2003,
            tmdb_id=11659,
            file_path="/storage/Nos meilleures années (2003) Partie 1.mkv",
        )
        s.add(movie)
        s.commit()
        s.refresh(movie)
        s.add(
            MoviePartModel(
                movie_id=movie.id,
                part_number=2,
                file_path="/storage/Nos meilleures années (2003) Partie 2.mkv",
                symlink_path="/video/Nos meilleures années (2003) Partie 2.mkv",
            )
        )
        s.commit()
        return movie.id


def test_fiche_film_affiche_le_bloc_parties(tmp_path):
    movie_id = _setup_db(tmp_path)
    client = TestClient(app)
    resp = client.get(f"/library/movies/{movie_id}")
    assert resp.status_code == 200
    body = resp.text
    assert "Parties" in body
    assert "Partie 1" in body
    assert "Partie 2" in body
    # Le play de la partie 2 cible l'endpoint dedie
    assert "/library/movie-parts/" in body
```

> Note : si `database._engine` n'est pas l'attribut utilisé, ouvrir `src/infrastructure/persistence/database.py` et adapter l'injection de moteur de test au mécanisme réel (variable module-level du moteur). Vérifier le nom exact avant d'écrire le test.

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `uv run --extra dev pytest tests/unit/web/test_movie_detail_parts.py -v`
Expected: FAIL (le template n'affiche pas encore de bloc « Parties »)

- [ ] **Step 3 : Charger les parties dans la route**

Dans `src/web/routes/library/detail.py` :

1. Ajouter `MoviePartModel` à l'import (lignes 10-15) :

```python
from ....infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    MoviePartModel,
    SeriesModel,
    VideoFileModel,
)
```

2. Dans `movie_detail`, à l'intérieur du `try` (après le chargement de `video_file`, ~ligne 52), charger les parties :

```python
        # Parties supplementaires (films multi-parties) ordonnees
        parts = session.exec(
            select(MoviePartModel)
            .where(MoviePartModel.movie_id == movie_id)
            .order_by(MoviePartModel.part_number)
        ).all()
```

3. Ajouter `"parts": parts,` au dictionnaire de contexte du `TemplateResponse` (~ligne 92, après `"is_phantom": is_phantom,`).

- [ ] **Step 4 : (le test passe après la Task 5 — template)**

Le test échouera encore tant que le template (Task 5) n'affiche pas le bloc. Enchaîner la Task 5 puis relancer.

- [ ] **Step 5 : Commit (après Task 5)**

Voir Task 5.

---

### Task 5 : Bloc « Parties » dans le template film

**Files:**
- Modify: `src/web/templates/library/movie_detail.html` (insérer après le bloc `</details>` des infos fichier, ~ligne 243, avant `</div></div></div>`)

- [ ] **Step 1 : Implémenter le bloc**

Dans `src/web/templates/library/movie_detail.html`, juste après la ligne `{% endif %}` qui ferme le bloc « Informations fichier » (ligne 243) et **avant** les trois `</div>` de fermeture (lignes 244-246), insérer :

```html
            {% if parts %}
            <div class="lib-detail-parts">
                <h3 class="lib-detail-section-title">Parties</h3>
                <div class="lib-episode-list">
                    {# Partie 1 : portee par la fiche Movie #}
                    {% if movie.file_path %}
                    <div class="lib-episode-row lib-episode-playable" tabindex="0"
                        data-play-url="/library/movies/{{ movie.id }}/play"
                        onclick="episodeRowClick(event, this)">
                        <span class="lib-episode-num">Partie 1</span>
                        <span class="lib-episode-title">{{ movie.file_path.split('/')|last }}</span>
                        {% with play_entity_type="movies", play_entity_id=movie.id, play_btn_class="lib-episode-play-btn", play_show_label=false %}
                        {% include "library/_play_btn.html" %}
                        {% endwith %}
                    </div>
                    {% endif %}
                    {# Parties >= 2 #}
                    {% for part in parts %}
                    <div class="lib-episode-row{% if part.file_path or part.symlink_path %} lib-episode-playable{% endif %}" tabindex="0"
                        {% if part.file_path or part.symlink_path %}
                        data-play-url="/library/movie-parts/{{ part.id }}/play"
                        onclick="episodeRowClick(event, this)"
                        {% endif %}>
                        <span class="lib-episode-num">Partie {{ part.part_number }}</span>
                        <span class="lib-episode-title">{{ (part.file_path or part.symlink_path or '').split('/')|last }}</span>
                        {% if part.file_path or part.symlink_path %}
                        {% with play_entity_type="movie-parts", play_entity_id=part.id, play_btn_class="lib-episode-play-btn", play_show_label=false %}
                        {% include "library/_play_btn.html" %}
                        {% endwith %}
                        {% endif %}
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endif %}
```

(Réutilise les classes `lib-episode-list` / `lib-episode-row` / `lib-episode-play-btn` déjà stylées, et la fonction JS `episodeRowClick` déjà présente sur la page bibliothèque — mêmes que `series_detail.html`.)

- [ ] **Step 2 : Lancer le test de la Task 4**

Run: `uv run --extra dev pytest tests/unit/web/test_movie_detail_parts.py -v`
Expected: PASS

- [ ] **Step 3 : Commit (Task 4 + 5 ensemble)**

```bash
git add src/web/routes/library/detail.py src/web/templates/library/movie_detail.html tests/unit/web/test_movie_detail_parts.py
git commit -m "feat(web): bloc Parties sur la fiche film multi-parties"
```

---

### Task 6 : Endpoint de lecture d'une partie

**Files:**
- Modify: `src/web/routes/library/player.py` (import `MoviePartModel` + nouvel endpoint après `movie_play`, ~ligne 356)
- Test: `tests/unit/web/test_movie_part_play.py`

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/unit/web/test_movie_part_play.py
"""Endpoint POST /library/movie-parts/{id}/play."""

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

from src.infrastructure.persistence import database
from src.infrastructure.persistence.models import MovieModel, MoviePartModel
from src.web.app import app


def _setup(tmp_path, real_file):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    SQLModel.metadata.create_all(engine)
    database._engine = engine
    with Session(engine) as s:
        movie = MovieModel(title="Film", year=2003, tmdb_id=1)
        s.add(movie)
        s.commit()
        s.refresh(movie)
        part = MoviePartModel(
            movie_id=movie.id, part_number=2,
            file_path=str(real_file), symlink_path=str(real_file),
        )
        s.add(part)
        s.commit()
        s.refresh(part)
        return part.id


def test_play_partie_inconnue_renvoie_404(tmp_path):
    _setup(tmp_path, tmp_path / "dummy.mkv")
    client = TestClient(app)
    resp = client.post("/library/movie-parts/99999/play")
    assert resp.status_code == 404


def test_play_partie_lance_le_lecteur(tmp_path, monkeypatch):
    real = tmp_path / "Film (2003) Partie 2.mkv"
    real.write_bytes(b"x")
    part_id = _setup(tmp_path, real)

    import src.web.routes.library.player as player

    launched = {}

    def fake_launch(path, profile_name=None):
        launched["path"] = str(path)
        return 4242, None, "mpv"

    monkeypatch.setattr(player, "_launch_player", fake_launch)

    client = TestClient(app)
    resp = client.post(f"/library/movie-parts/{part_id}/play")
    assert resp.status_code == 200
    assert launched["path"].endswith("Partie 2.mkv")
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `uv run --extra dev pytest tests/unit/web/test_movie_part_play.py -v`
Expected: FAIL (route 404 inexistante renvoie 404 par défaut FastAPI — le 2e test échoue car l'endpoint n'existe pas → 404 au lieu de 200)

- [ ] **Step 3 : Implémenter l'endpoint**

Dans `src/web/routes/library/player.py` :

1. Ajouter `MoviePartModel` à l'import des modèles (chercher la ligne qui importe `MovieModel, EpisodeModel, SeriesModel`) et ajouter `MoviePartModel`.

2. Après la fonction `movie_play` (qui se termine ~ligne 355), ajouter :

```python
@router.post("/movie-parts/{part_id}/play")
async def movie_part_play(
    request: Request, part_id: int, profile: Optional[str] = None
):
    """Lance le lecteur pour une partie d'un film multi-parties."""
    session = next(get_session())
    try:
        part = session.get(MoviePartModel, part_id)
        if not part:
            return Response(status_code=404)
        file_path = part.file_path or part.symlink_path
    finally:
        session.close()

    resolved = _resolve_video_path(file_path)
    if not resolved:
        return HTMLResponse(
            _error_html("Fichier vidéo introuvable", "movie-parts", part_id)
        )

    pid, _, pname = _launch_player(resolved, profile_name=profile)
    return HTMLResponse(_playing_html(pid, "movie-parts", part_id, pname))
```

- [ ] **Step 4 : Lancer le test pour vérifier qu'il passe**

Run: `uv run --extra dev pytest tests/unit/web/test_movie_part_play.py -v`
Expected: PASS

- [ ] **Step 5 : Commit**

```bash
git add src/web/routes/library/player.py tests/unit/web/test_movie_part_play.py
git commit -m "feat(web): endpoint de lecture d'une partie de film"
```

---

### Task 7 : Suppression en cascade des parties

**Files:**
- Modify: `src/web/routes/library/delete.py` (import `MoviePartModel` + `_delete_movie_record`, lignes 19-25 et 70-88)
- Test: `tests/unit/web/test_delete_movie_parts.py`

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/unit/web/test_delete_movie_parts.py
"""La suppression d'un film retire aussi ses parties (symlink + ligne)."""

from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine, select

from src.infrastructure.persistence.models import MovieModel, MoviePartModel
from src.web.routes.library.delete import _delete_movie_record


class _FakeFS:
    def __init__(self):
        self.removed = []

    def remove_symlink(self, path: Path):
        self.removed.append(str(path))


def test_suppression_film_retire_ses_parties():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    session = Session(engine)

    movie = MovieModel(
        title="Film", year=2003, tmdb_id=1,
        file_path="/storage/Film Partie 1.mkv",
    )
    session.add(movie)
    session.commit()
    session.refresh(movie)
    session.add(
        MoviePartModel(
            movie_id=movie.id, part_number=2,
            file_path="/storage/Film Partie 2.mkv",
            symlink_path="/video/Film Partie 2.mkv",
        )
    )
    session.commit()

    fs = _FakeFS()
    _delete_movie_record(session, movie, fs, "test")
    session.commit()

    remaining = session.exec(select(MoviePartModel)).all()
    assert remaining == []
    assert "/video/Film Partie 2.mkv" in fs.removed
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `uv run --extra dev pytest tests/unit/web/test_delete_movie_parts.py -v`
Expected: FAIL (la ligne `MoviePartModel` subsiste, le symlink n'est pas retiré)

- [ ] **Step 3 : Implémenter la cascade**

Dans `src/web/routes/library/delete.py` :

1. Ajouter `MoviePartModel` à l'import (lignes 19-25) :

```python
from ....infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    MoviePartModel,
    SeriesModel,
    TrashModel,
    VideoFileModel,
)
```

2. Dans `_delete_movie_record`, après le retrait du symlink/vidéo de la Partie 1 (après le bloc `if movie.file_path: … session.delete(vf)`, ~ligne 79) et **avant** le `session.add(TrashModel(...))`, ajouter :

```python
    # Cascade : parties supplementaires (storage conserve, symlink retire)
    parts = session.exec(
        select(MoviePartModel).where(MoviePartModel.movie_id == movie.id)
    ).all()
    for part in parts:
        if part.symlink_path:
            file_system.remove_symlink(Path(part.symlink_path))
        session.delete(part)
```

- [ ] **Step 4 : Lancer le test pour vérifier qu'il passe**

Run: `uv run --extra dev pytest tests/unit/web/test_delete_movie_parts.py -v`
Expected: PASS

- [ ] **Step 5 : Commit**

```bash
git add src/web/routes/library/delete.py tests/unit/web/test_delete_movie_parts.py
git commit -m "feat(web): cascade suppression des parties d'un film"
```

---

### Task 8 : Service `MoviePartLinker` (backfill)

Régularise les films multi-parties déjà sur le disque : pour chaque symlink `… Partie N …` (N ≥ 2) dans `video/`, retrouve le film via le symlink de la Partie 1 et crée la ligne `MoviePart` manquante (idempotent).

**Files:**
- Create: `src/services/movie_parts.py`
- Test: `tests/unit/services/test_movie_parts_linker.py`

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/unit/services/test_movie_parts_linker.py
"""Service de rattachement des parties orphelines (backfill)."""

from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine, select

from src.infrastructure.persistence.models import MovieModel, MoviePartModel
from src.services.movie_parts import MoviePartLinker


def _make_symlink(video_dir: Path, name: str, storage_dir: Path) -> Path:
    target = storage_dir / name
    target.write_bytes(b"x")
    link = video_dir / name
    link.symlink_to(target)
    return link


def test_linker_cree_les_parties_manquantes_et_est_idempotent(tmp_path):
    video_dir = tmp_path / "video"
    storage_dir = tmp_path / "storage"
    video_dir.mkdir()
    storage_dir.mkdir()

    p1 = _make_symlink(video_dir, "Nos meilleures années (2003) Partie 1 MULTi.mkv", storage_dir)
    _make_symlink(video_dir, "Nos meilleures années (2003) Partie 2 MULTi.mkv", storage_dir)

    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    session.add(
        MovieModel(
            title="Nos meilleures années", year=2003, tmdb_id=11659,
            file_path=str(p1.resolve()), symlink_path=str(p1),
        )
    )
    session.commit()

    linker = MoviePartLinker(session, video_dir)
    plan = linker.build_plan()
    assert len(plan) == 1
    assert plan[0].part_number == 2

    created = linker.apply(plan)
    assert created == 1

    parts = session.exec(select(MoviePartModel)).all()
    assert len(parts) == 1
    assert parts[0].part_number == 2
    assert parts[0].symlink_path.endswith("Partie 2 MULTi.mkv")

    # Idempotence : un second passage ne recree rien
    assert linker.build_plan() == []
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `uv run --extra dev pytest tests/unit/services/test_movie_parts_linker.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'src.services.movie_parts'`

- [ ] **Step 3 : Implémenter le service**

```python
# src/services/movie_parts.py
"""Service de rattachement des parties orphelines de films multi-parties.

Pour chaque symlink ``… Partie N …`` (N >= 2) present dans la zone video,
retrouve le film via le symlink de la Partie 1 (meme nom avec « Partie 1 ») et
cree la ligne MoviePart manquante. Idempotent : ne recree pas une partie deja
enregistree. Le storage n'est jamais modifie.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, select

from src.infrastructure.persistence.models import MovieModel, MoviePartModel

_PART_RE = re.compile(r"(?i)\bPartie\s+(\d+)\b")


@dataclass(frozen=True)
class PartLink:
    """Une partie a rattacher a un film."""

    movie_id: int
    part_number: int
    file_path: str
    symlink_path: str


class MoviePartLinker:
    """Detecte et rattache les parties orphelines (>= 2) dans la zone video."""

    def __init__(self, session: Session, video_dir: Path) -> None:
        self._session = session
        self._video_dir = Path(video_dir)

    def build_plan(self) -> list[PartLink]:
        """Construit la liste des parties a creer (sans rien ecrire)."""
        plan: list[PartLink] = []
        for symlink in sorted(self._video_dir.rglob("*")):
            if not symlink.is_symlink():
                continue
            match = _PART_RE.search(symlink.name)
            if not match:
                continue
            part_number = int(match.group(1))
            if part_number < 2:
                continue

            # Nom de la Partie 1 correspondante
            name_p1 = _PART_RE.sub("Partie 1", symlink.name)
            movie = self._session.exec(
                select(MovieModel).where(
                    MovieModel.symlink_path.like(f"%/{name_p1}")  # type: ignore[union-attr]
                )
            ).first()
            if not movie:
                continue

            # Idempotence : partie deja enregistree ?
            existing = self._session.exec(
                select(MoviePartModel).where(
                    MoviePartModel.movie_id == movie.id,
                    MoviePartModel.part_number == part_number,
                )
            ).first()
            if existing:
                continue

            storage = str(symlink.resolve())
            plan.append(
                PartLink(
                    movie_id=movie.id,
                    part_number=part_number,
                    file_path=storage,
                    symlink_path=str(symlink),
                )
            )
        return plan

    def apply(self, plan: list[PartLink]) -> int:
        """Cree les lignes MoviePart du plan. Retourne le nombre cree."""
        for link in plan:
            self._session.add(
                MoviePartModel(
                    movie_id=link.movie_id,
                    part_number=link.part_number,
                    file_path=link.file_path,
                    symlink_path=link.symlink_path,
                )
            )
        if plan:
            self._session.commit()
        return len(plan)
```

- [ ] **Step 4 : Lancer le test pour vérifier qu'il passe**

Run: `uv run --extra dev pytest tests/unit/services/test_movie_parts_linker.py -v`
Expected: PASS

- [ ] **Step 5 : Commit**

```bash
git add src/services/movie_parts.py tests/unit/services/test_movie_parts_linker.py
git commit -m "feat(films): service MoviePartLinker de rattachement des parties orphelines"
```

---

### Task 9 : Commande CLI `link-movie-parts`

**Files:**
- Create: `src/adapters/cli/commands/link_movie_parts_command.py`
- Modify: `src/adapters/cli/commands/__init__.py` (import + `__all__`)
- Modify: `src/main.py` (import + enregistrement)
- Test: `tests/unit/adapters/cli/test_link_movie_parts_command.py`

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/unit/adapters/cli/test_link_movie_parts_command.py
"""La commande link-movie-parts est exposee et applique le linker."""

def test_commande_importable():
    from src.adapters.cli.commands import link_movie_parts
    assert callable(link_movie_parts)


def test_commande_enregistree_dans_app():
    from src.main import app
    names = {cmd.name or cmd.callback.__name__ for cmd in app.registered_commands}
    assert "link-movie-parts" in names
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `uv run --extra dev pytest tests/unit/adapters/cli/test_link_movie_parts_command.py -v`
Expected: FAIL avec `ImportError: cannot import name 'link_movie_parts'`

- [ ] **Step 3 : Implémenter la commande**

```python
# src/adapters/cli/commands/link_movie_parts_command.py
"""Commande CLI link-movie-parts : rattache les parties orphelines de films.

Scanne la zone video a la recherche de symlinks « … Partie N … » (N >= 2) dont
le film (Partie 1) existe en base, et cree les lignes MoviePart manquantes.
Dry-run par defaut ; --apply pour ecrire. Le storage n'est jamais modifie.
"""

from pathlib import Path
from typing import Annotated

import typer

from src.adapters.cli.validation import console
from src.container import Container
from src.services.movie_parts import MoviePartLinker


def link_movie_parts(
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Exécuter (défaut : dry-run, rapport seul)"),
    ] = False,
) -> None:
    """Rattache les parties orphelines (Partie ≥ 2) des films multi-parties.

    Sans --apply : affiche le plan (rien n'est écrit).
    Avec --apply : crée les lignes MoviePart manquantes en base.
    """
    from loguru import logger as loguru_logger

    container = Container()
    config = container.config()
    container.database.init()

    loguru_logger.disable("src")
    session = container.session()
    try:
        linker = MoviePartLinker(session, Path(config.video_dir))
        with console.status("[cyan]Analyse de la zone video..."):
            plan = linker.build_plan()

        if not plan:
            console.print("\n[green]Aucune partie orpheline à rattacher.[/green]")
            return

        for link in plan:
            console.print(
                f"  [cyan]Partie {link.part_number}[/cyan] → film #{link.movie_id} : "
                f"{Path(link.symlink_path).name}"
            )

        if not apply:
            console.print(
                f"\n[bold]Dry-run :[/bold] {len(plan)} partie(s) à rattacher."
            )
            console.print("[dim]Pour exécuter : cineorg link-movie-parts --apply[/dim]")
        else:
            created = linker.apply(plan)
            console.print(
                f"\n[bold green]{created}[/bold green] partie(s) rattachée(s)."
            )
    finally:
        session.close()
```

- [ ] **Step 4 : Enregistrer la commande**

Dans `src/adapters/cli/commands/__init__.py`, à la suite des autres imports (ex. après le bloc `dedupe_series`), ajouter :

```python
from src.adapters.cli.commands.link_movie_parts_command import (
    link_movie_parts,
)
```

et ajouter `"link_movie_parts",` dans la liste `__all__`.

Dans `src/main.py` :
- Ajouter `link_movie_parts` à l'import depuis `.adapters.cli.commands` (bloc lignes 12-45).
- Après la ligne `app.command(name="dedupe-series")(dedupe_series)` (ligne 128), ajouter :

```python
app.command(name="link-movie-parts")(link_movie_parts)
```

- [ ] **Step 5 : Lancer le test pour vérifier qu'il passe**

Run: `uv run --extra dev pytest tests/unit/adapters/cli/test_link_movie_parts_command.py -v`
Expected: PASS

- [ ] **Step 6 : Vérifier que la CLI démarre**

Run: `uv run python -m src.main --help`
Expected: la commande `link-movie-parts` apparaît dans la liste.

- [ ] **Step 7 : Commit**

```bash
git add src/adapters/cli/commands/link_movie_parts_command.py src/adapters/cli/commands/__init__.py src/main.py tests/unit/adapters/cli/test_link_movie_parts_command.py
git commit -m "feat(cli): commande link-movie-parts de rattachement des parties"
```

---

### Task 10 : Lint, suite complète, README

**Files:**
- Modify: `README.md`

- [ ] **Step 1 : Lint sur les fichiers modifiés**

Run :
```bash
uv run --extra dev ruff format src/infrastructure/persistence/models.py src/adapters/cli/batch_builder.py src/services/workflow/transfer_step.py src/web/routes/library/detail.py src/web/routes/library/player.py src/web/routes/library/delete.py src/services/movie_parts.py src/adapters/cli/commands/link_movie_parts_command.py
uv run --extra dev ruff check src/services/movie_parts.py src/adapters/cli/commands/link_movie_parts_command.py src/services/workflow/transfer_step.py
```
Expected: aucune erreur (corriger le cas échéant ; ne pas élargir au reste du dépôt — dette lint préexistante hors périmètre).

- [ ] **Step 2 : Suite de tests ciblée**

Run :
```bash
uv run --extra dev pytest tests/unit/infrastructure/persistence/test_movie_part_model.py tests/unit/adapters/cli/test_batch_builder_movie_parts.py tests/unit/services/workflow/test_transfer_movie_parts.py tests/unit/web/test_movie_detail_parts.py tests/unit/web/test_movie_part_play.py tests/unit/web/test_delete_movie_parts.py tests/unit/services/test_movie_parts_linker.py tests/unit/adapters/cli/test_link_movie_parts_command.py -v
```
Expected: tous PASS.

- [ ] **Step 3 : Non-régression workflow & web**

Run :
```bash
uv run --extra dev pytest tests/unit/adapters/cli tests/unit/web tests/unit/services -q
```
Expected: pas de régression introduite par les changements (si des échecs préexistants subsistent, les distinguer des nouveaux).

- [ ] **Step 4 : Documenter dans le README**

Ajouter au `README.md` :
- Une sous-section « Films multi-parties » expliquant : détection des parties au transfert, regroupement sous une seule fiche, bloc « Parties » sur la fiche avec lecture individuelle.
- La commande `link-movie-parts` (usage, `--apply`, dry-run par défaut) dans la liste des commandes CLI, et une entrée dans la table des matières si pertinent.

- [ ] **Step 5 : Commit**

```bash
git add README.md
git commit -m "docs(films): documenter les films multi-parties et link-movie-parts"
```

---

## Validation de bout en bout (manuelle, après implémentation)

> À exécuter par l'utilisateur sur la vraie base/zone vidéo. Sauvegarder d'abord la base.

- [ ] **Sauvegarde** : `cp cineorg.db cineorg.db.bak.avant-multiparties-$(date +%s)`

- [ ] **Docteur Mabuse (backfill)** :
  1. `uv run python -m src.main link-movie-parts` (dry-run) → vérifier qu'il propose la Partie 2.
  2. `uv run python -m src.main link-movie-parts --apply`.
  3. Ouvrir la fiche « Docteur Mabuse le joueur » → vérifier le bloc « Parties » (Partie 1 + Partie 2), chacune jouable.

- [ ] **Nos meilleures années (workflow complet)** :
  1. Supprimer la fiche `Movie` (id actuel 5712) + toute ligne `movie_parts` associée.
  2. Retirer les symlinks `video/…/Nos meilleures années (2003) Partie 1 …` et `… Partie 2 …`.
  3. Replacer les deux fichiers source dans le répertoire de téléchargements/scan.
  4. Relancer le workflow (`uv run python -m src.main process` ou via l'interface web).
  5. Vérifier qu'**une seule fiche** est créée, avec un bloc « Parties » listant **deux parties jouables**.

---

## Self-review (couverture spec)

- Modèle `movie_parts` (table dédiée, parties ≥ 2, Partie 1 sur la fiche) → Task 1. ✓
- Workflow bout-en-bout (annotation + création MoviePart au transfert) → Tasks 2-3. ✓
- Fiche web + bloc « Parties » + play par partie → Tasks 4-6. ✓
- Suppression en cascade → Task 7. ✓
- Backfill `link-movie-parts` (Docteur Mabuse) → Tasks 8-9. ✓
- Validation bout-en-bout (déconstruction de « Nos meilleures années ») → section dédiée. ✓
- Hors périmètre (métadonnées par partie, playlist auto) → non implémenté, conforme au spec. ✓
- Déviation assumée : pas d'entité domaine `MoviePart` ni de méthodes au port `IMovieRepository` (style direct-session existant, YAGNI) → documenté en tête.
