"""Routes de fusion de fiches séries dupliquées (deux ou plus)."""

from typing import Optional

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import JSONResponse
from loguru import logger

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
async def merge_overlay(
    request: Request,
    ids: list[int] = Query(default=[]),
    keep: Optional[int] = None,
):
    """Affiche l'overlay de fusion de N fiches (N >= 2).

    La fiche conservée par défaut est la plus ancienne (created_at min) —
    presque toujours l'originale canonique. L'utilisateur peut en choisir une
    autre via le radio ; le front recharge alors avec ``keep``.
    """
    unique_ids = list(dict.fromkeys(ids))
    if len(unique_ids) < 2:
        return JSONResponse(
            {"error": "Sélectionner au moins deux fiches séries."}, status_code=400
        )
    container = request.app.state.container
    session = next(get_session())
    try:
        cards = [session.get(SeriesModel, i) for i in unique_ids]
        if any(c is None for c in cards):
            return JSONResponse({"error": "Fiche introuvable."}, status_code=404)
        recipient = next((c for c in cards if c.id == keep), None) or min(
            cards, key=lambda c: (c.created_at is None, c.created_at or 0, c.id)
        )
        absorbed = [c for c in cards if c.id != recipient.id]
        service = _build_service(session, container)
        try:
            previews = [service.preview(recipient.id, a.id) for a in absorbed]
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return templates.TemplateResponse(
            request,
            "library/_merge_overlay.html",
            {
                "recipient": recipient,
                "absorbed": absorbed,
                "cards": [recipient, *absorbed],
                "previews": previews,
            },
        )
    finally:
        session.close()


@router.post("/series/{recipient_id}/merge")
async def merge_apply(
    request: Request, recipient_id: int, absorbed_id: list[int] = Form(...)
):
    """Fusionne une ou plusieurs fiches dans la fiche conservée.

    Les fiches absorbées sont fusionnées l'une après l'autre ; chaque fusion
    est validée indépendamment. Réservé à la machine maître (localhost).
    """
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return JSONResponse(
            {"error": "Fusion autorisée uniquement depuis la machine maître."},
            status_code=403,
        )
    container = request.app.state.container
    session = next(get_session())
    done = 0
    try:
        service = _build_service(session, container)
        for absorbed in dict.fromkeys(absorbed_id):
            service.merge(recipient_id, absorbed)
            done += 1
    except ValueError as exc:
        return JSONResponse(
            {"error": f"{exc} ({done} fusion(s) déjà effectuée(s))"},
            status_code=400,
        )
    except Exception as exc:
        logger.exception("Échec de la fusion de séries")
        return JSONResponse(
            {
                "error": f"Échec de la fusion : {exc} "
                f"({done} fusion(s) déjà effectuée(s))"
            },
            status_code=500,
        )
    finally:
        session.close()
    return JSONResponse(
        {"merged": True, "recipient_id": recipient_id, "count": done},
        headers={"HX-Redirect": f"/library/series/{recipient_id}"},
    )
