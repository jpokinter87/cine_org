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

    def _find_item(self, item_id: str) -> MigrationItem:
        for it in self._plan.items:
            if it.item_id == item_id:
                return it
        raise KeyError(f"unknown item_id: {item_id}")
