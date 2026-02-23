"""
Route de la page d'accueil.

Affiche les statistiques de la vidéothèque (films, séries, épisodes, en attente).
"""

from fastapi import APIRouter, Request
from sqlalchemy import func
from sqlmodel import select

from ...infrastructure.persistence.database import get_session
from ...infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    PendingValidationModel,
    SeriesModel,
)
from ..deps import templates

router = APIRouter()


@router.get("/")
async def home(request: Request):
    """Page d'accueil avec statistiques de la vidéothèque."""
    session = next(get_session())
    try:
        movie_count = session.exec(
            select(func.count()).select_from(MovieModel)
        ).one()
        series_count = session.exec(
            select(func.count()).select_from(SeriesModel)
        ).one()
        episode_count = session.exec(
            select(func.count()).select_from(EpisodeModel)
        ).one()
        pending_count = session.exec(
            select(func.count())
            .select_from(PendingValidationModel)
            .where(PendingValidationModel.validation_status == "pending")
        ).one()
    finally:
        session.close()

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "movie_count": movie_count,
            "series_count": series_count,
            "episode_count": episode_count,
            "pending_count": pending_count,
        },
    )
