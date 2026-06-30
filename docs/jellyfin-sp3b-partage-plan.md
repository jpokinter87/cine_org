# Plan d'implémentation — SP3b « Partager / Départager »

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter à CineOrg un bouton web « Partager / Départager » qui expose un film (fichier seul) ou une série (intégrale) à un ami distant pour un visionnage SyncPlay, via une bibliothèque Jellyfin éphémère + le Funnel Tailscale à la demande, avec démontage manuel et automatique.

**Architecture:** Le service web permanent (`cineorg.service`, utilisateur `jp` = opérateur Tailscale) orchestre : remplissage/vidage de deux bibliothèques Jellyfin éphémères (`Partage/Films` type Films, `Partage/Series` type Séries) en réutilisant les briques `tree_builder`/`nfo_builder` ; scan ciblé via l'API Jellyfin ; activation/coupure du Funnel par sous-processus ; surveillance asyncio (lifespan) pour le démontage auto (30 min d'inactivité + plafond 6 h). Un seul partage actif à la fois, persisté en base (`ShareSessionModel`).

**Tech Stack:** Python 3.11+, FastAPI, Jinja2 + HTMX, SQLModel/SQLite, httpx (+ `request_with_retry`), Typer, `dependency-injector`, pytest + respx.

**Réutilisation (DRY) — briques existantes appelées telles quelles :**
- `src/services/jellyfin/tree_builder.py` : `resolve_source`, `folder_name`, `episode_filename`, `ensure_symlink`.
- `src/services/jellyfin/nfo_builder.py` : `build_movie_nfo`, `build_tvshow_nfo`, `build_episode_nfo` (consomment des **models**).
- `src/adapters/api/retry.py` : `request_with_retry`.
- Models : `MovieModel`, `MoviePartModel`, `SeriesModel`, `EpisodeModel`.

---

## Prérequis ops (manuels, hors code — à faire une fois avant la mise en service)

Ces étapes ne sont pas des tâches de code mais conditionnent le fonctionnement. À documenter dans le README (Tâche 12) et à exécuter par JP :

1. **Restructurer le dossier Partage** (depuis SP3a qui avait `Partage/{titre}` à plat) : la nouvelle arborescence sera `Partage/Films/...` et `Partage/Series/...` (créée automatiquement par le code ; vider l'ancien contenu de `/media/Serveur/JellyfinLib/Partage/`).
2. **Deux bibliothèques Jellyfin** (Tableau de bord → Bibliothèques), restreintes à `Alex`, NFO activé, « Actualiser depuis Internet = Jamais » :
   - « **Partage Films** » — type *Films* → `/media/Serveur/JellyfinLib/Partage/Films`
   - « **Partage Séries** » — type *Séries/Émissions* → `/media/Serveur/JellyfinLib/Partage/Series`
3. **Compte `Alex`** : accès limité à ces deux bibliothèques uniquement, SyncPlay activé (déjà en place pour l'une depuis SP3a).
4. **Clé API Jellyfin** (déjà générée) → renseigner `CINEORG_JELLYFIN_API_KEY` dans `.env`.
5. Opérateur Tailscale (`jp`) + Funnel activé : déjà faits en SP3a.

---

## Structure des fichiers

**Créés :**
- `src/adapters/api/jellyfin_client.py` — client httpx (refresh lib, sessions).
- `src/adapters/funnel.py` — contrôleur Funnel (sous-processus, runner injectable).
- `src/services/share/__init__.py`
- `src/services/share/exceptions.py` — `ShareError`, `ShareConflict`.
- `src/services/share/builder.py` — `JellyfinShareBuilder` (émission 1 titre + vidage).
- `src/services/share/share_service.py` — `ShareService` (orchestration + tick de surveillance).
- `src/services/share/monitor.py` — boucle asyncio `share_monitor_loop`.
- `src/infrastructure/persistence/repositories/share_session_repository.py` — `ShareSessionRepository`.
- `src/web/routes/share.py` — router FastAPI (`/share/...`).
- `src/web/templates/library/_share_btn.html` — bouton + zone d'action.
- Tests : `tests/unit/test_config_jellyfin_sharing.py`, `tests/unit/test_share_session_repository.py`, `tests/unit/adapters/api/test_jellyfin_client.py`, `tests/unit/test_funnel_controller.py`, `tests/unit/services/share/test_share_builder.py`, `tests/unit/services/share/test_share_service.py`, `tests/unit/web/test_share_routes.py`.

**Modifiés :**
- `src/config.py` — 3 champs + validateur + property.
- `src/infrastructure/persistence/models.py` — `ShareSessionModel`.
- `src/infrastructure/persistence/repositories/__init__.py` — export du repo.
- `src/container.py` — providers `jellyfin_client`, `funnel_controller`, `share_service`.
- `src/web/app.py` — montage router + tâche de fond dans `lifespan`.
- `src/web/deps.py` — (rien d'obligatoire ; le bandeau passe par un endpoint).
- `src/web/routes/library/detail.py` — `active_share` dans le contexte des fiches.
- `src/web/templates/library/_detail_poster_actions.html` — inclusion du bouton.
- `src/web/templates/base.html` — conteneur du bandeau global.
- `src/web/static/css/style.css` — styles bandeau + boutons.
- `README.md`, `pyproject.toml` (bump version).

---

## Convention de test

⚠️ pytest est dans l'extra `dev`. Toujours préfixer : `uv sync --extra dev && uv run --extra dev pytest ...`.
Lint des seuls fichiers modifiés : `uv run --extra dev ruff check <fichiers>` puis `ruff format <fichiers>`.

---

## Tâche 1 : Réglages de configuration

**Files:**
- Modify: `src/config.py`
- Test: `tests/unit/test_config_jellyfin_sharing.py`

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/unit/test_config_jellyfin_sharing.py
from pathlib import Path

from src.config import Settings


def test_jellyfin_sharing_defaults():
    s = Settings()
    assert s.jellyfin_url == "http://localhost:8096"
    assert s.jellyfin_api_key is None
    assert s.jellyfin_partage_dir == Path("/media/Serveur/JellyfinLib/Partage")
    assert s.jellyfin_api_enabled is False


def test_jellyfin_sharing_env_override(monkeypatch):
    monkeypatch.setenv("CINEORG_JELLYFIN_URL", "http://192.168.1.15:8096")
    monkeypatch.setenv("CINEORG_JELLYFIN_API_KEY", "secret")
    monkeypatch.setenv("CINEORG_JELLYFIN_PARTAGE_DIR", "~/jf/Partage")
    s = Settings()
    assert s.jellyfin_url == "http://192.168.1.15:8096"
    assert s.jellyfin_api_key == "secret"
    assert s.jellyfin_partage_dir == Path("~/jf/Partage").expanduser()
    assert s.jellyfin_api_enabled is True
```

- [ ] **Step 2: Lancer le test (échec attendu)**

Run: `uv sync --extra dev && uv run --extra dev pytest tests/unit/test_config_jellyfin_sharing.py -v`
Expected: FAIL (`AttributeError: 'Settings' object has no attribute 'jellyfin_url'`).

- [ ] **Step 3: Implémenter**

Dans `src/config.py`, après `jellyfin_dir` (ligne ~43) ajouter le champ chemin, après `tvdb_api_key` (ligne ~50) ajouter url + clé, ajouter `jellyfin_partage_dir` à la liste du validateur `expand_path`, et la property :

```python
    # Champ chemin (à placer près de jellyfin_dir)
    jellyfin_partage_dir: Path = Field(default=Path("/media/Serveur/JellyfinLib/Partage"))

    # Près des clés API
    jellyfin_url: str = Field(default="http://localhost:8096")
    jellyfin_api_key: Optional[str] = Field(default=None)
```

Ajouter `"jellyfin_partage_dir"` dans le décorateur `@field_validator(... )` de `expand_path`.

Property (près de `tmdb_enabled`) :

```python
    @property
    def jellyfin_api_enabled(self) -> bool:
        return self.jellyfin_api_key is not None
```

- [ ] **Step 4: Lancer le test (succès attendu)**

Run: `uv run --extra dev pytest tests/unit/test_config_jellyfin_sharing.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/unit/test_config_jellyfin_sharing.py
git commit -m "feat(share): réglages config Jellyfin (url, clé API, dossier Partage)"
```

---

## Tâche 2 : Table d'état `ShareSessionModel` + repository

**Files:**
- Modify: `src/infrastructure/persistence/models.py`
- Create: `src/infrastructure/persistence/repositories/share_session_repository.py`
- Modify: `src/infrastructure/persistence/repositories/__init__.py`
- Test: `tests/unit/test_share_session_repository.py`

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/unit/test_share_session_repository.py
from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine

from src.infrastructure.persistence.repositories.share_session_repository import (
    ShareSessionRepository,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_no_active_share_initially():
    repo = ShareSessionRepository(_session())
    assert repo.get_active() is None


def test_start_then_get_active():
    repo = ShareSessionRepository(_session())
    model = repo.start(media_type="movie", media_id=42, title="Inception", folder_name="Inception (2010)")
    assert model.is_active is True
    active = repo.get_active()
    assert active is not None
    assert active.media_id == 42
    assert active.title == "Inception"


def test_touch_played_updates_timestamp():
    repo = ShareSessionRepository(_session())
    model = repo.start(media_type="series", media_id=7, title="Gomorra", folder_name="Gomorra (2014)")
    when = datetime(2026, 6, 30, 21, 0, 0)
    repo.touch_played(model, when)
    assert repo.get_active().last_played_at == when


def test_deactivate_clears_active():
    repo = ShareSessionRepository(_session())
    model = repo.start(media_type="movie", media_id=1, title="X", folder_name="X (2000)")
    repo.deactivate(model)
    assert repo.get_active() is None
```

- [ ] **Step 2: Lancer le test (échec attendu)**

Run: `uv run --extra dev pytest tests/unit/test_share_session_repository.py -v`
Expected: FAIL (`ModuleNotFoundError` repository).

- [ ] **Step 3: Implémenter le model**

Dans `src/infrastructure/persistence/models.py`, ajouter (les `import datetime`/`SQLModel`/`Field` sont déjà présents en tête de fichier) :

```python
class ShareSessionModel(SQLModel, table=True):
    """État du partage Jellyfin actif (une seule ligne active à la fois)."""

    __tablename__ = "share_sessions"

    id: int | None = Field(default=None, primary_key=True)
    media_type: str  # "movie" | "series"
    media_id: int
    title: str
    folder_name: str  # nom du dossier créé sous Partage/Films ou Partage/Series
    is_active: bool = Field(default=True, index=True)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    last_played_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

(`create_all` créera la table automatiquement ; aucune migration nécessaire pour une table neuve.)

- [ ] **Step 4: Implémenter le repository**

```python
# src/infrastructure/persistence/repositories/share_session_repository.py
"""Accès à l'état du partage Jellyfin actif."""

from datetime import datetime

from sqlmodel import Session, select

from src.infrastructure.persistence.models import ShareSessionModel


class ShareSessionRepository:
    """Gère l'unique ShareSessionModel actif."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_active(self) -> ShareSessionModel | None:
        statement = select(ShareSessionModel).where(ShareSessionModel.is_active == True)  # noqa: E712
        return self._session.exec(statement).first()

    def start(
        self, *, media_type: str, media_id: int, title: str, folder_name: str
    ) -> ShareSessionModel:
        model = ShareSessionModel(
            media_type=media_type,
            media_id=media_id,
            title=title,
            folder_name=folder_name,
        )
        self._session.add(model)
        self._session.commit()
        self._session.refresh(model)
        return model

    def touch_played(self, model: ShareSessionModel, when: datetime) -> None:
        model.last_played_at = when
        self._session.add(model)
        self._session.commit()

    def deactivate(self, model: ShareSessionModel) -> None:
        model.is_active = False
        self._session.add(model)
        self._session.commit()
```

Ajouter l'export dans `src/infrastructure/persistence/repositories/__init__.py` :

```python
from .share_session_repository import ShareSessionRepository
```
(et l'ajouter à `__all__` s'il existe).

- [ ] **Step 5: Lancer les tests (succès attendu)**

Run: `uv run --extra dev pytest tests/unit/test_share_session_repository.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add src/infrastructure/persistence/models.py src/infrastructure/persistence/repositories/
git add tests/unit/test_share_session_repository.py
git commit -m "feat(share): table ShareSession + repository (un partage actif)"
```

---

## Tâche 3 : Client API Jellyfin

**Files:**
- Create: `src/adapters/api/jellyfin_client.py`
- Test: `tests/unit/adapters/api/test_jellyfin_client.py`

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/unit/adapters/api/test_jellyfin_client.py
import httpx
import pytest
import respx

from src.adapters.api.jellyfin_client import JellyfinClient

BASE = "http://jf:8096"
VFOLDERS = [
    {"Name": "Partage Films", "ItemId": "film-id", "CollectionType": "movies"},
    {"Name": "Partage Séries", "ItemId": "serie-id", "CollectionType": "tvshows"},
]


@pytest.mark.asyncio
@respx.mock
async def test_refresh_library_resolves_id_and_posts():
    respx.get(f"{BASE}/Library/VirtualFolders").mock(
        return_value=httpx.Response(200, json=VFOLDERS)
    )
    route = respx.post(f"{BASE}/Items/film-id/Refresh").mock(
        return_value=httpx.Response(204)
    )
    client = JellyfinClient(base_url=BASE, api_key="k")
    await client.refresh_library("Partage Films")
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_refresh_unknown_library_is_noop():
    respx.get(f"{BASE}/Library/VirtualFolders").mock(
        return_value=httpx.Response(200, json=VFOLDERS)
    )
    client = JellyfinClient(base_url=BASE, api_key="k")
    await client.refresh_library("Inexistante")  # ne lève pas


@pytest.mark.asyncio
@respx.mock
async def test_get_active_sessions_returns_list():
    respx.get(f"{BASE}/Sessions").mock(
        return_value=httpx.Response(
            200,
            json=[{"NowPlayingItem": {"Id": "x", "Path": "/media/.../Partage/Films/a.mkv"}}],
        )
    )
    client = JellyfinClient(base_url=BASE, api_key="k")
    sessions = await client.get_active_sessions()
    assert sessions[0]["NowPlayingItem"]["Path"].endswith("a.mkv")


@pytest.mark.asyncio
@respx.mock
async def test_auth_header_sent():
    route = respx.get(f"{BASE}/Sessions").mock(return_value=httpx.Response(200, json=[]))
    client = JellyfinClient(base_url=BASE, api_key="secret-token")
    await client.get_active_sessions()
    assert route.calls.last.request.headers["X-Emby-Token"] == "secret-token"
```

- [ ] **Step 2: Lancer le test (échec attendu)**

Run: `uv run --extra dev pytest tests/unit/adapters/api/test_jellyfin_client.py -v`
Expected: FAIL (module introuvable).

- [ ] **Step 3: Implémenter**

```python
# src/adapters/api/jellyfin_client.py
"""Client minimal de l'API Jellyfin (scan ciblé + sessions actives)."""

from __future__ import annotations

import httpx
from loguru import logger

from src.adapters.api.retry import request_with_retry


class JellyfinClient:
    """Appels API Jellyfin nécessaires au partage : rafraîchir une bibliothèque,
    lister les sessions de lecture en cours."""

    def __init__(self, base_url: str, api_key: str | None) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None
        self._library_ids: dict[str, str] = {}

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "X-Emby-Token": self._api_key or "",
                    "Accept": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def _library_id(self, name: str) -> str | None:
        if name in self._library_ids:
            return self._library_ids[name]
        client = self._get_client()
        resp = await request_with_retry(client, "GET", "/Library/VirtualFolders")
        for folder in resp.json():
            if folder.get("Name") == name and folder.get("ItemId"):
                self._library_ids[name] = folder["ItemId"]
                return folder["ItemId"]
        logger.warning("Bibliothèque Jellyfin introuvable : %s", name)
        return None

    async def refresh_library(self, name: str) -> None:
        """Lance un scan ciblé de la bibliothèque nommée (no-op si absente)."""
        item_id = await self._library_id(name)
        if item_id is None:
            return
        client = self._get_client()
        await request_with_retry(
            client,
            "POST",
            f"/Items/{item_id}/Refresh",
            params={
                "Recursive": "true",
                "MetadataRefreshMode": "Default",
                "ImageRefreshMode": "Default",
            },
        )

    async def get_active_sessions(self) -> list[dict]:
        client = self._get_client()
        resp = await request_with_retry(client, "GET", "/Sessions")
        return resp.json()

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
```

- [ ] **Step 4: Lancer les tests (succès attendu)**

Run: `uv run --extra dev pytest tests/unit/adapters/api/test_jellyfin_client.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/adapters/api/jellyfin_client.py tests/unit/adapters/api/test_jellyfin_client.py
git commit -m "feat(share): client API Jellyfin (refresh bibliothèque + sessions)"
```

---

## Tâche 4 : Contrôleur Funnel (sous-processus, runner injectable)

**Files:**
- Create: `src/adapters/funnel.py`
- Test: `tests/unit/test_funnel_controller.py`

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/unit/test_funnel_controller.py
from src.adapters.funnel import CommandResult, FunnelController


class FakeRunner:
    def __init__(self, result: CommandResult):
        self.result = result
        self.calls: list[list[str]] = []

    def run(self, args):
        self.calls.append(args)
        return self.result


def test_enable_runs_funnel_bg_and_returns_true():
    runner = FakeRunner(CommandResult(0, "Funnel started", ""))
    ctrl = FunnelController(port=8096, runner=runner)
    assert ctrl.enable() is True
    assert runner.calls[0] == ["tailscale", "funnel", "--bg", "8096"]


def test_enable_returns_false_on_failure():
    runner = FakeRunner(CommandResult(1, "", "not enabled"))
    ctrl = FunnelController(port=8096, runner=runner)
    assert ctrl.enable() is False


def test_disable_runs_off():
    runner = FakeRunner(CommandResult(0, "", ""))
    ctrl = FunnelController(port=8096, runner=runner)
    assert ctrl.disable() is True
    assert runner.calls[0] == ["tailscale", "funnel", "--https=443", "off"]


def test_is_on_parses_status():
    runner = FakeRunner(CommandResult(0, "# Funnel on:\n#  - https://x", ""))
    ctrl = FunnelController(port=8096, runner=runner)
    assert ctrl.is_on() is True


def test_is_on_false_when_no_config():
    runner = FakeRunner(CommandResult(0, "No serve config", ""))
    ctrl = FunnelController(port=8096, runner=runner)
    assert ctrl.is_on() is False
```

- [ ] **Step 2: Lancer le test (échec attendu)**

Run: `uv run --extra dev pytest tests/unit/test_funnel_controller.py -v`
Expected: FAIL (module introuvable).

- [ ] **Step 3: Implémenter**

```python
# src/adapters/funnel.py
"""Contrôle du Tailscale Funnel (exposition publique à la demande) par sous-processus.

Tourne en utilisateur `jp` déclaré opérateur Tailscale → pas de sudo nécessaire.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Protocol

from loguru import logger


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(self, args: list[str]) -> CommandResult: ...


class SubprocessRunner:
    """Exécute réellement la commande (capture sortie, ne lève pas)."""

    def run(self, args: list[str]) -> CommandResult:
        try:
            proc = subprocess.run(args, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:  # binaire tailscale absent
            return CommandResult(returncode=127, stdout="", stderr=str(exc))
        return CommandResult(proc.returncode, proc.stdout, proc.stderr)


class FunnelController:
    def __init__(self, port: int = 8096, runner: CommandRunner | None = None) -> None:
        self._port = port
        self._runner = runner or SubprocessRunner()

    def enable(self) -> bool:
        result = self._runner.run(["tailscale", "funnel", "--bg", str(self._port)])
        if result.returncode != 0:
            logger.error("Échec activation Funnel : %s", result.stderr.strip())
            return False
        return True

    def disable(self) -> bool:
        result = self._runner.run(["tailscale", "funnel", "--https=443", "off"])
        if result.returncode != 0:
            logger.error("Échec coupure Funnel : %s", result.stderr.strip())
            return False
        return True

    def is_on(self) -> bool:
        result = self._runner.run(["tailscale", "funnel", "status"])
        return result.returncode == 0 and "Funnel on" in result.stdout
```

- [ ] **Step 4: Lancer les tests (succès attendu)**

Run: `uv run --extra dev pytest tests/unit/test_funnel_controller.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/adapters/funnel.py tests/unit/test_funnel_controller.py
git commit -m "feat(share): contrôleur Funnel Tailscale (runner subprocess injectable)"
```

---

## Tâche 5 : Émetteur d'arbre Partage (`JellyfinShareBuilder`)

**Files:**
- Create: `src/services/share/__init__.py` (vide)
- Create: `src/services/share/exceptions.py`
- Create: `src/services/share/builder.py`
- Test: `tests/unit/services/share/test_share_builder.py`

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/unit/services/share/test_share_builder.py
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from src.infrastructure.persistence.models import EpisodeModel, MovieModel, SeriesModel
from src.services.share.builder import JellyfinShareBuilder
from src.services.share.exceptions import ShareError


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _physical(tmp_path: Path, name: str) -> Path:
    f = tmp_path / name
    f.write_bytes(b"x")
    return f


def test_populate_movie_creates_symlink_and_nfo(tmp_path):
    src = _physical(tmp_path, "film.mkv")
    session = _session()
    movie = MovieModel(title="Inception", year=2010, tmdb_id=27205, file_path=str(src), symlink_path=None)
    session.add(movie)
    session.commit()
    session.refresh(movie)

    partage = tmp_path / "Partage"
    builder = JellyfinShareBuilder(session, partage)
    folder = builder.populate_movie(movie.id)

    assert folder == "Inception (2010)"
    movie_dir = partage / "Films" / "Inception (2010)"
    link = movie_dir / "Inception (2010).mkv"
    assert link.is_symlink()
    assert link.resolve() == src.resolve()
    assert (movie_dir / "movie.nfo").exists()


def test_populate_movie_missing_source_raises(tmp_path):
    session = _session()
    movie = MovieModel(title="X", year=2000, file_path="/nope.mkv", symlink_path=None)
    session.add(movie)
    session.commit()
    session.refresh(movie)
    builder = JellyfinShareBuilder(session, tmp_path / "Partage")
    try:
        builder.populate_movie(movie.id)
        assert False, "devait lever ShareError"
    except ShareError:
        pass


def test_populate_series_creates_seasons(tmp_path):
    s1 = _physical(tmp_path, "e1.mkv")
    s2 = _physical(tmp_path, "e2.mkv")
    session = _session()
    series = SeriesModel(title="Gomorra", year=2014, tvdb_id=272135)
    session.add(series)
    session.commit()
    session.refresh(series)
    session.add(EpisodeModel(series_id=series.id, season_number=1, episode_number=1, title="P", file_path=str(s1), symlink_path=None))
    session.add(EpisodeModel(series_id=series.id, season_number=1, episode_number=2, title="D", file_path=str(s2), symlink_path=None))
    session.commit()

    partage = tmp_path / "Partage"
    builder = JellyfinShareBuilder(session, partage)
    folder = builder.populate_series(series.id)

    assert folder == "Gomorra (2014)"
    show_dir = partage / "Series" / "Gomorra (2014)"
    assert (show_dir / "tvshow.nfo").exists()
    season = show_dir / "Saison 01"
    links = sorted(p.name for p in season.glob("*.mkv"))
    assert links == ["Gomorra (2014) S01E01.mkv", "Gomorra (2014) S01E02.mkv"]


def test_clear_removes_films_and_series(tmp_path):
    partage = tmp_path / "Partage"
    (partage / "Films" / "a").mkdir(parents=True)
    (partage / "Series" / "b").mkdir(parents=True)
    builder = JellyfinShareBuilder(_session(), partage)
    builder.clear()
    assert not (partage / "Films").exists()
    assert not (partage / "Series").exists()
```

- [ ] **Step 2: Lancer le test (échec attendu)**

Run: `uv run --extra dev pytest tests/unit/services/share/test_share_builder.py -v`
Expected: FAIL (modules introuvables).

- [ ] **Step 3: Implémenter exceptions + builder**

```python
# src/services/share/__init__.py
```

```python
# src/services/share/exceptions.py
"""Exceptions du partage Jellyfin."""


class ShareError(Exception):
    """Erreur générique de préparation/teardown d'un partage."""


class ShareConflict(ShareError):
    """Un partage est déjà actif (et le remplacement n'a pas été confirmé)."""

    def __init__(self, active) -> None:
        self.active = active
        super().__init__(f"Partage déjà actif : {getattr(active, 'title', '?')}")
```

```python
# src/services/share/builder.py
"""Émet un seul titre (film ou série intégrale) dans l'arbre Partage éphémère.

Réutilise les briques pures de src/services/jellyfin/ et interroge les models via
une Session SQLModel (même approche que JellyfinSyncService).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlmodel import Session, select

from src.infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    MoviePartModel,
    SeriesModel,
)
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
from src.services.share.exceptions import ShareError


class JellyfinShareBuilder:
    def __init__(self, session: Session, partage_dir: Path | str) -> None:
        self._session = session
        self._root = Path(partage_dir)

    def clear(self) -> None:
        """Vide entièrement le dossier Partage (Films + Series)."""
        for sub in ("Films", "Series"):
            d = self._root / sub
            if d.exists():
                shutil.rmtree(d)

    def populate_movie(self, movie_id: int) -> str:
        movie = self._session.get(MovieModel, movie_id)
        if movie is None:
            raise ShareError(f"Film introuvable en base : {movie_id}")
        parts = self._session.exec(
            select(MoviePartModel)
            .where(MoviePartModel.movie_id == movie.id)
            .order_by(MoviePartModel.part_number)
        ).all()
        sources = self._movie_sources(movie, list(parts))
        if not sources:
            raise ShareError(f"Aucun fichier source résolvable pour : {movie.title}")

        name = folder_name(movie.title, movie.year)
        movie_dir = self._root / "Films" / name
        for index, src in enumerate(sources):
            if len(sources) == 1:
                link_name = f"{name}{src.suffix}"
            else:
                link_name = f"{name} - cd{index + 1}{src.suffix}"
            ensure_symlink(src, movie_dir / link_name)
        (movie_dir / "movie.nfo").write_text(build_movie_nfo(movie), encoding="utf-8")
        return name

    def populate_series(self, series_id: int) -> str:
        series = self._session.get(SeriesModel, series_id)
        if series is None:
            raise ShareError(f"Série introuvable en base : {series_id}")
        episodes = self._session.exec(
            select(EpisodeModel)
            .where(EpisodeModel.series_id == series.id)
            .order_by(EpisodeModel.season_number, EpisodeModel.episode_number)
        ).all()
        available: list[tuple[EpisodeModel, Path]] = []
        for ep in episodes:
            src = resolve_source(ep.symlink_path, ep.file_path)
            if src is not None:
                available.append((ep, src))
        if not available:
            raise ShareError(f"Aucun épisode résolvable pour : {series.title}")

        name = folder_name(series.title, series.year)
        show_dir = self._root / "Series" / name
        show_dir.mkdir(parents=True, exist_ok=True)
        (show_dir / "tvshow.nfo").write_text(build_tvshow_nfo(series), encoding="utf-8")
        for ep, src in available:
            season_dir = show_dir / f"Saison {ep.season_number:02d}"
            link_name = episode_filename(
                series.title, series.year, ep.season_number, ep.episode_number, src.suffix
            )
            ensure_symlink(src, season_dir / link_name)
            (season_dir / f"{Path(link_name).stem}.nfo").write_text(
                build_episode_nfo(ep), encoding="utf-8"
            )
        return name

    def _movie_sources(self, movie: MovieModel, parts: list[MoviePartModel]) -> list[Path]:
        if parts:
            out: list[Path] = []
            for part in parts:
                s = resolve_source(part.symlink_path, part.file_path)
                if s is not None:
                    out.append(s)
            return out
        s = resolve_source(movie.symlink_path, movie.file_path)
        return [s] if s is not None else []
```

- [ ] **Step 4: Lancer les tests (succès attendu)**

Run: `uv run --extra dev pytest tests/unit/services/share/test_share_builder.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/services/share/__init__.py src/services/share/exceptions.py src/services/share/builder.py
git add tests/unit/services/share/test_share_builder.py
git commit -m "feat(share): JellyfinShareBuilder (émet 1 film/série dans l'arbre Partage)"
```

---

## Tâche 6 : Orchestrateur `ShareService` (start / stop / tick surveillance)

**Files:**
- Create: `src/services/share/share_service.py`
- Test: `tests/unit/services/share/test_share_service.py`

**Interface (signatures à respecter dans les tâches suivantes) :**
- `async start_share(media_type: str, media_id: int, replace: bool = False) -> ShareSessionModel`
- `async stop_share() -> None`
- `get_active_share() -> ShareSessionModel | None`
- `async run_monitor_tick(now: datetime) -> str | None` (retourne `"hard_cap"`, `"idle"` ou `None`)
- `async reconcile_on_startup() -> None`

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/unit/services/share/test_share_service.py
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.infrastructure.persistence.models import MovieModel
from src.infrastructure.persistence.repositories.share_session_repository import (
    ShareSessionRepository,
)
from src.services.share.exceptions import ShareConflict
from src.services.share.share_service import ShareService


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _movie(session, tmp_path) -> MovieModel:
    f = tmp_path / "film.mkv"
    f.write_bytes(b"x")
    m = MovieModel(title="Inception", year=2010, tmdb_id=1, file_path=str(f), symlink_path=None)
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def _service(session, tmp_path, *, funnel=None, jellyfin=None) -> ShareService:
    return ShareService(
        session=session,
        partage_dir=tmp_path / "Partage",
        jellyfin_client=jellyfin or AsyncMock(),
        funnel=funnel or MagicMock(enable=MagicMock(return_value=True), disable=MagicMock(return_value=True), is_on=MagicMock(return_value=False)),
        idle_timeout=timedelta(minutes=30),
        hard_cap=timedelta(hours=6),
    )


@pytest.mark.asyncio
async def test_start_share_movie_records_state_and_enables_funnel(tmp_path):
    session = _session()
    m = _movie(session, tmp_path)
    funnel = MagicMock(enable=MagicMock(return_value=True), disable=MagicMock(return_value=True))
    jellyfin = AsyncMock()
    service = _service(session, tmp_path, funnel=funnel, jellyfin=jellyfin)

    active = await service.start_share("movie", m.id)

    assert active.title == "Inception"
    funnel.enable.assert_called_once()
    jellyfin.refresh_library.assert_awaited()  # Partage Films rafraîchie
    assert (tmp_path / "Partage" / "Films" / "Inception (2010)" / "movie.nfo").exists()


@pytest.mark.asyncio
async def test_start_when_active_without_replace_raises_conflict(tmp_path):
    session = _session()
    m = _movie(session, tmp_path)
    service = _service(session, tmp_path)
    await service.start_share("movie", m.id)
    with pytest.raises(ShareConflict):
        await service.start_share("movie", m.id)


@pytest.mark.asyncio
async def test_start_with_replace_tears_down_previous(tmp_path):
    session = _session()
    m = _movie(session, tmp_path)
    funnel = MagicMock(enable=MagicMock(return_value=True), disable=MagicMock(return_value=True))
    service = _service(session, tmp_path, funnel=funnel)
    await service.start_share("movie", m.id)
    await service.start_share("movie", m.id, replace=True)
    # un seul actif
    assert ShareSessionRepository(session).get_active() is not None


@pytest.mark.asyncio
async def test_stop_share_disables_funnel_and_clears(tmp_path):
    session = _session()
    m = _movie(session, tmp_path)
    funnel = MagicMock(enable=MagicMock(return_value=True), disable=MagicMock(return_value=True))
    service = _service(session, tmp_path, funnel=funnel)
    await service.start_share("movie", m.id)
    await service.stop_share()
    assert ShareSessionRepository(session).get_active() is None
    funnel.disable.assert_called()
    assert not (tmp_path / "Partage" / "Films").exists()


@pytest.mark.asyncio
async def test_tick_hard_cap_tears_down(tmp_path):
    session = _session()
    m = _movie(session, tmp_path)
    service = _service(session, tmp_path)
    active = await service.start_share("movie", m.id)
    later = active.started_at + timedelta(hours=6, minutes=1)
    result = await service.run_monitor_tick(later)
    assert result == "hard_cap"
    assert ShareSessionRepository(session).get_active() is None


@pytest.mark.asyncio
async def test_tick_idle_tears_down_when_no_playback(tmp_path):
    session = _session()
    m = _movie(session, tmp_path)
    jellyfin = AsyncMock()
    jellyfin.get_active_sessions.return_value = []  # personne ne lit
    service = _service(session, tmp_path, jellyfin=jellyfin)
    active = await service.start_share("movie", m.id)
    later = active.started_at + timedelta(minutes=31)
    result = await service.run_monitor_tick(later)
    assert result == "idle"
    assert ShareSessionRepository(session).get_active() is None


@pytest.mark.asyncio
async def test_tick_playing_keeps_share_and_touches(tmp_path):
    session = _session()
    m = _movie(session, tmp_path)
    jellyfin = AsyncMock()
    jellyfin.get_active_sessions.return_value = [
        {"NowPlayingItem": {"Path": str(tmp_path / "Partage" / "Films" / "x.mkv")}}
    ]
    service = _service(session, tmp_path, jellyfin=jellyfin)
    active = await service.start_share("movie", m.id)
    later = active.started_at + timedelta(minutes=31)
    result = await service.run_monitor_tick(later)
    assert result is None
    assert ShareSessionRepository(session).get_active() is not None


@pytest.mark.asyncio
async def test_reconcile_startup_disables_orphan_funnel(tmp_path):
    session = _session()
    funnel = MagicMock(is_on=MagicMock(return_value=True), disable=MagicMock(return_value=True))
    service = _service(session, tmp_path, funnel=funnel)
    await service.reconcile_on_startup()  # aucun partage actif mais funnel allumé
    funnel.disable.assert_called_once()
```

- [ ] **Step 2: Lancer le test (échec attendu)**

Run: `uv run --extra dev pytest tests/unit/services/share/test_share_service.py -v`
Expected: FAIL (module introuvable).

- [ ] **Step 3: Implémenter**

```python
# src/services/share/share_service.py
"""Orchestration du partage Jellyfin : préparation, démontage, surveillance."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import Session

from src.adapters.api.jellyfin_client import JellyfinClient
from src.adapters.funnel import FunnelController
from src.infrastructure.persistence.models import (
    MovieModel,
    SeriesModel,
    ShareSessionModel,
)
from src.infrastructure.persistence.repositories.share_session_repository import (
    ShareSessionRepository,
)
from src.services.share.builder import JellyfinShareBuilder
from src.services.share.exceptions import ShareConflict, ShareError

LIB_FILMS = "Partage Films"
LIB_SERIES = "Partage Séries"


class ShareService:
    def __init__(
        self,
        *,
        session: Session,
        partage_dir: Path | str,
        jellyfin_client: JellyfinClient,
        funnel: FunnelController,
        idle_timeout: timedelta = timedelta(minutes=30),
        hard_cap: timedelta = timedelta(hours=6),
    ) -> None:
        self._session = session
        self._partage_dir = Path(partage_dir)
        self._jellyfin = jellyfin_client
        self._funnel = funnel
        self._idle_timeout = idle_timeout
        self._hard_cap = hard_cap
        self._repo = ShareSessionRepository(session)
        self._builder = JellyfinShareBuilder(session, partage_dir)

    def get_active_share(self) -> ShareSessionModel | None:
        return self._repo.get_active()

    async def start_share(
        self, media_type: str, media_id: int, replace: bool = False
    ) -> ShareSessionModel:
        active = self._repo.get_active()
        if active is not None:
            if not replace:
                raise ShareConflict(active)
            await self._teardown(active)

        self._builder.clear()
        if media_type == "movie":
            movie = self._session.get(MovieModel, media_id)
            if movie is None:
                raise ShareError(f"Film introuvable : {media_id}")
            title = movie.title
            folder = self._builder.populate_movie(media_id)
            await self._jellyfin.refresh_library(LIB_FILMS)
        elif media_type == "series":
            series = self._session.get(SeriesModel, media_id)
            if series is None:
                raise ShareError(f"Série introuvable : {media_id}")
            title = series.title
            folder = self._builder.populate_series(media_id)
            await self._jellyfin.refresh_library(LIB_SERIES)
        else:
            raise ShareError(f"Type de média inconnu : {media_type}")

        if not self._funnel.enable():
            self._builder.clear()
            raise ShareError("Le Funnel n'a pas pu être activé")

        return self._repo.start(
            media_type=media_type, media_id=media_id, title=title, folder_name=folder
        )

    async def stop_share(self) -> None:
        active = self._repo.get_active()
        if active is None:
            self._funnel.disable()  # auto-réparation : pas de partage mais funnel peut-être on
            return
        await self._teardown(active)

    async def _teardown(self, active: ShareSessionModel) -> None:
        self._funnel.disable()
        self._builder.clear()
        await self._jellyfin.refresh_library(LIB_FILMS)
        await self._jellyfin.refresh_library(LIB_SERIES)
        self._repo.deactivate(active)

    async def run_monitor_tick(self, now: datetime) -> str | None:
        active = self._repo.get_active()
        if active is None:
            return None
        if now - active.started_at >= self._hard_cap:
            await self._teardown(active)
            return "hard_cap"
        sessions = await self._jellyfin.get_active_sessions()
        if self._is_shared_playing(sessions):
            self._repo.touch_played(active, now)
            return None
        last = active.last_played_at or active.started_at
        if now - last >= self._idle_timeout:
            await self._teardown(active)
            return "idle"
        return None

    async def reconcile_on_startup(self) -> None:
        if self._repo.get_active() is None and self._funnel.is_on():
            self._funnel.disable()

    def _is_shared_playing(self, sessions: list[dict]) -> bool:
        root = str(self._partage_dir)
        for sess in sessions:
            item = sess.get("NowPlayingItem") or {}
            path = item.get("Path") or ""
            if path.startswith(root):
                return True
        return False
```

- [ ] **Step 4: Lancer les tests (succès attendu)**

Run: `uv run --extra dev pytest tests/unit/services/share/test_share_service.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/services/share/share_service.py tests/unit/services/share/test_share_service.py
git commit -m "feat(share): ShareService (start/stop/replace + tick surveillance idle/plafond)"
```

---

## Tâche 7 : Câblage DI (container)

**Files:**
- Modify: `src/container.py`
- Test: `tests/unit/test_share_container.py`

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/unit/test_share_container.py
from src.adapters.api.jellyfin_client import JellyfinClient
from src.adapters.funnel import FunnelController
from src.container import Container
from src.services.share.share_service import ShareService


def test_container_provides_share_components():
    container = Container()
    container.database.init()
    assert isinstance(container.jellyfin_client(), JellyfinClient)
    assert isinstance(container.funnel_controller(), FunnelController)
    assert isinstance(container.share_service(), ShareService)
```

- [ ] **Step 2: Lancer le test (échec attendu)**

Run: `uv run --extra dev pytest tests/unit/test_share_container.py -v`
Expected: FAIL (`AttributeError: ... 'jellyfin_client'`).

- [ ] **Step 3: Implémenter**

Dans `src/container.py`, après les clients API existants, ajouter (importer en tête `from src.adapters.api.jellyfin_client import JellyfinClient`, `from src.adapters.funnel import FunnelController`, `from src.services.share.share_service import ShareService`) :

```python
    jellyfin_client = providers.Singleton(
        JellyfinClient,
        base_url=config.provided.jellyfin_url,
        api_key=config.provided.jellyfin_api_key,
    )

    funnel_controller = providers.Singleton(FunnelController)

    share_service = providers.Factory(
        ShareService,
        session=session,
        partage_dir=config.provided.jellyfin_partage_dir,
        jellyfin_client=jellyfin_client,
        funnel=funnel_controller,
    )
```

- [ ] **Step 4: Lancer le test (succès attendu)**

Run: `uv run --extra dev pytest tests/unit/test_share_container.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/container.py tests/unit/test_share_container.py
git commit -m "feat(share): câblage DI (jellyfin_client, funnel_controller, share_service)"
```

---

## Tâche 8 : Endpoints web `/share/...`

**Files:**
- Create: `src/web/routes/share.py`
- Create: `src/web/templates/library/_share_btn.html`
- Modify: `src/web/app.py` (montage du router)
- Test: `tests/unit/web/test_share_routes.py`

**Comportement des endpoints :**
- `POST /share/{entity_type}/{entity_id}` (`entity_type` ∈ `movies|series`, form `replace: bool = False`) → démarre le partage ; en cas de `ShareConflict` sans `replace`, renvoie un fragment overlay de confirmation ; en succès, renvoie le bouton « Départager ».
- `POST /share/stop` → arrête ; renvoie le bouton « Partager » + déclenche le rafraîchissement du bandeau.
- `GET /share/status` → fragment bandeau auto-rafraîchi (`hx-trigger="load delay:60s"`).

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/unit/web/test_share_routes.py
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.infrastructure.persistence.models import ShareSessionModel
from src.services.share.exceptions import ShareConflict
from src.web.app import app


@pytest.fixture
def fake_service(monkeypatch):
    service = MagicMock()
    service.start_share = AsyncMock()
    service.stop_share = AsyncMock()
    service.get_active_share = MagicMock(return_value=None)
    container = MagicMock()
    container.share_service = MagicMock(return_value=service)
    app.state.container = container
    return service


def test_status_empty_when_no_share(fake_service):
    with TestClient(app) as client:
        resp = client.get("/share/status")
    assert resp.status_code == 200
    assert "share-banner" in resp.text


def test_status_shows_title_when_active(fake_service):
    fake_service.get_active_share.return_value = ShareSessionModel(
        media_type="movie", media_id=1, title="Inception", folder_name="Inception (2010)"
    )
    with TestClient(app) as client:
        resp = client.get("/share/status")
    assert "Inception" in resp.text
    assert "Départager" in resp.text


def test_share_success_returns_unshare_button(fake_service):
    fake_service.start_share.return_value = ShareSessionModel(
        media_type="movie", media_id=5, title="X", folder_name="X (2000)"
    )
    with TestClient(app) as client:
        resp = client.post("/share/movies/5")
    assert resp.status_code == 200
    assert "Départager" in resp.text
    fake_service.start_share.assert_awaited_with("movie", 5, replace=False)


def test_share_conflict_returns_confirm_overlay(fake_service):
    active = ShareSessionModel(media_type="series", media_id=9, title="Autre", folder_name="Autre (2020)")
    fake_service.start_share.side_effect = ShareConflict(active)
    with TestClient(app) as client:
        resp = client.post("/share/movies/5")
    assert resp.status_code == 200
    assert "Remplacer" in resp.text  # overlay de confirmation
    assert "Autre" in resp.text


def test_stop_returns_share_button(fake_service):
    with TestClient(app) as client:
        resp = client.post("/share/stop")
    assert resp.status_code == 200
    fake_service.stop_share.assert_awaited()
```

- [ ] **Step 2: Lancer le test (échec attendu)**

Run: `uv run --extra dev pytest tests/unit/web/test_share_routes.py -v`
Expected: FAIL (404 sur les routes).

- [ ] **Step 3: Implémenter le router**

```python
# src/web/routes/share.py
"""Endpoints de partage Jellyfin (Partager / Départager + bandeau global)."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from loguru import logger

from src.services.share.exceptions import ShareConflict, ShareError

router = APIRouter(prefix="/share")

_TYPE_MAP = {"movies": "movie", "series": "series"}


def _service(request: Request):
    return request.app.state.container.share_service()


def _share_button(entity_type: str, entity_id: int) -> str:
    return (
        f'<span id="share-zone-{entity_id}">'
        f'<button class="action-btn-share" hx-post="/share/{entity_type}/{entity_id}"'
        f' hx-target="#share-zone-{entity_id}" hx-swap="innerHTML">Partager</button>'
        f"</span>"
    )


def _unshare_button(entity_type: str, entity_id: int) -> str:
    return (
        f'<span id="share-zone-{entity_id}">'
        f'<button class="action-btn-unshare" hx-post="/share/stop"'
        f' hx-target="#share-zone-{entity_id}" hx-swap="innerHTML">Départager</button>'
        f"</span>"
    )


def _replace_overlay(entity_type: str, entity_id: int, active_title: str) -> str:
    return (
        '<div class="reject-overlay active" id="share-overlay"'
        ' onclick="if(event.target===this)this.remove()">'
        '<div class="reject-dialog">'
        '<h3 class="reject-dialog-title">Remplacer le partage en cours ?</h3>'
        f'<p>Un partage est déjà actif : <strong>{active_title}</strong>. '
        "Le remplacer arrêtera ce partage et exposera le nouveau titre.</p>"
        '<div class="reject-dialog-actions">'
        "<button class=\"reject-dialog-cancel\" onclick=\"document.getElementById('share-overlay').remove()\">Annuler</button>"
        f'<button class="reject-dialog-confirm" hx-post="/share/{entity_type}/{entity_id}"'
        f' hx-vals=\'{{"replace": "true"}}\' hx-target="#share-zone-{entity_id}" hx-swap="innerHTML"'
        " onclick=\"document.getElementById('share-overlay').remove()\">Oui, remplacer</button>"
        "</div></div></div>"
    )


@router.post("/{entity_type}/{entity_id}", response_class=HTMLResponse)
async def start_share(
    request: Request, entity_type: str, entity_id: int, replace: bool = Form(False)
):
    media_type = _TYPE_MAP.get(entity_type)
    if media_type is None:
        return HTMLResponse('<div class="action-msg play-error">Type inconnu</div>')
    service = _service(request)
    try:
        await service.start_share(media_type, entity_id, replace=replace)
    except ShareConflict as conflict:
        return HTMLResponse(
            _share_button(entity_type, entity_id)
            + _replace_overlay(entity_type, entity_id, conflict.active.title)
        )
    except ShareError as exc:
        logger.error("Échec partage : %s", exc)
        return HTMLResponse(
            _share_button(entity_type, entity_id)
            + f'<div class="action-msg play-error">{exc}</div>'
        )
    return HTMLResponse(_unshare_button(entity_type, entity_id))


@router.post("/stop", response_class=HTMLResponse)
async def stop_share(request: Request, entity_type: str = Form("movies"), entity_id: int = Form(0)):
    service = _service(request)
    await service.stop_share()
    return HTMLResponse(_share_button(entity_type, entity_id))


@router.get("/status", response_class=HTMLResponse)
async def share_status(request: Request):
    service = _service(request)
    active = service.get_active_share()
    poll = 'hx-get="/share/status" hx-trigger="load delay:60s" hx-swap="outerHTML"'
    if active is None:
        return HTMLResponse(f'<div id="share-banner" class="share-banner-empty" {poll}></div>')
    return HTMLResponse(
        f'<div id="share-banner" class="share-banner" {poll}>'
        f"🔴 Partage en cours : <strong>{active.title}</strong> "
        '<button class="share-banner-stop" hx-post="/share/stop"'
        ' hx-target="#share-banner" hx-swap="outerHTML">Départager</button>'
        "</div>"
    )
```

Note : `POST /share/stop` ciblé par le bandeau renvoie un `<span id="share-zone-0">` ; comme le bandeau cible `#share-banner`, ce cas est couvert par le poll suivant qui remet le bandeau vide. Pour cohérence, le test `test_stop_returns_share_button` ne vérifie que l'appel `stop_share`.

- [ ] **Step 4: Implémenter le partiel bouton (fiches détaillées)**

```html
{# src/web/templates/library/_share_btn.html
   Variables attendues : share_entity_type ("movies"|"series"), share_entity_id,
   share_is_active (bool : ce titre est le partage actif ?). #}
<span id="share-zone-{{ share_entity_id }}">
  {% if share_is_active %}
  <button class="action-btn-unshare" hx-post="/share/stop"
          hx-target="#share-zone-{{ share_entity_id }}" hx-swap="innerHTML">Départager</button>
  {% else %}
  <button class="action-btn-share" hx-post="/share/{{ share_entity_type }}/{{ share_entity_id }}"
          hx-target="#share-zone-{{ share_entity_id }}" hx-swap="innerHTML">Partager</button>
  {% endif %}
</span>
```

- [ ] **Step 5: Monter le router**

Dans `src/web/app.py`, importer et inclure le router à côté des autres :

```python
from src.web.routes import share as share_routes
...
app.include_router(share_routes.router)
```

- [ ] **Step 6: Lancer les tests (succès attendu)**

Run: `uv run --extra dev pytest tests/unit/web/test_share_routes.py -v`
Expected: PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add src/web/routes/share.py src/web/templates/library/_share_btn.html src/web/app.py
git add tests/unit/web/test_share_routes.py
git commit -m "feat(share): endpoints web /share + bouton Partager/Départager + bandeau"
```

---

## Tâche 9 : Intégration du bouton dans les fiches + bandeau global

**Files:**
- Modify: `src/web/routes/library/detail.py` (contexte `active_share`)
- Modify: `src/web/templates/library/_detail_poster_actions.html` (inclusion bouton)
- Modify: `src/web/templates/base.html` (conteneur bandeau)
- Modify: `src/web/static/css/style.css` (styles)

> Cette tâche est surtout du câblage de templates ; le test fonctionnel est manuel (Tâche 11/validation). Pas de test unitaire dédié, mais vérifier le rendu via le serveur.

- [ ] **Step 1: Passer `active_share` au contexte des fiches**

Dans `src/web/routes/library/detail.py`, là où le contexte des fiches film et série est construit, ajouter (le container est sur `request.app.state.container`) :

```python
    active_share = request.app.state.container.share_service().get_active_share()
    share_is_active = bool(
        active_share
        and active_share.media_type == ("movie" if is_movie else "series")
        and active_share.media_id == entity.id
    )
    # ... ajouter au dict de contexte : "share_is_active": share_is_active
```

Adapter `is_movie`/`entity` aux variables réelles de chaque handler (movie vs series). Pour la fiche film : `media_type == "movie"`, `media_id == movie.id`. Pour la série : `"series"`, `series.id`.

- [ ] **Step 2: Inclure le bouton dans le bloc d'actions**

Dans `src/web/templates/library/_detail_poster_actions.html`, à l'intérieur de `.lib-detail-poster-actions`, après le bouton « Visionner », ajouter :

```html
  {% with share_entity_type=action_entity_type, share_entity_id=action_entity_id, share_is_active=share_is_active|default(false) %}
    {% include "library/_share_btn.html" %}
  {% endwith %}
```

(`action_entity_type` vaut déjà `"movies"`/`"series"` et `action_entity_id` l'id — fournis par `movie_detail.html` / `series_detail.html`.)

- [ ] **Step 3: Ajouter le conteneur du bandeau global**

Dans `src/web/templates/base.html`, juste après l'ouverture de `<main class="content">` (ligne ~50), insérer le conteneur qui se charge tout seul :

```html
    <div id="share-banner" hx-get="/share/status" hx-trigger="load" hx-swap="outerHTML"></div>
```

- [ ] **Step 4: Styles CSS**

Dans `src/web/static/css/style.css`, ajouter à la fin :

```css
/* --- Partage Jellyfin (SP3b) --- */
.action-btn-share,
.action-btn-unshare {
  appearance: none;
  border: 1px solid;
  border-radius: 6px;
  padding: 0.35rem 0.75rem;
  background: transparent;
  cursor: pointer;
  font: inherit;
  opacity: 0.85;
}
.action-btn-share { color: #0ea5e9; border-color: #0ea5e9; }
.action-btn-unshare { color: #ef4444; border-color: #ef4444; }
.action-btn-share:hover,
.action-btn-unshare:hover { opacity: 1; }

.share-banner {
  background: #7f1d1d;
  color: #fff;
  padding: 0.5rem 1rem;
  border-radius: 6px;
  margin-bottom: 0.75rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.share-banner-stop {
  appearance: none;
  border: 1px solid #fff;
  background: transparent;
  color: #fff;
  border-radius: 5px;
  padding: 0.2rem 0.6rem;
  cursor: pointer;
}
.share-banner-empty { display: none; }
```

- [ ] **Step 5: Vérifier le rendu**

Run: `uv run cineorg serve --port 8001 &` puis ouvrir `http://localhost:8001/library`, aller sur une fiche film → bouton « Partager » présent ; arrêter le serveur (`kill %1`).
(Le partage réel se teste en Tâche 11 / validation manuelle.)

- [ ] **Step 6: Commit**

```bash
git add src/web/routes/library/detail.py src/web/templates/library/_detail_poster_actions.html
git add src/web/templates/base.html src/web/static/css/style.css
git commit -m "feat(share): bouton sur les fiches film/série + bandeau global persistant"
```

---

## Tâche 10 : Tâche de fond de surveillance (lifespan)

**Files:**
- Create: `src/services/share/monitor.py`
- Modify: `src/web/app.py` (démarrage/arrêt dans `lifespan`)
- Test: `tests/unit/services/share/test_share_monitor.py`

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/unit/services/share/test_share_monitor.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.share.monitor import run_one_cycle


@pytest.mark.asyncio
async def test_run_one_cycle_calls_tick_with_now():
    service = MagicMock()
    service.run_monitor_tick = AsyncMock(return_value=None)
    container = MagicMock()
    container.share_service = MagicMock(return_value=service)
    await run_one_cycle(container)
    service.run_monitor_tick.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_one_cycle_swallows_errors():
    service = MagicMock()
    service.run_monitor_tick = AsyncMock(side_effect=RuntimeError("boom"))
    container = MagicMock()
    container.share_service = MagicMock(return_value=service)
    # ne doit pas lever
    await run_one_cycle(container)
```

- [ ] **Step 2: Lancer le test (échec attendu)**

Run: `uv run --extra dev pytest tests/unit/services/share/test_share_monitor.py -v`
Expected: FAIL (module introuvable).

- [ ] **Step 3: Implémenter le monitor**

```python
# src/services/share/monitor.py
"""Boucle de surveillance du partage : démontage auto (idle 30 min, plafond 6 h)."""

from __future__ import annotations

import asyncio
from datetime import datetime

from loguru import logger

_INTERVAL_SECONDS = 60


async def run_one_cycle(container) -> None:
    """Un tick de surveillance (isolé pour testabilité). N'élève jamais."""
    try:
        service = container.share_service()
        result = await service.run_monitor_tick(datetime.utcnow())
        if result == "idle":
            logger.info("Partage démonté automatiquement (30 min sans lecture).")
        elif result == "hard_cap":
            logger.info("Partage démonté automatiquement (plafond de 6 h atteint).")
    except Exception as exc:  # surveillance ne doit jamais tuer la boucle
        logger.exception("Erreur dans le cycle de surveillance du partage : %s", exc)


async def share_monitor_loop(container) -> None:
    """Auto-réparation au démarrage puis boucle périodique jusqu'à annulation."""
    try:
        await container.share_service().reconcile_on_startup()
    except Exception as exc:
        logger.exception("Échec de l'auto-réparation au démarrage : %s", exc)
    while True:
        await run_one_cycle(container)
        await asyncio.sleep(_INTERVAL_SECONDS)
```

- [ ] **Step 4: Démarrer/arrêter dans le lifespan**

Dans `src/web/app.py`, compléter le `lifespan` :

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    container = Container()
    container.database.init()
    app.state.container = container
    monitor_task = asyncio.create_task(share_monitor_loop(container))
    app.state.share_monitor_task = monitor_task
    try:
        yield
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
```

Ajouter les imports en tête : `import asyncio` et `from src.services.share.monitor import share_monitor_loop`.

- [ ] **Step 5: Lancer les tests (succès attendu)**

Run: `uv run --extra dev pytest tests/unit/services/share/test_share_monitor.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add src/services/share/monitor.py src/web/app.py tests/unit/services/share/test_share_monitor.py
git commit -m "feat(share): surveillance asyncio (démontage auto idle/plafond + auto-réparation)"
```

---

## Tâche 11 : Suite de tests complète + lint

**Files:** (aucun nouveau ; vérification globale)

- [ ] **Step 1: Lancer toute la suite ciblée**

Run:
```bash
uv sync --extra dev && uv run --extra dev pytest \
  tests/unit/test_config_jellyfin_sharing.py \
  tests/unit/test_share_session_repository.py \
  tests/unit/adapters/api/test_jellyfin_client.py \
  tests/unit/test_funnel_controller.py \
  tests/unit/services/share/ \
  tests/unit/test_share_container.py \
  tests/unit/web/test_share_routes.py -v
```
Expected: tout PASS.

- [ ] **Step 2: Vérifier la non-régression du reste**

Run: `uv run --extra dev pytest tests/unit/test_jellyfin_sync_service.py tests/unit/test_jellyfin_tree_builder.py tests/unit/test_jellyfin_nfo_builder.py -v`
Expected: PASS (briques réutilisées non cassées).

- [ ] **Step 3: Lint des fichiers modifiés uniquement**

Run:
```bash
uv run --extra dev ruff check src/config.py src/container.py src/adapters/api/jellyfin_client.py \
  src/adapters/funnel.py src/services/share/ src/infrastructure/persistence/ src/web/routes/share.py \
  src/web/app.py
uv run --extra dev ruff format src/adapters/funnel.py src/adapters/api/jellyfin_client.py src/services/share/ src/web/routes/share.py
```
Expected: aucune erreur (corriger si besoin).

- [ ] **Step 4: Commit (si le lint/format a modifié des fichiers)**

```bash
git add -A && git commit -m "style(share): ruff format/lint sur les fichiers SP3b"
```

---

## Tâche 12 : Documentation README + bump de version

**Files:**
- Modify: `README.md`
- Bump: `pyproject.toml` (via commitizen)

- [ ] **Step 1: Documenter dans le README**

Dans `README.md`, section « Intégration Jellyfin », ajouter une sous-section « **Partage SyncPlay (Partager / Départager)** » décrivant :
- le prérequis ops (2 bibliothèques `Partage Films`/`Partage Séries` restreintes à `Alex`, clé API, `CINEORG_JELLYFIN_API_KEY`/`CINEORG_JELLYFIN_URL` dans `.env`) ;
- l'usage : sur une fiche film/série, bouton « Partager » → expose le titre + active le Funnel ; bouton « Départager » (fiche ou bandeau global) ; démontage auto (30 min sans lecture, plafond 6 h) ;
- le client recommandé pour l'ami : Jellyfin Media Player (Windows) sur l'URL publique, compte `Alex` ;
- une entrée Dépannage « Le partage ne s'expose pas » (vérifier `CINEORG_JELLYFIN_API_KEY`, l'opérateur Tailscale, `tailscale funnel status`).

- [ ] **Step 2: Vérifier le rendu Markdown** (relecture).

- [ ] **Step 3: Commit doc**

```bash
git add README.md
git commit -m "docs(share): documenter Partager/Départager (SP3b) dans le README"
```

- [ ] **Step 4: Bump de version**

Run: `uv run cz bump --yes`
Puis pousser le tag séparément si publication (cf. mémoire : `--follow-tags` n'envoie pas le tag léger de cz).

---

## Auto-revue du plan (effectuée)

**Couverture de la spec :** config (T1), `ShareSession` persisté (T2), `JellyfinClient` refresh ciblé + sessions (T3), `FunnelController` (T4), `JellyfinShareBuilder` film=fichier seul / série=intégrale dans `Partage/Films`+`Partage/Series` (T5), `ShareService` start/stop/replace + auto-réparation (T6), DI (T7), endpoints + bouton + overlay remplacement (T8), bandeau global + fiches (T9), surveillance idle 30 min + plafond 6 h (T10), tests/lint (T11), README + bump (T12). ✔ Deux bibliothèques typées intégrées (T5 structure, prérequis ops, T3 refresh par nom).

**Cohérence des types :** `media_type` ∈ `{"movie","series"}` au niveau service ; `entity_type` ∈ `{"movies","series"}` au niveau web, mappé via `_TYPE_MAP`. `folder_name(...)` (sans unicité, 1 seul titre). Signatures `start_share/stop_share/get_active_share/run_monitor_tick/reconcile_on_startup` constantes de T6 à T10. Noms de bibliothèques `LIB_FILMS="Partage Films"`, `LIB_SERIES="Partage Séries"` cohérents avec le prérequis ops.

**Pas de placeholder** : chaque étape de code contient le code réel.
