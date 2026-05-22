"""Routes web pour la review interactive de la migration NAS."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from src.services.duplicate_detector import DuplicateDetector
from src.services.matcher import MatcherService
from src.services.migration.decisions import DecisionStatus, DuplicateAction
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


def _find_item(plan, item_id):
    """Retourne l'item correspondant à item_id, ou None si absent."""
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
    plan_path = _validate_plan_path(plan)
    container = request.app.state.container
    state_path = plan_path.with_suffix(plan_path.suffix + ".state.sqlite")
    store = MigrationStateStore(state_path)
    try:
        service = _build_service(plan_path, store, container)
        item = _find_item(service._plan, item_id)
        if item is None:
            return HTMLResponse("<p>Item non trouvé</p>", status_code=404)
        # Pour already_in_library : compute reco
        reco = None
        if item.bucket.value == "already_in_library":
            try:
                reco = service.duplicate_recommendation(item)
            except Exception:  # noqa: BLE001 — reco non bloquante
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
    plan_path = _validate_plan_path(plan)
    container = request.app.state.container
    state_path = plan_path.with_suffix(plan_path.suffix + ".state.sqlite")
    store = MigrationStateStore(state_path)
    try:
        service = _build_service(plan_path, store, container)
        if _find_item(service._plan, item_id) is None:
            return HTMLResponse("<p>Item non trouvé</p>", status_code=404)
        try:
            decision_enum = DecisionStatus(decision)
            duplicate_action_enum = (
                DuplicateAction(duplicate_action) if duplicate_action else None
            )
            tmdb_id_int = int(chosen_tmdb_id) if chosen_tmdb_id else None
            tvdb_id_int = int(chosen_tvdb_id) if chosen_tvdb_id else None
            year_int = int(chosen_year) if chosen_year else None
            score_float = float(chosen_score) if chosen_score else None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        service.decide(
            item_id=item_id,
            decision=decision_enum,
            chosen_tmdb_id=tmdb_id_int,
            chosen_tvdb_id=tvdb_id_int,
            chosen_title=chosen_title,
            chosen_year=year_int,
            chosen_score=score_float,
            duplicate_action=duplicate_action_enum,
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
    plan_path = _validate_plan_path(plan)
    container = request.app.state.container
    state_path = plan_path.with_suffix(plan_path.suffix + ".state.sqlite")
    store = MigrationStateStore(state_path)
    try:
        service = _build_service(plan_path, store, container)
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
