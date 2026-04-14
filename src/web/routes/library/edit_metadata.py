"""
Routes d'edition manuelle des metadonnees (phase 42-02).

Permet a l'utilisateur de surcharger affiche / synopsis / casting depuis
la fiche web d'un film ou d'une serie, avec option de protection contre
les re-enrichissements automatiques.

Routes :
- GET  /library/{entity_type}/{entity_id}/edit : overlay d'edition
- POST /library/{entity_type}/{entity_id}/edit : persistance (multipart)
- GET  /library/metadata/posters/{filename}    : sert les fichiers poster
"""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from ....config import Settings
from ....infrastructure.persistence.database import get_session
from ....infrastructure.persistence.models import MovieModel, SeriesModel
from ....services.metadata_overrides import (
    find_poster,
    get_metadata_dir,
    save_poster_from_url,
    save_poster_upload,
)
from ...deps import templates
from .helpers import _poster_url


router = APIRouter()

EntityTypeParam = Literal["movies", "series"]


def _get_storage_dir() -> Path:
    return Path(Settings().storage_dir).expanduser()


def _load_entity(entity_type: EntityTypeParam, entity_id: int):
    """Charge MovieModel ou SeriesModel avec la session appropriee."""
    session = next(get_session())
    try:
        if entity_type == "movies":
            entity = session.get(MovieModel, entity_id)
        else:
            entity = session.get(SeriesModel, entity_id)
        return entity, session
    except Exception:
        session.close()
        raise


def _effective_poster_url(entity, entity_type_singular: str) -> Optional[str]:
    """URL d'affichage de l'affiche, override en priorite."""
    if entity.poster_override:
        # Chemin fichier local ou URL externe
        path = entity.poster_override
        if path.startswith("http://") or path.startswith("https://"):
            return path
        # Servi via la route /library/metadata/posters/
        filename = Path(path).name
        return f"/library/metadata/posters/{filename}"
    return _poster_url(entity.poster_path)


def _split_cast(entity) -> list[dict[str, str]]:
    """Casting actuel : override si defini, sinon liste API (sans role)."""
    if entity.cast_override_json:
        return entity.cast_override or []
    return [{"name": a, "role": ""} for a in entity.cast or []]


@router.get("/{entity_type}/{entity_id}/edit", response_class=HTMLResponse)
async def edit_metadata_form(
    request: Request,
    entity_type: EntityTypeParam,
    entity_id: int,
):
    """Retourne l'overlay HTMX de formulaire d'edition."""
    entity, session = _load_entity(entity_type, entity_id)
    try:
        if entity is None:
            return HTMLResponse(
                '<div class="edit-error">Entité introuvable.</div>',
                status_code=404,
            )

        entity_type_singular = "movie" if entity_type == "movies" else "series"
        current_poster = _effective_poster_url(entity, entity_type_singular)
        current_overview = entity.overview_override or entity.overview or ""
        current_cast = _split_cast(entity)
        preserve = bool(entity.preserve_overrides)
        has_override = bool(
            entity.poster_override
            or entity.overview_override
            or entity.cast_override_json
        )
    finally:
        session.close()

    return templates.TemplateResponse(
        request,
        "library/_edit_metadata.html",
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_title": entity.title,
            "current_poster": current_poster,
            "current_overview": current_overview,
            "current_cast": current_cast,
            "preserve_overrides": preserve,
            "has_override": has_override,
            "overview_placeholder": entity.overview or "",
        },
    )


@router.post("/{entity_type}/{entity_id}/edit", response_class=HTMLResponse)
async def edit_metadata_save(
    request: Request,
    entity_type: EntityTypeParam,
    entity_id: int,
):
    """
    Persiste les overrides. Form multipart avec champs :
    - poster_mode: 'keep' | 'upload' | 'url' | 'clear'
    - poster_file: UploadFile (si mode=upload)
    - poster_url: str (si mode=url)
    - overview_override: str
    - cast_names[]: list[str]
    - cast_roles[]: list[str]

    preserve_overrides est calcule automatiquement : True si au moins un
    override est defini a l'issue de la sauvegarde, False sinon.
    """
    form = await request.form()
    poster_mode = str(form.get("poster_mode", "keep"))
    overview = str(form.get("overview_override", "")).strip()

    names = [str(n) for n in form.getlist("cast_names[]")]
    roles = [str(r) for r in form.getlist("cast_roles[]")]
    cast_entries = [
        {"name": name.strip(), "role": role.strip()}
        for name, role in zip(names, roles)
        if name.strip()
    ]

    storage_dir = _get_storage_dir()
    entity_type_singular = "movie" if entity_type == "movies" else "series"

    entity, session = _load_entity(entity_type, entity_id)
    try:
        if entity is None:
            return HTMLResponse(
                '<div class="edit-error">Entité introuvable.</div>',
                status_code=404,
            )

        # Gestion de l'affiche
        if poster_mode == "upload":
            upload: UploadFile | None = form.get("poster_file")  # type: ignore[assignment]
            if upload is None or not getattr(upload, "filename", ""):
                return HTMLResponse(
                    '<div class="edit-error">Aucun fichier reçu.</div>',
                    status_code=400,
                )
            content = await upload.read()
            try:
                path = save_poster_upload(
                    storage_dir,
                    entity_type_singular,
                    entity_id,
                    upload.filename,
                    content,
                )
            except ValueError as exc:
                return HTMLResponse(
                    f'<div class="edit-error">{exc}</div>', status_code=400
                )
            entity.poster_override = str(path)

        elif poster_mode == "url":
            url = str(form.get("poster_url", "")).strip()
            if not url:
                return HTMLResponse(
                    '<div class="edit-error">URL manquante.</div>',
                    status_code=400,
                )
            try:
                path = save_poster_from_url(
                    storage_dir, entity_type_singular, entity_id, url
                )
            except ValueError as exc:
                return HTMLResponse(
                    f'<div class="edit-error">{exc}</div>', status_code=400
                )
            entity.poster_override = str(path)

        elif poster_mode == "clear":
            # Supprime l'override d'affiche (retour API)
            entity.poster_override = None

        # 'keep' : on ne touche pas a poster_override

        # Synopsis
        entity.overview_override = overview if overview else None

        # Cast
        entity.cast_override_json = (
            json.dumps(cast_entries, ensure_ascii=False) if cast_entries else None
        )

        # preserve_overrides est automatique : True si au moins un override
        # reste defini a l'issue de la sauvegarde, False quand tout a ete
        # efface (retour au comportement API).
        entity.preserve_overrides = bool(
            entity.poster_override
            or entity.overview_override
            or entity.cast_override_json
        )

        session.add(entity)
        session.commit()
    finally:
        session.close()

    # HX-Redirect vers la fiche pour recharger avec les nouvelles valeurs
    response = HTMLResponse(
        '<div class="edit-success">Modifications enregistrées. Rechargement…</div>'
    )
    response.headers["HX-Redirect"] = f"/library/{entity_type}/{entity_id}"
    return response


@router.get("/metadata/posters/{filename}")
async def serve_poster(filename: str):
    """Sert un fichier poster depuis storage/.metadata/posters/."""
    # Sanitize : pas de traversal
    if "/" in filename or ".." in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")

    storage_dir = _get_storage_dir()
    target = get_metadata_dir(storage_dir) / filename
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Affiche introuvable")

    mime, _ = mimetypes.guess_type(str(target))
    return FileResponse(target, media_type=mime or "image/jpeg")
