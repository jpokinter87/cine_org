"""
Routes de suppression par lot — déplace les éléments sélectionnés vers la corbeille.
"""

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import select

from ....infrastructure.persistence.database import get_session
from ....infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
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

                # Sérialiser pour restauration
                metadata = _serialize_model(movie)

                # Supprimer le symlink vidéo
                _remove_symlink_for_file_path(session, movie.file_path, file_system)

                # Supprimer le VideoFileModel associé
                if movie.file_path:
                    vf = session.exec(
                        select(VideoFileModel).where(
                            VideoFileModel.path == movie.file_path
                        )
                    ).first()
                    if vf:
                        session.delete(vf)

                # Créer l'entrée corbeille
                trash = TrashModel(
                    entity_type="movie",
                    original_id=movie.id,
                    metadata_json=metadata,
                    deletion_reason="batch_delete",
                )
                session.add(trash)

                # Supprimer le film de la DB
                session.delete(movie)
                deleted += 1

            elif item.type == "series":
                series = session.get(SeriesModel, item.id)
                if not series:
                    continue

                # Sérialiser la série pour restauration
                series_metadata = _serialize_model(series)

                # Créer l'entrée corbeille pour la série
                trash_series = TrashModel(
                    entity_type="series",
                    original_id=series.id,
                    metadata_json=series_metadata,
                    deletion_reason="batch_delete",
                )
                session.add(trash_series)
                session.flush()  # Pour obtenir trash_series.id

                # Cascade : récupérer et supprimer tous les épisodes
                episodes = session.exec(
                    select(EpisodeModel).where(EpisodeModel.series_id == series.id)
                ).all()
                for ep in episodes:
                    ep_metadata_dict = json.loads(_serialize_model(ep))
                    ep_metadata_dict["_series_trash_id"] = trash_series.id
                    ep_metadata = json.dumps(ep_metadata_dict, ensure_ascii=False)

                    # Supprimer le symlink de l'épisode
                    _remove_symlink_for_file_path(session, ep.file_path, file_system)

                    # Supprimer le VideoFileModel de l'épisode
                    if ep.file_path:
                        vf = session.exec(
                            select(VideoFileModel).where(
                                VideoFileModel.path == ep.file_path
                            )
                        ).first()
                        if vf:
                            session.delete(vf)

                    trash_ep = TrashModel(
                        entity_type="episode",
                        original_id=ep.id,
                        metadata_json=ep_metadata,
                        deletion_reason="batch_delete",
                    )
                    session.add(trash_ep)
                    session.delete(ep)

                # Supprimer la série de la DB
                session.delete(series)
                deleted += 1

        session.commit()

    finally:
        session.close()

    return JSONResponse({"deleted": deleted})
