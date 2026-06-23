# Surveillance de la complétude des séries — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Détecter automatiquement les séries incomplètes (épisodes/saisons déjà diffusés mais absents) en confrontant la DB locale à TVDB, exposer un badge + un filtre web, et justifier le statut sur la fiche série.

**Architecture:** Un service `CompletenessChecker` calcule, pour une série à `tvdb_id`, l'écart entre épisodes **détenus** (ligne `EpisodeModel` avec fichier, hors `is_extra`) et épisodes **attendus déjà diffusés** (TVDB, `season ≥ 1`, `episode ≥ 1`, `air_date ≤ aujourd'hui`). Le verdict est persisté dans trois nouvelles colonnes de `SeriesModel`. Un déclenchement manuel (commande CLI + bouton page Maintenance avec SSE) peuple ces colonnes ; un filtre et un badge web les exploitent.

**Tech Stack:** Python 3.11+, SQLModel/SQLite, httpx (TVDB), Typer + Rich (CLI), FastAPI + Jinja2 + SSE (web). Tests : pytest, mocks `MagicMock`/objets stubs.

**Conventions du projet (rappel) :**
- Toujours `uv sync --extra dev && uv run pytest ...` (pytest est dans l'extra `dev`).
- Lint scopé aux fichiers modifiés : `uv run --extra dev ruff check <fichiers>` et `ruff format <fichiers>`.
- Commits conventionnels en français. Terminer chaque message de commit par :
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```
- Branche de travail : `feat/series-completeness` (déjà créée, le spec y est commité).

**Définitions de référence (issues du spec) :**
- **Attendu** : épisode TVDB tel que `season_number ≥ 1` ET `episode_number ≥ 1` ET `air_date` non nulle ET `air_date ≤ aujourd'hui`.
- **Détenu** : `EpisodeModel` (même série/saison/épisode) avec `file_path` non vide ET `is_extra = False`.
- **Manquant** : attendu mais non détenu.
- **Verdict** : `incomplete` si ≥ 1 manquant ; `complete` sinon ; `null` si pas de `tvdb_id`.
- **Saison entièrement absente** : saison dont aucun épisode attendu n'est détenu.

---

## Structure des fichiers

**Créés :**
- `src/services/completeness/__init__.py` — exports du package.
- `src/services/completeness/dataclasses.py` — `MissingEpisode`, `CompletenessResult`.
- `src/services/completeness/completeness_checker.py` — `CompletenessChecker.compute(...)` + `check_series_model(...)` + `_parse_air_date(...)`.
- `src/adapters/cli/commands/completeness_command.py` — commande `check-completeness`.
- `tests/unit/test_completeness_checker.py` — tests du calcul.
- `tests/unit/test_completeness_persistence.py` — tests colonnes DB + `check_series_model`.
- `tests/unit/test_tvdb_get_all_episodes.py` — test du fetch TVDB multi-saisons.
- `tests/unit/test_browse_incomplete_filter.py` — test du filtre web.

**Modifiés :**
- `src/infrastructure/persistence/models.py` — 3 colonnes sur `SeriesModel`.
- `src/infrastructure/persistence/database.py` — migration 13.
- `src/adapters/api/tvdb_client.py` — méthode `get_all_episodes(series_id)`.
- `src/main.py` — enregistrement de `check-completeness`.
- `src/adapters/cli/commands/__init__.py` — export de la commande.
- `src/web/routes/maintenance.py` — endpoint SSE `/maintenance/completeness`.
- `src/web/routes/library/browse.py` — paramètre + filtre `incomplete_series`.
- `src/web/routes/library/detail.py` — contexte complétude pour la fiche.
- `src/web/templates/maintenance/index.html` — bouton « Vérifier la complétude ».
- `src/web/templates/library/_filters.html` — case à cocher + tag actif.
- `src/web/templates/library/_grid.html` — badge « Incomplet » sur les cartes série.
- `src/web/templates/library/series_detail.html` — badge + bloc justification.
- `src/web/static/css/style.css` — styles du badge « Incomplet ».
- `README.md` — documentation de la fonctionnalité.

---

## Task 1 : Colonnes de complétude sur `SeriesModel` + migration DB

**Files:**
- Modify: `src/infrastructure/persistence/models.py:155` (après `preserve_overrides`)
- Modify: `src/infrastructure/persistence/database.py:371` (après migration 12, avant la fin du `with`)
- Test: `tests/unit/test_completeness_persistence.py`

- [ ] **Step 1 : Écrire le test de migration/colonnes (échoue)**

Créer `tests/unit/test_completeness_persistence.py` :

```python
"""Tests des colonnes de complétude sur SeriesModel et de leur persistance."""

from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine, select

from src.infrastructure.persistence.models import SeriesModel


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    return engine


def test_series_model_has_completeness_columns():
    """Les trois colonnes de complétude existent et sont persistées."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="Test", tvdb_id=123)
        series.completeness_status = "incomplete"
        series.completeness_checked_at = datetime(2026, 6, 23, 12, 0, 0)
        series.completeness_missing_json = '{"missing_seasons": [2]}'
        session.add(series)
        session.commit()
        session.refresh(series)

    with Session(engine) as session:
        loaded = session.exec(
            select(SeriesModel).where(SeriesModel.title == "Test")
        ).first()
        assert loaded.completeness_status == "incomplete"
        assert loaded.completeness_checked_at == datetime(2026, 6, 23, 12, 0, 0)
        assert loaded.completeness_missing_json == '{"missing_seasons": [2]}'


def test_completeness_status_defaults_to_none():
    """Une série jamais vérifiée a completeness_status = None."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="Neuve")
        session.add(series)
        session.commit()
        session.refresh(series)
        assert series.completeness_status is None
        assert series.completeness_checked_at is None
        assert series.completeness_missing_json is None
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `uv sync --extra dev && uv run pytest tests/unit/test_completeness_persistence.py -v`
Expected: FAIL (`AttributeError`/`TypeError` : `completeness_status` inconnu de `SeriesModel`).

- [ ] **Step 3 : Ajouter les colonnes au modèle**

Dans `src/infrastructure/persistence/models.py`, après la ligne `preserve_overrides: bool = Field(default=False, index=True)` (ligne 155), insérer :

```python
    # Complétude (phase série-completeness) : verdict issu de la confrontation
    # avec TVDB. None = jamais vérifié ou non vérifiable (pas de tvdb_id).
    completeness_status: str | None = Field(default=None, index=True)
    completeness_checked_at: datetime | None = None
    completeness_missing_json: str | None = None
```

- [ ] **Step 4 : Ajouter la migration 13**

Dans `src/infrastructure/persistence/database.py`, juste avant la fin du bloc `with engine.connect() as conn:` (après la migration 12, ligne ~371), insérer :

```python
        # Migration 13: Colonnes de complétude sur series (phase série-completeness)
        result = conn.execute(text("PRAGMA table_info(series)"))
        series_columns = [row[1] for row in result.fetchall()]

        if "completeness_status" not in series_columns:
            conn.execute(
                text("ALTER TABLE series ADD COLUMN completeness_status VARCHAR")
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_series_completeness_status "
                    "ON series(completeness_status)"
                )
            )
            conn.commit()
        if "completeness_checked_at" not in series_columns:
            conn.execute(
                text("ALTER TABLE series ADD COLUMN completeness_checked_at DATETIME")
            )
            conn.commit()
        if "completeness_missing_json" not in series_columns:
            conn.execute(
                text("ALTER TABLE series ADD COLUMN completeness_missing_json VARCHAR")
            )
            conn.commit()
```

- [ ] **Step 5 : Lancer le test, vérifier le succès**

Run: `uv run pytest tests/unit/test_completeness_persistence.py -v`
Expected: PASS (les deux tests passent).

- [ ] **Step 6 : Lint + commit**

```bash
uv run --extra dev ruff format src/infrastructure/persistence/models.py src/infrastructure/persistence/database.py tests/unit/test_completeness_persistence.py
uv run --extra dev ruff check src/infrastructure/persistence/models.py src/infrastructure/persistence/database.py tests/unit/test_completeness_persistence.py
git add src/infrastructure/persistence/models.py src/infrastructure/persistence/database.py tests/unit/test_completeness_persistence.py
git commit -m "feat(completeness): colonnes de complétude sur SeriesModel + migration

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2 : `TVDBClient.get_all_episodes(series_id)`

Récupère tous les épisodes (saisons ≥ 1) d'une série avec leur date de diffusion, en réutilisant le fetch brut paginé existant. Boucle sur les saisons à partir de 1 et s'arrête à la première saison vide (les saisons TVDB sont numérotées de façon contiguë).

**Files:**
- Modify: `src/adapters/api/tvdb_client.py` (ajouter la méthode après `get_season_episode_count`, vers la ligne 535)
- Test: `tests/unit/test_tvdb_get_all_episodes.py`

- [ ] **Step 1 : Écrire le test (échoue)**

Créer `tests/unit/test_tvdb_get_all_episodes.py` :

```python
"""Test de TVDBClient.get_all_episodes (agrégation multi-saisons)."""

import pytest

from src.adapters.api.tvdb_client import TVDBClient


@pytest.mark.asyncio
async def test_get_all_episodes_aggregates_seasons(monkeypatch):
    """Agrège les épisodes de toutes les saisons jusqu'à la première vide."""
    client = TVDBClient(api_key="x", cache=None)

    # Stub des dépendances réseau bas niveau.
    async def fake_ensure_token():
        return None

    async def fake_get_client():
        return object()

    # Saison 1 : 2 épisodes ; saison 2 : 1 épisode ; saison 3 : vide → stop.
    seasons = {
        1: [
            {
                "id": 11,
                "episodeName": "Pilote",
                "airedSeason": 1,
                "airedEpisodeNumber": 1,
                "firstAired": "2019-01-01",
                "overview": "o1",
            },
            {
                "id": 12,
                "episodeName": "Deux",
                "airedSeason": 1,
                "airedEpisodeNumber": 2,
                "firstAired": "2019-01-08",
                "overview": "o2",
            },
        ],
        2: [
            {
                "id": 21,
                "episodeName": "S2E1",
                "airedSeason": 2,
                "airedEpisodeNumber": 1,
                "firstAired": "2020-01-01",
                "overview": "o3",
            },
        ],
    }

    async def fake_raw(self, http_client, series_id, season, language):
        return seasons.get(season, [])

    monkeypatch.setattr(client, "_ensure_token", fake_ensure_token)
    monkeypatch.setattr(client, "_get_client", fake_get_client)
    monkeypatch.setattr(
        TVDBClient, "_fetch_all_season_episodes_raw", fake_raw, raising=True
    )

    episodes = await client.get_all_episodes("999")

    assert len(episodes) == 3
    keys = {(e.season_number, e.episode_number) for e in episodes}
    assert keys == {(1, 1), (1, 2), (2, 1)}
    by_key = {(e.season_number, e.episode_number): e for e in episodes}
    assert by_key[(1, 1)].air_date == "2019-01-01"
    assert by_key[(1, 1)].title == "Pilote"


@pytest.mark.asyncio
async def test_get_all_episodes_skips_none_episode_number(monkeypatch):
    """Un épisode sans numéro est ignoré."""
    client = TVDBClient(api_key="x", cache=None)

    async def fake_ensure_token():
        return None

    async def fake_get_client():
        return object()

    async def fake_raw(self, http_client, series_id, season, language):
        if season == 1:
            return [
                {"id": 1, "airedSeason": 1, "airedEpisodeNumber": None},
                {
                    "id": 2,
                    "airedSeason": 1,
                    "airedEpisodeNumber": 1,
                    "firstAired": "2019-01-01",
                    "episodeName": "ok",
                },
            ]
        return []

    monkeypatch.setattr(client, "_ensure_token", fake_ensure_token)
    monkeypatch.setattr(client, "_get_client", fake_get_client)
    monkeypatch.setattr(
        TVDBClient, "_fetch_all_season_episodes_raw", fake_raw, raising=True
    )

    episodes = await client.get_all_episodes("1")
    assert len(episodes) == 1
    assert episodes[0].episode_number == 1
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `uv run pytest tests/unit/test_tvdb_get_all_episodes.py -v`
Expected: FAIL (`AttributeError: 'TVDBClient' object has no attribute 'get_all_episodes'`).

- [ ] **Step 3 : Implémenter la méthode**

Dans `src/adapters/api/tvdb_client.py`, après la méthode `get_season_episode_count` (juste avant la propriété `source`, vers la ligne 536), insérer :

```python
    async def get_all_episodes(self, series_id: str) -> list[EpisodeDetails]:
        """
        Recupere tous les episodes d'une serie (saisons >= 1).

        Boucle sur les saisons a partir de 1 et s'arrete a la premiere
        saison vide (les saisons TVDB sont numerotees de facon contigue).
        Utilise le fetch brut FR (titres en francais, vides tolere).

        Args:
            series_id: ID TVDB de la serie

        Returns:
            Liste d'EpisodeDetails (season_number, episode_number, air_date, title)
        """
        await self._ensure_token()
        client = await self._get_client()

        episodes: list[EpisodeDetails] = []
        season = 1
        while True:
            raw = await self._fetch_all_season_episodes_raw(
                client, series_id, season, language="fr"
            )
            if not raw:
                break
            for ep_data in raw:
                ep_num = ep_data.get("airedEpisodeNumber")
                if ep_num is None:
                    continue
                episodes.append(
                    EpisodeDetails(
                        id=str(ep_data.get("id", "")),
                        title=ep_data.get("episodeName", "") or "",
                        season_number=ep_data.get("airedSeason", season),
                        episode_number=ep_num,
                        overview=ep_data.get("overview"),
                        air_date=ep_data.get("firstAired"),
                    )
                )
            season += 1

        return episodes
```

Vérifier que `EpisodeDetails` est bien importé en tête de `tvdb_client.py` (il l'est déjà — utilisé par `get_episode_details`).

- [ ] **Step 4 : Lancer le test, vérifier le succès**

Run: `uv run pytest tests/unit/test_tvdb_get_all_episodes.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5 : Lint + commit**

```bash
uv run --extra dev ruff format src/adapters/api/tvdb_client.py tests/unit/test_tvdb_get_all_episodes.py
uv run --extra dev ruff check src/adapters/api/tvdb_client.py tests/unit/test_tvdb_get_all_episodes.py
git add src/adapters/api/tvdb_client.py tests/unit/test_tvdb_get_all_episodes.py
git commit -m "feat(completeness): TVDBClient.get_all_episodes (agrégation multi-saisons)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3 : `CompletenessChecker.compute` + dataclasses

Le cœur du calcul, sans accès DB : prend un `tvdb_id`, l'ensemble des épisodes détenus et la date du jour ; renvoie le verdict. Testable avec un client TVDB stub.

**Files:**
- Create: `src/services/completeness/__init__.py`
- Create: `src/services/completeness/dataclasses.py`
- Create: `src/services/completeness/completeness_checker.py`
- Test: `tests/unit/test_completeness_checker.py`

- [ ] **Step 1 : Écrire les tests (échouent)**

Créer `tests/unit/test_completeness_checker.py` :

```python
"""Tests du calcul de complétude (CompletenessChecker.compute)."""

from datetime import date

import pytest

from src.core.ports.api_clients import EpisodeDetails
from src.services.completeness.completeness_checker import CompletenessChecker


class _StubTVDB:
    """Client TVDB minimal : renvoie une liste figée d'épisodes."""

    def __init__(self, episodes):
        self._episodes = episodes

    async def get_all_episodes(self, series_id):
        return self._episodes


def _ep(season, episode, air_date, title="t"):
    return EpisodeDetails(
        id=f"{season}-{episode}",
        title=title,
        season_number=season,
        episode_number=episode,
        overview=None,
        air_date=air_date,
    )


TODAY = date(2026, 6, 23)


@pytest.mark.asyncio
async def test_complete_when_all_aired_owned():
    """Aucun manquant → complete."""
    tvdb = _StubTVDB([_ep(1, 1, "2019-01-01"), _ep(1, 2, "2019-01-08")])
    checker = CompletenessChecker(tvdb)
    result = await checker.compute("1", owned={(1, 1), (1, 2)}, today=TODAY)
    assert result.status == "complete"
    assert result.missing_seasons == []
    assert result.missing_episodes == []
    assert result.expected_aired == 2
    assert result.owned == 2


@pytest.mark.asyncio
async def test_internal_hole_is_incomplete():
    """Un épisode du milieu manquant → incomplete + détail."""
    tvdb = _StubTVDB(
        [_ep(1, 1, "2019-01-01"), _ep(1, 2, "2019-01-08"), _ep(1, 3, "2019-01-15")]
    )
    checker = CompletenessChecker(tvdb)
    result = await checker.compute("1", owned={(1, 1), (1, 3)}, today=TODAY)
    assert result.status == "incomplete"
    assert result.missing_seasons == []
    assert [(m.season, m.episode) for m in result.missing_episodes] == [(1, 2)]


@pytest.mark.asyncio
async def test_interrupted_tail_is_incomplete():
    """Téléchargement arrêté : épisodes diffusés suivants manquants."""
    tvdb = _StubTVDB(
        [_ep(1, 1, "2019-01-01"), _ep(1, 2, "2019-01-08"), _ep(1, 3, "2019-01-15")]
    )
    checker = CompletenessChecker(tvdb)
    result = await checker.compute("1", owned={(1, 1)}, today=TODAY)
    assert result.status == "incomplete"
    assert [(m.season, m.episode) for m in result.missing_episodes] == [(1, 2), (1, 3)]


@pytest.mark.asyncio
async def test_future_episodes_not_counted():
    """Épisode à date future ou sans date → non compté."""
    tvdb = _StubTVDB(
        [_ep(1, 1, "2019-01-01"), _ep(1, 2, "2099-01-01"), _ep(1, 3, None)]
    )
    checker = CompletenessChecker(tvdb)
    result = await checker.compute("1", owned={(1, 1)}, today=TODAY)
    assert result.status == "complete"
    assert result.expected_aired == 1


@pytest.mark.asyncio
async def test_season_zero_and_episode_zero_excluded():
    """Saison 0 et épisode 0 (SxxE00) exclus de l'attendu."""
    tvdb = _StubTVDB(
        [_ep(0, 1, "2018-01-01"), _ep(1, 0, "2018-12-01"), _ep(1, 1, "2019-01-01")]
    )
    checker = CompletenessChecker(tvdb)
    result = await checker.compute("1", owned=set(), today=TODAY)
    # Seul (1, 1) est attendu → manquant.
    assert result.expected_aired == 1
    assert result.status == "incomplete"
    assert [(m.season, m.episode) for m in result.missing_episodes] == [(1, 1)]


@pytest.mark.asyncio
async def test_fully_missing_season_listed_separately():
    """Une saison sans aucun épisode détenu apparaît dans missing_seasons."""
    tvdb = _StubTVDB(
        [
            _ep(1, 1, "2019-01-01"),
            _ep(2, 1, "2020-01-01"),
            _ep(2, 2, "2020-01-08"),
        ]
    )
    checker = CompletenessChecker(tvdb)
    result = await checker.compute("1", owned={(1, 1)}, today=TODAY)
    assert result.status == "incomplete"
    assert result.missing_seasons == [2]
    # Saison 2 entièrement absente → pas listée épisode par épisode.
    assert result.missing_episodes == []


@pytest.mark.asyncio
async def test_no_aired_episodes_is_complete():
    """Série sans épisode diffusé (toutes dates futures) → complete."""
    tvdb = _StubTVDB([_ep(1, 1, "2099-01-01")])
    checker = CompletenessChecker(tvdb)
    result = await checker.compute("1", owned=set(), today=TODAY)
    assert result.status == "complete"
    assert result.expected_aired == 0
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run: `uv run pytest tests/unit/test_completeness_checker.py -v`
Expected: FAIL (`ModuleNotFoundError: src.services.completeness`).

- [ ] **Step 3 : Créer les dataclasses**

Créer `src/services/completeness/__init__.py` :

```python
"""Service de surveillance de la complétude des séries TV."""

from src.services.completeness.completeness_checker import (
    CompletenessChecker,
    check_series_model,
)
from src.services.completeness.dataclasses import (
    CompletenessResult,
    MissingEpisode,
)

__all__ = [
    "CompletenessChecker",
    "CompletenessResult",
    "MissingEpisode",
    "check_series_model",
]
```

Créer `src/services/completeness/dataclasses.py` :

```python
"""Structures de données pour le calcul de complétude des séries."""

from dataclasses import dataclass, field


@dataclass
class MissingEpisode:
    """Un épisode attendu (déjà diffusé) mais absent de la vidéothèque."""

    season: int
    episode: int
    air_date: str | None
    title: str


@dataclass
class CompletenessResult:
    """Verdict de complétude d'une série."""

    status: str  # "complete" | "incomplete"
    missing_seasons: list[int] = field(default_factory=list)
    missing_episodes: list[MissingEpisode] = field(default_factory=list)
    expected_aired: int = 0
    owned: int = 0
    source: str = "tvdb"
```

- [ ] **Step 4 : Implémenter le checker**

Créer `src/services/completeness/completeness_checker.py` :

```python
"""
Calcul de la complétude d'une série TV.

Confronte les épisodes détenus en base aux épisodes attendus (TVDB) déjà
diffusés (date de diffusion <= aujourd'hui), en excluant la saison 0, les
épisodes numérotés 0 (SxxE00) et les épisodes hors canon (is_extra).
"""

from __future__ import annotations

import json
from datetime import date, datetime

from sqlmodel import Session, select

from src.infrastructure.persistence.models import EpisodeModel, SeriesModel
from src.services.completeness.dataclasses import (
    CompletenessResult,
    MissingEpisode,
)


def _parse_air_date(raw: str | None) -> date | None:
    """Parse une date de diffusion TVDB (format ISO 'YYYY-MM-DD')."""
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


class CompletenessChecker:
    """Calcule le verdict de complétude d'une série à partir de TVDB."""

    def __init__(self, tvdb_client) -> None:
        """
        Args:
            tvdb_client: client exposant ``get_all_episodes(series_id)``.
        """
        self._tvdb = tvdb_client

    async def compute(
        self,
        tvdb_id: str,
        owned: set[tuple[int, int]],
        today: date,
    ) -> CompletenessResult:
        """
        Calcule la complétude d'une série.

        Args:
            tvdb_id: ID TVDB de la série.
            owned: ensemble des (saison, épisode) détenus avec fichier (hors extra).
            today: date du jour (injectée pour des tests déterministes).

        Returns:
            CompletenessResult décrivant le verdict et les manques.
        """
        all_episodes = await self._tvdb.get_all_episodes(tvdb_id)

        # Filtre « attendu déjà diffusé » : saison>=1, épisode>=1, date<=today.
        expected: dict[tuple[int, int], MissingEpisode] = {}
        for ep in all_episodes:
            if ep.season_number < 1 or ep.episode_number < 1:
                continue
            aired = _parse_air_date(ep.air_date)
            if aired is None or aired > today:
                continue
            key = (ep.season_number, ep.episode_number)
            expected[key] = MissingEpisode(
                season=ep.season_number,
                episode=ep.episode_number,
                air_date=ep.air_date,
                title=ep.title,
            )

        expected_keys = set(expected.keys())
        owned_in_expected = expected_keys & owned

        # Regrouper l'attendu par saison.
        seasons: dict[int, set[int]] = {}
        for season, episode in expected_keys:
            seasons.setdefault(season, set()).add(episode)

        missing_seasons: list[int] = []
        missing_episodes: list[MissingEpisode] = []
        for season, episodes in seasons.items():
            season_keys = {(season, ep) for ep in episodes}
            if season_keys.isdisjoint(owned):
                # Aucun épisode détenu pour cette saison → saison absente.
                missing_seasons.append(season)
            else:
                for key in season_keys:
                    if key not in owned:
                        missing_episodes.append(expected[key])

        missing_seasons.sort()
        missing_episodes.sort(key=lambda m: (m.season, m.episode))

        status = "incomplete" if (missing_seasons or missing_episodes) else "complete"

        return CompletenessResult(
            status=status,
            missing_seasons=missing_seasons,
            missing_episodes=missing_episodes,
            expected_aired=len(expected_keys),
            owned=len(owned_in_expected),
            source="tvdb",
        )


def _result_to_json(result: CompletenessResult) -> str:
    """Sérialise le détail des manques pour la colonne DB."""
    return json.dumps(
        {
            "missing_seasons": result.missing_seasons,
            "missing_episodes": [
                {
                    "season": m.season,
                    "episode": m.episode,
                    "air_date": m.air_date,
                    "title": m.title,
                }
                for m in result.missing_episodes
            ],
            "expected_aired": result.expected_aired,
            "owned": result.owned,
            "source": result.source,
        },
        ensure_ascii=False,
    )


async def check_series_model(
    session: Session,
    checker: CompletenessChecker,
    series: SeriesModel,
    today: date,
) -> str:
    """
    Vérifie une série, persiste le verdict sur le modèle, et le retourne.

    Args:
        session: session SQLModel active.
        checker: CompletenessChecker configuré avec un client TVDB.
        series: la série à vérifier (objet attaché à la session).
        today: date du jour.

    Returns:
        Le verdict : "complete", "incomplete" ou "unverifiable".
    """
    now = datetime.utcnow()

    if not series.tvdb_id:
        series.completeness_status = None
        series.completeness_checked_at = now
        series.completeness_missing_json = None
        session.add(series)
        session.commit()
        return "unverifiable"

    owned_models = session.exec(
        select(EpisodeModel).where(
            EpisodeModel.series_id == series.id,
            EpisodeModel.is_extra == False,  # noqa: E712
        )
    ).all()
    owned = {
        (e.season_number, e.episode_number)
        for e in owned_models
        if e.file_path
    }

    result = await checker.compute(str(series.tvdb_id), owned, today)

    series.completeness_status = result.status
    series.completeness_checked_at = now
    series.completeness_missing_json = _result_to_json(result)
    session.add(series)
    session.commit()

    return result.status
```

- [ ] **Step 5 : Lancer les tests, vérifier le succès**

Run: `uv run pytest tests/unit/test_completeness_checker.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6 : Lint + commit**

```bash
uv run --extra dev ruff format src/services/completeness/ tests/unit/test_completeness_checker.py
uv run --extra dev ruff check src/services/completeness/ tests/unit/test_completeness_checker.py
git add src/services/completeness/ tests/unit/test_completeness_checker.py
git commit -m "feat(completeness): service de calcul CompletenessChecker

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4 : Test d'intégration `check_series_model` (persistance + filtrage des détenus)

Vérifie que `check_series_model` lit correctement les épisodes détenus (fichier présent, hors extra) et écrit les colonnes. `check_series_model` a déjà été implémenté en Task 3 ; cette tâche ajoute sa couverture de bout en bout sur une DB en mémoire.

**Files:**
- Test: `tests/unit/test_completeness_persistence.py` (ajouts)

- [ ] **Step 1 : Ajouter les tests d'intégration (échouent au départ si on les exécute avant Task 3 ; sinon passent)**

Ajouter à la fin de `tests/unit/test_completeness_persistence.py` :

```python
from datetime import date

import pytest

from src.core.ports.api_clients import EpisodeDetails
from src.infrastructure.persistence.models import EpisodeModel
from src.services.completeness.completeness_checker import (
    CompletenessChecker,
    check_series_model,
)


class _StubTVDB:
    def __init__(self, episodes):
        self._episodes = episodes

    async def get_all_episodes(self, series_id):
        return self._episodes


def _epd(season, episode, air_date):
    return EpisodeDetails(
        id=f"{season}-{episode}",
        title="t",
        season_number=season,
        episode_number=episode,
        overview=None,
        air_date=air_date,
    )


@pytest.mark.asyncio
async def test_check_series_model_persists_incomplete():
    """Une série à qui il manque un épisode diffusé est marquée incomplete."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="S", tvdb_id=42)
        session.add(series)
        session.commit()
        session.refresh(series)

        # Épisode détenu (1,1) avec fichier ; (1,2) absent.
        session.add(
            EpisodeModel(
                series_id=series.id,
                season_number=1,
                episode_number=1,
                title="e1",
                file_path="/storage/s/e1.mkv",
            )
        )
        session.commit()

        tvdb = _StubTVDB([_epd(1, 1, "2019-01-01"), _epd(1, 2, "2019-01-08")])
        checker = CompletenessChecker(tvdb)
        verdict = await check_series_model(
            session, checker, series, date(2026, 6, 23)
        )

        assert verdict == "incomplete"
        session.refresh(series)
        assert series.completeness_status == "incomplete"
        assert series.completeness_checked_at is not None
        assert '"episode": 2' in series.completeness_missing_json


@pytest.mark.asyncio
async def test_check_series_model_episode_without_file_is_missing():
    """Un épisode sans fichier compte comme manquant."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="S", tvdb_id=42)
        session.add(series)
        session.commit()
        session.refresh(series)

        # Ligne présente mais SANS fichier → non détenu.
        session.add(
            EpisodeModel(
                series_id=series.id,
                season_number=1,
                episode_number=1,
                title="e1",
                file_path=None,
            )
        )
        session.commit()

        tvdb = _StubTVDB([_epd(1, 1, "2019-01-01")])
        checker = CompletenessChecker(tvdb)
        verdict = await check_series_model(
            session, checker, series, date(2026, 6, 23)
        )
        assert verdict == "incomplete"


@pytest.mark.asyncio
async def test_check_series_model_extra_episode_ignored():
    """Un épisode is_extra ne compte pas comme détenu."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="S", tvdb_id=42)
        session.add(series)
        session.commit()
        session.refresh(series)

        session.add(
            EpisodeModel(
                series_id=series.id,
                season_number=1,
                episode_number=1,
                title="e1",
                file_path="/storage/s/e1.mkv",
                is_extra=True,
            )
        )
        session.commit()

        tvdb = _StubTVDB([_epd(1, 1, "2019-01-01")])
        checker = CompletenessChecker(tvdb)
        verdict = await check_series_model(
            session, checker, series, date(2026, 6, 23)
        )
        assert verdict == "incomplete"


@pytest.mark.asyncio
async def test_check_series_model_no_tvdb_id_is_unverifiable():
    """Sans tvdb_id, la série est non vérifiable (status None)."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="S", tvdb_id=None)
        session.add(series)
        session.commit()
        session.refresh(series)

        tvdb = _StubTVDB([])
        checker = CompletenessChecker(tvdb)
        verdict = await check_series_model(
            session, checker, series, date(2026, 6, 23)
        )
        assert verdict == "unverifiable"
        session.refresh(series)
        assert series.completeness_status is None
        assert series.completeness_checked_at is not None
```

- [ ] **Step 2 : Lancer les tests, vérifier le succès**

Run: `uv run pytest tests/unit/test_completeness_persistence.py -v`
Expected: PASS (les 2 tests de colonnes + les 4 nouveaux).

- [ ] **Step 3 : Lint + commit**

```bash
uv run --extra dev ruff format tests/unit/test_completeness_persistence.py
uv run --extra dev ruff check tests/unit/test_completeness_persistence.py
git add tests/unit/test_completeness_persistence.py
git commit -m "test(completeness): couverture check_series_model (détenus, extra, sans tvdb_id)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5 : Commande CLI `check-completeness`

Balaye toutes les séries (ou une seule via `--series-id`), appelle `check_series_model`, affiche une progression Rich et un récap.

**Files:**
- Create: `src/adapters/cli/commands/completeness_command.py`
- Modify: `src/adapters/cli/commands/__init__.py`
- Modify: `src/main.py`

> Note : pas de test unitaire dédié (la logique métier est déjà couverte par les Tasks 3‑4 ; la commande n'est qu'un câblage CLI fin). Vérification manuelle à l'étape finale.

- [ ] **Step 1 : Lire le module CLI existant pour copier le pattern**

Run: `uv run cat src/adapters/cli/commands/enrichment_commands.py | head -120` (déjà étudié : fonction sync → `asyncio.run`, décorateur `@with_container()`, `console`, `suppress_loguru()`, `Progress`).

Vérifier l'import de `console` et de `suppress_loguru` utilisés dans ce fichier et les réutiliser à l'identique.

- [ ] **Step 2 : Créer la commande**

Créer `src/adapters/cli/commands/completeness_command.py` :

```python
"""
Commande CLI `check-completeness`.

Confronte chaque série de la vidéothèque à TVDB pour détecter les épisodes
ou saisons déjà diffusés mais absents, et persiste le verdict de complétude.
"""

import asyncio
from datetime import date
from typing import Annotated, Optional

import typer
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from sqlmodel import select

from src.adapters.cli.helpers import suppress_loguru, with_container
from src.adapters.cli.validation import console
from src.infrastructure.persistence.database import get_session
from src.infrastructure.persistence.models import SeriesModel
from src.services.completeness.completeness_checker import (
    CompletenessChecker,
    check_series_model,
)


def check_completeness(
    series_id: Annotated[
        Optional[int],
        typer.Option(
            "--series-id",
            help="Vérifier une seule série (ID interne) au lieu de tout le parc",
        ),
    ] = None,
) -> None:
    """Vérifie la complétude des séries par rapport à TVDB."""
    asyncio.run(_check_completeness_async(series_id))


@with_container()
async def _check_completeness_async(container, series_id: Optional[int]) -> None:
    """Implémentation async de check-completeness."""
    tvdb_client = container.tvdb_client()
    checker = CompletenessChecker(tvdb_client)
    today = date.today()

    session = next(get_session())
    try:
        statement = select(SeriesModel)
        if series_id is not None:
            statement = statement.where(SeriesModel.id == series_id)
        series_list = session.exec(statement).all()

        if not series_list:
            console.print("[yellow]Aucune série à vérifier.[/yellow]")
            return

        total = len(series_list)
        console.print(
            f"[bold cyan]Vérification de complétude[/bold cyan] : "
            f"{total} série(s)\n"
        )

        tally = {"complete": 0, "incomplete": 0, "unverifiable": 0}

        with suppress_loguru():
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(),
                console=console,
                transient=False,
            ) as progress:
                task = progress.add_task("[cyan]Analyse…", total=total)
                for i, series in enumerate(series_list):
                    verdict = await check_series_model(
                        session, checker, series, today
                    )
                    tally[verdict] = tally.get(verdict, 0) + 1
                    progress.update(task, completed=i + 1)
                    if verdict == "incomplete":
                        progress.console.print(
                            f"  [yellow]✗[/yellow] {series.title} "
                            f"({series.year or '?'})"
                        )

        console.print("\n[bold]Résumé :[/bold]")
        console.print(f"  [green]{tally['complete']}[/green] complète(s)")
        console.print(f"  [yellow]{tally['incomplete']}[/yellow] incomplète(s)")
        console.print(
            f"  [dim]{tally['unverifiable']}[/dim] non vérifiable(s) (sans tvdb_id)"
        )
    finally:
        session.close()
```

- [ ] **Step 3 : Exporter la commande**

Dans `src/adapters/cli/commands/__init__.py`, ajouter l'import et l'entrée `__all__` (suivre le format des exports existants) :

```python
from src.adapters.cli.commands.completeness_command import check_completeness
```

Et ajouter `"check_completeness"` à la liste `__all__` de ce fichier.

- [ ] **Step 4 : Enregistrer dans main.py**

Dans `src/main.py`, ajouter `check_completeness` à l'import groupé depuis `.adapters.cli.commands` (vers la ligne 98-109), puis enregistrer la commande à côté des autres `app.command(...)` (vers la ligne 130-140) :

```python
app.command(name="check-completeness")(check_completeness)
```

- [ ] **Step 5 : Vérifier que la commande est reconnue**

Run: `uv run python -m src.main --help`
Expected: la commande `check-completeness` apparaît dans la liste.

Run: `uv run python -m src.main check-completeness --help`
Expected: affiche l'aide avec l'option `--series-id`.

- [ ] **Step 6 : Lint + commit**

```bash
uv run --extra dev ruff format src/adapters/cli/commands/completeness_command.py src/adapters/cli/commands/__init__.py src/main.py
uv run --extra dev ruff check src/adapters/cli/commands/completeness_command.py src/adapters/cli/commands/__init__.py src/main.py
git add src/adapters/cli/commands/completeness_command.py src/adapters/cli/commands/__init__.py src/main.py
git commit -m "feat(completeness): commande CLI check-completeness

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6 : Web — endpoint SSE + bouton page Maintenance

Calque le pattern SSE GET de `maintenance.py` (`run_check_sse` + `_sse_progress`/`_sse_complete`). L'analyse async appelle `check_series_model` série par série en `yield`ant la progression.

**Files:**
- Modify: `src/web/routes/maintenance.py`
- Modify: `src/web/templates/maintenance/index.html`

- [ ] **Step 1 : Ajouter l'endpoint SSE**

Dans `src/web/routes/maintenance.py`, ajouter (après les endpoints SSE existants, par ex. après `run_check_sse`) :

```python
@router.get("/maintenance/completeness")
async def run_completeness_sse(request: Request):
    """SSE endpoint : vérification de complétude des séries (TVDB)."""
    from datetime import date

    from ...infrastructure.persistence.database import get_session
    from ...infrastructure.persistence.models import SeriesModel
    from ...services.completeness.completeness_checker import (
        CompletenessChecker,
        check_series_model,
    )

    container = request.app.state.container
    tvdb_client = container.tvdb_client()
    checker = CompletenessChecker(tvdb_client)
    today = date.today()

    async def event_stream():
        session = next(get_session())
        try:
            series_list = session.exec(select(SeriesModel)).all()
            total = len(series_list)
            tally = {"complete": 0, "incomplete": 0, "unverifiable": 0}

            yield _sse_progress(0, total, "Initialisation…")

            for i, series in enumerate(series_list):
                yield _sse_progress(i + 1, total, series.title)
                try:
                    verdict = await check_series_model(
                        session, checker, series, today
                    )
                except Exception as e:  # robustesse : une série en échec ne bloque pas
                    logger.warning(
                        "Complétude : échec sur '{}' : {}", series.title, e
                    )
                    verdict = "unverifiable"
                tally[verdict] = tally.get(verdict, 0) + 1

            html = (
                '<div class="maint-result-card">'
                "<h3>Vérification terminée</h3>"
                f"<p><strong>{tally['incomplete']}</strong> série(s) incomplète(s), "
                f"<strong>{tally['complete']}</strong> complète(s), "
                f"<strong>{tally['unverifiable']}</strong> non vérifiable(s).</p>"
                '<p><a href="/library/?type=series&incomplete_series=1">'
                "Voir les séries incomplètes</a></p>"
                "</div>"
            )
            yield _sse_complete(html)
        finally:
            session.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 2 : Ajouter le bouton dans le template Maintenance**

Dans `src/web/templates/maintenance/index.html`, repérer le bloc du bouton « Lancer l'analyse » d'intégrité (vers la ligne 26, `onclick="startAnalysis('check')"` avec sa progress bar `id="check-progress"` et son conteneur de résultat). Dupliquer ce bloc pour la complétude, en adaptant les identifiants :

```html
<div class="maint-section">
  <h2 class="maint-section-title">Complétude des séries</h2>
  <p class="maint-section-desc">
    Compare chaque série à TVDB pour détecter les épisodes ou saisons
    déjà diffusés mais absents de la vidéothèque.
  </p>
  <button class="maint-analyze-btn" id="btn-completeness"
          onclick="startAnalysis('completeness')">
    Vérifier la complétude
  </button>
  <div id="completeness-progress" class="maint-progress" style="display:none;">
    <div class="maint-progress-bar"><div class="maint-progress-fill"></div></div>
    <div class="maint-progress-label"></div>
  </div>
  <div id="completeness-result" class="maint-result"></div>
</div>
```

> Important : la fonction JS `startAnalysis(type)` (vers la ligne 251) construit l'URL `'/maintenance/' + type` et cible les éléments `#{type}-progress` et `#{type}-result`. En nommant les éléments `completeness-progress` / `completeness-result` et en passant `'completeness'`, l'endpoint `/maintenance/completeness` est consommé sans modifier le JS. **Vérifier ce point en lisant `startAnalysis`** : si les sélecteurs d'éléments y sont en dur pour `check`/autres types, étendre la fonction pour gérer `'completeness'` de façon analogue (mêmes noms d'événements `progress`/`complete`, même structure `{phase,total,label}` et `{html}`).

- [ ] **Step 3 : Vérification manuelle (rendu + exécution)**

Démarrer le serveur :

Run: `uv run uvicorn src.web.app:app --reload`
Ouvrir `http://127.0.0.1:8000/maintenance`, cliquer « Vérifier la complétude ».
Expected: barre de progression qui avance série par série, puis carte récap avec le lien « Voir les séries incomplètes ». Aucune erreur serveur dans la console.

- [ ] **Step 4 : Lint + commit**

```bash
uv run --extra dev ruff format src/web/routes/maintenance.py
uv run --extra dev ruff check src/web/routes/maintenance.py
git add src/web/routes/maintenance.py src/web/templates/maintenance/index.html
git commit -m "feat(completeness): bouton + SSE de vérification sur la page Maintenance

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7 : Web — filtre « Séries incomplètes » dans la bibliothèque

**Files:**
- Modify: `src/web/routes/library/browse.py`
- Modify: `src/web/templates/library/_filters.html`
- Test: `tests/unit/test_browse_incomplete_filter.py`

- [ ] **Step 1 : Lire la signature exacte de `library_index` et la section filtre séries**

Run: `uv run sed -n '40,260p' src/web/routes/library/browse.py` — repérer :
- la signature de `library_index(...)` (paramètres query, vers ligne 52),
- la construction `series_stmt = select(SeriesModel)` et ses `.where(...)` (vers ligne 179-251),
- le `context = {...}` final (vers ligne 395) pour y ajouter `current_incomplete_series`.

- [ ] **Step 2 : Écrire le test du filtre (échoue)**

Créer `tests/unit/test_browse_incomplete_filter.py` :

```python
"""Test du filtre 'séries incomplètes' de la bibliothèque."""

from fastapi.testclient import TestClient

from src.infrastructure.persistence.database import get_session
from src.infrastructure.persistence.models import SeriesModel
from src.web.app import app


def _seed_series():
    session = next(get_session())
    try:
        session.add(SeriesModel(title="Complete Show", completeness_status="complete"))
        session.add(
            SeriesModel(title="Broken Show", completeness_status="incomplete")
        )
        session.add(SeriesModel(title="Unknown Show", completeness_status=None))
        session.commit()
    finally:
        session.close()


def test_incomplete_filter_returns_only_incomplete():
    """incomplete_series=1 ne renvoie que les séries au statut 'incomplete'."""
    _seed_series()
    client = TestClient(app)
    resp = client.get("/library/?type=series&incomplete_series=1")
    assert resp.status_code == 200
    body = resp.text
    assert "Broken Show" in body
    assert "Complete Show" not in body
    assert "Unknown Show" not in body
```

> Note : ce test s'appuie sur la base configurée pour les tests (voir `tests/conftest.py` — DB temporaire/in-memory). Si une fixture de client/DB existe déjà (ex. `client` ou `web_client`), l'utiliser au lieu d'instancier `TestClient(app)` en dur et adapter le seed à la fixture DB.

- [ ] **Step 3 : Lancer le test, vérifier l'échec**

Run: `uv run pytest tests/unit/test_browse_incomplete_filter.py -v`
Expected: FAIL (le paramètre n'existe pas → les 3 séries ou un sous-ensemble erroné apparaissent).

- [ ] **Step 4 : Ajouter le paramètre et le filtre dans `browse.py`**

1. Ajouter le paramètre à la signature de `library_index` (à côté de `no_file`, `no_poster`) :

```python
    incomplete_series: Optional[str] = None,
```

2. Dans la section de construction de `series_stmt` (après les autres `.where(...)` séries), ajouter :

```python
        if incomplete_series == "1":
            series_stmt = series_stmt.where(
                SeriesModel.completeness_status == "incomplete"
            )
```

3. Dans le `context = {...}` final, ajouter :

```python
        "current_incomplete_series": incomplete_series == "1",
```

- [ ] **Step 5 : Ajouter la case à cocher et le tag actif dans `_filters.html`**

1. À côté des cases `no_file`/`no_poster` (vers la ligne 90), ajouter :

```html
<label class="lib-filter-checkbox lib-filter-checkbox-sm">
  <input type="checkbox" name="incomplete_series" value="1"
         {{ 'checked' if current_incomplete_series }}>
  Séries incomplètes
</label>
```

2. Dans la zone des tags de filtres actifs (vers la ligne 144-229), ajouter le tag de retrait sur le modèle des autres tags :

```html
{% if current_incomplete_series %}
<span class="lib-filter-tag">
  Incomplètes
  <a href="/library/?type={{ current_type }}" class="lib-filter-tag-remove">&times;</a>
</span>
{% endif %}
```

> Adapter le `href` de retrait au format réellement utilisé par les autres tags du fichier (ils reconstruisent souvent l'URL en conservant les autres filtres actifs). Reproduire ce format plutôt que de réinitialiser tous les filtres si c'est la convention locale.

- [ ] **Step 6 : Lancer le test, vérifier le succès**

Run: `uv run pytest tests/unit/test_browse_incomplete_filter.py -v`
Expected: PASS.

- [ ] **Step 7 : Lint + commit**

```bash
uv run --extra dev ruff format src/web/routes/library/browse.py tests/unit/test_browse_incomplete_filter.py
uv run --extra dev ruff check src/web/routes/library/browse.py tests/unit/test_browse_incomplete_filter.py
git add src/web/routes/library/browse.py src/web/templates/library/_filters.html tests/unit/test_browse_incomplete_filter.py
git commit -m "feat(completeness): filtre 'séries incomplètes' dans la bibliothèque

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8 : Web — badge « Incomplet » + bloc justification sur la fiche

**Files:**
- Modify: `src/web/routes/library/detail.py`
- Modify: `src/web/templates/library/series_detail.html`
- Modify: `src/web/templates/library/_grid.html`
- Modify: `src/web/static/css/style.css`

- [ ] **Step 1 : Exposer le détail de complétude parsé dans la route détail**

Dans `src/web/routes/library/detail.py`, fonction `series_detail` (vers la ligne 154-228), avant le `return templates.TemplateResponse(...)`, parser le JSON et l'ajouter au contexte :

```python
    import json as _json

    completeness_detail = None
    if series.completeness_missing_json:
        try:
            completeness_detail = _json.loads(series.completeness_missing_json)
        except (ValueError, TypeError):
            completeness_detail = None
```

Ajouter au dictionnaire de contexte :

```python
        "completeness_status": series.completeness_status,
        "completeness_detail": completeness_detail,
```

(`series` ici est le `SeriesModel` déjà chargé ; vérifier le nom de la variable locale et réutiliser celui en place.)

- [ ] **Step 2 : Badge sur l'en-tête de la fiche série**

Dans `src/web/templates/library/series_detail.html`, près du badge type « Série » (vers la ligne 43), ajouter :

```html
{% if completeness_status == 'incomplete' %}
<span class="badge-incomplete" title="Des épisodes déjà diffusés manquent">
  Incomplet
</span>
{% endif %}
```

- [ ] **Step 3 : Bloc justification**

Dans `series_detail.html`, juste avant la section « Saisons et épisodes » (vers la ligne 196), ajouter :

```html
{% if completeness_status == 'incomplete' and completeness_detail %}
<section class="completeness-block">
  <h2 class="completeness-title">Pourquoi cette série est incomplète</h2>
  <p class="completeness-summary">
    {{ completeness_detail.owned }} / {{ completeness_detail.expected_aired }}
    épisode(s) diffusé(s) présent(s).
  </p>
  {% if completeness_detail.missing_seasons %}
  <p class="completeness-missing-seasons">
    Saison(s) entièrement absente(s) :
    {% for s in completeness_detail.missing_seasons %}
      <span class="completeness-tag">Saison {{ '%02d'|format(s) }}</span>
    {% endfor %}
  </p>
  {% endif %}
  {% if completeness_detail.missing_episodes %}
  <ul class="completeness-missing-list">
    {% for ep in completeness_detail.missing_episodes %}
    <li>
      <span class="completeness-code">
        S{{ '%02d'|format(ep.season) }}E{{ '%02d'|format(ep.episode) }}
      </span>
      {% if ep.title %}<span class="completeness-ep-title">{{ ep.title }}</span>{% endif %}
      {% if ep.air_date %}<span class="completeness-ep-date">({{ ep.air_date }})</span>{% endif %}
    </li>
    {% endfor %}
  </ul>
  {% endif %}
</section>
{% endif %}
```

- [ ] **Step 4 : Badge sur la carte série dans la grille**

Dans `src/web/templates/library/_grid.html`, dans la carte (`.lib-card`), là où le badge de type série est rendu (vers la ligne 16-44), ajouter — en lisant l'attribut sur l'item (qui est un `SeriesModel`, donc `item.completeness_status` est disponible) :

```html
{% if item.completeness_status == 'incomplete' %}
<span class="lib-card-incomplete" title="Série incomplète">Incomplet</span>
{% endif %}
```

> Vérifier le nom de la variable d'itération réellement utilisée dans `_grid.html` (l'exploration indique `item`/`.lib-card`). Réutiliser ce nom.

- [ ] **Step 5 : Styles CSS du badge**

Dans `src/web/static/css/style.css`, à la suite des autres badges de carte/fiche (zone des badges, vers les lignes 3862-3953 pour les cartes et 4120-4182 pour la fiche), ajouter :

```css
/* Badge complétude (phase série-completeness) */
.badge-incomplete,
.lib-card-incomplete {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 6px;
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: #1a1a1a;
  background: #f59e0b; /* ambre */
}

.lib-card-incomplete {
  position: absolute;
  top: 0.4rem;
  left: 0.4rem;
  z-index: 2;
  backdrop-filter: blur(8px);
}

.completeness-block {
  margin: 1.5rem 0;
  padding: 1rem 1.25rem;
  border-left: 4px solid #f59e0b;
  background: rgba(245, 158, 11, 0.08);
  border-radius: 8px;
}

.completeness-title {
  font-size: 1.05rem;
  margin: 0 0 0.5rem;
}

.completeness-missing-list {
  margin: 0.5rem 0 0;
  padding-left: 1rem;
  list-style: none;
}

.completeness-missing-list li {
  padding: 0.15rem 0;
}

.completeness-code,
.completeness-tag {
  font-family: monospace;
  font-weight: 700;
  margin-right: 0.4rem;
}

.completeness-ep-date {
  color: var(--text-muted, #888);
  margin-left: 0.3rem;
}
```

> Adapter les noms de variables CSS (`--text-muted`, etc.) à celles du thème si elles diffèrent ; sinon la valeur de repli s'applique.

- [ ] **Step 6 : Vérification manuelle du rendu**

Run: `uv run uvicorn src.web.app:app --reload`
- Ouvrir une fiche de série connue incomplète : le badge « Incomplet » et le bloc justification s'affichent avec saisons/épisodes manquants.
- Sur `http://127.0.0.1:8000/library/?type=series` : les cartes des séries incomplètes portent le badge ambre.
- Sur `http://127.0.0.1:8000/library/?type=series&incomplete_series=1` : seules les incomplètes apparaissent.

- [ ] **Step 7 : Commit**

```bash
git add src/web/routes/library/detail.py src/web/templates/library/series_detail.html src/web/templates/library/_grid.html src/web/static/css/style.css
git commit -m "feat(completeness): badge 'Incomplet' et bloc justification sur la fiche série

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9 : Documentation README + vérification finale

**Files:**
- Modify: `README.md`

- [ ] **Step 1 : Documenter la fonctionnalité**

Dans `README.md`, ajouter une section décrivant la surveillance de complétude :
- objectif (détecter épisodes/saisons déjà diffusés mais absents) ;
- critère (basé sur les dates de diffusion passées, exclusions saison 0 / SxxE00 / `is_extra`, séries sans `tvdb_id` non vérifiées) ;
- usage CLI : `uv run python -m src.main check-completeness [--series-id N]` ;
- usage web : bouton « Vérifier la complétude » sur la page Maintenance ;
- filtre « Séries incomplètes » et badge dans la bibliothèque ;
- limite connue V1 : TVDB uniquement (séries seulement-TMDB non vérifiées).

Mettre à jour la table des matières si elle existe. Ajouter une entrée Dépannage si pertinent (ex. « toutes mes séries sont non vérifiées » → absence de `tvdb_id` / clé API TVDB).

- [ ] **Step 2 : Suite de tests complète + lint global des fichiers touchés**

```bash
uv sync --extra dev && uv run pytest tests/unit/test_completeness_checker.py tests/unit/test_completeness_persistence.py tests/unit/test_tvdb_get_all_episodes.py tests/unit/test_browse_incomplete_filter.py -v
```
Expected: tous PASS.

Lancer aussi la suite globale pour vérifier l'absence de régression :

```bash
uv run pytest
```
Expected: pas de nouvelle régression.

- [ ] **Step 3 : Commit**

```bash
git add README.md
git commit -m "docs(completeness): documenter la surveillance de complétude des séries

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4 : Finalisation de la branche**

La fonctionnalité est implémentée sur `feat/series-completeness`. Utiliser le skill `superpowers:finishing-a-development-branch` pour décider de la suite (PR vers master, etc.).

---

## Auto-revue du plan

**Couverture du spec :**
- Interprétation A (dates de diffusion passées) → Task 3 (`compute`, filtre `air_date <= today`). ✓
- Exclusions saison 0 / SxxE00 / `is_extra` → Task 3 (tests dédiés) + Task 3 `check_series_model` (filtre `is_extra`). ✓
- « Présent = ligne + fichier » → Task 3/4 (`if e.file_path`). ✓
- Persistance (3 colonnes + migration) → Task 1. ✓
- Source TVDB seule, séries sans `tvdb_id` = `null` → Task 2 + Task 3 (`unverifiable`). ✓
- Service `CompletenessChecker` (sous-package) → Task 3. ✓
- CLI `check-completeness` → Task 5. ✓
- Bouton Maintenance + SSE → Task 6. ✓
- Filtre web → Task 7. ✓
- Badge (carte + fiche) + bloc justification → Task 8. ✓
- Format `completeness_missing_json` (missing_seasons / missing_episodes / expected_aired / owned / source) → Task 3 (`_result_to_json`). ✓
- Tests TDD (trou, queue, en cours, exclusions, sans fichier, sans tvdb_id, repo réel, route) → Tasks 1,3,4,7. ✓
- Hors périmètre (repli TMDB, déclenchement workflow auto, invalidation au transfert) → non implémentés, conformes au spec. ✓
- README → Task 9. ✓

**Cohérence des types/signatures :**
- `CompletenessChecker(tvdb_client)` ; `.compute(tvdb_id: str, owned: set[tuple[int,int]], today: date) -> CompletenessResult` — utilisée identiquement dans Tasks 3, 4, 5, 6. ✓
- `check_series_model(session, checker, series, today) -> str` — signature identique en Tasks 3 (def), 4 (test), 5 (CLI), 6 (web). ✓
- `TVDBClient.get_all_episodes(series_id) -> list[EpisodeDetails]` — Task 2 (def), consommée par `compute` en Task 3. ✓
- `EpisodeDetails` (champs `season_number`, `episode_number`, `air_date: str|None`, `title`) — conforme à `src/core/ports/api_clients.py:80`. ✓
- Colonnes `completeness_status` / `completeness_checked_at` / `completeness_missing_json` — mêmes noms en Tasks 1, 3, 6, 7, 8. ✓

**Placeholders :** aucun TODO/TBD ; tout le code Python testable est fourni en intégral. Les tâches templates/CSS (6, 7, 8) référencent des points d'insertion précis et demandent de vérifier les noms de variables Jinja réels (`item`, variable série de `detail.py`) et le comportement de `startAnalysis` — vérifications explicites incluses dans les steps.
