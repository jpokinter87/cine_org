"""
Routes de validation des fichiers vidéo.

Affiche la liste des fichiers en attente et le détail des candidats enrichis
(jaquettes, synopsis, score, acteurs). Gère les actions HTMX : valider,
rejeter, recherche manuelle par titre et recherche par ID externe.
"""

import logging
import re
from typing import Optional

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse

from ...core.ports.api_clients import MediaDetails, SearchResult
from ...utils.helpers import parse_candidates
from ..deps import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/validation")

# Nombre max de candidats enrichis par page détail
_MAX_ENRICHED_CANDIDATES = 10


def _is_series(candidates: list[SearchResult], filename: str) -> bool:
    """Détecte si le fichier est une série (source tvdb ou pattern SxxExx)."""
    if candidates and candidates[0].source == "tvdb":
        return True
    return bool(re.search(r"[Ss]\d{2}[Ee]\d{2}", filename))


def _format_size(size_bytes: int) -> str:
    """Formate une taille en octets en chaîne lisible."""
    if size_bytes >= 1_073_741_824:
        return f"{size_bytes / 1_073_741_824:.1f} Go"
    if size_bytes >= 1_048_576:
        return f"{size_bytes / 1_048_576:.0f} Mo"
    return f"{size_bytes / 1024:.0f} Ko"


def _format_duration(seconds: Optional[int]) -> Optional[str]:
    """Formate une durée en secondes en chaîne lisible."""
    if not seconds:
        return None
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours:
        return f"{hours}h{minutes:02d}"
    return f"{minutes} min"


def _duration_match_class(file_duration: Optional[int], api_duration: Optional[int]) -> str:
    """Retourne la classe CSS pour la comparaison de durée."""
    if not file_duration or not api_duration:
        return ""
    ratio = abs(file_duration - api_duration) / api_duration
    if ratio <= 0.10:
        return "duration-match"
    if ratio <= 0.25:
        return "duration-close"
    return "duration-mismatch"


def _score_class(score: float) -> str:
    """Retourne la classe CSS pour un score."""
    if score >= 85:
        return "score-high"
    if score >= 60:
        return "score-medium"
    return "score-low"


@router.get("/", response_class=HTMLResponse)
async def validation_list(request: Request):
    """Liste des fichiers en attente de validation."""
    container = request.app.state.container
    service = container.validation_service()
    pending_list = service.list_pending()

    # Préparer les données pour le template
    items = []
    for pending in pending_list:
        candidates = parse_candidates(pending.candidates)
        filename = pending.video_file.filename if pending.video_file else "Inconnu"
        best_score = candidates[0].score if candidates else 0.0
        is_series = _is_series(candidates, filename)

        items.append({
            "id": pending.id,
            "filename": filename,
            "is_series": is_series,
            "candidate_count": len(candidates),
            "best_score": best_score,
            "score_class": _score_class(best_score),
            "created_at": pending.created_at,
        })

    # Trier par date décroissante
    items.sort(key=lambda x: x["created_at"] or "", reverse=True)

    return templates.TemplateResponse(
        request,
        "validation/list.html",
        {"items": items, "total": len(items)},
    )


@router.get("/{pending_id}", response_class=HTMLResponse)
async def validation_detail(
    request: Request,
    pending_id: str,
    page: int = Query(1, ge=1),
):
    """Détail d'un fichier avec candidats enrichis (paginé)."""
    container = request.app.state.container
    service = container.validation_service()
    pending = service.get_pending_by_id(pending_id)

    if pending is None:
        return templates.TemplateResponse(
            request,
            "validation/not_found.html",
            {"pending_id": pending_id},
            status_code=404,
        )

    candidates = parse_candidates(pending.candidates)
    filename = pending.video_file.filename if pending.video_file else "Inconnu"
    is_series = _is_series(candidates, filename)

    # Infos du fichier
    file_info = {
        "filename": filename,
        "size": _format_size(pending.video_file.size_bytes) if pending.video_file else None,
        "duration": None,
        "duration_seconds": None,
    }
    if pending.video_file and pending.video_file.media_info:
        dur = pending.video_file.media_info.duration_seconds
        file_info["duration"] = _format_duration(dur)
        file_info["duration_seconds"] = dur

    # Pagination
    total_candidates = len(candidates)
    total_pages = max(1, (total_candidates + _MAX_ENRICHED_CANDIDATES - 1) // _MAX_ENRICHED_CANDIDATES)
    page = min(page, total_pages)
    start = (page - 1) * _MAX_ENRICHED_CANDIDATES
    end = start + _MAX_ENRICHED_CANDIDATES
    page_candidates = candidates[start:end]

    # Enrichir les candidats de la page courante
    enriched = []
    for candidate in page_candidates:
        details = await _fetch_details(container, candidate.source, candidate.id)
        enriched.append({
            "candidate": candidate,
            "details": details,
            "score_class": _score_class(candidate.score),
            "duration_str": _format_duration(details.duration_seconds) if details else None,
            "duration_class": _duration_match_class(
                file_info["duration_seconds"],
                details.duration_seconds if details else None,
            ),
        })

    return templates.TemplateResponse(
        request,
        "validation/detail.html",
        {
            "pending": pending,
            "file_info": file_info,
            "is_series": is_series,
            "enriched_candidates": enriched,
            "total_candidates": total_candidates,
            "page": page,
            "total_pages": total_pages,
            "start_index": start,
        },
    )


@router.post("/{pending_id}/validate", response_class=HTMLResponse)
async def validate_candidate(
    request: Request,
    pending_id: str,
    candidate_id: str = Form(...),
    source: str = Form(...),
):
    """Valide un candidat sélectionné via HTMX."""
    container = request.app.state.container
    service = container.validation_service()
    pending = service.get_pending_by_id(pending_id)

    if pending is None:
        return HTMLResponse(
            '<div class="action-msg action-error">Fichier introuvable.</div>',
            status_code=404,
        )

    # Trouver le SearchResult correspondant parmi les candidats
    candidates = parse_candidates(pending.candidates)
    selected = None
    for c in candidates:
        if c.id == candidate_id and c.source == source:
            selected = c
            break

    # Si non trouvé dans les candidats existants (résultat de recherche manuelle),
    # créer un SearchResult minimal
    if selected is None:
        selected = SearchResult(id=candidate_id, title="", source=source, score=0.0)

    try:
        await service.validate_candidate(pending, selected)
    except ValueError as exc:
        logger.warning("Erreur validation %s: %s", pending_id, exc)
        return HTMLResponse(
            f'<div class="action-msg action-error">Erreur : {exc}</div>',
        )

    # Auto-valider les autres épisodes de la même série (source tvdb)
    auto_count = 0
    if selected.source == "tvdb":
        auto_count = await _auto_validate_series_episodes(
            service, pending, selected
        )

    title = selected.title or candidate_id
    if auto_count > 0:
        msg = (
            f'Validé : <strong>{title}</strong> '
            f'+ {auto_count} autre(s) épisode(s) auto-validé(s) — Redirection…'
        )
    else:
        msg = f'Validé : <strong>{title}</strong> — Redirection…'

    html = (
        f'<div class="action-msg action-success">'
        f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        f'width="18" height="18"><polyline points="20 6 9 17 4 12"/></svg>'
        f'{msg}'
        f'</div>'
    )
    response = HTMLResponse(html)
    response.headers["HX-Redirect"] = "/validation"
    return response


async def _auto_validate_series_episodes(
    service, pending, candidate
) -> int:
    """Auto-valide les autres épisodes de la même série.

    Parcourt les pending restants et valide ceux qui ont le même
    candidat TVDB (même ID) dans leur liste de candidats.

    Returns:
        Nombre d'épisodes auto-validés.
    """
    from ...core.entities.video import ValidationStatus

    candidate_id = candidate.id
    auto_count = 0

    remaining = [
        p for p in service.list_pending()
        if p.validation_status == ValidationStatus.PENDING
        and not p.auto_validated
        and p.id != pending.id
    ]

    for other in remaining:
        other_candidates = parse_candidates(other.candidates)
        matching = [c for c in other_candidates if c.id == candidate_id]
        if matching:
            await service.validate_candidate(other, matching[0])
            auto_count += 1
            fname = other.video_file.filename if other.video_file else "?"
            logger.info("Auto-validé (cascade série): %s", fname)

    return auto_count


@router.post("/{pending_id}/reject", response_class=HTMLResponse)
async def reject_pending(
    request: Request,
    pending_id: str,
):
    """Rejette un fichier en attente via HTMX."""
    container = request.app.state.container
    service = container.validation_service()
    pending = service.get_pending_by_id(pending_id)

    if pending is None:
        return HTMLResponse(
            '<div class="action-msg action-error">Fichier introuvable.</div>',
            status_code=404,
        )

    service.reject_pending(pending)
    html = (
        '<div class="action-msg action-warning">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'width="18" height="18"><line x1="18" y1="6" x2="6" y2="18"/>'
        '<line x1="6" y1="6" x2="18" y2="18"/></svg>'
        'Fichier rejeté. Redirection…'
        '</div>'
    )
    response = HTMLResponse(html)
    response.headers["HX-Redirect"] = "/validation"
    return response


@router.get("/{pending_id}/search", response_class=HTMLResponse)
async def search_manual(
    request: Request,
    pending_id: str,
    q: str = Query("", min_length=1),
    year: Optional[str] = Query(None),
):
    """Recherche manuelle par titre via HTMX."""
    container = request.app.state.container
    service = container.validation_service()
    pending = service.get_pending_by_id(pending_id)

    if pending is None:
        return HTMLResponse(
            '<div class="action-msg action-error">Fichier introuvable.</div>',
            status_code=404,
        )

    candidates = parse_candidates(pending.candidates)
    filename = pending.video_file.filename if pending.video_file else ""
    is_series = _is_series(candidates, filename)

    # Convertir year string → int (le formulaire HTML envoie "" si vide)
    year_int: Optional[int] = None
    if year and year.strip():
        try:
            year_int = int(year.strip())
        except ValueError:
            year_int = None

    # Recherche via le service
    results = await service.search_manual(q, is_series=is_series, year=year_int)

    # Scorer les résultats
    matcher = container.matcher_service()
    file_duration = None
    if pending.video_file and pending.video_file.media_info:
        file_duration = pending.video_file.media_info.duration_seconds

    scored = matcher.score_results(
        results, q, query_year=year_int, query_duration=file_duration, is_series=is_series
    )

    # Enrichir les top-10
    enriched = []
    for candidate in scored[:_MAX_ENRICHED_CANDIDATES]:
        details = await _fetch_details(container, candidate.source, candidate.id)
        enriched.append({
            "candidate": candidate,
            "details": details,
            "score_class": _score_class(candidate.score),
            "duration_str": _format_duration(details.duration_seconds) if details else None,
            "duration_class": _duration_match_class(
                file_duration, details.duration_seconds if details else None
            ),
        })

    return templates.TemplateResponse(
        request,
        "validation/_search_results.html",
        {"enriched_candidates": enriched, "pending_id": pending_id, "query": q},
    )


@router.get("/{pending_id}/search-id", response_class=HTMLResponse)
async def search_by_id(
    request: Request,
    pending_id: str,
    id_type: str = Query(...),
    id_value: str = Query(...),
):
    """Recherche par ID externe (TMDB/TVDB/IMDB) via HTMX."""
    container = request.app.state.container
    service = container.validation_service()
    pending = service.get_pending_by_id(pending_id)

    if pending is None:
        return HTMLResponse(
            '<div class="action-msg action-error">Fichier introuvable.</div>',
            status_code=404,
        )

    # Normaliser l'ID IMDB : ajouter le préfixe 'tt' si absent
    if id_type == "imdb" and id_value.isdigit():
        id_value = f"tt{id_value}"

    details = await service.search_by_external_id(id_type, id_value)

    if details is None:
        return HTMLResponse(
            '<div class="search-empty">'
            f'<p>Aucun résultat pour {id_type.upper()} ID : <strong>{id_value}</strong></p>'
            '</div>'
        )

    # Construire un enriched candidate à partir des details
    file_duration = None
    if pending.video_file and pending.video_file.media_info:
        file_duration = pending.video_file.media_info.duration_seconds

    enriched = [{
        "candidate": SearchResult(
            id=id_value,
            title=details.title or id_value,
            year=details.year,
            score=100.0,
            source=id_type if id_type != "imdb" else "tmdb",
        ),
        "details": details,
        "score_class": "score-high",
        "duration_str": _format_duration(details.duration_seconds) if details else None,
        "duration_class": _duration_match_class(
            file_duration, details.duration_seconds if details else None
        ),
    }]

    return templates.TemplateResponse(
        request,
        "validation/_search_results.html",
        {"enriched_candidates": enriched, "pending_id": pending_id, "query": f"{id_type}:{id_value}"},
    )


async def _fetch_details(
    container, source: str, media_id: str
) -> Optional[MediaDetails]:
    """Récupère les détails d'un média via le client API approprié."""
    try:
        if source == "tmdb":
            client = container.tmdb_client()
            api_key = getattr(client, "_api_key", None)
            if not api_key:
                return None
            return await client.get_details(media_id)
        elif source == "tvdb":
            client = container.tvdb_client()
            api_key = getattr(client, "_api_key", None)
            if not api_key:
                return None
            return await client.get_details(media_id)
    except Exception:
        return None
    return None
