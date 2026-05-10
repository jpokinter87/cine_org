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
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.services.migration.dataclasses import (
    Bucket,
    MigrationPlan,
    TransferOutcome,
    TransferStatus,
)


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
        self._conn.execute(_SCHEMA)
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


def _now_iso() -> str:
    return datetime.utcnow().isoformat()
