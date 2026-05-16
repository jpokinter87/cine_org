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
