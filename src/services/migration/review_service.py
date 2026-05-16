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
