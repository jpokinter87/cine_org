"""Endpoints de partage Jellyfin (Partager / Départager + bandeau global)."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from loguru import logger

from src.services.share.exceptions import ShareConflict, ShareError

router = APIRouter(prefix="/share")

_TYPE_MAP = {"movies": "movie", "series": "series"}


def _service(request: Request):
    return request.app.state.container.share_service()


def _share_button(entity_type: str, entity_id: int) -> str:
    return (
        f'<span id="share-zone-{entity_id}">'
        f'<button class="action-btn-share" hx-post="/share/{entity_type}/{entity_id}"'
        f' hx-target="#share-zone-{entity_id}" hx-swap="innerHTML">Partager</button>'
        f"</span>"
    )


def _unshare_button(entity_type: str, entity_id: int) -> str:
    # hx-vals transmet l'entité à /share/stop pour régénérer le bon bouton
    # Partager au départage (sinon retombe sur /share/movies/0 → introuvable).
    return (
        f'<span id="share-zone-{entity_id}">'
        f'<button class="action-btn-unshare" hx-post="/share/stop"'
        f' hx-vals=\'{{"entity_type": "{entity_type}", "entity_id": "{entity_id}"}}\''
        f' hx-target="#share-zone-{entity_id}" hx-swap="innerHTML">Départager</button>'
        f"</span>"
    )


def _replace_overlay(entity_type: str, entity_id: int, active_title: str) -> str:
    return (
        '<div class="reject-overlay active" id="share-overlay"'
        ' onclick="if(event.target===this)this.remove()">'
        '<div class="reject-dialog">'
        '<h3 class="reject-dialog-title">Remplacer le partage en cours ?</h3>'
        f"<p>Un partage est déjà actif : <strong>{active_title}</strong>. "
        "Le remplacer arrêtera ce partage et exposera le nouveau titre.</p>"
        '<div class="reject-dialog-actions">'
        '<button class="reject-dialog-cancel" onclick="document.getElementById(\'share-overlay\').remove()">Annuler</button>'
        f'<button class="reject-dialog-confirm" hx-post="/share/{entity_type}/{entity_id}"'
        f' hx-vals=\'{{"replace": "true"}}\' hx-target="#share-zone-{entity_id}" hx-swap="innerHTML"'
        " onclick=\"document.getElementById('share-overlay').remove()\">Oui, remplacer</button>"
        "</div></div></div>"
    )


@router.post("/{entity_type}/{entity_id}", response_class=HTMLResponse)
async def start_share(
    request: Request, entity_type: str, entity_id: int, replace: bool = Form(False)
):
    """Démarre le partage du média indiqué.

    En cas de conflit sans remplacement confirmé, renvoie un overlay de confirmation.
    En succès, renvoie le bouton Départager.
    """
    media_type = _TYPE_MAP.get(entity_type)
    if media_type is None:
        return HTMLResponse('<div class="action-msg play-error">Type inconnu</div>')
    service = _service(request)
    try:
        await service.start_share(media_type, entity_id, replace=replace)
    except ShareConflict as conflict:
        return HTMLResponse(
            _share_button(entity_type, entity_id)
            + _replace_overlay(entity_type, entity_id, conflict.active.title)
        )
    except ShareError as exc:
        logger.error("Échec partage : {}", exc)
        return HTMLResponse(
            _share_button(entity_type, entity_id)
            + f'<div class="action-msg play-error">{exc}</div>'
        )
    # HX-Trigger : le bandeau global se rafraîchit immédiatement (sans attendre
    # son poll de 60 s) pour afficher « Partage en cours ».
    return HTMLResponse(
        _unshare_button(entity_type, entity_id),
        headers={"HX-Trigger": "shareChanged"},
    )


@router.post("/stop", response_class=HTMLResponse)
async def stop_share(
    request: Request, entity_type: str = Form("movies"), entity_id: int = Form(0)
):
    """Arrête le partage actif et renvoie le bouton Partager."""
    service = _service(request)
    await service.stop_share()
    # HX-Trigger : le bandeau global disparaît immédiatement (sans attendre son
    # poll de 60 s).
    return HTMLResponse(
        _share_button(entity_type, entity_id),
        headers={"HX-Trigger": "shareChanged"},
    )


@router.get("/status", response_class=HTMLResponse)
async def share_status(request: Request):
    """Bandeau de statut auto-rafraîchi (poll toutes les 60 s)."""
    service = _service(request)
    active = service.get_active_share()
    # Le bandeau se rafraîchit sur poll (filet de sécurité) ET immédiatement sur
    # l'évènement `shareChanged` émis par Partager/Départager (HX-Trigger).
    poll = (
        'hx-get="/share/status" hx-trigger="load delay:60s, shareChanged from:body"'
        ' hx-swap="outerHTML"'
    )
    if active is None:
        return HTMLResponse(
            f'<div id="share-banner" class="share-banner-empty" {poll}></div>'
        )
    # Le bouton du bandeau utilise hx-swap="none" : sa réponse (bouton Partager
    # d'une fiche) ne doit pas remplacer le bandeau ; c'est `shareChanged` qui le
    # rafraîchit proprement en bandeau vide.
    return HTMLResponse(
        f'<div id="share-banner" class="share-banner" {poll}>'
        f"🔴 Partage en cours : <strong>{active.title}</strong> "
        '<button class="share-banner-stop" hx-post="/share/stop"'
        ' hx-swap="none">Départager</button>'
        "</div>"
    )
