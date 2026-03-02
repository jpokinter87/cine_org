"""
Routes du workflow de traitement des vidéos.

Permet de lancer le workflow complet (scan → matching → auto-validation)
depuis l'interface web avec suivi de progression en temps réel via SSE.
"""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from starlette.responses import RedirectResponse, StreamingResponse

from sqlmodel import delete, select

from ...core.entities.video import ValidationStatus
from ...core.value_objects.parsed_info import MediaType
from ...infrastructure.persistence.models import (
    PendingValidationModel,
    VideoFileModel,
)
from ...services.workflow.pending_factory import create_pending_validation
from ..deps import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflow")


class WorkflowProgress:
    """État de progression partagé entre le workflow et le SSE."""

    def __init__(self) -> None:
        self.step: str = ""
        self.step_number: int = 0
        self.total_steps: int = 4
        self.current: int = 0
        self.total: int = 0
        self.filename: str = ""
        self.message: str = ""
        self.complete: bool = False
        self.error: Optional[str] = None
        # Résultats finaux
        self.scanned: int = 0
        self.undersized_ignored: int = 0
        self.orphans_cleaned: int = 0
        self.auto_validated: int = 0
        self.pending_remaining: int = 0
        # Noms de fichiers par catégorie (pour tooltips)
        self.scanned_files: list[str] = []
        self.auto_validated_files: list[str] = []
        self.pending_files: list[str] = []
        self.undersized_files: list[str] = []


async def _run_web_workflow(
    container,
    filter_type: str,
    progress: WorkflowProgress,
) -> None:
    """
    Exécute le workflow web (scan → matching → auto-validation).

    Réutilise les services individuels du container sans passer
    par WorkflowService.execute() qui est couplé à Rich/Confirm.
    """
    try:
        # Convertir le filtre textuel en MediaType pour le scanner
        scan_media_type: Optional[MediaType] = None
        if filter_type == "movies":
            scan_media_type = MediaType.MOVIE
        elif filter_type == "series":
            scan_media_type = MediaType.SERIES

        # Initialiser les services
        scanner = container.scanner_service()
        validation_service = container.validation_service()
        matcher = container.matcher_service()
        tmdb_client = container.tmdb_client()
        tvdb_client = container.tvdb_client()
        pending_repo = container.pending_validation_repository()
        video_file_repo = container.video_file_repository()

        # ── Étape 1/4 : Réinitialisation de la base ──
        progress.step = "Nettoyage"
        progress.step_number = 1
        progress.message = "Suppression des traitements précédents…"

        # Suppression batch (un seul commit au lieu d'un par entrée)
        session = pending_repo._session
        count = len(session.exec(select(PendingValidationModel)).all())
        if count > 0:
            session.exec(delete(PendingValidationModel))
            session.exec(delete(VideoFileModel))
            session.commit()
            progress.orphans_cleaned = count
            progress.message = f"{count} enregistrement(s) précédent(s) supprimé(s)"
        await asyncio.sleep(0.1)

        # ── Étape 2/4 : Scan des téléchargements ──
        progress.step = "Scan"
        progress.step_number = 2
        progress.message = "Scan des téléchargements…"
        await asyncio.sleep(0.1)

        # Exécuter le scan dans un thread pour libérer l'event loop
        # (mediainfo ouvre chaque fichier — lent sur NAS réseau)
        def _collect_scan():
            results = []
            for result in scanner.scan_downloads(media_type=scan_media_type):
                progress.filename = result.video_file.filename
                progress.message = f"Scan : {result.video_file.filename}"
                results.append(result)
                progress.current = len(results)
            return results

        scan_results = await asyncio.to_thread(_collect_scan)

        # Compter les undersized ignorés (pas de Confirm en web)
        def _collect_undersized():
            return list(scanner.scan_undersized_files(media_type=scan_media_type))

        undersized_filtered = await asyncio.to_thread(_collect_undersized)
        progress.undersized_ignored = len(undersized_filtered)
        progress.undersized_files = [r.video_file.filename for r in undersized_filtered]

        progress.total = len(scan_results)

        if not scan_results:
            progress.message = "Aucun fichier à traiter."
            progress.complete = True
            return

        progress.message = f"{len(scan_results)} fichier(s) trouvé(s)"
        await asyncio.sleep(0.2)

        # ── Étape 3/4 : Matching avec les APIs ──
        progress.step = "Matching"
        progress.step_number = 3
        progress.current = 0
        progress.total = len(scan_results)
        progress.message = "Matching avec les APIs…"
        await asyncio.sleep(0.1)

        created_video_file_ids: list[str] = []

        for i, result in enumerate(scan_results):
            progress.current = i + 1
            progress.filename = result.video_file.filename
            progress.message = f"Matching : {result.video_file.filename}"

            # Rechercher les candidats via API
            video_file, pending = await create_pending_validation(
                result, matcher, tmdb_client, tvdb_client
            )

            # Sauvegarder
            saved_vf = video_file_repo.save(video_file)
            if saved_vf.id:
                created_video_file_ids.append(saved_vf.id)
                progress.scanned_files.append(result.video_file.filename)
            pending.video_file = saved_vf
            pending_repo.save(pending)

            # Laisser respirer l'event loop
            if i % 3 == 0:
                await asyncio.sleep(0)

        # Compteur scanned = nombre réel de fichiers sauvegardés en DB
        progress.scanned = len(created_video_file_ids)
        progress.message = f"{progress.scanned} fichier(s) matchés"
        await asyncio.sleep(0.2)

        # ── Étape 4/4 : Auto-validation ──
        progress.step = "Auto-validation"
        progress.step_number = 4
        progress.message = "Auto-validation en cours…"

        pending_list = validation_service.list_pending()
        progress.current = 0
        progress.total = len(pending_list)

        auto_count = 0
        for i, pend in enumerate(pending_list):
            progress.current = i + 1
            progress.filename = pend.video_file.filename if pend.video_file else ""

            fname = pend.video_file.filename if pend.video_file else "?"
            result = await validation_service.process_auto_validation(pend)
            if result.auto_validated:
                auto_count += 1
                progress.auto_validated_files.append(fname)
            progress.message = f"Auto-validation : {auto_count} validé(s)"

            if i % 5 == 0:
                await asyncio.sleep(0)

        progress.auto_validated = auto_count

        # Compter les pending restants (PENDING uniquement, pas VALIDATED)
        remaining = [
            p for p in validation_service.list_pending()
            if p.validation_status == ValidationStatus.PENDING
        ]
        progress.pending_remaining = len(remaining)
        progress.pending_files = [
            p.video_file.filename for p in remaining if p.video_file
        ]

        # Vérification de cohérence des compteurs
        if progress.scanned != progress.auto_validated + progress.pending_remaining:
            logger.warning(
                "Décalage compteurs: scanned=%d, auto=%d, pending=%d",
                progress.scanned,
                progress.auto_validated,
                progress.pending_remaining,
            )

        progress.message = "Traitement terminé"
        progress.complete = True

    except Exception as e:
        logger.exception("Erreur lors du workflow web: %s", e)
        progress.error = str(e)
        progress.complete = True


# ═══════════════════════════════════════
# Routes
# ═══════════════════════════════════════

@router.get("/", response_class=HTMLResponse)
async def workflow_index(request: Request):
    """Page principale du workflow."""
    container = request.app.state.container
    validation_service = container.validation_service()

    pending_count = len(validation_service.list_pending())
    validated_count = len(validation_service.list_validated())

    # Vérifier si un workflow est en cours
    progress = getattr(request.app.state, "workflow_progress", None)
    running = progress is not None and not progress.complete

    return templates.TemplateResponse(
        request,
        "workflow/index.html",
        {
            "pending_count": pending_count,
            "validated_count": validated_count,
            "running": running,
            "progress": progress,
        },
    )


@router.post("/start", response_class=HTMLResponse)
async def workflow_start(
    request: Request,
    filter_type: str = Form("all"),
):
    """Lance le workflow en arrière-plan."""
    container = request.app.state.container

    # Vérifier qu'un workflow n'est pas déjà en cours
    existing = getattr(request.app.state, "workflow_progress", None)
    if existing and not existing.complete:
        return HTMLResponse(
            '<div class="action-msg action-warning">'
            "Un traitement est déjà en cours."
            "</div>"
        )

    # Créer l'état de progression
    progress = WorkflowProgress()
    request.app.state.workflow_progress = progress

    # Lancer le workflow en arrière-plan
    task = asyncio.create_task(
        _run_web_workflow(container, filter_type, progress)
    )
    request.app.state.workflow_task = task

    # Retourner le fragment qui active le suivi SSE
    return templates.TemplateResponse(
        request,
        "workflow/_progress.html",
        {"progress": progress},
    )


@router.get("/progress")
async def workflow_progress_sse(request: Request):
    """SSE endpoint pour le suivi de progression."""
    progress = getattr(request.app.state, "workflow_progress", None)

    async def event_stream():
        if progress is None:
            yield 'event: error\ndata: {"message": "Aucun traitement en cours"}\n\n'
            return

        last_sent = ""
        while not progress.complete:
            # Construire les données de progression
            data = (
                f'{{"step": "{progress.step}", '
                f'"step_number": {progress.step_number}, '
                f'"total_steps": {progress.total_steps}, '
                f'"current": {progress.current}, '
                f'"total": {progress.total}, '
                f'"filename": "{_escape_json(progress.filename)}", '
                f'"message": "{_escape_json(progress.message)}"}}'
            )

            # N'envoyer que si les données ont changé
            if data != last_sent:
                yield f"event: progress\ndata: {data}\n\n"
                last_sent = data

            await asyncio.sleep(0.4)

        # Envoyer le résultat final
        if progress.error:
            yield (
                f'event: error\n'
                f'data: {{"message": "{_escape_json(progress.error)}"}}\n\n'
            )
        else:
            complete_data = json.dumps({
                "scanned": progress.scanned,
                "auto_validated": progress.auto_validated,
                "pending_remaining": progress.pending_remaining,
                "undersized_ignored": progress.undersized_ignored,
                "orphans_cleaned": progress.orphans_cleaned,
                "scanned_files": progress.scanned_files,
                "auto_validated_files": progress.auto_validated_files,
                "pending_files": progress.pending_files,
                "undersized_files": progress.undersized_files,
            }, ensure_ascii=False)
            yield f'event: complete\ndata: {complete_data}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/reset", response_class=HTMLResponse)
async def workflow_reset(request: Request):
    """Réinitialise le workflow en supprimant toutes les données intermédiaires."""
    container = request.app.state.container
    session = container.pending_validation_repository()._session

    pending_count = session.exec(
        select(PendingValidationModel)
    ).all()
    video_count = session.exec(
        select(VideoFileModel)
    ).all()

    session.exec(delete(PendingValidationModel))
    session.exec(delete(VideoFileModel))
    session.commit()

    logger.info(
        "Workflow réinitialisé : %d validations et %d fichiers supprimés",
        len(pending_count),
        len(video_count),
    )

    # Nettoyer l'état de progression
    request.app.state.workflow_progress = None

    return RedirectResponse(url="/workflow/", status_code=303)


def _escape_json(s: str) -> str:
    """Échappe une chaîne pour inclusion dans du JSON."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
