"""Routes web pour la review interactive de la migration NAS."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, Request

from src.services.duplicate_detector import DuplicateDetector
from src.services.matcher import MatcherService
from src.services.migration.plan_builder import deserialize_plan
from src.services.migration.review_service import MigrationReviewService
from src.services.migration.state_store import MigrationStateStore
from src.web.deps import templates


router = APIRouter(prefix="/migration", tags=["migration"])


def _build_service(
    plan_path: Path, container
) -> tuple[MigrationReviewService, MigrationStateStore]:
    """Câble MigrationReviewService depuis le container + le chemin du plan."""
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
    plan: str = Query(..., description="Chemin absolu du plan.json"),
):
    """Liste des items en attente de décision (4 buckets de review)."""
    plan_path = Path(plan)
    container = request.app.state.container
    service, store = _build_service(plan_path, container)
    try:
        items = list(service.iter_pending(resume=False))
        decisions = store.load_decisions()
        summary = service.summary()
    finally:
        store.close()

    return templates.TemplateResponse(
        request,
        "migration/review_list.html",
        {
            "plan_path": str(plan_path),
            "items": items,
            "decisions": decisions,
            "summary": summary,
        },
    )
