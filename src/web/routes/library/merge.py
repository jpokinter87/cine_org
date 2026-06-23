"""Routes de fusion de deux fiches séries dupliquées."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse

from ....infrastructure.persistence.database import get_session
from ....infrastructure.persistence.models import SeriesModel
from ....infrastructure.persistence.repositories.episode_repository import (
    SQLModelEpisodeRepository,
)
from ....infrastructure.persistence.repositories.series_repository import (
    SQLModelSeriesRepository,
)
from ....services.duplicate_detector import DuplicateDetector
from ....services.organizer import OrganizerService
from ....services.renamer import RenamerService
from ....services.series_merge import SeriesMergeService
from ...deps import templates

router = APIRouter()

# Adresses considérées comme locales (machine maître)
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _build_service(session, container) -> SeriesMergeService:
    """Construit le service de fusion avec ses dépendances."""
    settings = container.config()
    return SeriesMergeService(
        session=session,
        video_dir=settings.video_dir,
        file_system=container.file_system(),
        organizer=OrganizerService(),
        renamer=RenamerService(),
        duplicate_detector=DuplicateDetector(),
        series_repo=SQLModelSeriesRepository(session),
        episode_repo=SQLModelEpisodeRepository(session),
    )


@router.get("/merge/overlay")
async def merge_overlay(request: Request, a: int, b: int):
    """Affiche l'overlay de fusion.

    Le récipiendaire pré-coché par défaut est la fiche la plus ancienne
    (created_at min) — presque toujours l'originale canonique. L'utilisateur
    peut inverser via le radio ; le front recharge alors avec explicit=1.
    """
    container = request.app.state.container
    session = next(get_session())
    try:
        sa = session.get(SeriesModel, a)
        sb = session.get(SeriesModel, b)
        if sa is None or sb is None:
            return JSONResponse({"error": "Fiche introuvable."}, status_code=404)
        explicit = request.query_params.get("explicit") == "1"
        if (
            not explicit
            and sb.created_at
            and sa.created_at
            and sb.created_at < sa.created_at
        ):
            sa, sb = sb, sa
        preview = _build_service(session, container).preview(sa.id, sb.id)
        return templates.TemplateResponse(
            request,
            "library/_merge_overlay.html",
            {"recipient": sa, "absorbed": sb, "preview": preview},
        )
    finally:
        session.close()


@router.post("/series/{recipient_id}/merge")
async def merge_apply(request: Request, recipient_id: int, absorbed_id: int = Form(...)):
    """Exécute la fusion. Réservé à la machine maître (localhost)."""
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return JSONResponse(
            {"error": "Fusion autorisée uniquement depuis la machine maître."},
            status_code=403,
        )
    container = request.app.state.container
    session = next(get_session())
    try:
        result = _build_service(session, container).merge(recipient_id, absorbed_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    finally:
        session.close()
    return JSONResponse(
        {"merged": True, "recipient_id": result.recipient_id},
        headers={"HX-Redirect": f"/library/series/{recipient_id}"},
    )
