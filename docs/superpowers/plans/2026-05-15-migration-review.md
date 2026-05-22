# Migration NAS — Review interactive — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformer les buckets non-MIGRATE de `migrate-nas` (needs_validation, unrated, low_rated, already_in_library) en queue de décisions exploitable via une review CLI interactive (web optionnel en polish).

**Architecture:** Décisions découplées du plan, persistées dans `state_store` SQLite (nouvelle table `migration_decisions`). CLI `migrate-nas review` itère sur les items pending, applique les décisions via `MigrationReviewService` partagé. `apply` joint plan + decisions et hydrate `item.match` avant transfert. `raw_finalizer` inchangé.

**Tech Stack:** Python 3.13, SQLModel/sqlite3, Typer, Rich, FastAPI/Jinja2/HTMX. Réutilise `tmdb_client`, `MatcherService`, `DuplicateDetector`, `candidate_display`, `_reassociate_*` templates.

**Spec source:** [docs/superpowers/specs/2026-05-15-migration-review-design.md](../specs/2026-05-15-migration-review-design.md)

---

## File Structure

### New files

```
src/services/migration/
├── decisions.py                     # Decision dataclass + DecisionStatus enum
└── review_service.py                # MigrationReviewService (orchestrateur)

src/adapters/cli/commands/migrate_nas_command/
└── review.py                        # CLI command + interactive loop

src/web/routes/migration/            # phase 44.7
├── __init__.py
└── review.py

src/web/templates/migration/         # phase 44.7
├── review_list.html
├── _review_card.html
├── _review_detail.html
└── _duplicate_compare.html

tests/unit/services/migration/
├── test_decisions.py
└── test_review_service.py

tests/unit/adapters/cli/
└── test_migrate_nas_review.py

tests/unit/web/                      # phase 44.7
└── test_migration_review_routes.py
```

### Modified files

```
src/services/migration/state_store.py           # +table migration_decisions + CRUD
src/adapters/cli/commands/migrate_nas_command/
├── __init__.py                                  # re-export review_command
└── orchestrators.py                             # run_apply hydrate from decisions

tests/unit/services/migration/test_state_store.py  # +tests CRUD decisions
tests/unit/adapters/cli/test_migrate_nas_command.py # +test apply with decisions
README.md                                          # phase 44.9
```

---

## Phase 44.1 — Decisions + storage

### Task 1: `Decision` dataclass + `DecisionStatus` enum

**Files:**
- Create: `src/services/migration/decisions.py`
- Test: `tests/unit/services/migration/test_decisions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/services/migration/test_decisions.py
"""Tests pour Decision dataclass + DecisionStatus enum."""

from datetime import datetime, timezone

from src.services.migration.decisions import (
    Decision,
    DecisionStatus,
    DuplicateAction,
)


def test_decision_status_values():
    assert DecisionStatus.APPROVED.value == "approved"
    assert DecisionStatus.REJECTED.value == "rejected"
    assert DecisionStatus.SKIPPED.value == "skipped"
    assert DecisionStatus.DEFERRED_TO_WEB.value == "deferred_to_web"


def test_duplicate_action_values():
    assert DuplicateAction.KEEP_DEST.value == "keep_dest"
    assert DuplicateAction.REPLACE_DEST.value == "replace_dest"
    assert DuplicateAction.DELETE_SOURCE.value == "delete_source"


def test_decision_minimal_construction():
    d = Decision(
        item_id="abc123",
        bucket_origin="needs_validation",
        decision=DecisionStatus.SKIPPED,
        decided_at=datetime.now(timezone.utc),
        decided_via="cli",
    )
    assert d.item_id == "abc123"
    assert d.decision == DecisionStatus.SKIPPED
    assert d.chosen_tmdb_id is None
    assert d.delete_source_after is False


def test_decision_approved_with_match():
    d = Decision(
        item_id="abc123",
        bucket_origin="needs_validation",
        decision=DecisionStatus.APPROVED,
        chosen_tmdb_id=19995,
        chosen_title="Avatar",
        chosen_year=2009,
        chosen_score=95.0,
        decided_at=datetime.now(timezone.utc),
        decided_via="cli",
    )
    assert d.chosen_tmdb_id == 19995
    assert d.chosen_score == 95.0
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/services/migration/test_decisions.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.migration.decisions'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/services/migration/decisions.py
"""
Décisions de review pour les items migration en attente.

Une Decision matérialise le choix utilisateur sur un item d'un bucket
non-MIGRATE (needs_validation, unrated, low_rated, already_in_library).
Persistée dans state_store SQLite via MigrationStateStore.

Utilisée par migrate-nas apply pour hydrater item.match avant transfert
(les items approved deviennent traitables comme des MIGRATE classiques).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class DecisionStatus(str, Enum):
    """Statut d'une décision review."""

    APPROVED = "approved"  # à transférer (avec chosen_*)
    REJECTED = "rejected"  # marqué refusé (raison libre)
    SKIPPED = "skipped"  # passé pour cette session, à reprendre plus tard
    DEFERRED_TO_WEB = "deferred_to_web"  # arbitrage différé à l'overlay web


class DuplicateAction(str, Enum):
    """Action sur un doublon already_in_library."""

    KEEP_DEST = "keep_dest"  # garde la version existante (DB)
    REPLACE_DEST = "replace_dest"  # écrase dest avec source NAS
    DELETE_SOURCE = "delete_source"  # supprime source NAS, garde DB


@dataclass
class Decision:
    """Décision d'arbitrage sur un MigrationItem en attente."""

    item_id: str
    bucket_origin: str  # bucket d'origine (informationnel pour audit)
    decision: DecisionStatus
    decided_at: datetime
    decided_via: str  # "cli" | "web"
    chosen_tmdb_id: Optional[int] = None
    chosen_tvdb_id: Optional[int] = None
    chosen_title: Optional[str] = None
    chosen_year: Optional[int] = None
    chosen_score: Optional[float] = None
    duplicate_action: Optional[DuplicateAction] = None
    delete_source_after: bool = False
    reason: Optional[str] = None
```

- [ ] **Step 4: Run test to verify it passes**

```
uv run pytest tests/unit/services/migration/test_decisions.py -v
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/services/migration/decisions.py tests/unit/services/migration/test_decisions.py
git commit -m "feat(migration): Decision dataclass + DecisionStatus/DuplicateAction enums"
```

---

### Task 2: `MigrationStateStore` — table migration_decisions + CRUD

**Files:**
- Modify: `src/services/migration/state_store.py:31-43` (extend `_SCHEMA`), `:148-210` (add CRUD methods)
- Test: `tests/unit/services/migration/test_state_store.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/services/migration/test_state_store.py` :

```python
from datetime import datetime, timezone

from src.services.migration.decisions import (
    Decision,
    DecisionStatus,
    DuplicateAction,
)


def _decision(item_id: str = "abc", **overrides) -> Decision:
    base = dict(
        item_id=item_id,
        bucket_origin="needs_validation",
        decision=DecisionStatus.APPROVED,
        chosen_tmdb_id=19995,
        chosen_title="Avatar",
        chosen_year=2009,
        chosen_score=95.0,
        decided_at=datetime.now(timezone.utc),
        decided_via="cli",
    )
    base.update(overrides)
    return Decision(**base)


def test_save_decision_persists(tmp_path):
    store = MigrationStateStore(tmp_path / "s.sqlite")
    store.save_decision(_decision("item-1"))
    loaded = store.get_decision("item-1")
    assert loaded is not None
    assert loaded.chosen_tmdb_id == 19995
    assert loaded.decision == DecisionStatus.APPROVED


def test_save_decision_idempotent_overwrites(tmp_path):
    store = MigrationStateStore(tmp_path / "s.sqlite")
    store.save_decision(_decision("item-1"))
    store.save_decision(
        _decision("item-1", decision=DecisionStatus.SKIPPED, chosen_tmdb_id=None)
    )
    loaded = store.get_decision("item-1")
    assert loaded.decision == DecisionStatus.SKIPPED
    assert loaded.chosen_tmdb_id is None


def test_get_decision_returns_none_when_absent(tmp_path):
    store = MigrationStateStore(tmp_path / "s.sqlite")
    assert store.get_decision("missing") is None


def test_load_decisions_returns_dict_keyed_by_item_id(tmp_path):
    store = MigrationStateStore(tmp_path / "s.sqlite")
    store.save_decision(_decision("a"))
    store.save_decision(_decision("b", decision=DecisionStatus.SKIPPED))
    decisions = store.load_decisions()
    assert set(decisions.keys()) == {"a", "b"}
    assert decisions["b"].decision == DecisionStatus.SKIPPED


def test_decision_summary_groups_by_status(tmp_path):
    store = MigrationStateStore(tmp_path / "s.sqlite")
    store.save_decision(_decision("a", decision=DecisionStatus.APPROVED))
    store.save_decision(_decision("b", decision=DecisionStatus.APPROVED))
    store.save_decision(_decision("c", decision=DecisionStatus.SKIPPED))
    summary = store.decision_summary()
    assert summary[DecisionStatus.APPROVED] == 2
    assert summary[DecisionStatus.SKIPPED] == 1


def test_save_decision_with_duplicate_action(tmp_path):
    store = MigrationStateStore(tmp_path / "s.sqlite")
    store.save_decision(
        _decision(
            "dup-1",
            bucket_origin="already_in_library",
            duplicate_action=DuplicateAction.REPLACE_DEST,
        )
    )
    loaded = store.get_decision("dup-1")
    assert loaded.duplicate_action == DuplicateAction.REPLACE_DEST


def test_save_decision_with_delete_source_after(tmp_path):
    store = MigrationStateStore(tmp_path / "s.sqlite")
    store.save_decision(
        _decision(
            "low-1",
            bucket_origin="low_rated",
            delete_source_after=True,
        )
    )
    loaded = store.get_decision("low-1")
    assert loaded.delete_source_after is True
```

- [ ] **Step 2: Run tests to verify failure**

```
uv run pytest tests/unit/services/migration/test_state_store.py -v -k "decision"
```
Expected: FAIL with `AttributeError: 'MigrationStateStore' object has no attribute 'save_decision'`.

- [ ] **Step 3: Extend `_SCHEMA` with the new table**

Edit `src/services/migration/state_store.py` — replace `_SCHEMA` constant :

```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS migration_items (
    item_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    source_path TEXT,
    destination_path TEXT,
    source_hash TEXT,
    destination_hash TEXT,
    bytes_transferred INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS migration_decisions (
    item_id TEXT PRIMARY KEY,
    bucket_origin TEXT NOT NULL,
    decision TEXT NOT NULL,
    chosen_tmdb_id INTEGER,
    chosen_tvdb_id INTEGER,
    chosen_title TEXT,
    chosen_year INTEGER,
    chosen_score REAL,
    duplicate_action TEXT,
    delete_source_after INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    decided_at TEXT NOT NULL,
    decided_via TEXT NOT NULL
);
"""
```

Then update `__init__` to use `executescript` instead of `execute` for multi-statement DDL :

```python
def __init__(self, db_path: Path) -> None:
    self._db_path = Path(db_path)
    self._db_path.parent.mkdir(parents=True, exist_ok=True)
    self._conn = sqlite3.connect(self._db_path)
    self._conn.row_factory = sqlite3.Row
    self._conn.executescript(_SCHEMA)
    self._conn.commit()
```

- [ ] **Step 4: Add CRUD methods on `MigrationStateStore`**

Append after the existing `update_status` method :

```python
    # ---- Décisions de review (phase 44.1) -------------------------------

    def save_decision(self, decision) -> None:
        """Persiste (insert or replace) une décision review.

        Idempotent : ré-décider le même item_id écrase la décision précédente.
        """
        self._conn.execute(
            """
            INSERT OR REPLACE INTO migration_decisions
                (item_id, bucket_origin, decision, chosen_tmdb_id,
                 chosen_tvdb_id, chosen_title, chosen_year, chosen_score,
                 duplicate_action, delete_source_after, reason,
                 decided_at, decided_via)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.item_id,
                decision.bucket_origin,
                decision.decision.value,
                decision.chosen_tmdb_id,
                decision.chosen_tvdb_id,
                decision.chosen_title,
                decision.chosen_year,
                decision.chosen_score,
                decision.duplicate_action.value if decision.duplicate_action else None,
                int(decision.delete_source_after),
                decision.reason,
                decision.decided_at.isoformat(),
                decision.decided_via,
            ),
        )
        self._conn.commit()

    def get_decision(self, item_id: str):
        """Retourne la décision pour cet item_id, ou None si absente."""
        row = self._conn.execute(
            """
            SELECT item_id, bucket_origin, decision, chosen_tmdb_id,
                   chosen_tvdb_id, chosen_title, chosen_year, chosen_score,
                   duplicate_action, delete_source_after, reason,
                   decided_at, decided_via
            FROM migration_decisions WHERE item_id = ?
            """,
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_decision(row)

    def load_decisions(self) -> dict:
        """Retourne toutes les décisions sous forme {item_id: Decision}."""
        rows = self._conn.execute(
            """
            SELECT item_id, bucket_origin, decision, chosen_tmdb_id,
                   chosen_tvdb_id, chosen_title, chosen_year, chosen_score,
                   duplicate_action, delete_source_after, reason,
                   decided_at, decided_via
            FROM migration_decisions
            """
        ).fetchall()
        return {r["item_id"]: _row_to_decision(r) for r in rows}

    def decision_summary(self) -> dict:
        """Retourne {DecisionStatus: count} pour la table decisions."""
        from src.services.migration.decisions import DecisionStatus

        rows = self._conn.execute(
            "SELECT decision, COUNT(*) AS n FROM migration_decisions GROUP BY decision"
        ).fetchall()
        return {DecisionStatus(r["decision"]): r["n"] for r in rows}
```

Then add the helper module-level function (just before `_now_iso`) :

```python
def _row_to_decision(row):
    """Reconstruit une Decision depuis une row sqlite3.Row."""
    from datetime import datetime

    from src.services.migration.decisions import (
        Decision,
        DecisionStatus,
        DuplicateAction,
    )

    return Decision(
        item_id=row["item_id"],
        bucket_origin=row["bucket_origin"],
        decision=DecisionStatus(row["decision"]),
        chosen_tmdb_id=row["chosen_tmdb_id"],
        chosen_tvdb_id=row["chosen_tvdb_id"],
        chosen_title=row["chosen_title"],
        chosen_year=row["chosen_year"],
        chosen_score=row["chosen_score"],
        duplicate_action=(
            DuplicateAction(row["duplicate_action"])
            if row["duplicate_action"]
            else None
        ),
        delete_source_after=bool(row["delete_source_after"]),
        reason=row["reason"],
        decided_at=datetime.fromisoformat(row["decided_at"]),
        decided_via=row["decided_via"],
    )
```

- [ ] **Step 5: Run tests to verify pass**

```
uv run pytest tests/unit/services/migration/test_state_store.py -v
```
Expected: PASS (all existing tests + 7 new decision tests).

- [ ] **Step 6: Commit**

```bash
git add src/services/migration/state_store.py tests/unit/services/migration/test_state_store.py
git commit -m "feat(migration state_store): table migration_decisions + CRUD"
```

---

### Task 3: `MigrationReviewService` — skeleton + `iter_pending`

**Files:**
- Create: `src/services/migration/review_service.py`
- Test: `tests/unit/services/migration/test_review_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/services/migration/test_review_service.py
"""Tests pour MigrationReviewService — orchestrateur de la review."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.services.migration.dataclasses import (
    Bucket,
    MatchInfo,
    MigrationItem,
    MigrationPlan,
    MigrationStats,
    RatingDecision,
)
from src.services.migration.decisions import Decision, DecisionStatus
from src.services.migration.review_service import MigrationReviewService
from src.services.migration.state_store import MigrationStateStore


def _item(item_id: str, bucket: Bucket, **overrides) -> MigrationItem:
    base = dict(
        item_id=item_id,
        bucket=bucket,
        symlink_path=Path(f"/old/{item_id}.mkv"),
        source_path=Path(f"/old/{item_id}.mkv"),
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1000,
        rating=RatingDecision(),
        match=MatchInfo(),
        is_symlink_source=False,
    )
    base.update(overrides)
    return MigrationItem(**base)


def _plan(items) -> MigrationPlan:
    return MigrationPlan(
        version=1,
        source_root=Path("/src"),
        destination_root=Path("/dst"),
        threshold=6.0,
        stats=MigrationStats(),
        items=items,
    )


@pytest.fixture
def store(tmp_path):
    return MigrationStateStore(tmp_path / "s.sqlite")


def test_iter_pending_yields_review_buckets_only(store):
    plan = _plan([
        _item("m1", Bucket.MIGRATE),
        _item("nv1", Bucket.NEEDS_VALIDATION),
        _item("u1", Bucket.UNRATED),
        _item("lr1", Bucket.LOW_RATED),
        _item("ail1", Bucket.ALREADY_IN_LIBRARY),
        _item("br1", Bucket.BROKEN),
    ])
    service = MigrationReviewService(
        plan=plan,
        state_store=store,
        tmdb_client=MagicMock(),
        tvdb_client=MagicMock(),
        matcher=MagicMock(),
        duplicate_detector=MagicMock(),
    )
    pending = list(service.iter_pending())
    ids = [it.item_id for it in pending]
    assert set(ids) == {"nv1", "u1", "lr1", "ail1"}
    assert "m1" not in ids
    assert "br1" not in ids  # BROKEN exclu (sans solution review)


def test_iter_pending_filters_by_bucket(store):
    plan = _plan([
        _item("nv1", Bucket.NEEDS_VALIDATION),
        _item("u1", Bucket.UNRATED),
    ])
    service = MigrationReviewService(
        plan=plan,
        state_store=store,
        tmdb_client=MagicMock(),
        tvdb_client=MagicMock(),
        matcher=MagicMock(),
        duplicate_detector=MagicMock(),
    )
    pending = list(service.iter_pending(bucket=Bucket.NEEDS_VALIDATION))
    assert [it.item_id for it in pending] == ["nv1"]


def test_iter_pending_resume_skips_decided(store):
    plan = _plan([
        _item("nv1", Bucket.NEEDS_VALIDATION),
        _item("nv2", Bucket.NEEDS_VALIDATION),
    ])
    store.save_decision(
        Decision(
            item_id="nv1",
            bucket_origin="needs_validation",
            decision=DecisionStatus.SKIPPED,
            decided_at=datetime.now(timezone.utc),
            decided_via="cli",
        )
    )
    service = MigrationReviewService(
        plan=plan,
        state_store=store,
        tmdb_client=MagicMock(),
        tvdb_client=MagicMock(),
        matcher=MagicMock(),
        duplicate_detector=MagicMock(),
    )
    pending = list(service.iter_pending(resume=True))
    assert [it.item_id for it in pending] == ["nv2"]


def test_iter_pending_no_resume_yields_all(store):
    plan = _plan([_item("nv1", Bucket.NEEDS_VALIDATION)])
    store.save_decision(
        Decision(
            item_id="nv1",
            bucket_origin="needs_validation",
            decision=DecisionStatus.SKIPPED,
            decided_at=datetime.now(timezone.utc),
            decided_via="cli",
        )
    )
    service = MigrationReviewService(
        plan=plan,
        state_store=store,
        tmdb_client=MagicMock(),
        tvdb_client=MagicMock(),
        matcher=MagicMock(),
        duplicate_detector=MagicMock(),
    )
    pending = list(service.iter_pending(resume=False))
    assert [it.item_id for it in pending] == ["nv1"]
```

- [ ] **Step 2: Run tests to verify failure**

```
uv run pytest tests/unit/services/migration/test_review_service.py -v
```
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/services/migration/review_service.py
"""
MigrationReviewService — orchestrateur de la review interactive.

Service partagé entre CLI (`migrate-nas review`) et web
(`/migration/<plan>/review`). Encapsule :
- l'itération sur les items en attente (filtrée par bucket, resume)
- l'enregistrement des décisions (delegate à MigrationStateStore)
- la recherche TMDB live (réutilise tmdb_client + MatcherService)
- la recommandation duplicate (réutilise DuplicateDetector)

Ne touche pas au plan.json (artefact immuable). Toutes les mutations
passent par la table migration_decisions.
"""

from __future__ import annotations

from typing import Iterator, Optional

from src.services.migration.dataclasses import (
    Bucket,
    MigrationItem,
    MigrationPlan,
)
from src.services.migration.state_store import MigrationStateStore


# Buckets éligibles à la review (BROKEN exclu — pas de solution UI possible).
REVIEW_BUCKETS: frozenset[Bucket] = frozenset({
    Bucket.NEEDS_VALIDATION,
    Bucket.UNRATED,
    Bucket.LOW_RATED,
    Bucket.ALREADY_IN_LIBRARY,
})


class MigrationReviewService:
    """Service métier de la review interactive (4 buckets non-MIGRATE)."""

    def __init__(
        self,
        *,
        plan: MigrationPlan,
        state_store: MigrationStateStore,
        tmdb_client,
        tvdb_client,
        matcher,
        duplicate_detector,
    ) -> None:
        self._plan = plan
        self._store = state_store
        self._tmdb = tmdb_client
        self._tvdb = tvdb_client
        self._matcher = matcher
        self._duplicate_detector = duplicate_detector

    def iter_pending(
        self,
        *,
        bucket: Optional[Bucket] = None,
        resume: bool = True,
    ) -> Iterator[MigrationItem]:
        """Yield les items en attente de décision.

        - Filtre sur `REVIEW_BUCKETS` (exclut MIGRATE, BROKEN, etc.).
        - Si `bucket` fourni, restreint à ce bucket.
        - Si `resume=True`, skippe les items avec décision déjà persistée.
        """
        decided_ids = (
            set(self._store.load_decisions().keys()) if resume else set()
        )
        for item in self._plan.items:
            if item.bucket not in REVIEW_BUCKETS:
                continue
            if bucket is not None and item.bucket != bucket:
                continue
            if item.item_id in decided_ids:
                continue
            yield item
```

- [ ] **Step 4: Run tests to verify pass**

```
uv run pytest tests/unit/services/migration/test_review_service.py -v
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/services/migration/review_service.py tests/unit/services/migration/test_review_service.py
git commit -m "feat(migration review_service): squelette + iter_pending"
```

---

### Task 4: `MigrationReviewService.decide` + `summary`

**Files:**
- Modify: `src/services/migration/review_service.py` (append methods)
- Test: `tests/unit/services/migration/test_review_service.py` (append tests)

- [ ] **Step 1: Write the failing tests**

Append :

```python
def test_decide_persists_via_state_store(store):
    plan = _plan([_item("nv1", Bucket.NEEDS_VALIDATION)])
    service = MigrationReviewService(
        plan=plan, state_store=store,
        tmdb_client=MagicMock(), tvdb_client=MagicMock(),
        matcher=MagicMock(), duplicate_detector=MagicMock(),
    )
    service.decide(
        item_id="nv1",
        decision=DecisionStatus.APPROVED,
        chosen_tmdb_id=19995,
        chosen_title="Avatar",
        chosen_year=2009,
        chosen_score=95.0,
        decided_via="cli",
    )
    loaded = store.get_decision("nv1")
    assert loaded.chosen_tmdb_id == 19995
    assert loaded.bucket_origin == "needs_validation"  # auto-rempli depuis l'item


def test_decide_unknown_item_id_raises(store):
    plan = _plan([_item("nv1", Bucket.NEEDS_VALIDATION)])
    service = MigrationReviewService(
        plan=plan, state_store=store,
        tmdb_client=MagicMock(), tvdb_client=MagicMock(),
        matcher=MagicMock(), duplicate_detector=MagicMock(),
    )
    with pytest.raises(KeyError, match="unknown"):
        service.decide(
            item_id="unknown",
            decision=DecisionStatus.SKIPPED,
            decided_via="cli",
        )


def test_summary_combines_pending_and_decided(store):
    plan = _plan([
        _item("nv1", Bucket.NEEDS_VALIDATION),
        _item("nv2", Bucket.NEEDS_VALIDATION),
        _item("u1", Bucket.UNRATED),
    ])
    service = MigrationReviewService(
        plan=plan, state_store=store,
        tmdb_client=MagicMock(), tvdb_client=MagicMock(),
        matcher=MagicMock(), duplicate_detector=MagicMock(),
    )
    service.decide(
        item_id="nv1",
        decision=DecisionStatus.APPROVED,
        chosen_tmdb_id=1,
        decided_via="cli",
    )
    summary = service.summary()
    assert summary["pending"] == 2
    assert summary["approved"] == 1
    assert summary["total_review_buckets"] == 3
```

- [ ] **Step 2: Run failing**

```
uv run pytest tests/unit/services/migration/test_review_service.py -v -k "decide or summary"
```
Expected: FAIL `AttributeError: ... 'decide'`.

- [ ] **Step 3: Implement**

Append to `src/services/migration/review_service.py` :

```python
    def decide(
        self,
        *,
        item_id: str,
        decision,  # DecisionStatus
        decided_via: str,
        chosen_tmdb_id: Optional[int] = None,
        chosen_tvdb_id: Optional[int] = None,
        chosen_title: Optional[str] = None,
        chosen_year: Optional[int] = None,
        chosen_score: Optional[float] = None,
        duplicate_action=None,  # DuplicateAction
        delete_source_after: bool = False,
        reason: Optional[str] = None,
    ) -> None:
        """Persiste une décision sur un item du plan.

        Auto-rempli `bucket_origin` depuis le bucket actuel de l'item
        (informationnel pour audit). Idempotent.
        """
        from datetime import datetime, timezone

        from src.services.migration.decisions import Decision

        item = self._find_item(item_id)
        self._store.save_decision(
            Decision(
                item_id=item_id,
                bucket_origin=item.bucket.value,
                decision=decision,
                chosen_tmdb_id=chosen_tmdb_id,
                chosen_tvdb_id=chosen_tvdb_id,
                chosen_title=chosen_title,
                chosen_year=chosen_year,
                chosen_score=chosen_score,
                duplicate_action=duplicate_action,
                delete_source_after=delete_source_after,
                reason=reason,
                decided_at=datetime.now(timezone.utc),
                decided_via=decided_via,
            )
        )

    def summary(self) -> dict[str, int]:
        """Retourne le récap : pending vs décidés (par status)."""
        from src.services.migration.decisions import DecisionStatus

        review_items = [
            it for it in self._plan.items if it.bucket in REVIEW_BUCKETS
        ]
        decisions = self._store.load_decisions()
        decided_ids = set(decisions.keys())
        pending = sum(1 for it in review_items if it.item_id not in decided_ids)
        out: dict[str, int] = {
            "total_review_buckets": len(review_items),
            "pending": pending,
        }
        for status in DecisionStatus:
            out[status.value] = sum(
                1 for d in decisions.values() if d.decision == status
            )
        return out

    def _find_item(self, item_id: str) -> MigrationItem:
        for it in self._plan.items:
            if it.item_id == item_id:
                return it
        raise KeyError(f"unknown item_id: {item_id}")
```

- [ ] **Step 4: Run pass**

```
uv run pytest tests/unit/services/migration/test_review_service.py -v
```
Expected: PASS (7 tests now).

- [ ] **Step 5: Commit**

```bash
git add src/services/migration/review_service.py tests/unit/services/migration/test_review_service.py
git commit -m "feat(migration review_service): decide() + summary()"
```

---

### Task 5: `MigrationReviewService.search_tmdb` (live TMDB lookup)

**Files:**
- Modify: `src/services/migration/review_service.py` (append `search_tmdb`)
- Test: `tests/unit/services/migration/test_review_service.py` (append)

- [ ] **Step 1: Failing test**

Append :

```python
import asyncio


def test_search_tmdb_movies_uses_tmdb_client_and_matcher(store):
    from src.core.ports.api_clients import SearchResult

    plan = _plan([])
    fake_tmdb = MagicMock()
    fake_tmdb.search = MagicMock()
    raw_results = [
        SearchResult(id="1", title="Foo", year=2020, score=0, source="tmdb"),
        SearchResult(id="2", title="Bar", year=2021, score=0, source="tmdb"),
    ]
    # tmdb_client.search est async — utilise AsyncMock
    from unittest.mock import AsyncMock
    fake_tmdb.search = AsyncMock(return_value=raw_results)
    fake_matcher = MagicMock()
    scored = [
        SearchResult(id="1", title="Foo", year=2020, score=92.0, source="tmdb"),
        SearchResult(id="2", title="Bar", year=2021, score=58.0, source="tmdb"),
    ]
    fake_matcher.score_results = MagicMock(return_value=scored)

    service = MigrationReviewService(
        plan=plan, state_store=store,
        tmdb_client=fake_tmdb, tvdb_client=MagicMock(),
        matcher=fake_matcher, duplicate_detector=MagicMock(),
    )
    results = asyncio.run(
        service.search_tmdb(query="Foo", is_series=False, year=None)
    )
    assert len(results) == 2
    assert results[0].score == 92.0
    fake_tmdb.search.assert_called_once_with("Foo", year=None)
    fake_matcher.score_results.assert_called_once_with(
        raw_results, query_title="Foo", query_year=None, is_series=False
    )


def test_search_tmdb_series_uses_search_tv(store):
    from unittest.mock import AsyncMock

    plan = _plan([])
    fake_tmdb = MagicMock()
    fake_tmdb.search_tv = AsyncMock(return_value=[])
    fake_matcher = MagicMock()
    fake_matcher.score_results = MagicMock(return_value=[])

    service = MigrationReviewService(
        plan=plan, state_store=store,
        tmdb_client=fake_tmdb, tvdb_client=MagicMock(),
        matcher=fake_matcher, duplicate_detector=MagicMock(),
    )
    asyncio.run(service.search_tmdb(query="GoT", is_series=True, year=2011))
    fake_tmdb.search_tv.assert_called_once_with("GoT", year=2011)
```

- [ ] **Step 2: Failing**

```
uv run pytest tests/unit/services/migration/test_review_service.py -v -k "search_tmdb"
```
Expected: FAIL `AttributeError ... 'search_tmdb'`.

- [ ] **Step 3: Implement**

Append :

```python
    async def search_tmdb(
        self,
        *,
        query: str,
        is_series: bool,
        year: Optional[int] = None,
    ):
        """Recherche TMDB live + scoring. Retourne list[SearchResult] scorée.

        Pour les films : `tmdb_client.search(query, year)`.
        Pour les séries : `tmdb_client.search_tv(query, year)`.
        Pas de fallback TVDB ici — l'utilisateur peut chercher par ID
        externe via `validation_service.search_by_external_id` si besoin.
        """
        if is_series:
            raw = await self._tmdb.search_tv(query, year=year)
        else:
            raw = await self._tmdb.search(query, year=year)
        return self._matcher.score_results(
            raw, query_title=query, query_year=year, is_series=is_series
        )
```

- [ ] **Step 4: Pass**

```
uv run pytest tests/unit/services/migration/test_review_service.py -v
```
Expected: PASS (9 tests now).

- [ ] **Step 5: Commit**

```bash
git add src/services/migration/review_service.py tests/unit/services/migration/test_review_service.py
git commit -m "feat(migration review_service): search_tmdb live (films + séries)"
```

---

### Task 6: `MigrationReviewService.duplicate_recommendation`

**Files:**
- Modify: `src/services/migration/review_service.py` (append)
- Test: `tests/unit/services/migration/test_review_service.py` (append)

- [ ] **Step 1: Failing test**

Append :

```python
def test_duplicate_recommendation_uses_compare_quality(store, tmp_path):
    """already_in_library : compare source NAS vs file en DB via DuplicateDetector."""
    from src.services.duplicate_detector import (
        ExistingFileInfo,
        QualityComparison,
    )

    # Création de 2 fichiers réels (le service ouvre les paths pour mediainfo)
    src = tmp_path / "source.mkv"
    src.write_bytes(b"\x00" * 1024)
    dst = tmp_path / "dest.mkv"
    dst.write_bytes(b"\x00" * 2048)

    item = _item("ail-1", Bucket.ALREADY_IN_LIBRARY,
                 source_path=src,
                 tags=[f"existing:{dst}"])
    plan = _plan([item])

    fake_dd = MagicMock()
    fake_dd.compare_quality = MagicMock(
        return_value=QualityComparison(
            recommended="new",
            existing_score=80.0,
            new_score=92.0,
            existing_breakdown=[],
            new_breakdown={},
        )
    )

    service = MigrationReviewService(
        plan=plan, state_store=store,
        tmdb_client=MagicMock(), tvdb_client=MagicMock(),
        matcher=MagicMock(), duplicate_detector=fake_dd,
    )
    reco = service.duplicate_recommendation(item)
    assert reco.recommended == "new"  # source NAS gagne
    assert fake_dd.compare_quality.called
    # Vérifie que les ExistingFileInfo passés ont les bons chemins
    call_args = fake_dd.compare_quality.call_args
    existing_files, new_file = call_args.args
    assert new_file.path == src
    assert existing_files[0].path == dst
```

- [ ] **Step 2: Failing**

```
uv run pytest tests/unit/services/migration/test_review_service.py -v -k "duplicate"
```
Expected: FAIL `AttributeError ... 'duplicate_recommendation'`.

- [ ] **Step 3: Implement**

Append :

```python
    def duplicate_recommendation(self, item: MigrationItem):
        """Pour un item already_in_library : score qualité source vs dest.

        Lit le tag `existing:<path>` posé par le plan_builder. Délègue le
        scoring au DuplicateDetector existant via `compare_quality`.
        Retourne un `QualityComparison` (recommended="new"|"old", scores,
        breakdowns pour affichage).
        """
        from pathlib import Path

        from src.services.duplicate_detector import ExistingFileInfo

        existing_path: Optional[Path] = None
        for tag in item.tags:
            if tag.startswith("existing:"):
                existing_path = Path(tag.split(":", 1)[1])
                break
        if existing_path is None:
            raise ValueError(
                f"item {item.item_id} sans tag 'existing:' — pas un doublon"
            )
        if item.source_path is None:
            raise ValueError(f"item {item.item_id} sans source_path")

        # Construit les ExistingFileInfo via mediainfo extraction
        # (réutilise les helpers internes — voir _build_existing_file_info).
        new_info = _build_existing_file_info(item.source_path)
        existing_info = _build_existing_file_info(existing_path)
        return self._duplicate_detector.compare_quality(
            [existing_info], new_info
        )
```

Add module-level helper above the class :

```python
def _build_existing_file_info(path):
    """Construit un ExistingFileInfo minimaliste pour compare_quality.

    Réutilise pymediainfo via le pattern existant (cf duplicate_detector).
    Si mediainfo échoue, retourne un info avec juste path + size.
    """
    from src.services.duplicate_detector import ExistingFileInfo

    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    info = ExistingFileInfo(
        path=path,
        size_bytes=size,
        resolution=None,
        video_codec=None,
        audio_codec=None,
        video_bitrate_kbps=None,
        audio_bitrate_kbps=None,
        duration_seconds=None,
    )
    # Best-effort enrichment via mediainfo (optionnel — compare_quality
    # tolère les champs None et tombe sur la taille comme proxy).
    try:
        from pymediainfo import MediaInfo

        mi = MediaInfo.parse(str(path))
        for track in mi.tracks:
            if track.track_type == "Video" and info.resolution is None:
                if track.height:
                    info.resolution = f"{track.height}p"
                info.video_codec = track.codec_id or track.format
                if track.bit_rate:
                    info.video_bitrate_kbps = int(track.bit_rate) // 1000
                if track.duration:
                    info.duration_seconds = int(track.duration) // 1000
            if track.track_type == "Audio" and info.audio_codec is None:
                info.audio_codec = track.codec_id or track.format
                if track.bit_rate:
                    info.audio_bitrate_kbps = int(track.bit_rate) // 1000
    except Exception:  # noqa: BLE001 — mediainfo optionnel, fallback taille
        pass
    return info
```

- [ ] **Step 4: Pass**

```
uv run pytest tests/unit/services/migration/test_review_service.py -v
```
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add src/services/migration/review_service.py tests/unit/services/migration/test_review_service.py
git commit -m "feat(migration review_service): duplicate_recommendation via DuplicateDetector"
```

---

## Phase 44.2 — CLI loop (needs_validation)

### Task 7: CLI scaffold + Typer registration

**Files:**
- Create: `src/adapters/cli/commands/migrate_nas_command/review.py`
- Modify: `src/adapters/cli/commands/migrate_nas_command/commands.py` (register `review_command`)
- Modify: `src/adapters/cli/commands/migrate_nas_command/__init__.py` (re-export)
- Test: `tests/unit/adapters/cli/test_migrate_nas_review.py`

- [ ] **Step 1: Failing test**

```python
# tests/unit/adapters/cli/test_migrate_nas_review.py
"""Tests pour la commande CLI `migrate-nas review`."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.adapters.cli.commands.migrate_nas_command import migrate_nas_app


def test_review_command_help():
    """`migrate-nas review --help` doit afficher l'usage sans erreur."""
    runner = CliRunner()
    result = runner.invoke(migrate_nas_app, ["review", "--help"])
    assert result.exit_code == 0
    assert "review" in result.stdout.lower()
    assert "--bucket" in result.stdout
    assert "--resume" in result.stdout
```

- [ ] **Step 2: Failing**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py -v
```
Expected: FAIL `No such command 'review'`.

- [ ] **Step 3: Create review.py with stub**

```python
# src/adapters/cli/commands/migrate_nas_command/review.py
"""
Sous-commande `migrate-nas review` : review interactive des items en attente.

Itère sur les 4 buckets non-MIGRATE (needs_validation, unrated, low_rated,
already_in_library), affiche une carte Rich par item, prompt l'utilisateur
pour une décision. Décisions persistées dans state_store, consultables
ensuite par `migrate-nas apply`.

Reprise via --resume (skippe les items déjà décidés).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from src.adapters.cli.validation import console
from src.services.migration.dataclasses import Bucket
from src.services.migration.plan_builder import deserialize_plan
from src.services.migration.state_store import MigrationStateStore


def review_command(
    plan_path: Annotated[
        Path,
        typer.Argument(help="Chemin du plan JSON produit par `plan`."),
    ],
    bucket: Annotated[
        Optional[str],
        typer.Option(
            "--bucket",
            help=(
                "Filtre sur un bucket précis (needs_validation, unrated, "
                "low_rated, already_in_library). Défaut : tous."
            ),
        ),
    ] = None,
    resume: Annotated[
        bool,
        typer.Option(
            "--resume/--restart",
            help=(
                "Reprend en sautant les items déjà décidés (défaut). "
                "--restart force le re-traitement de tous."
            ),
        ),
    ] = True,
    state_store: Annotated[
        Optional[Path],
        typer.Option(
            "--state-store",
            help="Chemin du journal SQLite (défaut: <plan>.state.sqlite).",
        ),
    ] = None,
) -> None:
    """Review interactive des items en attente (4 buckets non-MIGRATE)."""
    state_path = state_store or plan_path.with_suffix(
        plan_path.suffix + ".state.sqlite"
    )
    bucket_filter = Bucket(bucket) if bucket else None
    console.print(
        f"[bold cyan]Review[/bold cyan] depuis [yellow]{plan_path}[/yellow] "
        f"(state: [dim]{state_path}[/dim], "
        f"bucket: {bucket_filter.value if bucket_filter else 'tous'}, "
        f"resume: {resume})"
    )
    # TODO Task 9 : interactive loop
    console.print("[yellow]Pas encore implémenté — Task 9 fournit la loop.[/yellow]")
```

- [ ] **Step 4: Register dans `commands.py`**

Append à `src/adapters/cli/commands/migrate_nas_command/commands.py` après `status_command` :

```python
from src.adapters.cli.commands.migrate_nas_command.review import review_command

migrate_nas_app.command("review")(review_command)
```

- [ ] **Step 5: Run test**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/adapters/cli/commands/migrate_nas_command/review.py src/adapters/cli/commands/migrate_nas_command/commands.py tests/unit/adapters/cli/test_migrate_nas_review.py
git commit -m "feat(migrate-nas CLI): scaffold review_command (Typer registration + stub)"
```

---

### Task 8: `render_review_card` for needs_validation bucket

**Files:**
- Modify: `src/adapters/cli/commands/migrate_nas_command/review.py` (add render fn)
- Test: `tests/unit/adapters/cli/test_migrate_nas_review.py` (append)

- [ ] **Step 1: Failing test**

Append :

```python
from io import StringIO
from pathlib import Path

from rich.console import Console

from src.adapters.cli.commands.migrate_nas_command.review import (
    render_review_card,
)
from src.services.migration.dataclasses import (
    Bucket,
    MatchInfo,
    MigrationItem,
    RatingDecision,
)


def _nv_item():
    return MigrationItem(
        item_id="nv1",
        bucket=Bucket.NEEDS_VALIDATION,
        symlink_path=Path("/old/Wrong.mkv"),
        source_path=Path("/old/Wrong.mkv"),
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1_500_000_000,
        rating=RatingDecision(),
        match=MatchInfo(
            top_candidates=[
                {"title": "Wrong", "year": 2012, "score": 67.0,
                 "source": "tmdb", "tmdb_id": 83186},
                {"title": "Détour mortel", "year": 2003, "score": 44.67,
                 "source": "tmdb", "tmdb_id": 9902},
            ]
        ),
        is_symlink_source=False,
    )


def test_render_review_card_needs_validation_shows_top_candidates():
    item = _nv_item()
    buf = StringIO()
    console = Console(file=buf, width=100, force_terminal=False)
    render_review_card(console, item, position=(42, 140))
    out = buf.getvalue()
    assert "Wrong.mkv" in out
    assert "Wrong" in out and "2012" in out
    assert "67" in out  # score top
    assert "Détour mortel" in out
    assert "42/140" in out  # position
    assert "needs_validation" in out
```

- [ ] **Step 2: Failing**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py::test_render_review_card_needs_validation_shows_top_candidates -v
```
Expected: FAIL `ImportError`.

- [ ] **Step 3: Implement**

Append to `review.py` :

```python
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.services.migration.dataclasses import MigrationItem


def render_review_card(
    console: Console,
    item: MigrationItem,
    *,
    position: tuple[int, int],
) -> None:
    """Affiche une carte Rich pour un item en attente.

    Format :
        ┌─ [N/total] bucket • media_root ─────────────┐
        │ Source : <path> (size MB)                    │
        │ Top candidates TMDB :                        │
        │   1. Title (year) score N                    │
        └──────────────────────────────────────────────┘
    """
    pos_n, pos_total = position
    bucket = item.bucket.value
    title_line = f"[{pos_n}/{pos_total}] {bucket} • {item.media_root or '?'}"

    size_mb = (item.size_bytes or 0) / (1024**2)
    body_lines = [
        f"[dim]Source :[/dim] {item.symlink_path}  ({size_mb:.0f} MB)",
    ]

    if item.bucket == Bucket.NEEDS_VALIDATION:
        body_lines.append("")
        body_lines.append("[bold]Top candidates TMDB :[/bold]")
        for i, c in enumerate(item.match.top_candidates[:5], start=1):
            title = c.get("title", "?")
            year = c.get("year", "?")
            score = c.get("score", 0.0)
            body_lines.append(
                f"  {i}. {title:<40} ({year}) score {score:.0f}"
            )
    elif item.bucket == Bucket.UNRATED:
        body_lines.append("[yellow]Note absente — décider de migrer.[/yellow]")
    elif item.bucket == Bucket.LOW_RATED:
        rating = item.rating.value
        body_lines.append(
            f"[yellow]Note {rating} (< seuil) — décider de migrer.[/yellow]"
        )
    elif item.bucket == Bucket.ALREADY_IN_LIBRARY:
        existing = next(
            (t.split(":", 1)[1] for t in item.tags if t.startswith("existing:")),
            "?",
        )
        body_lines.append(f"[cyan]Doublon — existe déjà :[/cyan] {existing}")

    console.print(
        Panel(
            "\n".join(body_lines),
            title=title_line,
            border_style="cyan",
        )
    )
```

- [ ] **Step 4: Pass**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adapters/cli/commands/migrate_nas_command/review.py tests/unit/adapters/cli/test_migrate_nas_review.py
git commit -m "feat(migrate-nas review): render_review_card pour les 4 buckets"
```

---

### Task 9: Interactive loop with `[a]/[1-5]/[r]/[k]/[q]` actions (needs_validation)

**Files:**
- Modify: `src/adapters/cli/commands/migrate_nas_command/review.py`
- Test: `tests/unit/adapters/cli/test_migrate_nas_review.py`

- [ ] **Step 1: Failing test (drive the loop with mocked input)**

Append :

```python
from unittest.mock import patch
from typer.testing import CliRunner


def _write_plan_with_nv(tmp_path):
    """Crée un plan minimal avec 1 item needs_validation, retourne paths."""
    from src.services.migration.dataclasses import (
        MigrationPlan,
        MigrationStats,
    )
    from src.services.migration.plan_builder import serialize_plan

    item = _nv_item()
    plan = MigrationPlan(
        version=1,
        source_root=Path("/src"),
        destination_root=Path("/dst"),
        threshold=6.0,
        stats=MigrationStats(),
        items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    return plan_path, item


def test_review_loop_accept_top_persists_decision(tmp_path):
    """User tape 'a' → décision approved avec match du top candidate."""
    from src.services.migration.state_store import MigrationStateStore
    from src.services.migration.decisions import DecisionStatus

    plan_path, item = _write_plan_with_nv(tmp_path)
    state_path = tmp_path / "s.sqlite"
    runner = CliRunner()
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="a\n",  # accept top
    )
    assert result.exit_code == 0, result.output
    store = MigrationStateStore(state_path)
    decision = store.get_decision(item.item_id)
    assert decision is not None
    assert decision.decision == DecisionStatus.APPROVED
    assert decision.chosen_tmdb_id == 83186  # top candidate id
    assert decision.chosen_score == 67.0
    store.close()


def test_review_loop_pick_candidate_by_number(tmp_path):
    """User tape '2' → décision approved avec match du 2e candidate."""
    from src.services.migration.state_store import MigrationStateStore

    plan_path, item = _write_plan_with_nv(tmp_path)
    state_path = tmp_path / "s.sqlite"
    runner = CliRunner()
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="2\n",
    )
    assert result.exit_code == 0
    store = MigrationStateStore(state_path)
    decision = store.get_decision(item.item_id)
    assert decision.chosen_tmdb_id == 9902  # 2e candidate (Détour mortel)
    store.close()


def test_review_loop_skip_persists_skipped(tmp_path):
    from src.services.migration.state_store import MigrationStateStore
    from src.services.migration.decisions import DecisionStatus

    plan_path, item = _write_plan_with_nv(tmp_path)
    state_path = tmp_path / "s.sqlite"
    runner = CliRunner()
    runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="k\n",
    )
    store = MigrationStateStore(state_path)
    assert store.get_decision(item.item_id).decision == DecisionStatus.SKIPPED
    store.close()


def test_review_loop_quit_stops_iteration(tmp_path):
    """Avec 2 items, taper 'q' au 1er ne décide rien."""
    from src.services.migration.dataclasses import (
        MigrationPlan,
        MigrationStats,
    )
    from src.services.migration.plan_builder import serialize_plan
    from src.services.migration.state_store import MigrationStateStore

    items = [_nv_item(), _nv_item()]
    items[1] = MigrationItem(
        item_id="nv2",
        bucket=Bucket.NEEDS_VALIDATION,
        symlink_path=Path("/old/Other.mkv"),
        source_path=Path("/old/Other.mkv"),
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1000,
        rating=RatingDecision(),
        match=MatchInfo(top_candidates=[]),
        is_symlink_source=False,
    )
    plan = MigrationPlan(
        version=1, source_root=Path("/src"), destination_root=Path("/dst"),
        threshold=6.0, stats=MigrationStats(), items=items,
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "s.sqlite"

    runner = CliRunner()
    runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="q\n",
    )
    store = MigrationStateStore(state_path)
    assert store.get_decision("nv1") is None
    assert store.get_decision("nv2") is None
    store.close()
```

- [ ] **Step 2: Failing**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py -v -k "loop"
```
Expected: FAIL — current stub doesn't implement loop.

- [ ] **Step 3: Implement the loop**

Replace `review_command` body (the stub `# TODO Task 9` part) with the actual loop. Add helpers above :

```python
from rich.prompt import Prompt

from src.container import Container
from src.services.matcher import MatcherService
from src.services.duplicate_detector import DuplicateDetector
from src.services.migration.decisions import DecisionStatus
from src.services.migration.review_service import MigrationReviewService


def _build_review_service(plan_path: Path, state_path: Path) -> tuple:
    """Câble le ReviewService depuis le container. Retourne (service, store)."""
    plan = deserialize_plan(plan_path.read_text(encoding="utf-8"))
    store = MigrationStateStore(state_path)
    container = Container()
    service = MigrationReviewService(
        plan=plan,
        state_store=store,
        tmdb_client=container.tmdb_client(),
        tvdb_client=container.tvdb_client(),
        matcher=MatcherService(),
        duplicate_detector=DuplicateDetector(),
    )
    return service, store


def _handle_needs_validation(
    service: MigrationReviewService,
    item: MigrationItem,
) -> str:
    """Prompt + dispatch action pour un item needs_validation.

    Retourne 'continue' (item suivant), 'quit' (sortie loop), ou 'redraw'
    (re-affiche la même carte — typiquement après search).
    """
    candidates = item.match.top_candidates[:5]
    valid_keys = ["a", "r", "k", "q"]
    valid_keys.extend(str(i) for i in range(1, len(candidates) + 1))
    answer = Prompt.ask(
        "[a]ccept top  [1-N] pick  [r]eject  [k]eep skip  [q]uit",
        choices=valid_keys,
        default="a",
        show_choices=False,
    )

    if answer == "q":
        return "quit"
    if answer == "k":
        service.decide(
            item_id=item.item_id,
            decision=DecisionStatus.SKIPPED,
            decided_via="cli",
        )
        return "continue"
    if answer == "r":
        reason = Prompt.ask("Raison du rejet (optionnelle)", default="")
        service.decide(
            item_id=item.item_id,
            decision=DecisionStatus.REJECTED,
            reason=reason or None,
            decided_via="cli",
        )
        return "continue"
    if answer == "a":
        chosen = candidates[0] if candidates else None
    else:  # "1".."5"
        chosen = candidates[int(answer) - 1]
    if chosen is None:
        console.print("[red]Pas de candidat — utilise 's'earch ou 'k'eep skip.[/red]")
        return "redraw"

    service.decide(
        item_id=item.item_id,
        decision=DecisionStatus.APPROVED,
        chosen_tmdb_id=chosen.get("tmdb_id"),
        chosen_tvdb_id=chosen.get("tvdb_id"),
        chosen_title=chosen.get("title"),
        chosen_year=chosen.get("year"),
        chosen_score=chosen.get("score"),
        decided_via="cli",
    )
    return "continue"
```

Then replace the stub at the end of `review_command` :

```python
    service, store = _build_review_service(plan_path, state_path)
    try:
        items = list(service.iter_pending(bucket=bucket_filter, resume=resume))
        total = len(items)
        if total == 0:
            console.print("[yellow]Aucun item en attente — rien à reviewer.[/yellow]")
            return
        for idx, item in enumerate(items, start=1):
            while True:
                render_review_card(console, item, position=(idx, total))
                if item.bucket == Bucket.NEEDS_VALIDATION:
                    result = _handle_needs_validation(service, item)
                else:
                    # Tasks 12-14 : autres buckets
                    console.print(
                        f"[yellow]Bucket {item.bucket.value} pas encore "
                        "supporté — Tasks 12-14.[/yellow]"
                    )
                    result = "continue"
                if result == "quit":
                    console.print("\n[cyan]Sortie demandée.[/cyan]")
                    return
                if result == "continue":
                    break
                # "redraw" → re-affiche le même item
    finally:
        store.close()
```

- [ ] **Step 4: Pass**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py -v
```
Expected: PASS (4 loop tests + 2 setup tests).

- [ ] **Step 5: Commit**

```bash
git add src/adapters/cli/commands/migrate_nas_command/review.py tests/unit/adapters/cli/test_migrate_nas_review.py
git commit -m "feat(migrate-nas review): loop interactive needs_validation (a/N/r/k/q)"
```

---

## Phase 44.3 — Search action

### Task 10: `[s]earch` action — TMDB live lookup

**Files:**
- Modify: `src/adapters/cli/commands/migrate_nas_command/review.py`
- Test: `tests/unit/adapters/cli/test_migrate_nas_review.py`

- [ ] **Step 1: Failing test (mock TMDB via service injection)**

Append :

```python
def test_review_loop_search_replaces_candidates(tmp_path, monkeypatch):
    """User tape 's' → prompt "Wrong Turn" → search live → choisir nouveau candidat."""
    from src.core.ports.api_clients import SearchResult
    from src.services.migration.state_store import MigrationStateStore
    from unittest.mock import AsyncMock

    plan_path, item = _write_plan_with_nv(tmp_path)
    state_path = tmp_path / "s.sqlite"

    # Patch ReviewService.search_tmdb pour retourner un nouveau candidat
    new_results = [
        SearchResult(id="9902", title="Détour mortel", year=2003,
                     score=98.0, source="tmdb"),
    ]

    async def fake_search(*args, **kwargs):
        return new_results

    monkeypatch.setattr(
        "src.services.migration.review_service.MigrationReviewService.search_tmdb",
        fake_search,
    )

    runner = CliRunner()
    # Inputs : 's' → "Wrong Turn" → '1' (choisir 1er résultat search)
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="s\nWrong Turn\n1\n",
    )
    assert result.exit_code == 0, result.output
    store = MigrationStateStore(state_path)
    decision = store.get_decision(item.item_id)
    assert decision.chosen_tmdb_id == 9902
    assert decision.chosen_title == "Détour mortel"
    store.close()
```

- [ ] **Step 2: Failing**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py::test_review_loop_search_replaces_candidates -v
```
Expected: FAIL (current loop doesn't accept 's').

- [ ] **Step 3: Implement search action**

Modify `_handle_needs_validation` :

```python
def _handle_needs_validation(
    service: MigrationReviewService,
    item: MigrationItem,
) -> str:
    candidates = item.match.top_candidates[:5]
    valid_keys = ["a", "r", "k", "q", "s"]
    valid_keys.extend(str(i) for i in range(1, len(candidates) + 1))
    answer = Prompt.ask(
        "[a]ccept top  [1-N] pick  [s]earch  [r]eject  [k]eep skip  [q]uit",
        choices=valid_keys,
        default="a",
        show_choices=False,
    )

    if answer == "q":
        return "quit"
    if answer == "k":
        service.decide(
            item_id=item.item_id,
            decision=DecisionStatus.SKIPPED,
            decided_via="cli",
        )
        return "continue"
    if answer == "r":
        reason = Prompt.ask("Raison du rejet (optionnelle)", default="")
        service.decide(
            item_id=item.item_id,
            decision=DecisionStatus.REJECTED,
            reason=reason or None,
            decided_via="cli",
        )
        return "continue"
    if answer == "s":
        return _handle_search_then_pick(service, item)
    if answer == "a":
        chosen = candidates[0] if candidates else None
    else:
        chosen = candidates[int(answer) - 1]
    if chosen is None:
        console.print("[red]Pas de candidat — utilise 's'earch ou 'k'eep skip.[/red]")
        return "redraw"
    _persist_approved(service, item, chosen)
    return "continue"


def _handle_search_then_pick(
    service: MigrationReviewService,
    item: MigrationItem,
) -> str:
    """Prompt nouveau titre, lance search TMDB, présente résultats, capture choix."""
    import asyncio

    query = Prompt.ask("Nouveau titre")
    if not query.strip():
        console.print("[yellow]Recherche annulée.[/yellow]")
        return "redraw"

    is_series = (item.media_root or "").lower().startswith(
        ("seri", "séri", "anim")
    )
    results = asyncio.run(
        service.search_tmdb(query=query.strip(), is_series=is_series)
    )
    if not results:
        console.print("[red]Aucun résultat TMDB.[/red]")
        return "redraw"

    console.print("[bold]Résultats TMDB :[/bold]")
    for i, r in enumerate(results[:5], start=1):
        console.print(f"  {i}. {r.title:<40} ({r.year}) score {r.score:.0f}")

    pick = Prompt.ask(
        "Choisir [1-N] ou 'b' pour revenir",
        choices=[*[str(i) for i in range(1, min(5, len(results)) + 1)], "b"],
        default="b",
    )
    if pick == "b":
        return "redraw"

    chosen_result = results[int(pick) - 1]
    chosen = {
        "title": chosen_result.title,
        "year": chosen_result.year,
        "score": chosen_result.score,
        "tmdb_id": int(chosen_result.id) if chosen_result.id.isdigit() else None,
        "tvdb_id": None,
    }
    _persist_approved(service, item, chosen)
    return "continue"


def _persist_approved(
    service: MigrationReviewService,
    item: MigrationItem,
    chosen: dict,
) -> None:
    service.decide(
        item_id=item.item_id,
        decision=DecisionStatus.APPROVED,
        chosen_tmdb_id=chosen.get("tmdb_id"),
        chosen_tvdb_id=chosen.get("tvdb_id"),
        chosen_title=chosen.get("title"),
        chosen_year=chosen.get("year"),
        chosen_score=chosen.get("score"),
        decided_via="cli",
    )
```

- [ ] **Step 4: Pass**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adapters/cli/commands/migrate_nas_command/review.py tests/unit/adapters/cli/test_migrate_nas_review.py
git commit -m "feat(migrate-nas review): action [s]earch TMDB live + pick"
```

---

## Phase 44.4 — Buckets unrated/low_rated/already_in_library

### Task 11: Action handler `unrated` ([m]igrate-anyway / [s]kip)

**Files:**
- Modify: `src/adapters/cli/commands/migrate_nas_command/review.py`
- Test: `tests/unit/adapters/cli/test_migrate_nas_review.py`

- [ ] **Step 1: Failing test**

Append :

```python
def test_review_loop_unrated_migrate_anyway(tmp_path):
    """unrated + 'm' → décision APPROVED avec match déjà connu."""
    from src.services.migration.dataclasses import (
        Bucket, MigrationItem, MigrationPlan, MigrationStats,
        RatingDecision, MatchInfo,
    )
    from src.services.migration.plan_builder import serialize_plan
    from src.services.migration.state_store import MigrationStateStore
    from src.services.migration.decisions import DecisionStatus

    item = MigrationItem(
        item_id="u1",
        bucket=Bucket.UNRATED,
        symlink_path=Path("/old/Untitled.mkv"),
        source_path=Path("/old/Untitled.mkv"),
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1000,
        rating=RatingDecision(),
        match=MatchInfo(tmdb_id=12345, score=88.0,
                        top_candidates=[
                            {"title": "Some film", "year": 2020, "score": 88.0,
                             "tmdb_id": 12345, "source": "tmdb"}
                        ]),
        is_symlink_source=False,
    )
    plan = MigrationPlan(
        version=1, source_root=Path("/s"), destination_root=Path("/d"),
        threshold=6.0, stats=MigrationStats(), items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "s.sqlite"

    runner = CliRunner()
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="m\n",
    )
    assert result.exit_code == 0, result.output
    store = MigrationStateStore(state_path)
    d = store.get_decision("u1")
    assert d.decision == DecisionStatus.APPROVED
    assert d.chosen_tmdb_id == 12345  # repris du match existant
    store.close()
```

- [ ] **Step 2: Failing**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py::test_review_loop_unrated_migrate_anyway -v
```
Expected: FAIL — current handler refuses non-NEEDS_VALIDATION.

- [ ] **Step 3: Implement `_handle_unrated_or_low_rated`**

Add to `review.py` :

```python
def _handle_unrated(service, item) -> str:
    """unrated : [m]igrate-anyway (avec match du plan), [s]kip, [w]eb, [q]uit."""
    answer = Prompt.ask(
        "[m]igrate-anyway  [k]eep skip  [q]uit",
        choices=["m", "k", "q"],
        default="k",
        show_choices=False,
    )
    if answer == "q":
        return "quit"
    if answer == "k":
        service.decide(
            item_id=item.item_id,
            decision=DecisionStatus.SKIPPED,
            decided_via="cli",
        )
        return "continue"
    # "m" → APPROVED avec le match déjà identifié au plan-time
    chosen = {
        "tmdb_id": item.match.tmdb_id,
        "tvdb_id": item.match.tvdb_id,
        "title": item.match.top_candidates[0].get("title")
        if item.match.top_candidates else None,
        "year": item.match.top_candidates[0].get("year")
        if item.match.top_candidates else None,
        "score": item.match.score,
    }
    _persist_approved(service, item, chosen)
    return "continue"
```

Modify the loop dispatch :

```python
                if item.bucket == Bucket.NEEDS_VALIDATION:
                    result = _handle_needs_validation(service, item)
                elif item.bucket == Bucket.UNRATED:
                    result = _handle_unrated(service, item)
                else:
                    # Tasks 12-13 : low_rated, already_in_library
                    console.print(...)
                    result = "continue"
```

- [ ] **Step 4: Pass**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adapters/cli/commands/migrate_nas_command/review.py tests/unit/adapters/cli/test_migrate_nas_review.py
git commit -m "feat(migrate-nas review): action handler bucket unrated"
```

---

### Task 12: Action handler `low_rated` (incl. [d]elete-source-after)

**Files:**
- Modify: `src/adapters/cli/commands/migrate_nas_command/review.py`
- Test: `tests/unit/adapters/cli/test_migrate_nas_review.py`

- [ ] **Step 1: Failing test**

Append :

```python
def test_review_loop_low_rated_delete_source_after(tmp_path):
    """low_rated + 'd' → APPROVED + delete_source_after=True."""
    from src.services.migration.dataclasses import (
        Bucket, MigrationItem, MigrationPlan, MigrationStats,
        RatingDecision, MatchInfo,
    )
    from src.services.migration.plan_builder import serialize_plan
    from src.services.migration.state_store import MigrationStateStore
    from src.services.migration.decisions import DecisionStatus

    item = MigrationItem(
        item_id="lr1",
        bucket=Bucket.LOW_RATED,
        symlink_path=Path("/old/Bad.mkv"),
        source_path=Path("/old/Bad.mkv"),
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1000,
        rating=RatingDecision(value=3.5, source="imdb"),
        match=MatchInfo(tmdb_id=99, top_candidates=[
            {"title": "Bad", "year": 2010, "score": 100.0, "tmdb_id": 99,
             "source": "tmdb"}
        ]),
        is_symlink_source=False,
    )
    plan = MigrationPlan(
        version=1, source_root=Path("/s"), destination_root=Path("/d"),
        threshold=6.0, stats=MigrationStats(), items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "s.sqlite"

    runner = CliRunner()
    # 'd' → "Confirmer suppression source ? > y"
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="d\ny\n",
    )
    assert result.exit_code == 0, result.output
    store = MigrationStateStore(state_path)
    d = store.get_decision("lr1")
    assert d.decision == DecisionStatus.APPROVED
    assert d.delete_source_after is True
    store.close()
```

- [ ] **Step 2: Failing**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py::test_review_loop_low_rated_delete_source_after -v
```
Expected: FAIL.

- [ ] **Step 3: Implement**

Append to `review.py` :

```python
from rich.prompt import Confirm


def _handle_low_rated(service, item) -> str:
    """low_rated : [m]igrate-anyway, [d]elete-source-after, [k]eep skip, [q]uit."""
    answer = Prompt.ask(
        "[m]igrate-anyway  [d]elete-source-after  [k]eep skip  [q]uit",
        choices=["m", "d", "k", "q"],
        default="k",
        show_choices=False,
    )
    if answer == "q":
        return "quit"
    if answer == "k":
        service.decide(
            item_id=item.item_id,
            decision=DecisionStatus.SKIPPED,
            decided_via="cli",
        )
        return "continue"
    delete_source = False
    if answer == "d":
        # Garde-fou : confirmation explicite
        if not Confirm.ask(
            "[red]Supprimer la source APRÈS commit transfert réussi ?[/red]",
            default=False,
        ):
            console.print("[yellow]Suppression annulée.[/yellow]")
            return "redraw"
        delete_source = True
    # Match repris du plan
    top = item.match.top_candidates[0] if item.match.top_candidates else {}
    service.decide(
        item_id=item.item_id,
        decision=DecisionStatus.APPROVED,
        chosen_tmdb_id=top.get("tmdb_id") or item.match.tmdb_id,
        chosen_tvdb_id=top.get("tvdb_id") or item.match.tvdb_id,
        chosen_title=top.get("title"),
        chosen_year=top.get("year"),
        chosen_score=top.get("score") or item.match.score,
        delete_source_after=delete_source,
        decided_via="cli",
    )
    return "continue"
```

Modify dispatch :

```python
                elif item.bucket == Bucket.LOW_RATED:
                    result = _handle_low_rated(service, item)
```

- [ ] **Step 4: Pass**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adapters/cli/commands/migrate_nas_command/review.py tests/unit/adapters/cli/test_migrate_nas_review.py
git commit -m "feat(migrate-nas review): action handler bucket low_rated (+ delete_source_after avec confirmation)"
```

---

### Task 13: Action handler `already_in_library` (DuplicateDetector reco)

**Files:**
- Modify: `src/adapters/cli/commands/migrate_nas_command/review.py`
- Test: `tests/unit/adapters/cli/test_migrate_nas_review.py`

- [ ] **Step 1: Failing test**

Append :

```python
def test_review_loop_already_in_library_keep_dest(tmp_path):
    """already_in_library + 'k' → APPROVED + duplicate_action=keep_dest."""
    from src.services.migration.dataclasses import (
        Bucket, MigrationItem, MigrationPlan, MigrationStats,
        RatingDecision, MatchInfo,
    )
    from src.services.migration.plan_builder import serialize_plan
    from src.services.migration.state_store import MigrationStateStore
    from src.services.migration.decisions import (
        DecisionStatus, DuplicateAction,
    )

    src_file = tmp_path / "src.mkv"
    src_file.write_bytes(b"\x00" * 1024)
    dest_file = tmp_path / "dst.mkv"
    dest_file.write_bytes(b"\x00" * 2048)

    item = MigrationItem(
        item_id="ail1",
        bucket=Bucket.ALREADY_IN_LIBRARY,
        symlink_path=src_file,
        source_path=src_file,
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1024,
        rating=RatingDecision(),
        match=MatchInfo(tmdb_id=42),
        is_symlink_source=False,
        tags=[f"existing:{dest_file}"],
    )
    plan = MigrationPlan(
        version=1, source_root=Path("/s"), destination_root=Path("/d"),
        threshold=6.0, stats=MigrationStats(), items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "s.sqlite"

    runner = CliRunner()
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="k\n",
    )
    assert result.exit_code == 0, result.output
    store = MigrationStateStore(state_path)
    d = store.get_decision("ail1")
    assert d.decision == DecisionStatus.APPROVED
    assert d.duplicate_action == DuplicateAction.KEEP_DEST
    store.close()
```

- [ ] **Step 2: Failing**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py::test_review_loop_already_in_library_keep_dest -v
```
Expected: FAIL.

- [ ] **Step 3: Implement**

Append to `review.py` :

```python
from src.services.migration.decisions import DuplicateAction


def _handle_already_in_library(service, item) -> str:
    """already_in_library : compare source vs dest, propose action."""
    try:
        reco = service.duplicate_recommendation(item)
        reco_label = "source NAS" if reco.recommended == "new" else "dest existante"
        console.print(
            f"[bold cyan]Reco DuplicateDetector :[/bold cyan] "
            f"garder {reco_label} "
            f"(scores : new={reco.new_score:.0f} existing={reco.existing_score:.0f})"
        )
    except Exception as e:  # noqa: BLE001 — reco non bloquante
        console.print(f"[yellow]Reco indisponible : {e}[/yellow]")
        reco = None

    answer = Prompt.ask(
        "[a]ccept reco  [k]eep dest  [r]eplace dest  [d]elete source  [q]uit",
        choices=["a", "k", "r", "d", "q"],
        default="k",
        show_choices=False,
    )
    if answer == "q":
        return "quit"

    duplicate_action: Optional[DuplicateAction] = None
    if answer == "k":
        duplicate_action = DuplicateAction.KEEP_DEST
    elif answer == "r":
        if not Confirm.ask(
            "[red]Écraser la version existante en DB ?[/red]", default=False
        ):
            return "redraw"
        duplicate_action = DuplicateAction.REPLACE_DEST
    elif answer == "d":
        if not Confirm.ask(
            "[red]Supprimer la source NAS (garder la DB) ?[/red]",
            default=False,
        ):
            return "redraw"
        duplicate_action = DuplicateAction.DELETE_SOURCE
    elif answer == "a":
        if reco is None:
            console.print("[red]Pas de reco — choisir manuellement.[/red]")
            return "redraw"
        duplicate_action = (
            DuplicateAction.REPLACE_DEST
            if reco.recommended == "new"
            else DuplicateAction.KEEP_DEST
        )

    service.decide(
        item_id=item.item_id,
        decision=DecisionStatus.APPROVED,
        duplicate_action=duplicate_action,
        chosen_tmdb_id=item.match.tmdb_id,
        chosen_tvdb_id=item.match.tvdb_id,
        decided_via="cli",
    )
    return "continue"
```

Modify dispatch :

```python
                elif item.bucket == Bucket.ALREADY_IN_LIBRARY:
                    result = _handle_already_in_library(service, item)
```

- [ ] **Step 4: Pass**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adapters/cli/commands/migrate_nas_command/review.py tests/unit/adapters/cli/test_migrate_nas_review.py
git commit -m "feat(migrate-nas review): action handler bucket already_in_library (DuplicateDetector reco)"
```

---

## Phase 44.5 — Web defer + summary

### Task 14: `[w]eb` defer action

**Files:**
- Modify: `src/adapters/cli/commands/migrate_nas_command/review.py`
- Test: `tests/unit/adapters/cli/test_migrate_nas_review.py`

- [ ] **Step 1: Failing test**

Append :

```python
def test_review_loop_defer_to_web(tmp_path):
    """User tape 'w' → décision DEFERRED_TO_WEB."""
    from src.services.migration.state_store import MigrationStateStore
    from src.services.migration.decisions import DecisionStatus

    plan_path, item = _write_plan_with_nv(tmp_path)
    state_path = tmp_path / "s.sqlite"
    runner = CliRunner()
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="w\n",
    )
    assert result.exit_code == 0
    store = MigrationStateStore(state_path)
    d = store.get_decision(item.item_id)
    assert d.decision == DecisionStatus.DEFERRED_TO_WEB
    store.close()
```

- [ ] **Step 2: Failing**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py::test_review_loop_defer_to_web -v
```
Expected: FAIL.

- [ ] **Step 3: Implement — add 'w' to all 4 handlers**

Edit each `_handle_*` function : add `"w"` to the choices list and after the `q`/`k` branch :

```python
    if answer == "w":
        service.decide(
            item_id=item.item_id,
            decision=DecisionStatus.DEFERRED_TO_WEB,
            decided_via="cli",
        )
        return "continue"
```

Update prompt strings : add `[w]eb` mention.

- [ ] **Step 4: Pass**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adapters/cli/commands/migrate_nas_command/review.py tests/unit/adapters/cli/test_migrate_nas_review.py
git commit -m "feat(migrate-nas review): action [w]eb defer (tous les handlers)"
```

---

### Task 15: End-of-pass summary + URL si items deferred

**Files:**
- Modify: `src/adapters/cli/commands/migrate_nas_command/review.py`
- Test: `tests/unit/adapters/cli/test_migrate_nas_review.py`

- [ ] **Step 1: Failing test**

Append :

```python
def test_review_summary_shown_at_end(tmp_path):
    """Après quit, affiche un résumé : N approuvés, M skippés, etc."""
    plan_path, item = _write_plan_with_nv(tmp_path)
    state_path = tmp_path / "s.sqlite"
    runner = CliRunner()
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="a\n",  # accept top, fin auto (1 seul item)
    )
    assert result.exit_code == 0
    out = result.output
    assert "Session review" in out or "session" in out.lower()
    assert "1" in out  # 1 approuvé


def test_review_summary_shows_web_url_when_deferred(tmp_path):
    """Si items deferred-to-web, affiche l'URL."""
    plan_path, item = _write_plan_with_nv(tmp_path)
    state_path = tmp_path / "s.sqlite"
    runner = CliRunner()
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="w\n",
    )
    out = result.output
    assert "/migration/review" in out
```

- [ ] **Step 2: Failing**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py -v -k "summary"
```
Expected: FAIL.

- [ ] **Step 3: Implement summary**

Add helper to `review.py` :

```python
def _print_summary(
    service: MigrationReviewService,
    plan_path: Path,
    state_path: Path,
) -> None:
    """Affiche le résumé final + URL web si items deferred."""
    summary = service.summary()
    console.print()
    console.print("─" * 60)
    console.print("[bold]Session review terminée[/bold]")
    console.print(f"  Total review buckets : {summary['total_review_buckets']}")
    console.print(f"  [green]✓[/green] Approuvés : {summary.get('approved', 0)}")
    console.print(f"  [yellow]⊘[/yellow] Skippés  : {summary.get('skipped', 0)}")
    console.print(f"  [red]✗[/red] Rejetés   : {summary.get('rejected', 0)}")
    deferred = summary.get('deferred_to_web', 0)
    if deferred:
        console.print(
            f"  [cyan]↗[/cyan] Déférés web : {deferred}"
            f"\n      → http://localhost:8000/migration/review?plan={plan_path}"
        )
    pending = summary.get("pending", 0)
    if pending:
        console.print(f"  [dim]En attente : {pending} (--resume pour reprendre)[/dim]")
    else:
        console.print(
            "[green]Tous les items ont une décision.[/green] "
            f"Lance [bold]migrate-nas apply {plan_path}[/bold] pour transférer "
            "les approuvés."
        )
    console.print("─" * 60)
```

Call it at the end of the loop in `review_command`. Replace the `try: ... finally: store.close()` block to invoke `_print_summary` before the close (both on normal end and quit) :

```python
    service, store = _build_review_service(plan_path, state_path)
    try:
        items = list(service.iter_pending(bucket=bucket_filter, resume=resume))
        total = len(items)
        if total == 0:
            console.print("[yellow]Aucun item en attente — rien à reviewer.[/yellow]")
            _print_summary(service, plan_path, state_path)
            return
        for idx, item in enumerate(items, start=1):
            while True:
                render_review_card(console, item, position=(idx, total))
                if item.bucket == Bucket.NEEDS_VALIDATION:
                    result = _handle_needs_validation(service, item)
                elif item.bucket == Bucket.UNRATED:
                    result = _handle_unrated(service, item)
                elif item.bucket == Bucket.LOW_RATED:
                    result = _handle_low_rated(service, item)
                elif item.bucket == Bucket.ALREADY_IN_LIBRARY:
                    result = _handle_already_in_library(service, item)
                else:
                    result = "continue"
                if result == "quit":
                    console.print("\n[cyan]Sortie demandée.[/cyan]")
                    _print_summary(service, plan_path, state_path)
                    return
                if result == "continue":
                    break
        _print_summary(service, plan_path, state_path)
    finally:
        store.close()
```

- [ ] **Step 4: Pass**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adapters/cli/commands/migrate_nas_command/review.py tests/unit/adapters/cli/test_migrate_nas_review.py
git commit -m "feat(migrate-nas review): résumé fin de pass + URL web si items deferred"
```

---

## Phase 44.6 — Apply integration

### Task 16: `run_apply` lit decisions, hydrate match, transfère

**Files:**
- Modify: `src/adapters/cli/commands/migrate_nas_command/orchestrators.py`
- Test: `tests/unit/adapters/cli/test_migrate_nas_command.py` (append)

- [ ] **Step 1: Failing test**

Append à `tests/unit/adapters/cli/test_migrate_nas_command.py` :

```python
def test_run_apply_promotes_approved_review_items_to_migrate(
    layout, tmp_path
):
    """Un item NEEDS_VALIDATION avec décision APPROVED doit être transféré.

    Hydrate item.match depuis la décision avant de passer à raw_finalizer.
    """
    from datetime import datetime, timezone

    from src.adapters.cli.commands.migrate_nas_command import run_apply
    from src.services.migration.dataclasses import (
        Bucket, MigrationItem, MigrationPlan, MigrationStats,
        MatchInfo, RatingDecision,
    )
    from src.services.migration.decisions import Decision, DecisionStatus
    from src.services.migration.plan_builder import serialize_plan
    from src.services.migration.state_store import MigrationStateStore

    # Item raw NEEDS_VALIDATION (pas de tmdb_id résolu au plan-time)
    src = layout["source_file"]
    dest = layout["new_storage"] / "Films" / "SF" / "X" / "Avatar.mkv"
    item = MigrationItem(
        item_id="nv1",
        bucket=Bucket.NEEDS_VALIDATION,
        symlink_path=src,  # raw : source = symlink_path
        source_path=src,
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=src.stat().st_size,
        rating=RatingDecision(),
        match=MatchInfo(top_candidates=[]),
        is_symlink_source=False,
    )
    plan = MigrationPlan(
        version=1, source_root=Path("/s"),
        destination_root=layout["new_storage"],
        threshold=6.0, stats=MigrationStats(), items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))

    state_path = tmp_path / "plan.json.state.sqlite"
    store = MigrationStateStore(state_path)
    store.save_decision(
        Decision(
            item_id="nv1",
            bucket_origin="needs_validation",
            decision=DecisionStatus.APPROVED,
            chosen_tmdb_id=19995,
            chosen_title="Avatar",
            chosen_year=2009,
            chosen_score=95.0,
            decided_at=datetime.now(timezone.utc),
            decided_via="cli",
        )
    )
    store.close()

    # Lance apply avec FakeRsync + faux raw_finalizer
    rsync = FakeRsync([_Behavior(success=True, on_success=_copy_file)])
    fake_finalizer = MagicMock()
    fake_finalizer.prepare = MagicMock(return_value=dest)
    fake_finalizer.finalize = MagicMock()

    # Patch _build_raw_finalizer pour injecter le fake
    with patch(
        "src.adapters.cli.commands.migrate_nas_command.orchestrators._build_raw_finalizer",
        return_value=fake_finalizer,
    ):
        outcomes = run_apply(
            plan_path=plan_path,
            state_store_path=state_path,
            rsync_runner=rsync,
        )

    # L'item a bien été transféré (decision approved → MIGRATE virtuel)
    assert len(outcomes) == 1
    fake_finalizer.prepare.assert_called_once()
    # Le match a été hydraté depuis la décision
    item_passed = fake_finalizer.prepare.call_args.args[0]
    assert item_passed.match.tmdb_id == 19995


def test_run_apply_ignores_skipped_items(layout, tmp_path):
    """Un item SKIPPED ne doit PAS être transféré."""
    from datetime import datetime, timezone

    from src.adapters.cli.commands.migrate_nas_command import run_apply
    from src.services.migration.dataclasses import (
        Bucket, MigrationItem, MigrationPlan, MigrationStats,
        MatchInfo, RatingDecision,
    )
    from src.services.migration.decisions import Decision, DecisionStatus
    from src.services.migration.plan_builder import serialize_plan
    from src.services.migration.state_store import MigrationStateStore

    item = MigrationItem(
        item_id="nv2",
        bucket=Bucket.NEEDS_VALIDATION,
        symlink_path=layout["source_file"],
        source_path=layout["source_file"],
        destination_path=None,
        media_root="Films", relative_category="",
        size_bytes=1000, rating=RatingDecision(),
        match=MatchInfo(), is_symlink_source=False,
    )
    plan = MigrationPlan(
        version=1, source_root=Path("/s"),
        destination_root=layout["new_storage"],
        threshold=6.0, stats=MigrationStats(), items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "plan.json.state.sqlite"
    store = MigrationStateStore(state_path)
    store.save_decision(
        Decision(
            item_id="nv2", bucket_origin="needs_validation",
            decision=DecisionStatus.SKIPPED,
            decided_at=datetime.now(timezone.utc), decided_via="cli",
        )
    )
    store.close()

    rsync = FakeRsync([])  # ne doit pas être appelé
    outcomes = run_apply(
        plan_path=plan_path,
        state_store_path=state_path,
        rsync_runner=rsync,
    )
    assert outcomes == []
    assert rsync.calls == []
```

- [ ] **Step 2: Failing**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_command.py -v -k "approved or skipped"
```
Expected: FAIL — current `run_apply` ignore les buckets non-MIGRATE.

- [ ] **Step 3: Implement hydration in `run_apply`**

Edit `src/adapters/cli/commands/migrate_nas_command/orchestrators.py`. Add helper above `run_apply` :

```python
from src.services.migration.dataclasses import Bucket
from src.services.migration.decisions import DecisionStatus


def _apply_decisions_to_plan(plan, decisions: dict) -> None:
    """Mute le plan en place : items APPROVED en review-buckets → MIGRATE.

    Hydrate `item.match.tmdb_id` / `tvdb_id` depuis la décision pour que
    raw_finalizer puisse calculer la destination canonique. Items
    SKIPPED/REJECTED/DEFERRED_TO_WEB sont retirés du plan.
    """
    review_buckets = {
        Bucket.NEEDS_VALIDATION, Bucket.UNRATED,
        Bucket.LOW_RATED, Bucket.ALREADY_IN_LIBRARY,
    }
    enhanced = []
    for item in plan.items:
        if item.bucket == Bucket.MIGRATE:
            enhanced.append(item)
            continue
        if item.bucket not in review_buckets:
            enhanced.append(item)  # BROKEN, ALREADY_ON_DESTINATION, etc.
            continue
        decision = decisions.get(item.item_id)
        if decision is None or decision.decision != DecisionStatus.APPROVED:
            continue  # pending / skipped / rejected / deferred → drop
        # Hydrate match si la décision contient des choix
        if decision.chosen_tmdb_id is not None:
            item.match.tmdb_id = decision.chosen_tmdb_id
        if decision.chosen_tvdb_id is not None:
            item.match.tvdb_id = decision.chosen_tvdb_id
        item.bucket = Bucket.MIGRATE
        # Tag décisions spéciales pour raw_finalizer / post-commit hooks
        if decision.delete_source_after:
            item.tags.append("delete_source_after_commit")
        if decision.duplicate_action:
            item.tags.append(f"duplicate_action:{decision.duplicate_action.value}")
        enhanced.append(item)
    plan.items = enhanced
```

Then modify `run_apply` to call it after `init_from_plan` (but BEFORE the executor):

```python
    plan = deserialize_plan(plan_path.read_text(encoding="utf-8"))
    store = MigrationStateStore(state_store_path)
    raw_finalizer = None
    has_raw_items = any(
        not item.is_symlink_source for item in plan.items
    )
    if has_raw_items:
        raw_finalizer = _build_raw_finalizer(plan, session=session)
    try:
        # NOUVEAU : hydrate les approvés review en MIGRATE virtuels
        decisions = store.load_decisions()
        _apply_decisions_to_plan(plan, decisions)

        store.init_from_plan(plan)
        ...  # reste inchangé
```

- [ ] **Step 4: Pass**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_command.py -v
```
Expected: PASS (existing 6 + new 2).

- [ ] **Step 5: Commit**

```bash
git add src/adapters/cli/commands/migrate_nas_command/orchestrators.py tests/unit/adapters/cli/test_migrate_nas_command.py
git commit -m "feat(migrate-nas apply): hydrate les approuvés review en items MIGRATE virtuels"
```

---

### Task 17: Honor `delete_source_after_commit` tag (post-commit cleanup)

**Files:**
- Modify: `src/services/migration/transfer_executor.py` (post-commit hook)
- Test: `tests/unit/services/migration/test_transfer_executor.py` (append)

- [ ] **Step 1: Failing test**

Append :

```python
def test_delete_source_after_commit_tag_removes_source_post_commit(
    layout, store, tmp_path
):
    """Tag 'delete_source_after_commit' → source supprimée après COMMITTED."""
    from src.services.migration.dataclasses import Bucket

    item = _migrate_item(layout)
    item.tags = ["delete_source_after_commit"]
    plan = _plan([item], layout)
    store.init_from_plan(plan)
    rsync = FakeRsync([_Behavior(success=True, on_success=_copy_file)])

    executor = MigrationTransferExecutor(
        plan=plan, state_store=store, rsync_runner=rsync,
    )
    outcome = executor.execute_one(item)
    assert outcome.status == TransferStatus.COMMITTED
    # Source supprimée
    assert not layout["source_file"].exists()
    # Mais destination intacte
    assert layout["destination"].exists()


def test_no_tag_keeps_source_intact(layout, store):
    """Sans tag, comportement standard : source intacte."""
    item = _migrate_item(layout)
    plan = _plan([item], layout)
    store.init_from_plan(plan)
    rsync = FakeRsync([_Behavior(success=True, on_success=_copy_file)])

    executor = MigrationTransferExecutor(
        plan=plan, state_store=store, rsync_runner=rsync,
    )
    executor.execute_one(item)
    assert layout["source_file"].exists()  # intacte (mode symlinks default)
```

- [ ] **Step 2: Failing**

```
uv run pytest tests/unit/services/migration/test_transfer_executor.py -v -k "delete_source"
```
Expected: FAIL.

- [ ] **Step 3: Implement post-commit hook**

Edit `_finalize` method in `src/services/migration/transfer_executor.py`. After `update_status(... COMMITTED)`, add :

```python
        self._store.update_status(item.item_id, TransferStatus.COMMITTED)
        self._emit(item, "committed")

        # Post-commit cleanup : honor tag delete_source_after_commit
        # (posé par run_apply depuis Decision.delete_source_after).
        if "delete_source_after_commit" in item.tags:
            self._post_commit_delete_source(item)

        outcome = self._store.get_outcome(item.item_id)
        ...
```

Add the helper method on `MigrationTransferExecutor` :

```python
    def _post_commit_delete_source(self, item: MigrationItem) -> None:
        """Supprime la source physique après COMMITTED (low_rated [d]).

        Idempotent (FileNotFoundError ignoré). Logue toujours.
        """
        if item.source_path is None:
            return
        try:
            item.source_path.unlink()
            logger.info(
                "Source supprimée post-commit (delete_source_after_commit) : {}",
                item.source_path,
            )
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning(
                "Échec suppression source post-commit pour {} : {}",
                item.source_path, exc,
            )
```

- [ ] **Step 4: Pass**

```
uv run pytest tests/unit/services/migration/test_transfer_executor.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/services/migration/transfer_executor.py tests/unit/services/migration/test_transfer_executor.py
git commit -m "feat(migration transfer_executor): honor tag delete_source_after_commit"
```

---

### Task 18: MVP smoke test e2e

**Files:**
- Create: `tests/integration/test_migration_review_e2e.py`

- [ ] **Step 1: Write the e2e test**

```python
# tests/integration/test_migration_review_e2e.py
"""Test e2e MVP : plan synthétique → review CLI scriptée → apply."""

from pathlib import Path
from unittest.mock import patch, MagicMock

from typer.testing import CliRunner

from src.adapters.cli.commands.migrate_nas_command import migrate_nas_app
from src.services.migration.dataclasses import (
    Bucket, MigrationItem, MigrationPlan, MigrationStats,
    MatchInfo, RatingDecision,
)
from src.services.migration.plan_builder import serialize_plan
from src.services.migration.state_store import MigrationStateStore
from src.services.migration.decisions import DecisionStatus


def test_plan_to_review_to_apply_flow(tmp_path):
    """Smoke test : 1 item NV → review accept top → apply le transfère."""
    src = tmp_path / "old" / "movie.mkv"
    src.parent.mkdir()
    src.write_bytes(b"FAKE_MOVIE_CONTENT" * 1000)

    item = MigrationItem(
        item_id="e2e1",
        bucket=Bucket.NEEDS_VALIDATION,
        symlink_path=src,
        source_path=src,
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=src.stat().st_size,
        rating=RatingDecision(),
        match=MatchInfo(
            top_candidates=[
                {"title": "Avatar", "year": 2009, "score": 95.0,
                 "tmdb_id": 19995, "source": "tmdb"}
            ]
        ),
        is_symlink_source=False,
    )
    plan = MigrationPlan(
        version=1, source_root=tmp_path / "old",
        destination_root=tmp_path / "new",
        threshold=6.0, stats=MigrationStats(), items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "plan.json.state.sqlite"

    runner = CliRunner()
    # Étape 1 : review en mode "accept top"
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="a\n",
    )
    assert result.exit_code == 0, result.output

    # Vérif décision persistée
    store = MigrationStateStore(state_path)
    d = store.get_decision("e2e1")
    assert d.decision == DecisionStatus.APPROVED
    assert d.chosen_tmdb_id == 19995
    store.close()

    # Étape 2 : apply (mock raw_finalizer + rsync runner)
    fake_finalizer = MagicMock()
    fake_finalizer.prepare = MagicMock(
        return_value=tmp_path / "new" / "Avatar.mkv"
    )
    fake_finalizer.finalize = MagicMock()

    class FakeRsync:
        def run(self, source, destination, on_progress=None):
            from src.services.migration.transfer_executor import RsyncResult
            destination.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(source, destination)
            return RsyncResult(success=True)

    with patch(
        "src.adapters.cli.commands.migrate_nas_command.orchestrators._build_raw_finalizer",
        return_value=fake_finalizer,
    ):
        from src.adapters.cli.commands.migrate_nas_command import run_apply
        outcomes = run_apply(
            plan_path=plan_path,
            state_store_path=state_path,
            rsync_runner=FakeRsync(),
        )
    assert len(outcomes) == 1
    from src.services.migration.dataclasses import TransferStatus
    assert outcomes[0].status == TransferStatus.COMMITTED
    fake_finalizer.prepare.assert_called_once()
    # Le match a bien été hydraté
    item_passed = fake_finalizer.prepare.call_args.args[0]
    assert item_passed.match.tmdb_id == 19995
```

- [ ] **Step 2: Run**

```
mkdir -p tests/integration && uv run pytest tests/integration/test_migration_review_e2e.py -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_migration_review_e2e.py
git commit -m "test(migration): smoke test e2e plan→review→apply (MVP 44.6 boucle complete)"
```

**🎯 MVP livré. À ce stade, l'utilisateur peut consommer la totalité de wd10-1 sans CSV inerte.**

---

## Phase 44.7 — Web (polish)

### Task 19: Routes web liste `/migration/review`

**Files:**
- Create: `src/web/routes/migration/__init__.py`
- Create: `src/web/routes/migration/review.py`
- Create: `src/web/templates/migration/review_list.html`
- Create: `src/web/templates/migration/_review_card.html`
- Modify: `src/web/app.py` (register router)
- Test: `tests/unit/web/test_migration_review_routes.py`

- [ ] **Step 1: Failing test**

```python
# tests/unit/web/test_migration_review_routes.py
"""Tests pour les routes /migration/review."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_plan(tmp_path):
    """Crée un plan minimal et un client FastAPI configuré."""
    from src.services.migration.dataclasses import (
        Bucket, MigrationItem, MigrationPlan, MigrationStats,
        MatchInfo, RatingDecision,
    )
    from src.services.migration.plan_builder import serialize_plan
    from src.web.app import create_app

    item = MigrationItem(
        item_id="nv1",
        bucket=Bucket.NEEDS_VALIDATION,
        symlink_path=Path("/old/Wrong.mkv"),
        source_path=Path("/old/Wrong.mkv"),
        destination_path=None,
        media_root="Films",
        relative_category="",
        size_bytes=1500_000_000,
        rating=RatingDecision(),
        match=MatchInfo(top_candidates=[
            {"title": "Wrong", "year": 2012, "score": 67.0,
             "tmdb_id": 83186, "source": "tmdb"}
        ]),
        is_symlink_source=False,
    )
    plan = MigrationPlan(
        version=1, source_root=Path("/s"), destination_root=Path("/d"),
        threshold=6.0, stats=MigrationStats(), items=[item],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "plan.json.state.sqlite"

    app = create_app()
    return TestClient(app), plan_path, state_path


def test_review_list_renders(client_with_plan):
    client, plan_path, _ = client_with_plan
    response = client.get(
        "/migration/review", params={"plan": str(plan_path)}
    )
    assert response.status_code == 200
    assert "Wrong.mkv" in response.text
    assert "needs_validation" in response.text.lower()
```

- [ ] **Step 2: Failing**

```
uv run pytest tests/unit/web/test_migration_review_routes.py -v
```
Expected: FAIL — route inexistante.

- [ ] **Step 3: Create routes + templates**

```python
# src/web/routes/migration/__init__.py
from src.web.routes.migration.review import router

__all__ = ["router"]
```

```python
# src/web/routes/migration/review.py
"""Routes web pour la review interactive de la migration NAS."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from src.adapters.parsing.guessit_parser import GuessitFilenameParser
from src.services.matcher import MatcherService
from src.services.duplicate_detector import DuplicateDetector
from src.services.migration.plan_builder import deserialize_plan
from src.services.migration.review_service import (
    MigrationReviewService,
    REVIEW_BUCKETS,
)
from src.services.migration.state_store import MigrationStateStore
from src.web.deps import templates


router = APIRouter(prefix="/migration", tags=["migration"])


def _build_service(plan_path: Path, container):
    """Câble MigrationReviewService depuis container + plan path."""
    plan = deserialize_plan(plan_path.read_text(encoding="utf-8"))
    state_path = plan_path.with_suffix(plan_path.suffix + ".state.sqlite")
    store = MigrationStateStore(state_path)
    service = MigrationReviewService(
        plan=plan,
        state_store=store,
        tmdb_client=container.tmdb_client(),
        tvdb_client=container.tvdb_client(),
        matcher=MatcherService(),
        duplicate_detector=DuplicateDetector(),
    )
    return service, store


@router.get("/review")
async def review_list(
    request: Request,
    plan: str = Query(..., description="Path absolu du plan.json"),
):
    """Liste des items en attente de décision (4 buckets review)."""
    plan_path = Path(plan)
    container = request.app.state.container
    service, store = _build_service(plan_path, container)
    try:
        items = list(service.iter_pending(resume=False))
        decisions = store.load_decisions()
    finally:
        store.close()

    return templates.TemplateResponse(
        request,
        "migration/review_list.html",
        {
            "plan_path": str(plan_path),
            "items": items,
            "decisions": decisions,
            "summary": service.summary(),
        },
    )
```

```html
<!-- src/web/templates/migration/review_list.html -->
{% extends "base.html" %}
{% block content %}
<div class="container">
  <h1>Migration NAS — Review</h1>
  <p class="dim">Plan : <code>{{ plan_path }}</code></p>

  <div class="summary">
    <span>Pending : {{ summary.pending }}</span>
    <span>Approved : {{ summary.approved | default(0) }}</span>
    <span>Skipped : {{ summary.skipped | default(0) }}</span>
    <span>Deferred : {{ summary.deferred_to_web | default(0) }}</span>
  </div>

  <div class="review-list">
    {% for item in items %}
      {% include "migration/_review_card.html" %}
    {% endfor %}
  </div>
</div>
{% endblock %}
```

```html
<!-- src/web/templates/migration/_review_card.html -->
<div class="review-card review-card--{{ item.bucket.value }}"
     id="review-{{ item.item_id }}">
  <div class="review-card__header">
    <span class="bucket-badge">{{ item.bucket.value }}</span>
    <strong>{{ item.symlink_path.name }}</strong>
  </div>
  <div class="review-card__body">
    {% if item.bucket.value == "needs_validation" and item.match.top_candidates %}
      <p>Top match : <strong>{{ item.match.top_candidates[0].title }}</strong>
         ({{ item.match.top_candidates[0].year }})
         score {{ "%.0f"|format(item.match.top_candidates[0].score) }}</p>
    {% elif item.bucket.value == "already_in_library" %}
      <p>Doublon — existant en biblio</p>
    {% endif %}
    <button hx-get="/migration/review/{{ item.item_id }}?plan={{ plan_path }}"
            hx-target="#review-{{ item.item_id }}"
            hx-swap="outerHTML">
      Voir détail
    </button>
  </div>
</div>
```

Edit `src/web/app.py` to register the router :

```python
from src.web.routes.migration import router as migration_router

app.include_router(migration_router)
```

- [ ] **Step 4: Pass**

```
uv run pytest tests/unit/web/test_migration_review_routes.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/web/routes/migration/ src/web/templates/migration/ src/web/app.py tests/unit/web/test_migration_review_routes.py
git commit -m "feat(web migration): page liste /migration/review (HTMX)"
```

---

### Task 20: Routes détail + POST decide + GET search

**Files:**
- Modify: `src/web/routes/migration/review.py`
- Create: `src/web/templates/migration/_review_detail.html`
- Create: `src/web/templates/migration/_duplicate_compare.html`
- Test: `tests/unit/web/test_migration_review_routes.py` (append)

- [ ] **Step 1: Failing tests**

Append :

```python
def test_review_detail_returns_overlay_fragment(client_with_plan):
    client, plan_path, _ = client_with_plan
    response = client.get(
        "/migration/review/nv1", params={"plan": str(plan_path)}
    )
    assert response.status_code == 200
    assert "Wrong.mkv" in response.text
    # Fragment HTMX (pas la page complète)
    assert "<html" not in response.text.lower()


def test_review_decide_post_persists(client_with_plan):
    client, plan_path, state_path = client_with_plan
    response = client.post(
        f"/migration/review/nv1/decide",
        params={"plan": str(plan_path)},
        data={
            "decision": "approved",
            "chosen_tmdb_id": "83186",
            "chosen_title": "Wrong",
            "chosen_year": "2012",
            "chosen_score": "67.0",
        },
    )
    assert response.status_code == 200
    from src.services.migration.state_store import MigrationStateStore
    from src.services.migration.decisions import DecisionStatus
    store = MigrationStateStore(state_path)
    d = store.get_decision("nv1")
    assert d.decision == DecisionStatus.APPROVED
    assert d.decided_via == "web"
    store.close()
```

- [ ] **Step 2: Failing**

```
uv run pytest tests/unit/web/test_migration_review_routes.py -v -k "detail or decide"
```
Expected: FAIL.

- [ ] **Step 3: Implement routes**

Append to `src/web/routes/migration/review.py` :

```python
from datetime import datetime, timezone
from typing import Optional

from fastapi import Form

from src.services.migration.decisions import (
    Decision, DecisionStatus, DuplicateAction,
)


def _find_item(plan, item_id):
    for it in plan.items:
        if it.item_id == item_id:
            return it
    return None


@router.get("/review/{item_id}")
async def review_detail(
    request: Request,
    item_id: str,
    plan: str = Query(...),
):
    """Fragment HTMX détail d'un item."""
    plan_path = Path(plan)
    container = request.app.state.container
    service, store = _build_service(plan_path, container)
    try:
        item = _find_item(service._plan, item_id)
        if item is None:
            return HTMLResponse("<p>Item non trouvé</p>", status_code=404)
        # Pour already_in_library : compute reco
        reco = None
        if item.bucket.value == "already_in_library":
            try:
                reco = service.duplicate_recommendation(item)
            except Exception:
                pass
        return templates.TemplateResponse(
            request,
            "migration/_review_detail.html",
            {
                "item": item,
                "plan_path": plan,
                "reco": reco,
            },
        )
    finally:
        store.close()


@router.post("/review/{item_id}/decide")
async def review_decide(
    request: Request,
    item_id: str,
    plan: str = Query(...),
    decision: str = Form(...),
    chosen_tmdb_id: Optional[str] = Form(None),
    chosen_tvdb_id: Optional[str] = Form(None),
    chosen_title: Optional[str] = Form(None),
    chosen_year: Optional[str] = Form(None),
    chosen_score: Optional[str] = Form(None),
    duplicate_action: Optional[str] = Form(None),
    delete_source_after: bool = Form(False),
    reason: Optional[str] = Form(None),
):
    """POST décision depuis le web."""
    plan_path = Path(plan)
    container = request.app.state.container
    service, store = _build_service(plan_path, container)
    try:
        service.decide(
            item_id=item_id,
            decision=DecisionStatus(decision),
            chosen_tmdb_id=int(chosen_tmdb_id) if chosen_tmdb_id else None,
            chosen_tvdb_id=int(chosen_tvdb_id) if chosen_tvdb_id else None,
            chosen_title=chosen_title,
            chosen_year=int(chosen_year) if chosen_year else None,
            chosen_score=float(chosen_score) if chosen_score else None,
            duplicate_action=DuplicateAction(duplicate_action)
            if duplicate_action else None,
            delete_source_after=delete_source_after,
            reason=reason,
            decided_via="web",
        )
        return HTMLResponse(
            f'<div class="review-card review-card--decided">'
            f'  ✓ Décision enregistrée pour {item_id}'
            f'</div>'
        )
    finally:
        store.close()


@router.get("/review/{item_id}/search")
async def review_search(
    request: Request,
    item_id: str,
    plan: str = Query(...),
    q: str = Query(""),
):
    """Recherche TMDB live depuis le web (fragment HTMX)."""
    if not q.strip():
        return HTMLResponse('<p class="dim">Saisissez un titre</p>')
    plan_path = Path(plan)
    container = request.app.state.container
    service, store = _build_service(plan_path, container)
    try:
        item = _find_item(service._plan, item_id)
        if item is None:
            return HTMLResponse('<p>Item non trouvé</p>', status_code=404)
        is_series = (item.media_root or "").lower().startswith(
            ("seri", "séri", "anim")
        )
        results = await service.search_tmdb(query=q.strip(), is_series=is_series)
        return templates.TemplateResponse(
            request,
            "migration/_search_results.html",
            {"item": item, "results": results, "plan_path": plan},
        )
    finally:
        store.close()
```

```html
<!-- src/web/templates/migration/_review_detail.html -->
<div class="review-detail" id="review-{{ item.item_id }}">
  <h3>{{ item.symlink_path.name }}</h3>
  <p>{{ item.bucket.value }} · {{ item.media_root }} · {{ (item.size_bytes / 1024 / 1024) | round(0) }} MB</p>

  {% if item.match.top_candidates %}
    <h4>Top candidates TMDB</h4>
    <ul>
      {% for c in item.match.top_candidates[:5] %}
      <li>
        <strong>{{ c.title }}</strong> ({{ c.year }})
        — score {{ "%.0f"|format(c.score) }}
        <form hx-post="/migration/review/{{ item.item_id }}/decide?plan={{ plan_path }}"
              hx-target="#review-{{ item.item_id }}"
              hx-swap="outerHTML"
              style="display:inline">
          <input type="hidden" name="decision" value="approved">
          <input type="hidden" name="chosen_tmdb_id" value="{{ c.tmdb_id or '' }}">
          <input type="hidden" name="chosen_tvdb_id" value="{{ c.tvdb_id or '' }}">
          <input type="hidden" name="chosen_title" value="{{ c.title }}">
          <input type="hidden" name="chosen_year" value="{{ c.year or '' }}">
          <input type="hidden" name="chosen_score" value="{{ c.score }}">
          <button>Choisir</button>
        </form>
      </li>
      {% endfor %}
    </ul>
  {% endif %}

  {% if reco %}
    {% include "migration/_duplicate_compare.html" %}
  {% endif %}

  <div class="search-box">
    <input type="text" name="q" placeholder="Recherche TMDB live..."
           hx-get="/migration/review/{{ item.item_id }}/search?plan={{ plan_path }}"
           hx-trigger="keyup changed delay:400ms"
           hx-target="#search-results-{{ item.item_id }}">
    <div id="search-results-{{ item.item_id }}"></div>
  </div>

  <div class="actions">
    <form hx-post="/migration/review/{{ item.item_id }}/decide?plan={{ plan_path }}"
          hx-target="#review-{{ item.item_id }}"
          hx-swap="outerHTML">
      <input type="hidden" name="decision" value="skipped">
      <button>Skip</button>
    </form>
  </div>
</div>
```

```html
<!-- src/web/templates/migration/_duplicate_compare.html -->
<div class="duplicate-compare">
  <h4>Comparaison qualité (DuplicateDetector)</h4>
  <p>Recommandation : <strong>{{ reco.recommended }}</strong>
     (new={{ "%.0f"|format(reco.new_score) }}, existing={{ "%.0f"|format(reco.existing_score) }})</p>
</div>
```

```html
<!-- src/web/templates/migration/_search_results.html -->
{% for r in results[:5] %}
<div class="search-result">
  <strong>{{ r.title }}</strong> ({{ r.year }})
  — score {{ "%.0f"|format(r.score) }}
  <form hx-post="/migration/review/{{ item.item_id }}/decide?plan={{ plan_path }}"
        hx-target="#review-{{ item.item_id }}"
        hx-swap="outerHTML"
        style="display:inline">
    <input type="hidden" name="decision" value="approved">
    <input type="hidden" name="chosen_tmdb_id" value="{{ r.id if r.source.startswith('tmdb') else '' }}">
    <input type="hidden" name="chosen_tvdb_id" value="{{ r.id if r.source == 'tvdb' else '' }}">
    <input type="hidden" name="chosen_title" value="{{ r.title }}">
    <input type="hidden" name="chosen_year" value="{{ r.year or '' }}">
    <input type="hidden" name="chosen_score" value="{{ r.score }}">
    <button>Choisir</button>
  </form>
</div>
{% endfor %}
```

- [ ] **Step 4: Pass**

```
uv run pytest tests/unit/web/test_migration_review_routes.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/web/routes/migration/review.py src/web/templates/migration/ tests/unit/web/test_migration_review_routes.py
git commit -m "feat(web migration): détail + decide + search TMDB live (HTMX fragments)"
```

---

## Phase 44.8 — Multi-parts auto-handle

### Task 21: Détection multi-parts (collision_tmdb tag) en CLI

**Files:**
- Modify: `src/adapters/cli/commands/migrate_nas_command/review.py`
- Test: `tests/unit/adapters/cli/test_migrate_nas_review.py`

- [ ] **Step 1: Failing test**

Append :

```python
def test_review_collision_tmdb_offers_bulk_accept(tmp_path):
    """4 items collision_tmdb:X → premier item propose 'Accepter pour les 4 ?'.

    Si user accepte (Y), les 4 reçoivent décisions APPROVED avec titres
    suffixés Part 1 / Part 2 / etc.
    """
    from src.services.migration.dataclasses import (
        Bucket, MigrationItem, MigrationPlan, MigrationStats,
        MatchInfo, RatingDecision,
    )
    from src.services.migration.plan_builder import serialize_plan
    from src.services.migration.state_store import MigrationStateStore
    from src.services.migration.decisions import DecisionStatus

    items = [
        MigrationItem(
            item_id=f"f{i}",
            bucket=Bucket.NEEDS_VALIDATION,
            symlink_path=Path(f"/old/La.Flor.partie {i}.mkv"),
            source_path=Path(f"/old/La.Flor.partie {i}.mkv"),
            destination_path=None,
            media_root="Films",
            relative_category="",
            size_bytes=1000,
            rating=RatingDecision(),
            match=MatchInfo(top_candidates=[
                {"title": "La Flor", "year": 2018, "score": 100.0,
                 "tmdb_id": 423778, "source": "tmdb"}
            ]),
            is_symlink_source=False,
            tags=["collision_tmdb:423778"],
        )
        for i in range(1, 5)
    ]
    plan = MigrationPlan(
        version=1, source_root=Path("/s"), destination_root=Path("/d"),
        threshold=6.0, stats=MigrationStats(), items=items,
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(serialize_plan(plan))
    state_path = tmp_path / "s.sqlite"

    runner = CliRunner()
    # 'a' au 1er → prompt bulk → 'y'
    result = runner.invoke(
        migrate_nas_app,
        ["review", str(plan_path), "--state-store", str(state_path)],
        input="a\ny\n",
    )
    assert result.exit_code == 0, result.output
    store = MigrationStateStore(state_path)
    for i in range(1, 5):
        d = store.get_decision(f"f{i}")
        assert d is not None, f"item f{i} sans décision"
        assert d.decision == DecisionStatus.APPROVED
        assert d.chosen_tmdb_id == 423778
        assert "Part" in d.chosen_title  # suffix auto
    store.close()
```

- [ ] **Step 2: Failing**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py::test_review_collision_tmdb_offers_bulk_accept -v
```
Expected: FAIL.

- [ ] **Step 3: Implement bulk-accept**

Add helper to `review.py` :

```python
def _collision_tmdb_id(item: MigrationItem) -> Optional[str]:
    """Retourne l'id de collision_tmdb tag si présent, sinon None."""
    for tag in item.tags:
        if tag.startswith("collision_tmdb:"):
            return tag.split(":", 1)[1]
    return None


def _items_in_collision_group(plan, group_id: str) -> list:
    """Retourne tous les items du plan partageant ce collision_tmdb id."""
    return [
        it for it in plan.items
        if f"collision_tmdb:{group_id}" in it.tags
    ]


def _maybe_bulk_accept_collision(
    service: MigrationReviewService,
    item: MigrationItem,
    chosen: dict,
) -> bool:
    """Si l'item fait partie d'un groupe collision_tmdb, propose accept en masse.

    Retourne True si bulk-accept appliqué (caller doit alors continue), False
    si user a refusé (caller fait le single-accept normal).
    """
    group_id = _collision_tmdb_id(item)
    if group_id is None:
        return False
    siblings = _items_in_collision_group(service._plan, group_id)
    if len(siblings) < 2:
        return False
    if not Confirm.ask(
        f"[cyan]🔗 Multi-parts détecté ({len(siblings)} items, "
        f"tag collision_tmdb:{group_id}). Accepter pour les {len(siblings)} ?"
        f"[/cyan]",
        default=True,
    ):
        return False
    base_title = chosen.get("title", "Untitled")
    for n, sibling in enumerate(siblings, start=1):
        sibling_chosen = dict(chosen)
        sibling_chosen["title"] = f"{base_title} - Part {n}"
        _persist_approved(service, sibling, sibling_chosen)
    return True
```

Modify `_handle_needs_validation` : after computing `chosen` (and before `_persist_approved`), call :

```python
    if _maybe_bulk_accept_collision(service, item, chosen):
        return "continue"
    _persist_approved(service, item, chosen)
    return "continue"
```

- [ ] **Step 4: Pass**

```
uv run pytest tests/unit/adapters/cli/test_migrate_nas_review.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adapters/cli/commands/migrate_nas_command/review.py tests/unit/adapters/cli/test_migrate_nas_review.py
git commit -m "feat(migrate-nas review): bulk-accept multi-parts via tag collision_tmdb"
```

---

## Phase 44.9 — Doc

### Task 22: README + exemple session complète

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add review section to README.md**

Locate the existing `migrate-nas` section in README.md and add subsections after `apply` :

```markdown
### `migrate-nas review` — Review interactive des items en attente

Après `migrate-nas plan`, les items qui n'atterrissent pas dans le bucket
MIGRATE (4 buckets : needs_validation, unrated, low_rated, already_in_library)
sont en attente d'arbitrage. La commande `review` ouvre une boucle CLI
interactive pour décider par item.

```bash
uv run python -m src.main migrate-nas review migration/plan.json
uv run python -m src.main migrate-nas review migration/plan.json --bucket needs_validation
uv run python -m src.main migrate-nas review migration/plan.json --restart  # ignore decisions précédentes
```

**Actions par bucket :**

| Bucket | Touches | Description |
|---|---|---|
| **needs_validation** | a / 1-5 / s / r / k / w / q | accept top, pick N, search TMDB live, reject, keep skip, web defer, quit |
| **unrated** | m / k / w / q | migrate-anyway, keep skip, web, quit |
| **low_rated** | m / d / k / w / q | migrate-anyway, **delete-source-after-commit (avec confirmation)**, keep skip, web, quit |
| **already_in_library** | a / k / r / d / w / q | accept reco DuplicateDetector, keep dest, replace dest, delete source, web, quit |

Les décisions sont persistées dans `<plan>.state.sqlite` (table `migration_decisions`).
Reprenable via `--resume` (par défaut). Les items deferred-to-web sont arbitrés sur
la page `/migration/review?plan=<chemin>`.

### `migrate-nas apply` (étendu)

Désormais, `apply` consulte les décisions review en plus du bucket MIGRATE.
Les items APPROVED des 4 buckets review sont hydratés (`item.match.tmdb_id`
remplacé par la décision) et transférés via `raw_finalizer`.

```bash
# Workflow complet
uv run python -m src.main migrate-nas plan --source /media/wd10-1 --output migration/plan.json --csv-dir migration/review --include-raw
uv run python -m src.main migrate-nas review migration/plan.json
uv run python -m src.main migrate-nas apply migration/plan.json
```

### Page web `/migration/review`

Pour les items difficiles (besoin de comparaison visuelle), la page web propose :
- Liste filtrable (par bucket, par statut décision)
- Overlay détail avec poster TMDB + 5 candidats + recherche live
- Pour `already_in_library` : comparaison qualité côte-à-côte
```

- [ ] **Step 2: Verify markdown is valid**

```
test -s README.md && grep -c "migrate-nas review" README.md
```
Expected: ≥ 2

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(README): section migrate-nas review + workflow étendu apply"
```

---

## Self-Review (à exécuter en fin de plan)

- [ ] **Spec coverage check** — vérifier que chaque section du spec est couverte par au moins une tâche :

| Spec section | Couverture |
|---|---|
| 4.1 ReviewService | Tasks 3-6 |
| 4.2 state_store extension | Task 2 |
| 4.3 CLI review | Tasks 7-15 |
| 4.4 Web review | Tasks 19-20 |
| 4.5 apply integration | Tasks 16-17 |
| 6.1 Multi-parts | Task 21 |
| 6.4 plan regen safe (item_id stable) | Couvert par design item_id = hash(symlink_path) |
| 6.5 apply mid-review | Couvert par Task 16 (decoupled) |

- [ ] **Validation finale**

```
uv run pytest tests/unit/services/migration/ tests/unit/adapters/cli/ tests/unit/web/ tests/integration/ --tb=short -q
uv run ruff check src/services/migration/ src/adapters/cli/commands/migrate_nas_command/ src/web/routes/migration/
```
Expected: all green.

---

## Execution Notes

**Each task is self-contained** : tests TDD avant impl, run, commit. Si une tâche
échoue à mi-chemin, ne pas amender le commit précédent — fix + nouveau commit.

**Order strict 1→22** : les tasks 7+ dépendent du service (1-6), les tasks 16-17
dépendent du CLI loop (7-15), Task 18 e2e dépend de tout le MVP. Tasks 19-22
(web + multi-parts + doc) indépendantes du MVP — peuvent être réordonnées.

**Cible MVP utile** = Task 18 inclus (e2e plan→review→apply fonctionnel sur les
4 buckets). Polish web + multi-parts livrable séparément.
