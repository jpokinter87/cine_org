"""
Routes de suppression — lot (corbeille) et fiche fantôme depuis le détail.

Une fiche « fantôme » est une fiche sans fichiers réels : série dont aucun
épisode n'a de ``file_path``, ou film sans ``file_path``. Elle résulte
typiquement d'un mauvais matching laissé en place après une re-analyse
(cas « Sous ses yeux » associée à tort au documentaire « Il Testimonio »).
"""

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlmodel import select

from ....infrastructure.persistence.database import get_session
from ....infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    MoviePartModel,
    SeriesModel,
    TrashModel,
    VideoFileModel,
)

router = APIRouter()

# Adresses considérées comme locales (machine maître)
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


class DeleteItem(BaseModel):
    """Élément à supprimer."""

    type: str  # "movie" | "series"
    id: int


class DeleteRequest(BaseModel):
    """Requête de suppression par lot."""

    items: list[DeleteItem]


def _serialize_model(model) -> str:
    """Sérialise toutes les colonnes d'un SQLModel en JSON pour restauration."""
    data = {}
    for col in model.__class__.__table__.columns:
        val = getattr(model, col.name)
        if val is not None:
            # Convertir les types non-JSON
            if hasattr(val, "isoformat"):
                val = val.isoformat()
        data[col.name] = val
    return json.dumps(data, ensure_ascii=False)


def _remove_symlink_for_file_path(session, file_path: str | None, file_system) -> None:
    """Supprime le symlink vidéo associé à un file_path."""
    if not file_path:
        return
    vf = session.exec(
        select(VideoFileModel).where(VideoFileModel.path == file_path)
    ).first()
    if vf and vf.symlink_path:
        file_system.remove_symlink(Path(vf.symlink_path))


def _delete_movie_record(session, movie, file_system, reason: str) -> None:
    """Supprime un film vers la corbeille (symlink retiré, storage conservé)."""
    metadata = _serialize_model(movie)
    _remove_symlink_for_file_path(session, movie.file_path, file_system)
    if movie.file_path:
        vf = session.exec(
            select(VideoFileModel).where(VideoFileModel.path == movie.file_path)
        ).first()
        if vf:
            session.delete(vf)
    # Cascade : parties supplementaires (storage conserve, symlink retire)
    parts = session.exec(
        select(MoviePartModel).where(MoviePartModel.movie_id == movie.id)
    ).all()
    for part in parts:
        if part.symlink_path:
            file_system.remove_symlink(Path(part.symlink_path))
        session.delete(part)
    session.add(
        TrashModel(
            entity_type="movie",
            original_id=movie.id,
            metadata_json=metadata,
            deletion_reason=reason,
        )
    )
    session.delete(movie)


def _delete_series_record(session, series, file_system, reason: str) -> None:
    """Supprime une série + ses épisodes vers la corbeille (storage conservé)."""
    series_metadata = _serialize_model(series)
    trash_series = TrashModel(
        entity_type="series",
        original_id=series.id,
        metadata_json=series_metadata,
        deletion_reason=reason,
    )
    session.add(trash_series)
    session.flush()  # Pour obtenir trash_series.id

    episodes = session.exec(
        select(EpisodeModel).where(EpisodeModel.series_id == series.id)
    ).all()
    for ep in episodes:
        ep_metadata_dict = json.loads(_serialize_model(ep))
        ep_metadata_dict["_series_trash_id"] = trash_series.id
        ep_metadata = json.dumps(ep_metadata_dict, ensure_ascii=False)

        _remove_symlink_for_file_path(session, ep.file_path, file_system)
        if ep.file_path:
            vf = session.exec(
                select(VideoFileModel).where(VideoFileModel.path == ep.file_path)
            ).first()
            if vf:
                session.delete(vf)

        session.add(
            TrashModel(
                entity_type="episode",
                original_id=ep.id,
                metadata_json=ep_metadata,
                deletion_reason=reason,
            )
        )
        session.delete(ep)

    session.delete(series)


def _series_is_phantom(session, series_id: int) -> bool:
    """Vrai si la série n'a aucun épisode porteur d'un ``file_path``."""
    episodes = session.exec(
        select(EpisodeModel).where(EpisodeModel.series_id == series_id)
    ).all()
    return not any(ep.file_path for ep in episodes)


def _movie_is_phantom(movie) -> bool:
    """Vrai si le film n'a pas de ``file_path`` en base."""
    return not movie.file_path


@router.post("/delete-batch")
async def delete_batch(request: Request):
    """Supprime un lot d'éléments vers la corbeille.

    Reçoit une liste d'items {type, id}. Pour les séries,
    cascade automatique vers tous les épisodes.
    Supprime les symlinks vidéo mais conserve les fichiers storage.
    """
    # Sécurité : suppression uniquement depuis la machine maître
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return JSONResponse(
            {"error": "Suppression autorisée uniquement depuis la machine maître."},
            status_code=403,
        )

    body = await request.json()
    items = [DeleteItem(**item) for item in body.get("items", [])]

    if not items:
        return JSONResponse({"deleted": 0})

    container = request.app.state.container
    file_system = container.file_system()
    session = next(get_session())
    deleted = 0

    try:
        for item in items:
            if item.type == "movie":
                movie = session.get(MovieModel, item.id)
                if not movie:
                    continue
                _delete_movie_record(session, movie, file_system, "batch_delete")
                deleted += 1

            elif item.type == "series":
                series = session.get(SeriesModel, item.id)
                if not series:
                    continue
                _delete_series_record(session, series, file_system, "batch_delete")
                deleted += 1

        session.commit()

    finally:
        session.close()

    return JSONResponse({"deleted": deleted})


@router.post("/series/{series_id}/delete-phantom")
async def delete_phantom_series(request: Request, series_id: int):
    """Supprime une fiche série fantôme (sans aucun fichier).

    Garde-fou : refuse (400) si la série possède au moins un épisode
    porteur d'un ``file_path`` — indépendant de l'affichage du bouton.
    """
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return JSONResponse(
            {"error": "Suppression autorisée uniquement depuis la machine maître."},
            status_code=403,
        )

    container = request.app.state.container
    file_system = container.file_system()
    session = next(get_session())
    try:
        series = session.get(SeriesModel, series_id)
        if not series:
            return JSONResponse({"error": "Série non trouvée"}, status_code=404)
        if not _series_is_phantom(session, series_id):
            return JSONResponse(
                {"error": "La fiche possède des fichiers — suppression refusée."},
                status_code=400,
            )
        _delete_series_record(session, series, file_system, "phantom_delete")
        session.commit()
    finally:
        session.close()

    response = Response(status_code=200)
    response.headers["HX-Redirect"] = "/library/"
    return response


@router.post("/movies/{movie_id}/delete-phantom")
async def delete_phantom_movie(request: Request, movie_id: int):
    """Supprime une fiche film fantôme (sans ``file_path``).

    Garde-fou : refuse (400) si le film possède un ``file_path``.
    """
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return JSONResponse(
            {"error": "Suppression autorisée uniquement depuis la machine maître."},
            status_code=403,
        )

    container = request.app.state.container
    file_system = container.file_system()
    session = next(get_session())
    try:
        movie = session.get(MovieModel, movie_id)
        if not movie:
            return JSONResponse({"error": "Film non trouvé"}, status_code=404)
        if not _movie_is_phantom(movie):
            return JSONResponse(
                {"error": "La fiche possède un fichier — suppression refusée."},
                status_code=400,
            )
        _delete_movie_record(session, movie, file_system, "phantom_delete")
        session.commit()
    finally:
        session.close()

    response = Response(status_code=200)
    response.headers["HX-Redirect"] = "/library/"
    return response
