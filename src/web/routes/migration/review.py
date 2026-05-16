"""Routes web pour la review interactive de la migration NAS."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from src.services.duplicate_detector import DuplicateDetector
from src.services.matcher import MatcherService
from src.services.migration.plan_builder import deserialize_plan
from src.services.migration.review_service import MigrationReviewService
from src.services.migration.state_store import MigrationStateStore
from src.web.deps import templates


router = APIRouter(prefix="/migration", tags=["migration"])


def _validate_plan_path(plan: str) -> Path:
    """Valide le paramètre plan : chemin existant, suffixe .json."""
    plan_path = Path(plan).resolve()
    if not plan_path.exists():
        raise HTTPException(status_code=400, detail=f"Plan introuvable : {plan}")
    if plan_path.suffix.lower() != ".json":
        raise HTTPException(
            status_code=400,
            detail=f"Plan doit être un fichier .json : {plan}",
        )
    return plan_path


def _build_service(
    plan_path: Path,
    store: MigrationStateStore,
    container,
) -> MigrationReviewService:
    """Câble MigrationReviewService depuis container + plan + store déjà ouvert."""
    plan = deserialize_plan(plan_path.read_text(encoding="utf-8"))
    return MigrationReviewService(
        plan=plan,
        state_store=store,
        tmdb_client=container.tmdb_client(),
        tvdb_client=container.tvdb_client(),
        matcher=MatcherService(),
        duplicate_detector=DuplicateDetector(),
    )


@router.get("/review")
async def review_list(
    request: Request,
    plan: str = Query(..., description="Path absolu du plan.json"),
):
    """Liste des items en attente de décision (4 buckets review)."""
    plan_path = _validate_plan_path(plan)
    container = request.app.state.container
    state_path = plan_path.with_suffix(plan_path.suffix + ".state.sqlite")
    store = MigrationStateStore(state_path)
    try:
        service = _build_service(plan_path, store, container)
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
