"""
Persistance reprenable de l'état d'avancement de la migration NAS.

Stocke pour chaque item du plan (uniquement les items du bucket MIGRATE) son
statut de transfert (`TransferStatus`), les hashes source/destination, le
nombre d'octets transférés et un éventuel message d'erreur.

Le store est volontairement local au package migration (sqlite3 stdlib, pas
de SQLModel) : il s'agit d'un journal opérationnel séparé de la DB CineOrg
principale, qui peut être supprimé une fois la migration terminée.

Reprise : `pending_items()` exclut les items en `COMMITTED` mais conserve les
échecs (`FAILED_*`) pour permettre une relance ciblée après diagnostic.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.services.migration.dataclasses import (
    Bucket,
    MigrationPlan,
    TransferOutcome,
    TransferStatus,
)

if TYPE_CHECKING:
    from src.services.migration.decisions import Decision, DecisionStatus


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


class MigrationStateStore:
    """
    Journal SQLite des transferts de migration.

    Args:
        db_path: Chemin du fichier SQLite (créé s'il n'existe pas).
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ---- Lifecycle ------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    # ---- Initialisation depuis un plan ---------------------------------

    def init_from_plan(self, plan: MigrationPlan) -> None:
        """
        Insère en PENDING les items du bucket MIGRATE absents du store.

        Idempotent : les items déjà présents conservent leur statut. Les
        items ajoutés dans un re-plan sont insérés en PENDING.
        """
        now = _now_iso()
        rows = [
            (
                item.item_id,
                TransferStatus.PENDING.value,
                str(item.source_path) if item.source_path else None,
                str(item.destination_path) if item.destination_path else None,
                now,
            )
            for item in plan.items
            if item.bucket == Bucket.MIGRATE
        ]
        if not rows:
            return
        self._conn.executemany(
            """
            INSERT OR IGNORE INTO migration_items
                (item_id, status, source_path, destination_path, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._conn.commit()

    # ---- Lecture --------------------------------------------------------

    def get_status(self, item_id: str) -> Optional[TransferStatus]:
        row = self._conn.execute(
            "SELECT status FROM migration_items WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        return TransferStatus(row["status"])

    def get_outcome(self, item_id: str) -> Optional[TransferOutcome]:
        row = self._conn.execute(
            """
            SELECT item_id, status, source_hash, destination_hash,
                   bytes_transferred, error_message
            FROM migration_items WHERE item_id = ?
            """,
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        return TransferOutcome(
            item_id=row["item_id"],
            status=TransferStatus(row["status"]),
            source_hash=row["source_hash"],
            destination_hash=row["destination_hash"],
            error_message=row["error_message"],
            bytes_transferred=row["bytes_transferred"] or 0,
        )

    def pending_items(self) -> list[str]:
        """
        Items à traiter : tout sauf COMMITTED. Les échecs sont inclus pour
        permettre une relance après diagnostic.
        """
        rows = self._conn.execute(
            "SELECT item_id FROM migration_items WHERE status != ? ORDER BY item_id",
            (TransferStatus.COMMITTED.value,),
        ).fetchall()
        return [r["item_id"] for r in rows]

    def summary(self) -> dict[TransferStatus, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM migration_items GROUP BY status"
        ).fetchall()
        return {TransferStatus(r["status"]): r["n"] for r in rows}

    # ---- Mise à jour ----------------------------------------------------

    def update_status(
        self,
        item_id: str,
        status: TransferStatus,
        *,
        source_hash: Optional[str] = None,
        destination_hash: Optional[str] = None,
        bytes_transferred: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Met à jour (ou crée) la ligne d'un item.

        Tolérant à l'absence : permet d'enregistrer un transfert pour un
        item qui n'aurait pas été inséré par init_from_plan (cas marginal).
        Seuls les champs non-None remplacent l'existant.
        """
        existing = self._conn.execute(
            "SELECT item_id FROM migration_items WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        now = _now_iso()
        if existing is None:
            self._conn.execute(
                """
                INSERT INTO migration_items
                    (item_id, status, source_hash, destination_hash,
                     bytes_transferred, error_message, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    status.value,
                    source_hash,
                    destination_hash,
                    bytes_transferred or 0,
                    error_message,
                    now,
                ),
            )
        else:
            updates = ["status = ?", "updated_at = ?"]
            params: list = [status.value, now]
            if source_hash is not None:
                updates.append("source_hash = ?")
                params.append(source_hash)
            if destination_hash is not None:
                updates.append("destination_hash = ?")
                params.append(destination_hash)
            if bytes_transferred is not None:
                updates.append("bytes_transferred = ?")
                params.append(bytes_transferred)
            if error_message is not None:
                updates.append("error_message = ?")
                params.append(error_message)
            params.append(item_id)
            self._conn.execute(
                f"UPDATE migration_items SET {', '.join(updates)} WHERE item_id = ?",
                params,
            )
        self._conn.commit()

    # ---- Décisions de review (phase 44.1) -------------------------------

    def save_decision(self, decision: "Decision") -> None:
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
                _as_utc_iso(decision.decided_at),
                decision.decided_via,
            ),
        )
        self._conn.commit()

    def get_decision(self, item_id: str) -> Optional["Decision"]:
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

    def load_decisions(self) -> dict[str, "Decision"]:
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

    def decision_summary(self) -> dict["DecisionStatus", int]:
        """Retourne {DecisionStatus: count} pour la table decisions."""
        from src.services.migration.decisions import DecisionStatus

        rows = self._conn.execute(
            "SELECT decision, COUNT(*) AS n FROM migration_decisions GROUP BY decision"
        ).fetchall()
        return {DecisionStatus(r["decision"]): r["n"] for r in rows}


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_utc_iso(dt: datetime) -> str:
    """Force tz-aware UTC puis sérialise en ISO 8601."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()
