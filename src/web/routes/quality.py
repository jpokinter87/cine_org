"""
Routes de la page Qualité — détection d'associations TMDB suspectes.

Affiche les films et séries dont l'association TMDB est potentiellement erronée,
avec score de confiance et raisons. Progression SSE en temps réel.
Les résultats sont mis en cache pour éviter de rescanner à chaque affichage.
"""

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from sqlmodel import select

from ...infrastructure.persistence.database import get_session
from ...infrastructure.persistence.models import (
    ConfirmedAssociationModel,
    MovieModel,
    SeriesModel,
)
from ...services.association_checker import AssociationChecker, SuspiciousAssociation
from ..deps import templates

router = APIRouter(prefix="/quality", tags=["quality"])

# --- Cache fichier persistant des résultats de scan ---
_CACHE_DIR = Path.home() / ".cineorg"
_CACHE_FILE = _CACHE_DIR / "quality_scan_cache.json"
_CACHE_MAX_AGE = 24 * 60 * 60  # 24 heures


def _invalidate_cache() -> None:
    """Invalide entièrement le cache."""
    _CACHE_FILE.unlink(missing_ok=True)


def _remove_from_cache(entity_type: str, entity_id: int) -> None:
    """Retire un item du cache sans tout invalider."""
    results = _get_cache()
    if results is not None:
        results = [
            r for r in results
            if not (r.entity_type == entity_type and r.entity_id == entity_id)
        ]
        _set_cache(results)


def _set_cache(results: list[SuspiciousAssociation]) -> None:
    """Sauvegarde les résultats du scan sur disque."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "time": time.time(),
        "results": [
            {
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "title_tmdb": r.title_tmdb,
                "title_parsed": r.title_parsed,
                "year_tmdb": r.year_tmdb,
                "year_parsed": r.year_parsed,
                "confidence_score": r.confidence_score,
                "reasons": r.reasons,
                "poster_path": r.poster_path,
            }
            for r in results
        ],
    }
    _CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False))


def _get_cache() -> list[SuspiciousAssociation] | None:
    """Charge le cache depuis le disque s'il est valide."""
    if not _CACHE_FILE.exists():
        return None
    try:
        data = json.loads(_CACHE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if time.time() - data.get("time", 0) > _CACHE_MAX_AGE:
        _invalidate_cache()
        return None
    return [
        SuspiciousAssociation(**item) for item in data.get("results", [])
    ]


def _sse_event(event: str, data: dict) -> str:
    """Construit un événement SSE."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _render_results(
    results: list[SuspiciousAssociation], filter: str, from_cache: bool = False
) -> str:
    """Filtre et rend le HTML des résultats."""
    if filter == "movie":
        results = [r for r in results if r.entity_type == "movie"]
    elif filter == "series":
        results = [r for r in results if r.entity_type == "series"]

    movie_count = sum(1 for r in results if r.entity_type == "movie")
    series_count = sum(1 for r in results if r.entity_type == "series")

    return templates.get_template("quality/_suspicious_list.html").render(
        results=results,
        total=len(results),
        movie_count=movie_count,
        series_count=series_count,
        current_filter=filter,
        from_cache=from_cache,
    )


@router.get("/suspicious", response_class=HTMLResponse)
async def suspicious_page(request: Request):
    """Page principale listant les associations suspectes."""
    return templates.TemplateResponse(request, "quality/suspicious.html", {})


@router.get("/suspicious/scan")
async def suspicious_scan_sse(
    request: Request, filter: str = "all", force: str = "false"
):
    """SSE endpoint : scan des associations suspectes avec progression."""

    # Vérifier le cache sauf si force=true
    cached = _get_cache() if force != "true" else None
    if cached is not None:
        # Retourner immédiatement depuis le cache
        async def generate_cached() -> AsyncGenerator[str, None]:
            html = _render_results(cached, filter, from_cache=True)
            yield _sse_event("complete", {"html": html})

        return StreamingResponse(
            generate_cached(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def generate() -> AsyncGenerator[str, None]:
        session = next(get_session())
        try:
            checker = AssociationChecker(session)
            progress_queue: asyncio.Queue[tuple[int, int, str]] = asyncio.Queue()

            def on_progress(current: int, total: int, label: str) -> None:
                progress_queue.put_nowait((current, total, label))

            # Lancer le scan dans un thread (I/O bound — mediainfo)
            loop = asyncio.get_event_loop()
            scan_task = loop.run_in_executor(
                None, lambda: checker.scan_suspicious(on_progress=on_progress)
            )

            # Émettre les événements de progression
            while not scan_task.done():
                try:
                    current, total, label = await asyncio.wait_for(
                        progress_queue.get(), timeout=0.3
                    )
                    pct = int(current / total * 100) if total > 0 else 0
                    yield _sse_event(
                        "progress",
                        {"current": current, "total": total, "pct": pct, "label": label},
                    )
                except asyncio.TimeoutError:
                    pass

            results: list[SuspiciousAssociation] = scan_task.result()

            # Vider les événements restants
            while not progress_queue.empty():
                current, total, label = progress_queue.get_nowait()
                pct = int(current / total * 100) if total > 0 else 0
                yield _sse_event(
                    "progress",
                    {"current": current, "total": total, "pct": pct, "label": label},
                )

            # Mettre en cache les résultats complets (avant filtrage)
            _set_cache(results)

            html = _render_results(results, filter)
            yield _sse_event("complete", {"html": html})

        finally:
            session.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/suspicious/confirm")
async def confirm_association(
    entity_type: str = Form(...),
    entity_id: int = Form(...),
):
    """Confirme une association TMDB comme correcte (exclue des futurs scans)."""
    session = next(get_session())
    try:
        confirmed = ConfirmedAssociationModel(
            entity_type=entity_type,
            entity_id=entity_id,
        )
        session.add(confirmed)
        session.commit()
        _remove_from_cache(entity_type, entity_id)
        return HTMLResponse(
            '<span class="quality-confirmed-badge">'
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="2">'
            '<polyline points="20 6 9 17 4 12"/></svg>'
            "Confirmé</span>"
        )
    finally:
        session.close()


@router.get("/suspicious/check-confirmed")
async def check_confirmed(ids: str = Query(...)):
    """Vérifie quels entity_type:entity_id sont confirmés.

    Paramètre ids : chaîne "movie:1,series:5,movie:42"
    Retourne la liste des confirmés avec les infos mises à jour.
    """
    session = next(get_session())
    try:
        confirmed = session.exec(select(ConfirmedAssociationModel)).all()
        confirmed_set = {(c.entity_type, c.entity_id) for c in confirmed}

        result = []
        for item in ids.split(","):
            parts = item.strip().split(":")
            if len(parts) == 2:
                entity_type, entity_id = parts[0], int(parts[1])
                if (entity_type, entity_id) in confirmed_set:
                    entry = {"entity_type": entity_type, "entity_id": entity_id}
                    # Récupérer les infos mises à jour
                    if entity_type == "movie":
                        movie = session.get(MovieModel, entity_id)
                        if movie:
                            entry["title"] = movie.title
                            entry["year"] = movie.year
                            entry["poster_path"] = movie.poster_path
                    elif entity_type == "series":
                        series = session.get(SeriesModel, entity_id)
                        if series:
                            entry["title"] = series.title
                            entry["year"] = series.year
                            entry["poster_path"] = series.poster_path
                    result.append(entry)
        return JSONResponse(result)
    finally:
        session.close()
