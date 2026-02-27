"""
Routes corbeille — consultation, restauration individuelle, vidage définitif.
"""

from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlmodel import select

from ....infrastructure.persistence.database import get_session
from ....infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    SeriesModel,
    TrashModel,
)
from ...deps import templates

router = APIRouter()

# Adresses considérées comme locales (machine maître)
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _parse_metadata(trash: TrashModel) -> dict:
    """Extrait les infos affichables depuis metadata_json."""
    meta = trash.entity_metadata
    return {
        "id": trash.id,
        "entity_type": trash.entity_type,
        "title": meta.get("title", "Sans titre"),
        "year": meta.get("year"),
        "poster_path": meta.get("poster_path"),
        "file_path": meta.get("file_path"),
        "deleted_at": trash.deleted_at,
        "original_id": trash.original_id,
    }


@router.get("/trash")
async def trash_index(request: Request):
    """Page de la corbeille — liste des éléments supprimés."""
    client_host = request.client.host if request.client else ""
    is_local = client_host in _LOCAL_HOSTS

    session = next(get_session())
    try:
        items_raw = session.exec(
            select(TrashModel).order_by(TrashModel.deleted_at.desc())
        ).all()

        # Filtrer : ne pas afficher les épisodes individuels (affichés via la série)
        items = []
        for t in items_raw:
            if t.entity_type == "episode":
                continue
            items.append(_parse_metadata(t))

        # Compter les épisodes par série en corbeille
        episode_counts: dict[int, int] = {}
        for t in items_raw:
            if t.entity_type == "episode":
                meta = t.entity_metadata
                series_trash_id = meta.get("_series_trash_id")
                if series_trash_id:
                    episode_counts[series_trash_id] = (
                        episode_counts.get(series_trash_id, 0) + 1
                    )

        for item in items:
            if item["entity_type"] == "series":
                item["episode_count"] = episode_counts.get(item["id"], 0)

    finally:
        session.close()

    context = {
        "items": items,
        "total_items": len(items),
        "is_local": is_local,
    }

    return templates.TemplateResponse(request, "library/trash.html", context)


@router.post("/trash/{trash_id}/restore", response_class=HTMLResponse)
async def restore_item(request: Request, trash_id: int):
    """Restaure un élément depuis la corbeille vers la bibliothèque.

    Recrée les modèles DB. Les symlinks vidéo devront être recréés
    via repair-links ou cleanup si nécessaire.
    """
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return HTMLResponse(
            '<div class="action-msg action-error">Restauration autorisée uniquement depuis la machine maître.</div>',
            status_code=403,
        )

    session = next(get_session())

    try:
        trash = session.get(TrashModel, trash_id)
        if not trash:
            return HTMLResponse(
                '<div class="action-msg action-error">Élément introuvable.</div>',
                status_code=404,
            )

        meta = trash.entity_metadata

        if trash.entity_type == "movie":
            movie = MovieModel()
            _apply_metadata(movie, meta, exclude={"id"})
            session.add(movie)

        elif trash.entity_type == "series":
            # Restaurer la série
            series = SeriesModel()
            _apply_metadata(series, meta, exclude={"id"})
            session.add(series)
            session.flush()
            new_series_id = series.id

            # Restaurer les épisodes liés
            episode_trash_items = session.exec(
                select(TrashModel).where(TrashModel.entity_type == "episode")
            ).all()

            for ep_trash in episode_trash_items:
                ep_meta = ep_trash.entity_metadata
                if ep_meta.get("_series_trash_id") == trash.id:
                    episode = EpisodeModel()
                    _apply_metadata(
                        episode, ep_meta, exclude={"id", "_series_trash_id"}
                    )
                    episode.series_id = new_series_id
                    session.add(episode)
                    session.delete(ep_trash)

        session.delete(trash)
        session.commit()

    finally:
        session.close()

    response = HTMLResponse(
        '<div class="action-msg action-success">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'width="18" height="18"><polyline points="20 6 9 17 4 12"/></svg>'
        "Élément restauré."
        "</div>"
    )
    response.headers["HX-Redirect"] = "/library/trash"
    return response


@router.post("/trash/empty", response_class=HTMLResponse)
async def empty_trash(request: Request):
    """Vide définitivement la corbeille — suppression physique des fichiers storage."""
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return HTMLResponse(
            '<div class="action-msg action-error">Vidage autorisé uniquement depuis la machine maître.</div>',
            status_code=403,
        )

    session = next(get_session())
    container = request.app.state.container
    file_system = container.file_system()

    try:
        all_trash = session.exec(select(TrashModel)).all()
        deleted_files = 0

        for trash in all_trash:
            meta = trash.entity_metadata
            file_path = meta.get("file_path")
            if file_path:
                path = Path(file_path)
                if path.exists():
                    file_system.delete(path)
                    deleted_files += 1
            session.delete(trash)

        session.commit()

    finally:
        session.close()

    response = HTMLResponse(
        '<div class="action-msg action-success">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'width="18" height="18"><polyline points="20 6 9 17 4 12"/></svg>'
        f"Corbeille vidée ({deleted_files} fichier(s) supprimé(s))."
        "</div>"
    )
    response.headers["HX-Redirect"] = "/library/trash"
    return response


def _apply_metadata(model, meta: dict, exclude: set[str] | None = None) -> None:
    """Applique les métadonnées JSON sur un modèle SQLModel."""
    exclude = exclude or set()
    for col in model.__class__.__table__.columns:
        if col.name in exclude:
            continue
        if col.name in meta and meta[col.name] is not None:
            val = meta[col.name]
            # Reconvertir les dates/datetimes depuis ISO
            col_type = str(col.type)
            if "DATE" in col_type and isinstance(val, str):
                try:
                    if "T" in val or " " in val:
                        val = datetime.fromisoformat(val)
                    else:
                        val = date.fromisoformat(val)
                except ValueError:
                    pass
            setattr(model, col.name, val)
