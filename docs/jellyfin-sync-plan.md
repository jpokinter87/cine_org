# Plan d'implémentation — `jellyfin-sync` (Sous-projet 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Une commande CLI `jellyfin-sync` qui génère un arbre de symlinks « à plat » + des sidecars `.nfo` complets (identité verrouillée par ID) pour les films et séries CineOrg, afin que Jellyfin identifie tout sans erreur ni série zappée.

**Architecture:** Service isolé `src/services/jellyfin/` découpé en unités pures et testables (NFO, arbre, orchestration) ; commande Typer qui l'invoque. Lecture directe des modèles SQLModel (champs riches), écriture filesystem idempotente, aucune API externe. Conforme à la spec `docs/jellyfin-sync-design.md`.

**Tech Stack:** Python 3.11+, SQLModel/SQLite, Typer, Rich, `xml.etree.ElementTree`, `pathvalidate` (via `sanitize_for_filesystem` existant), pytest.

---

## Préliminaires (pour l'exécutant)

- **Toujours** préfixer les tests par l'installation des extras dev :
  `uv sync --extra dev && uv run pytest …` (pytest est dans l'extra `dev`).
- Lint scopé aux fichiers modifiés uniquement : `uv run --extra dev ruff check <fichiers>` puis `uv run --extra dev ruff format <fichiers>`.
- Commits conventionnels en français (`feat:`, `test:`, `docs:`). Ne pas bumper la version à la main.
- Référence de conception : `docs/jellyfin-sync-design.md`.

### Carte des fichiers

| Fichier | Rôle |
|---|---|
| `src/config.py` (modif) | Nouveau réglage `jellyfin_dir` |
| `src/services/jellyfin/__init__.py` (créer) | Package |
| `src/services/jellyfin/dataclasses.py` (créer) | `JellyfinSyncReport` |
| `src/services/jellyfin/nfo_builder.py` (créer) | Fonctions pures modèle → XML NFO |
| `src/services/jellyfin/tree_builder.py` (créer) | Résolution source, noms, symlinks idempotents |
| `src/services/jellyfin/jellyfin_sync_service.py` (créer) | Orchestration `JellyfinSyncService` |
| `src/adapters/cli/commands/jellyfin_sync_command.py` (créer) | Commande Typer `jellyfin-sync` |
| `src/main.py` (modif) | Enregistrement de la commande |
| `tests/unit/test_jellyfin_nfo_builder.py` (créer) | Tests NFO |
| `tests/unit/test_jellyfin_tree_builder.py` (créer) | Tests arbre |
| `tests/unit/test_jellyfin_sync_service.py` (créer) | Tests orchestration (`:memory:`) |
| `README.md` (modif) | Doc commande + runbook Jellyfin |

---

## Task 1 : Réglage de configuration `jellyfin_dir`

**Files:**
- Modify: `src/config.py:39-42` (bloc « Chemins ») et `src/config.py:75-82` (validateur `expand_path`)
- Test: `tests/unit/test_config_jellyfin_dir.py`

- [ ] **Step 1 : Écrire le test qui échoue**

Create `tests/unit/test_config_jellyfin_dir.py` :

```python
"""Tests du réglage jellyfin_dir dans Settings."""

from pathlib import Path

from src.config import Settings


def test_jellyfin_dir_default():
    """Par défaut, jellyfin_dir vaut /media/Serveur/JellyfinLib."""
    settings = Settings()
    assert settings.jellyfin_dir == Path("/media/Serveur/JellyfinLib")


def test_jellyfin_dir_env_override(monkeypatch):
    """CINEORG_JELLYFIN_DIR surcharge la valeur et étend ~."""
    monkeypatch.setenv("CINEORG_JELLYFIN_DIR", "~/JellyfinTest")
    settings = Settings()
    assert settings.jellyfin_dir == Path.home() / "JellyfinTest"
```

- [ ] **Step 2 : Lancer le test pour vérifier l'échec**

Run: `uv sync --extra dev && uv run pytest tests/unit/test_config_jellyfin_dir.py -v`
Expected: FAIL (`AttributeError: 'Settings' object has no attribute 'jellyfin_dir'`).

- [ ] **Step 3 : Implémenter le réglage**

Dans `src/config.py`, après la ligne `video_dir: Path = Field(default=Path("~/Videos/video"))` (ligne 42), ajouter :

```python
    jellyfin_dir: Path = Field(default=Path("/media/Serveur/JellyfinLib"))
```

Et ajouter `"jellyfin_dir",` dans la liste du décorateur `@field_validator(...)` (vers ligne 75-82), par exemple juste après `"video_dir",` :

```python
    @field_validator(
        "downloads_dir",
        "storage_dir",
        "video_dir",
        "jellyfin_dir",
        "sandbox_dir",
        "log_file",
        mode="before",
    )
```

- [ ] **Step 4 : Lancer le test pour vérifier le succès**

Run: `uv run pytest tests/unit/test_config_jellyfin_dir.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5 : Commit**

```bash
git add src/config.py tests/unit/test_config_jellyfin_dir.py
git commit -m "feat(jellyfin): réglage jellyfin_dir dans la configuration"
```

---

## Task 2 : Dataclass `JellyfinSyncReport`

**Files:**
- Create: `src/services/jellyfin/__init__.py`
- Create: `src/services/jellyfin/dataclasses.py`
- Test: `tests/unit/test_jellyfin_report.py`

- [ ] **Step 1 : Écrire le test qui échoue**

Create `tests/unit/test_jellyfin_report.py` :

```python
"""Tests du rapport de synchronisation Jellyfin."""

from src.services.jellyfin.dataclasses import JellyfinSyncReport


def test_report_defaults_are_empty():
    report = JellyfinSyncReport()
    assert report.movies == 0
    assert report.series == 0
    assert report.episodes == 0
    assert report.skipped == []
    assert report.id_less == []
    assert report.pruned == []
    assert report.errors == []


def test_report_accumulates():
    report = JellyfinSyncReport()
    report.movies += 1
    report.skipped.append("/x/y.mkv")
    assert report.movies == 1
    assert report.skipped == ["/x/y.mkv"]
```

- [ ] **Step 2 : Lancer le test (échec)**

Run: `uv run pytest tests/unit/test_jellyfin_report.py -v`
Expected: FAIL (`ModuleNotFoundError: src.services.jellyfin`).

- [ ] **Step 3 : Implémenter**

Create `src/services/jellyfin/__init__.py` :

```python
"""Services d'intégration Jellyfin (génération arbre dédié + NFO)."""
```

Create `src/services/jellyfin/dataclasses.py` :

```python
"""Objets de données pour la synchronisation Jellyfin."""

from dataclasses import dataclass, field


@dataclass
class JellyfinSyncReport:
    """Bilan d'une exécution de `jellyfin-sync`.

    - movies / series / episodes : éléments effectivement liés (NFO + symlink).
    - skipped : sources introuvables (chaîne de repli épuisée).
    - id_less : œuvres sans identifiant TMDB/TVDB (liées quand même, titre/année).
    - pruned : entrées supprimées de l'arbre Jellyfin (option --prune).
    - errors : messages d'erreur non bloquants rencontrés.
    """

    movies: int = 0
    series: int = 0
    episodes: int = 0
    skipped: list[str] = field(default_factory=list)
    id_less: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
```

- [ ] **Step 4 : Lancer le test (succès)**

Run: `uv run pytest tests/unit/test_jellyfin_report.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5 : Commit**

```bash
git add src/services/jellyfin/__init__.py src/services/jellyfin/dataclasses.py tests/unit/test_jellyfin_report.py
git commit -m "feat(jellyfin): dataclass JellyfinSyncReport"
```

---

## Task 3 : NFO film (`build_movie_nfo`)

**Files:**
- Create: `src/services/jellyfin/nfo_builder.py`
- Test: `tests/unit/test_jellyfin_nfo_builder.py`

Les fonctions sont **pures** : elles prennent un `MovieModel`/`SeriesModel`/`EpisodeModel` et renvoient une chaîne XML. Les tests **parsent** la sortie (pas d'assertion sur des espaces) pour rester robustes.

- [ ] **Step 1 : Écrire le test qui échoue**

Create `tests/unit/test_jellyfin_nfo_builder.py` :

```python
"""Tests des générateurs de NFO Jellyfin."""

import xml.etree.ElementTree as ET

from src.infrastructure.persistence.models import MovieModel
from src.services.jellyfin.nfo_builder import build_movie_nfo


def _parse(xml_str: str) -> ET.Element:
    return ET.fromstring(xml_str)


def test_movie_nfo_uniqueids_and_titles():
    movie = MovieModel(
        title="Inception",
        original_title="Inception",
        year=2010,
        tmdb_id=27205,
        imdb_id="tt1375666",
        duration_seconds=8880,  # 148 min
        overview="Un voleur…",
        vote_average=8.4,
        vote_count=30000,
        imdb_rating=8.8,
        imdb_votes=2400000,
        personal_rating=9,
        director="Christopher Nolan",
        collection_name="Saga Inception",
    )
    movie.genres = ["Action", "Science-Fiction"]
    movie.cast = ["Leonardo DiCaprio", "Elliot Page"]

    root = _parse(build_movie_nfo(movie))

    assert root.tag == "movie"
    assert root.findtext("title") == "Inception"
    assert root.findtext("originaltitle") == "Inception"
    assert root.findtext("year") == "2010"
    assert root.findtext("runtime") == "148"
    assert root.findtext("plot") == "Un voleur…"

    ids = {u.get("type"): (u.text, u.get("default")) for u in root.findall("uniqueid")}
    assert ids["tmdb"] == ("27205", "true")
    assert ids["imdb"][0] == "tt1375666"

    genres = [g.text for g in root.findall("genre")]
    assert genres == ["Action", "Science-Fiction"]

    actors = [a.findtext("name") for a in root.findall("actor")]
    assert actors == ["Leonardo DiCaprio", "Elliot Page"]

    assert root.findtext("set/name") == "Saga Inception"
    assert root.findtext("userrating") == "9"


def test_movie_nfo_overrides_take_precedence():
    movie = MovieModel(title="X", year=2000, tmdb_id=1, overview="ancien")
    movie.overview_override = "nouveau synopsis"
    movie.poster_override = "http://poster/override.jpg"
    movie.poster_path = "http://poster/origin.jpg"
    movie.cast_override_json = '[{"name": "Acteur Surchargé", "role": "Héros"}]'

    root = _parse(build_movie_nfo(movie))

    assert root.findtext("plot") == "nouveau synopsis"
    assert root.findtext("art/poster") == "http://poster/override.jpg"
    actors = [(a.findtext("name"), a.findtext("role")) for a in root.findall("actor")]
    assert actors == [("Acteur Surchargé", "Héros")]


def test_movie_nfo_omits_absent_fields():
    movie = MovieModel(title="Minimal", tmdb_id=42)
    root = _parse(build_movie_nfo(movie))
    assert root.findtext("title") == "Minimal"
    assert root.find("year") is None
    assert root.find("plot") is None
    assert root.find("set") is None


def test_movie_nfo_escapes_special_chars():
    movie = MovieModel(title="Tom & Jerry <Le film>", year=2021, tmdb_id=5)
    xml_str = build_movie_nfo(movie)
    # Doit rester parsable (échappement correct) et restituer le texte brut.
    root = _parse(xml_str)
    assert root.findtext("title") == "Tom & Jerry <Le film>"
```

- [ ] **Step 2 : Lancer le test (échec)**

Run: `uv run pytest tests/unit/test_jellyfin_nfo_builder.py -v`
Expected: FAIL (`ModuleNotFoundError` / `build_movie_nfo` introuvable).

- [ ] **Step 3 : Implémenter `nfo_builder.py` (partie film)**

Create `src/services/jellyfin/nfo_builder.py` :

```python
"""Générateurs de fichiers NFO (XML) pour Jellyfin, à partir des modèles DB.

Fonctions pures : un modèle en entrée, une chaîne XML en sortie. Les champs
absents sont omis (pas de balise vide). Les valeurs surchargées (`*_override`)
priment sur les valeurs d'origine.
"""

import json
import xml.etree.ElementTree as ET

from src.infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    SeriesModel,
)

_XML_DECL = '<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n'


def _text(parent: ET.Element, tag: str, value) -> None:
    """Ajoute <tag>value</tag> si value est non vide/non None."""
    if value is None:
        return
    s = str(value).strip()
    if s == "":
        return
    ET.SubElement(parent, tag).text = s


def _add_ratings(root: ET.Element, tmdb_avg, tmdb_votes, imdb_avg, imdb_votes) -> None:
    """Ajoute un bloc <ratings> + un <rating> de tête (compat Jellyfin)."""
    entries = []
    if tmdb_avg is not None:
        entries.append(("themoviedb", tmdb_avg, tmdb_votes, "true"))
    if imdb_avg is not None:
        entries.append(("imdb", imdb_avg, imdb_votes, "false"))
    if not entries:
        return
    ratings = ET.SubElement(root, "ratings")
    for name, value, votes, default in entries:
        r = ET.SubElement(ratings, "rating", {"name": name, "max": "10", "default": default})
        ET.SubElement(r, "value").text = f"{value:.1f}"
        if votes is not None:
            ET.SubElement(r, "votes").text = str(votes)
    # <rating> de tête = première entrée (TMDB prioritaire si présent).
    _text(root, "rating", f"{entries[0][1]:.1f}")


def _add_actors(root: ET.Element, model) -> None:
    """Ajoute les <actor>. Priorité au cast surchargé (avec rôles)."""
    override = []
    if getattr(model, "cast_override_json", None):
        override = json.loads(model.cast_override_json)
    if override:
        for entry in override:
            actor = ET.SubElement(root, "actor")
            _text(actor, "name", entry.get("name"))
            _text(actor, "role", entry.get("role"))
        return
    for name in model.cast:  # propriété -> list[str]
        actor = ET.SubElement(root, "actor")
        _text(actor, "name", name)


def _add_common(root: ET.Element, model) -> None:
    """Champs communs film/série : titres, année, plot, genres, notes, etc."""
    _text(root, "title", model.title)
    _text(root, "originaltitle", model.original_title)
    _text(root, "year", model.year)
    plot = model.overview_override or model.overview
    _text(root, "plot", plot)
    if model.duration_seconds:
        _text(root, "runtime", model.duration_seconds // 60)
    for genre in model.genres:  # propriété -> list[str]
        _text(root, "genre", genre)
    _add_ratings(
        root, model.vote_average, model.vote_count, model.imdb_rating, model.imdb_votes
    )
    _text(root, "userrating", model.personal_rating)
    if model.director:
        for name in [d.strip() for d in model.director.split(",") if d.strip()]:
            _text(root, "director", name)
    _add_actors(root, model)
    poster = model.poster_override or model.poster_path
    if poster:
        art = ET.SubElement(root, "art")
        _text(art, "poster", poster)


def _serialize(root: ET.Element) -> str:
    return _XML_DECL + ET.tostring(root, encoding="unicode")


def build_movie_nfo(movie: MovieModel) -> str:
    """Construit le contenu de `movie.nfo`."""
    root = ET.Element("movie")
    _add_common(root, movie)
    if movie.tmdb_id is not None:
        ET.SubElement(root, "uniqueid", {"type": "tmdb", "default": "true"}).text = str(movie.tmdb_id)
    if movie.imdb_id:
        ET.SubElement(root, "uniqueid", {"type": "imdb"}).text = movie.imdb_id
    if movie.collection_name:
        s = ET.SubElement(root, "set")
        _text(s, "name", movie.collection_name)
    if getattr(movie, "watched", False):
        _text(root, "playcount", 1)
        _text(root, "watched", "true")
    return _serialize(root)
```

- [ ] **Step 4 : Lancer le test (succès)**

Run: `uv run pytest tests/unit/test_jellyfin_nfo_builder.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5 : Commit**

```bash
git add src/services/jellyfin/nfo_builder.py tests/unit/test_jellyfin_nfo_builder.py
git commit -m "feat(jellyfin): génération NFO film (IDs + métadonnées complètes)"
```

---

## Task 4 : NFO série + épisode (`build_tvshow_nfo`, `build_episode_nfo`)

**Files:**
- Modify: `src/services/jellyfin/nfo_builder.py`
- Test: `tests/unit/test_jellyfin_nfo_builder.py` (ajouts)

- [ ] **Step 1 : Ajouter les tests qui échouent**

Ajouter dans `tests/unit/test_jellyfin_nfo_builder.py` :

```python
from src.infrastructure.persistence.models import EpisodeModel, SeriesModel
from src.services.jellyfin.nfo_builder import build_episode_nfo, build_tvshow_nfo


def test_tvshow_nfo_uniqueids():
    series = SeriesModel(
        title="12 Monkeys",
        year=2015,
        tvdb_id=272644,
        tmdb_id=60948,
        imdb_id="tt3148266",
        overview="Voyage temporel…",
    )
    series.genres = ["Science-Fiction"]
    series.cast = ["Aaron Stanford"]
    root = ET.fromstring(build_tvshow_nfo(series))

    assert root.tag == "tvshow"
    assert root.findtext("title") == "12 Monkeys"
    ids = {u.get("type"): (u.text, u.get("default")) for u in root.findall("uniqueid")}
    assert ids["tvdb"] == ("272644", "true")
    assert ids["tmdb"][0] == "60948"
    assert ids["imdb"][0] == "tt3148266"
    assert [g.text for g in root.findall("genre")] == ["Science-Fiction"]


def test_episode_nfo_fields():
    from datetime import date

    ep = EpisodeModel(
        series_id=1,
        season_number=1,
        episode_number=3,
        title="Le Syndrome de Cassandra",
        air_date=date(2015, 1, 30),
        overview="Cole et Railly…",
        duration_seconds=2580,  # 43 min
    )
    root = ET.fromstring(build_episode_nfo(ep))

    assert root.tag == "episodedetails"
    assert root.findtext("title") == "Le Syndrome de Cassandra"
    assert root.findtext("season") == "1"
    assert root.findtext("episode") == "3"
    assert root.findtext("aired") == "2015-01-30"
    assert root.findtext("plot") == "Cole et Railly…"
    assert root.findtext("runtime") == "43"
```

- [ ] **Step 2 : Lancer (échec)**

Run: `uv run pytest tests/unit/test_jellyfin_nfo_builder.py -v`
Expected: FAIL (`build_tvshow_nfo` / `build_episode_nfo` introuvables).

- [ ] **Step 3 : Implémenter (ajouts dans `nfo_builder.py`)**

Ajouter à la fin de `src/services/jellyfin/nfo_builder.py` :

```python
def build_tvshow_nfo(series: SeriesModel) -> str:
    """Construit le contenu de `tvshow.nfo`."""
    root = ET.Element("tvshow")
    _add_common(root, series)
    if series.tvdb_id is not None:
        ET.SubElement(root, "uniqueid", {"type": "tvdb", "default": "true"}).text = str(series.tvdb_id)
    if series.tmdb_id is not None:
        ET.SubElement(root, "uniqueid", {"type": "tmdb"}).text = str(series.tmdb_id)
    if series.imdb_id:
        ET.SubElement(root, "uniqueid", {"type": "imdb"}).text = series.imdb_id
    return _serialize(root)


def build_episode_nfo(episode: EpisodeModel) -> str:
    """Construit le NFO d'un épisode (sidecar `{nom}.nfo`)."""
    root = ET.Element("episodedetails")
    _text(root, "title", episode.title)
    _text(root, "season", episode.season_number)
    _text(root, "episode", episode.episode_number)
    if episode.air_date is not None:
        _text(root, "aired", episode.air_date.isoformat())
    _text(root, "plot", episode.overview)
    if episode.duration_seconds:
        _text(root, "runtime", episode.duration_seconds // 60)
    return _serialize(root)
```

- [ ] **Step 4 : Lancer (succès)**

Run: `uv run pytest tests/unit/test_jellyfin_nfo_builder.py -v`
Expected: PASS (6 tests au total).

- [ ] **Step 5 : Commit**

```bash
git add src/services/jellyfin/nfo_builder.py tests/unit/test_jellyfin_nfo_builder.py
git commit -m "feat(jellyfin): génération NFO série et épisode"
```

---

## Task 5 : Résolution de la source (chaîne de repli)

**Files:**
- Create: `src/services/jellyfin/tree_builder.py`
- Test: `tests/unit/test_jellyfin_tree_builder.py`

- [ ] **Step 1 : Écrire le test qui échoue**

Create `tests/unit/test_jellyfin_tree_builder.py` :

```python
"""Tests de la construction de l'arbre Jellyfin."""

from src.services.jellyfin.tree_builder import resolve_source


def test_resolve_prefers_valid_symlink(tmp_path):
    physical = tmp_path / "phys.mkv"
    physical.write_text("x")
    link = tmp_path / "link.mkv"
    link.symlink_to(physical)

    result = resolve_source(str(link), None)
    assert result == physical.resolve()


def test_resolve_falls_back_to_file_path(tmp_path):
    physical = tmp_path / "phys.mkv"
    physical.write_text("x")
    missing_link = tmp_path / "gone.mkv"  # n'existe pas

    result = resolve_source(str(missing_link), str(physical))
    assert result == physical.resolve()


def test_resolve_returns_none_when_all_missing(tmp_path):
    result = resolve_source(str(tmp_path / "a.mkv"), str(tmp_path / "b.mkv"))
    assert result is None


def test_resolve_handles_none_inputs():
    assert resolve_source(None, None) is None
```

- [ ] **Step 2 : Lancer (échec)**

Run: `uv run pytest tests/unit/test_jellyfin_tree_builder.py -v`
Expected: FAIL (`ModuleNotFoundError` / `resolve_source` introuvable).

- [ ] **Step 3 : Implémenter (début de `tree_builder.py`)**

Create `src/services/jellyfin/tree_builder.py` :

```python
"""Construction de l'arbre de symlinks dédié à Jellyfin.

Résolution de la source (chaîne de repli), calcul des noms à plat, création
idempotente des symlinks.
"""

from pathlib import Path

from src.services.renamer import sanitize_for_filesystem


def resolve_source(symlink_path: str | None, file_path: str | None) -> Path | None:
    """Résout le fichier physique réel à lier.

    Chaîne de repli : `realpath(symlink_path)` s'il résout vers un fichier
    présent, sinon `file_path` s'il existe, sinon None.
    """
    for candidate in (symlink_path, file_path):
        if not candidate:
            continue
        p = Path(candidate)
        if p.exists():  # suit les symlinks ; True seulement si la cible existe
            return p.resolve()
    return None
```

- [ ] **Step 4 : Lancer (succès)**

Run: `uv run pytest tests/unit/test_jellyfin_tree_builder.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5 : Commit**

```bash
git add src/services/jellyfin/tree_builder.py tests/unit/test_jellyfin_tree_builder.py
git commit -m "feat(jellyfin): résolution source avec chaîne de repli"
```

---

## Task 6 : Noms à plat + symlink idempotent

**Files:**
- Modify: `src/services/jellyfin/tree_builder.py`
- Test: `tests/unit/test_jellyfin_tree_builder.py` (ajouts)

- [ ] **Step 1 : Ajouter les tests qui échouent**

Ajouter dans `tests/unit/test_jellyfin_tree_builder.py` :

```python
from src.services.jellyfin.tree_builder import (
    ensure_symlink,
    episode_filename,
    folder_name,
)


def test_folder_name_with_year():
    assert folder_name("Inception", 2010) == "Inception (2010)"


def test_folder_name_without_year():
    assert folder_name("Sans Année", None) == "Sans Année"


def test_folder_name_with_tmdb_suffix():
    assert folder_name("Doublon", 2010, tmdb_id=42, with_id=True) == "Doublon (2010) [tmdbid-42]"


def test_folder_name_sanitizes_illegal_chars():
    # ':' et '/' sont remplacés par des tirets par sanitize_for_filesystem.
    out = folder_name("A: B/C", 2020)
    assert ":" not in out and "/" not in out
    assert out.endswith("(2020)")


def test_episode_filename():
    assert episode_filename("12 Monkeys", 2015, 1, 3, ".mkv") == "12 Monkeys (2015) S01E03.mkv"


def test_ensure_symlink_creates_and_is_idempotent(tmp_path):
    target = tmp_path / "phys.mkv"
    target.write_text("x")
    link = tmp_path / "sub" / "dir" / "link.mkv"

    ensure_symlink(target, link)
    assert link.is_symlink()
    assert link.resolve() == target.resolve()

    # Rejouer : ne lève pas, lien inchangé.
    ensure_symlink(target, link)
    assert link.resolve() == target.resolve()


def test_ensure_symlink_replaces_wrong_target(tmp_path):
    old = tmp_path / "old.mkv"
    old.write_text("o")
    new = tmp_path / "new.mkv"
    new.write_text("n")
    link = tmp_path / "link.mkv"
    link.symlink_to(old)

    ensure_symlink(new, link)
    assert link.resolve() == new.resolve()
```

- [ ] **Step 2 : Lancer (échec)**

Run: `uv run pytest tests/unit/test_jellyfin_tree_builder.py -v`
Expected: FAIL (`folder_name` / `episode_filename` / `ensure_symlink` introuvables).

- [ ] **Step 3 : Implémenter (ajouts dans `tree_builder.py`)**

Ajouter à la fin de `src/services/jellyfin/tree_builder.py` :

```python
def folder_name(title: str, year: int | None, tmdb_id: int | None = None, with_id: bool = False) -> str:
    """Nom de dossier à plat : `Titre (Année)`, avec suffixe `[tmdbid-N]` en cas de collision."""
    base = sanitize_for_filesystem(title)
    if year:
        base = f"{base} ({year})"
    if with_id and tmdb_id is not None:
        base = f"{base} [tmdbid-{tmdb_id}]"
    return base


def episode_filename(title: str, year: int | None, season: int, episode: int, ext: str) -> str:
    """Nom de fichier d'épisode : `Titre (Année) SxxExx.ext`."""
    base = sanitize_for_filesystem(title)
    if year:
        base = f"{base} ({year})"
    return f"{base} S{season:02d}E{episode:02d}{ext}"


def ensure_symlink(target: Path, link_path: Path) -> None:
    """Crée (ou corrige) un symlink `link_path -> target`, de façon idempotente."""
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.is_symlink():
        if link_path.readlink() == target:
            return
        link_path.unlink()
    elif link_path.exists():
        link_path.unlink()
    link_path.symlink_to(target)
```

- [ ] **Step 4 : Lancer (succès)**

Run: `uv run pytest tests/unit/test_jellyfin_tree_builder.py -v`
Expected: PASS (11 tests au total).

- [ ] **Step 5 : Commit**

```bash
git add src/services/jellyfin/tree_builder.py tests/unit/test_jellyfin_tree_builder.py
git commit -m "feat(jellyfin): noms à plat et création idempotente des symlinks"
```

---

## Task 7 : Orchestration — synchronisation des films

**Files:**
- Create: `src/services/jellyfin/jellyfin_sync_service.py`
- Test: `tests/unit/test_jellyfin_sync_service.py`

Le service interroge **directement les modèles** (champs riches) via une `Session`.

- [ ] **Step 1 : Écrire le test qui échoue**

Create `tests/unit/test_jellyfin_sync_service.py` :

```python
"""Tests d'orchestration de JellyfinSyncService."""

from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.infrastructure.persistence.models import MovieModel, MoviePartModel
from src.services.jellyfin.jellyfin_sync_service import JellyfinSyncService


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


def _make_physical(tmp_path: Path, name: str) -> Path:
    f = tmp_path / "phys" / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x")
    return f


def test_sync_movie_creates_tree_and_nfo(engine, tmp_path):
    phys = _make_physical(tmp_path, "Inception (2010).mkv")
    with Session(engine) as session:
        m = MovieModel(
            title="Inception", year=2010, tmdb_id=27205, imdb_id="tt1375666",
            symlink_path=str(phys),
        )
        session.add(m)
        session.commit()

    jf = tmp_path / "JellyfinLib"
    report = JellyfinSyncService(Session(engine), jf).sync(series_only=False)

    movie_dir = jf / "Films" / "Inception (2010)"
    assert (movie_dir / "Inception (2010).mkv").is_symlink()
    assert (movie_dir / "movie.nfo").exists()
    assert report.movies == 1
    assert "tt1375666" in (movie_dir / "movie.nfo").read_text()


def test_sync_skips_missing_source(engine, tmp_path):
    with Session(engine) as session:
        session.add(MovieModel(title="Perdu", year=1999, tmdb_id=1,
                               symlink_path="/n/existe/pas.mkv"))
        session.commit()

    jf = tmp_path / "JellyfinLib"
    report = JellyfinSyncService(Session(engine), jf).sync()

    assert report.movies == 0
    assert len(report.skipped) == 1


def test_sync_multipart_movie(engine, tmp_path):
    p1 = _make_physical(tmp_path, "hobbit1.mkv")
    p2 = _make_physical(tmp_path, "hobbit2.mkv")
    with Session(engine) as session:
        m = MovieModel(title="Le Hobbit", year=2012, tmdb_id=49051, symlink_path=str(p1))
        session.add(m)
        session.commit()
        session.refresh(m)
        session.add(MoviePartModel(movie_id=m.id, part_number=1, symlink_path=str(p1)))
        session.add(MoviePartModel(movie_id=m.id, part_number=2, symlink_path=str(p2)))
        session.commit()

    jf = tmp_path / "JellyfinLib"
    JellyfinSyncService(Session(engine), jf).sync()

    movie_dir = jf / "Films" / "Le Hobbit (2012)"
    links = sorted(p.name for p in movie_dir.glob("*.mkv"))
    assert len(links) == 2


def test_sync_collision_appends_tmdb_id(engine, tmp_path):
    p1 = _make_physical(tmp_path, "a.mkv")
    p2 = _make_physical(tmp_path, "b.mkv")
    with Session(engine) as session:
        session.add(MovieModel(title="Doublon", year=2000, tmdb_id=11, symlink_path=str(p1)))
        session.add(MovieModel(title="Doublon", year=2000, tmdb_id=22, symlink_path=str(p2)))
        session.commit()

    jf = tmp_path / "JellyfinLib"
    JellyfinSyncService(Session(engine), jf).sync()

    films = jf / "Films"
    names = sorted(d.name for d in films.iterdir())
    assert names == ["Doublon (2000)", "Doublon (2000) [tmdbid-22]"]


def test_sync_dry_run_creates_nothing(engine, tmp_path):
    phys = _make_physical(tmp_path, "x.mkv")
    with Session(engine) as session:
        session.add(MovieModel(title="X", year=2001, tmdb_id=3, symlink_path=str(phys)))
        session.commit()

    jf = tmp_path / "JellyfinLib"
    report = JellyfinSyncService(Session(engine), jf).sync(dry_run=True)

    assert not (jf / "Films").exists()
    assert report.movies == 1  # compté, mais rien écrit
```

- [ ] **Step 2 : Lancer (échec)**

Run: `uv run pytest tests/unit/test_jellyfin_sync_service.py -v`
Expected: FAIL (`ModuleNotFoundError` / `JellyfinSyncService` introuvable).

- [ ] **Step 3 : Implémenter le service (films)**

Create `src/services/jellyfin/jellyfin_sync_service.py` :

```python
"""Orchestration de la synchronisation CineOrg -> Jellyfin."""

from pathlib import Path

from sqlmodel import Session, select

from src.infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    MoviePartModel,
    SeriesModel,
)
from src.services.jellyfin.dataclasses import JellyfinSyncReport
from src.services.jellyfin.nfo_builder import (
    build_episode_nfo,
    build_movie_nfo,
    build_tvshow_nfo,
)
from src.services.jellyfin.tree_builder import (
    ensure_symlink,
    episode_filename,
    folder_name,
    resolve_source,
)


class JellyfinSyncService:
    """Génère l'arbre Jellyfin dédié (symlinks + NFO) depuis la base."""

    def __init__(self, session: Session, jellyfin_dir: Path) -> None:
        self._session = session
        self._root = Path(jellyfin_dir)

    def sync(
        self,
        *,
        movies_only: bool = False,
        series_only: bool = False,
        dry_run: bool = False,
        prune: bool = False,
    ) -> JellyfinSyncReport:
        report = JellyfinSyncReport()
        if not series_only:
            self._sync_movies(report, dry_run)
        if not movies_only:
            self._sync_series(report, dry_run)
        return report

    # --- Films -------------------------------------------------------------

    def _sync_movies(self, report: JellyfinSyncReport, dry_run: bool) -> None:
        films_root = self._root / "Films"
        used_dirs: set[str] = set()
        movies = self._session.exec(select(MovieModel)).all()
        for movie in movies:
            parts = self._session.exec(
                select(MoviePartModel).where(MoviePartModel.movie_id == movie.id)
            ).all()
            sources = self._movie_sources(movie, parts)
            if not sources:
                report.skipped.append(movie.symlink_path or movie.file_path or movie.title)
                continue
            if movie.tmdb_id is None:
                report.id_less.append(movie.title)

            # Nom de dossier + résolution de collision.
            name = folder_name(movie.title, movie.year)
            if name in used_dirs:
                name = folder_name(movie.title, movie.year, movie.tmdb_id, with_id=True)
            used_dirs.add(name)
            movie_dir = films_root / name

            if not dry_run:
                base = folder_name(movie.title, movie.year)
                for index, src in enumerate(sources):
                    if len(sources) == 1:
                        link_name = f"{base}{src.suffix}"
                    else:
                        link_name = f"{base} - cd{index + 1}{src.suffix}"
                    ensure_symlink(src, movie_dir / link_name)
                (movie_dir / "movie.nfo").write_text(
                    build_movie_nfo(movie), encoding="utf-8"
                )
            report.movies += 1

    def _movie_sources(self, movie: MovieModel, parts: list[MoviePartModel]) -> list[Path]:
        """Liste ordonnée des fichiers physiques à lier (gère le multi-parties)."""
        if parts:
            resolved = []
            for part in sorted(parts, key=lambda p: p.part_number):
                src = resolve_source(part.symlink_path, part.file_path)
                if src:
                    resolved.append(src)
            return resolved
        src = resolve_source(movie.symlink_path, movie.file_path)
        return [src] if src else []

    # --- Séries (Task 8) ---------------------------------------------------

    def _sync_series(self, report: JellyfinSyncReport, dry_run: bool) -> None:
        # Implémenté dans la Task 8.
        pass
```

- [ ] **Step 4 : Lancer (succès films)**

Run: `uv run pytest tests/unit/test_jellyfin_sync_service.py -v`
Expected: PASS (5 tests films).

- [ ] **Step 5 : Commit**

```bash
git add src/services/jellyfin/jellyfin_sync_service.py tests/unit/test_jellyfin_sync_service.py
git commit -m "feat(jellyfin): orchestration synchronisation des films"
```

---

## Task 8 : Orchestration — séries, épisodes, et `--prune`

**Files:**
- Modify: `src/services/jellyfin/jellyfin_sync_service.py` (méthode `_sync_series`, ajout `_prune`)
- Test: `tests/unit/test_jellyfin_sync_service.py` (ajouts)

- [ ] **Step 1 : Ajouter les tests qui échouent**

Ajouter dans `tests/unit/test_jellyfin_sync_service.py` :

```python
from src.infrastructure.persistence.models import EpisodeModel, SeriesModel


def test_sync_series_and_episodes(engine, tmp_path):
    ep_phys = _make_physical(tmp_path, "ep1.mkv")
    with Session(engine) as session:
        s = SeriesModel(title="12 Monkeys", year=2015, tvdb_id=272644, tmdb_id=60948)
        session.add(s)
        session.commit()
        session.refresh(s)
        session.add(EpisodeModel(
            series_id=s.id, season_number=1, episode_number=1,
            title="Fragmentation", symlink_path=str(ep_phys),
        ))
        session.commit()

    jf = tmp_path / "JellyfinLib"
    report = JellyfinSyncService(Session(engine), jf).sync(movies_only=False)

    show_dir = jf / "Séries" / "12 Monkeys (2015)"
    assert (show_dir / "tvshow.nfo").exists()
    season_dir = show_dir / "Saison 01"
    assert (season_dir / "12 Monkeys (2015) S01E01.mkv").is_symlink()
    assert (season_dir / "12 Monkeys (2015) S01E01.nfo").exists()
    assert report.series == 1
    assert report.episodes == 1


def test_sync_series_skips_missing_episode(engine, tmp_path):
    with Session(engine) as session:
        s = SeriesModel(title="Sérieuse", year=2020, tvdb_id=1)
        session.add(s)
        session.commit()
        session.refresh(s)
        session.add(EpisodeModel(
            series_id=s.id, season_number=1, episode_number=1,
            title="Absent", symlink_path="/pas/la.mkv",
        ))
        session.commit()

    jf = tmp_path / "JellyfinLib"
    report = JellyfinSyncService(Session(engine), jf).sync()
    assert report.episodes == 0
    assert len(report.skipped) == 1


def test_prune_removes_stale_entries(engine, tmp_path):
    phys = _make_physical(tmp_path, "ok.mkv")
    with Session(engine) as session:
        session.add(MovieModel(title="Garde", year=2000, tmdb_id=1, symlink_path=str(phys)))
        session.commit()

    jf = tmp_path / "JellyfinLib"
    # Entrée périmée pré-existante.
    stale = jf / "Films" / "Vieux Film (1990)"
    stale.mkdir(parents=True)
    (stale / "x.nfo").write_text("vieux")

    report = JellyfinSyncService(Session(engine), jf).sync(prune=True)

    assert (jf / "Films" / "Garde (2000)").exists()
    assert not stale.exists()
    assert any("Vieux Film" in p for p in report.pruned)
```

- [ ] **Step 2 : Lancer (échec)**

Run: `uv run pytest tests/unit/test_jellyfin_sync_service.py -v`
Expected: FAIL (séries non écrites ; `pass` actuel).

- [ ] **Step 3 : Implémenter `_sync_series` et `_prune`**

Remplacer la méthode `_sync_series` (le `pass`) dans `src/services/jellyfin/jellyfin_sync_service.py` par :

```python
    def _sync_series(self, report: JellyfinSyncReport, dry_run: bool) -> None:
        series_root = self._root / "Séries"
        used_dirs: set[str] = set()
        all_series = self._session.exec(select(SeriesModel)).all()
        for series in all_series:
            episodes = self._session.exec(
                select(EpisodeModel).where(EpisodeModel.series_id == series.id)
            ).all()
            resolved = [
                (ep, resolve_source(ep.symlink_path, ep.file_path)) for ep in episodes
            ]
            available = [(ep, src) for ep, src in resolved if src is not None]
            for ep, src in resolved:
                if src is None:
                    report.skipped.append(ep.symlink_path or ep.file_path or ep.title)
            if not available:
                continue  # série sans aucun épisode présent : on ne crée rien

            if series.tvdb_id is None and series.tmdb_id is None:
                report.id_less.append(series.title)

            name = folder_name(series.title, series.year)
            if name in used_dirs:
                name = folder_name(series.title, series.year, series.tmdb_id, with_id=True)
            used_dirs.add(name)
            show_dir = series_root / name

            if not dry_run:
                show_dir.mkdir(parents=True, exist_ok=True)
                (show_dir / "tvshow.nfo").write_text(
                    build_tvshow_nfo(series), encoding="utf-8"
                )
                for ep, src in available:
                    season_dir = show_dir / f"Saison {ep.season_number:02d}"
                    link_name = episode_filename(
                        series.title, series.year, ep.season_number, ep.episode_number, src.suffix
                    )
                    ensure_symlink(src, season_dir / link_name)
                    (season_dir / f"{Path(link_name).stem}.nfo").write_text(
                        build_episode_nfo(ep), encoding="utf-8"
                    )
            report.series += 1
            report.episodes += len(available)
```

Puis modifier `sync(...)` pour appeler l'élagage après coup. Remplacer le corps de `sync` par :

```python
        report = JellyfinSyncReport()
        self._expected_dirs: set[Path] = set()
        if not series_only:
            self._sync_movies(report, dry_run)
        if not movies_only:
            self._sync_series(report, dry_run)
        if prune and not dry_run:
            self._prune(report, movies_only, series_only)
        return report
```

Pour suivre les dossiers attendus, ajouter `self._expected_dirs.add(movie_dir)` à la fin de la boucle film (juste après `report.movies += 1`) et `self._expected_dirs.add(show_dir)` à la fin de la boucle série (après `report.series += 1`). Initialiser `self._expected_dirs = set()` aussi dans `__init__` pour les appels sans prune.

Enfin, ajouter la méthode `_prune` :

```python
    def _prune(self, report: JellyfinSyncReport, movies_only: bool, series_only: bool) -> None:
        """Supprime les dossiers de l'arbre Jellyfin absents de la base."""
        roots = []
        if not series_only:
            roots.append(self._root / "Films")
        if not movies_only:
            roots.append(self._root / "Séries")
        for root in roots:
            if not root.exists():
                continue
            for entry in root.iterdir():
                if entry.is_dir() and entry not in self._expected_dirs:
                    shutil.rmtree(entry)
                    report.pruned.append(str(entry))
```

Ajouter l'import en tête de fichier : `import shutil`.

- [ ] **Step 4 : Lancer (succès)**

Run: `uv run pytest tests/unit/test_jellyfin_sync_service.py -v`
Expected: PASS (8 tests au total).

- [ ] **Step 5 : Lancer toute la suite Jellyfin + lint**

Run:
```bash
uv run pytest tests/unit/test_jellyfin_nfo_builder.py tests/unit/test_jellyfin_tree_builder.py tests/unit/test_jellyfin_sync_service.py tests/unit/test_jellyfin_report.py tests/unit/test_config_jellyfin_dir.py -v
uv run --extra dev ruff check src/services/jellyfin/ src/config.py
uv run --extra dev ruff format src/services/jellyfin/
```
Expected: tous PASS ; ruff sans erreur.

- [ ] **Step 6 : Commit**

```bash
git add src/services/jellyfin/jellyfin_sync_service.py tests/unit/test_jellyfin_sync_service.py
git commit -m "feat(jellyfin): synchronisation séries/épisodes et élagage --prune"
```

---

## Task 9 : Commande CLI `jellyfin-sync`

**Files:**
- Create: `src/adapters/cli/commands/jellyfin_sync_command.py`
- Modify: `src/main.py` (import + enregistrement)
- Test: manuel (`--help` + `--dry-run`) — la logique est déjà couverte par les tests du service.

- [ ] **Step 1 : Implémenter la commande**

Create `src/adapters/cli/commands/jellyfin_sync_command.py` :

```python
"""Commande CLI `jellyfin-sync` : génère l'arbre Jellyfin dédié + NFO."""

from pathlib import Path
from typing import Annotated

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn
from sqlmodel import Session

from src.adapters.cli.validation import console
from src.container import Container
from src.infrastructure.persistence.database import get_engine
from src.services.jellyfin.jellyfin_sync_service import JellyfinSyncService


def jellyfin_sync(
    movies_only: Annotated[
        bool, typer.Option("--movies-only", help="Synchroniser seulement les films")
    ] = False,
    series_only: Annotated[
        bool, typer.Option("--series-only", help="Synchroniser seulement les séries")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Simuler sans rien écrire")
    ] = False,
    prune: Annotated[
        bool, typer.Option("--prune", help="Supprimer de l'arbre Jellyfin les entrées absentes de la base")
    ] = False,
) -> None:
    """Génère un arbre de symlinks dédié + NFO pour Jellyfin (films et séries)."""
    container = Container()
    config = container.config()
    container.database.init()

    jellyfin_dir = Path(config.jellyfin_dir)
    console.print(f"[cyan]Arbre Jellyfin :[/cyan] {jellyfin_dir}")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("[cyan]Synchronisation en cours...", total=None)
        with Session(get_engine()) as session:
            service = JellyfinSyncService(session, jellyfin_dir)
            report = service.sync(
                movies_only=movies_only,
                series_only=series_only,
                dry_run=dry_run,
                prune=prune,
            )

    prefix = "[yellow](simulation)[/yellow] " if dry_run else ""
    console.print(f"{prefix}[green]Films liés :[/green] {report.movies}")
    console.print(f"{prefix}[green]Séries liées :[/green] {report.series} "
                  f"([green]épisodes :[/green] {report.episodes})")
    if report.id_less:
        console.print(f"[yellow]Sans identifiant (titre/année seuls) :[/yellow] {len(report.id_less)}")
    if report.skipped:
        console.print(f"[yellow]Ignorés (source absente) :[/yellow] {len(report.skipped)}")
    if report.pruned:
        console.print(f"[magenta]Élagués :[/magenta] {len(report.pruned)}")
    if report.errors:
        console.print(f"[red]Erreurs :[/red] {len(report.errors)}")
```

- [ ] **Step 2 : Enregistrer dans `src/main.py`**

Dans le bloc d'import des commandes (autour des lignes 12-48 — voir `from .adapters.cli.commands import (...)`), ajouter `jellyfin_sync,` à la liste importée. Si l'import se fait par sous-module, suivre le style local ; sinon ajouter en tête :

```python
from .adapters.cli.commands.jellyfin_sync_command import jellyfin_sync
```

Puis, à côté des autres `app.command(...)` (autour des lignes 118-134), ajouter :

```python
app.command(name="jellyfin-sync")(jellyfin_sync)
```

> Vérifier le mécanisme d'export exact : si `src/adapters/cli/commands/__init__.py` ré-exporte les fonctions, y ajouter `jellyfin_sync`. Sinon, l'import direct ci-dessus suffit.

- [ ] **Step 3 : Vérifier `--help`**

Run: `uv run python -m src.main jellyfin-sync --help`
Expected: l'aide s'affiche avec les options `--movies-only`, `--series-only`, `--dry-run`, `--prune`.

- [ ] **Step 4 : Vérifier l'enregistrement global**

Run: `uv run python -m src.main --help`
Expected: `jellyfin-sync` apparaît dans la liste des commandes.

- [ ] **Step 5 : Commit**

```bash
git add src/adapters/cli/commands/jellyfin_sync_command.py src/main.py
git commit -m "feat(jellyfin): commande CLI jellyfin-sync"
```

---

## Task 10 : Vérification sur la base réelle (dry-run)

**Files:** aucun (validation manuelle).

- [ ] **Step 1 : Dry-run sur la vraie base**

Run: `uv run python -m src.main jellyfin-sync --dry-run`
Expected: compteurs cohérents (≈ totaux DB) ; « Ignorés » de l'ordre de ~62 films + quelques épisodes (constat d'intégrité §7 de la spec) ; aucun fichier écrit.

- [ ] **Step 2 : Exécution réelle**

Run: `uv run python -m src.main jellyfin-sync`
Expected: l'arbre `/media/Serveur/JellyfinLib/{Films,Séries}` est généré.

- [ ] **Step 3 : Contrôles de structure**

Run:
```bash
ls "/media/Serveur/JellyfinLib/Films" | head
find "/media/Serveur/JellyfinLib/Séries" -maxdepth 2 -name "tvshow.nfo" | head
```
Expected: dossiers `Titre (Année)/` avec `movie.nfo` ; séries à plat avec `tvshow.nfo` + `Saison NN/`.

- [ ] **Step 4 : Idempotence**

Run: `uv run python -m src.main jellyfin-sync` (une 2ᵉ fois)
Expected: ré-exécution sans erreur, mêmes compteurs liés, aucun doublon de dossier.

---

## Task 11 : Documentation (README + runbook Jellyfin)

**Files:**
- Modify: `README.md`

- [ ] **Step 1 : Documenter la commande**

Ajouter dans `README.md` (section commandes CLI + table des matières) une entrée `jellyfin-sync` : objectif, options (`--movies-only`, `--series-only`, `--dry-run`, `--prune`), exemple, et explication (arbre dédié à plat + NFO à IDs ; chaîne de repli ; périmètre Films/Séries).

- [ ] **Step 2 : Ajouter le runbook Jellyfin (volet ops, spec §6)**

Ajouter une sous-section « Brancher Jellyfin » avec la commande `docker run` :

```bash
docker run -d \
  --name jellyfin \
  --restart=unless-stopped \
  -p 8096:8096 \
  -v /home/jp/jellyfin/config:/config \
  -v /home/jp/jellyfin/cache:/cache \
  -v /media/Serveur/JellyfinLib:/media/Serveur/JellyfinLib:ro \
  -v /media/NAS64:/media/NAS64:ro \
  -v /media/Serveur:/media/Serveur:ro \
  jellyfin/jellyfin
```

Et les réglages : bibliothèque **Films** (type *Films*) → `/media/Serveur/JellyfinLib/Films` ; bibliothèque **Séries** (type *Séries/Émissions*) → `/media/Serveur/JellyfinLib/Séries` ; activer la **lecture des NFO locaux** comme source prioritaire, langue **fr**.

- [ ] **Step 3 : Commit**

```bash
git add README.md
git commit -m "docs(jellyfin): documenter jellyfin-sync et le branchement Jellyfin"
```

- [ ] **Step 4 : Bump de version**

Run: `uv run cz bump --yes` puis pousser le tag séparément si demandé.
Expected: version incrémentée (minor, car `feat:`), CHANGELOG mis à jour.

---

## Auto-revue du plan (effectuée)

- **Couverture de la spec :** §3.1 arbre (Tasks 6-8) ; §3.2 chaîne de repli (Task 5) ; §3.3 NFO complets + overrides (Tasks 3-4) ; §4 composants (Tasks 2,5,6,7,8,9) ; §5 flux (Tasks 7-8) ; §6 runbook ops (Task 11) ; §7 intégrité gérée par repli + signalée (Tasks 5,7,10) ; §8 erreurs non bloquantes (skipped/id_less, Tasks 7-8) ; §9 tests (chaque task TDD) ; §10 critères de succès (Task 10). ✅
- **Placeholders :** aucun TODO/TBD ; tout le code est fourni.
- **Cohérence des types :** `resolve_source`, `folder_name`, `episode_filename`, `ensure_symlink`, `build_movie_nfo`/`build_tvshow_nfo`/`build_episode_nfo`, `JellyfinSyncReport(.movies/.series/.episodes/.skipped/.id_less/.pruned/.errors)`, `JellyfinSyncService(session, jellyfin_dir).sync(...)` — noms identiques entre définition et usage.

### Points à confirmer pendant l'implémentation (non bloquants)
- Mécanisme exact d'export des commandes dans `src/adapters/cli/commands/__init__.py` (Task 9, Step 2) — adapter l'import au style local.
- `EpisodeModel` n'a pas d'ID fournisseur par épisode : le NFO épisode reste titre/saison/épisode/plot/aired/runtime (confirmé dans la spec §3.3).
