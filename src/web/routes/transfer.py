"""
Routes de transfert des fichiers validés.

Affiche le résumé batch des transferts prévus (arborescence),
permet l'exécution du transfert avec progression SSE,
et gère la résolution interactive des conflits.
"""

import asyncio
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from starlette.responses import StreamingResponse

from ..deps import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transfer")


# ═══════════════════════════════════════
# Structures de données
# ═══════════════════════════════════════


class TransferProgress:
    """État de progression partagé entre le transfert et le SSE."""

    def __init__(self) -> None:
        self.current: int = 0
        self.total: int = 0
        self.filename: str = ""
        self.message: str = "Initialisation…"
        self.complete: bool = False
        self.error: Optional[str] = None

        # Conflit en attente de résolution
        self.conflict_pending: bool = False
        self.conflict_data: Optional[dict] = None
        self.conflict_choice: Optional[str] = None
        self.conflict_event: asyncio.Event = asyncio.Event()

        # Mode simulation
        self.dry_run: bool = False

        # Compteurs finaux
        self.transferred: int = 0
        self.duplicates_ignored: int = 0
        self.conflicts_resolved: int = 0
        self.errors: int = 0

        # Détails par fichier
        self.transferred_files: list[str] = []
        self.transferred_details: list[dict] = []  # {name, storage, symlink}
        self.duplicate_files: list[str] = []
        self.error_files: list[str] = []


def _format_size(size_bytes: int) -> str:
    """Formate une taille en octets en chaîne lisible."""
    if size_bytes >= 1_073_741_824:
        return f"{size_bytes / 1_073_741_824:.1f} Go"
    if size_bytes >= 1_048_576:
        return f"{size_bytes / 1_048_576:.0f} Mo"
    return f"{size_bytes / 1024:.0f} Ko"


def _build_tree_data(transfers: list[dict], storage_dir: Path, video_dir: Path) -> dict:
    """
    Organise les transferts en arborescence pour le template.

    Returns:
        Dict avec 'movies' et 'series', chacun organisé hiérarchiquement.
    """
    movies = []
    series = []

    for t in transfers:
        source = t.get("source")
        source_size = source.stat().st_size if source and source.exists() else 0

        pending = t.get("pending")
        entry = {
            "new_filename": t["new_filename"],
            "source_name": source.name if source else "?",
            "source_size": _format_size(source_size) if source_size else "?",
            "storage_rel": "",
            "symlink_rel": "",
            "title": t.get("title", ""),
            "year": t.get("year"),
            "pending_id": pending.id if pending else None,
        }

        # Calculer les chemins relatifs pour l'affichage
        dest = t.get("destination")
        if dest and storage_dir:
            try:
                entry["storage_rel"] = str(dest.relative_to(storage_dir))
            except ValueError:
                entry["storage_rel"] = str(dest)

        symlink = t.get("symlink_destination")
        if symlink and video_dir:
            try:
                entry["symlink_rel"] = str(symlink.relative_to(video_dir))
            except ValueError:
                entry["symlink_rel"] = str(symlink)

        if t.get("is_series", False):
            series.append(entry)
        else:
            movies.append(entry)

    # Organiser les films par sous-répertoire
    movies_tree = _group_by_path(movies, key="symlink_rel", prefix="Films")

    # Organiser les séries par sous-répertoire
    series_tree = _group_by_path(series, key="symlink_rel", prefix="Séries")

    return {
        "movies": movies_tree,
        "series": series_tree,
        "total": len(transfers),
        "movie_count": len(movies),
        "series_count": len(series),
    }


def _group_by_path(entries: list[dict], key: str, prefix: str) -> list[dict]:
    """
    Regroupe des entrées par leur chemin parent.

    Retourne une liste de groupes avec label (chemin parent) et items.
    """
    groups: dict[str, list[dict]] = defaultdict(list)

    for entry in entries:
        rel = entry.get(key, "")
        # Extraire le répertoire parent (sans le fichier)
        parts = Path(rel).parts
        if len(parts) > 1:
            # Supprimer le préfixe (Films/ ou Séries/) et le fichier
            parent_parts = parts[1:-1] if parts[0] == prefix else parts[:-1]
            parent = "/".join(parent_parts)
        else:
            parent = ""
        groups[parent].append(entry)

    result = []
    for path in sorted(groups.keys()):
        items = sorted(groups[path], key=lambda e: e["new_filename"])
        result.append({"path": path, "files": items})

    return result


# ═══════════════════════════════════════
# Logique de transfert web
# ═══════════════════════════════════════


async def _run_web_transfer(
    container,
    transfers: list[dict],
    progress: TransferProgress,
    *,
    dry_run: bool = False,
) -> None:
    """
    Exécute les transferts avec gestion des conflits et progression.

    En mode dry_run, simule le transfert sans toucher au système de fichiers.

    Pour chaque transfert :
    1. Vérifie les conflits (DUPLICATE / NAME_COLLISION)
    2. Si DUPLICATE → ignore automatiquement
    3. Si NAME_COLLISION ou SIMILAR_CONTENT → pause pour résolution
    4. Sinon → transfer_file()
    """
    try:
        settings = container.config()
        transferer = container.transferer_service(
            storage_dir=settings.storage_dir,
            video_dir=settings.video_dir,
        )

        storage_dir = settings.storage_dir
        video_dir = settings.video_dir
        mode_label = "Simulation" if dry_run else "Transfert"
        progress.total = len(transfers)
        progress.message = f"{mode_label} de {len(transfers)} fichier(s)…"

        def _record_transfer(name: str, dest: Path, sym: Optional[Path]) -> None:
            """Enregistre les détails d'un transfert réussi."""
            progress.transferred_files.append(name)
            try:
                storage_rel = str(dest.relative_to(storage_dir))
            except ValueError:
                storage_rel = str(dest)
            symlink_rel = ""
            if sym:
                try:
                    symlink_rel = str(sym.relative_to(video_dir))
                except ValueError:
                    symlink_rel = str(sym)
            progress.transferred_details.append(
                {
                    "name": name,
                    "storage": storage_rel,
                    "symlink": symlink_rel,
                }
            )

        for i, transfer in enumerate(transfers):
            source = transfer["source"]
            destination = transfer["destination"]
            symlink_dest = transfer.get("symlink_destination")
            new_filename = transfer.get("new_filename", "")
            source_name = source.name if hasattr(source, "name") else str(source)
            display_name = new_filename or source_name

            progress.current = i + 1
            progress.filename = source_name
            progress.message = f"{mode_label} : {source_name}"

            # Vérifier les conflits
            conflict = transferer.check_conflict(source, destination)

            if conflict:
                from src.services.transferer import ConflictType

                if conflict.conflict_type == ConflictType.DUPLICATE:
                    progress.duplicates_ignored += 1
                    progress.duplicate_files.append(display_name)
                    progress.message = (
                        f"[Simulation] Doublon : {display_name}"
                        if dry_run
                        else f"Doublon ignoré : {display_name}"
                    )
                    await asyncio.sleep(0.1)
                    continue

                elif conflict.conflict_type in (
                    ConflictType.NAME_COLLISION,
                    ConflictType.SIMILAR_CONTENT,
                ):
                    existing_path = conflict.existing_path
                    existing_size = (
                        existing_path.stat().st_size if existing_path.exists() else 0
                    )
                    new_size = source.stat().st_size if source.exists() else 0

                    progress.conflict_pending = True
                    progress.conflict_data = {
                        "type": conflict.conflict_type.value,
                        "filename": display_name,
                        "existing_path": str(existing_path),
                        "existing_name": existing_path.name,
                        "existing_size": _format_size(existing_size),
                        "new_name": display_name,
                        "new_size": _format_size(new_size),
                        "transfer_index": i,
                    }

                    try:
                        existing_info = transferer._get_file_info(existing_path)
                        new_info = transferer._get_file_info(source)
                        progress.conflict_data.update(
                            {
                                "existing_resolution": existing_info.resolution or "?",
                                "existing_video_codec": existing_info.video_codec
                                or "?",
                                "existing_audio_codec": existing_info.audio_codec
                                or "?",
                                "new_resolution": new_info.resolution or "?",
                                "new_video_codec": new_info.video_codec or "?",
                                "new_audio_codec": new_info.audio_codec or "?",
                            }
                        )
                    except Exception:
                        progress.conflict_data.update(
                            {
                                "existing_resolution": "?",
                                "existing_video_codec": "?",
                                "existing_audio_codec": "?",
                                "new_resolution": "?",
                                "new_video_codec": "?",
                                "new_audio_codec": "?",
                            }
                        )

                    progress.conflict_event.clear()
                    progress.message = (
                        f"Conflit : {display_name} — en attente de résolution"
                    )
                    await progress.conflict_event.wait()

                    choice = progress.conflict_choice
                    progress.conflict_pending = False
                    progress.conflict_data = None
                    progress.conflict_choice = None

                    if choice == "keep_old":
                        progress.conflicts_resolved += 1
                        progress.message = (
                            f"Conflit résolu : ancien conservé pour {display_name}"
                        )
                        await asyncio.sleep(0.1)
                        continue

                    elif choice == "keep_new":
                        if dry_run:
                            progress.transferred += 1
                            _record_transfer(display_name, destination, symlink_dest)
                            progress.message = (
                                f"[Simulation] Remplacement : {display_name}"
                            )
                        else:
                            try:
                                trash_dir = getattr(
                                    settings, "trash_dir", Path("/tmp/cineorg_trash")
                                )
                                transferer.move_to_staging(existing_path, trash_dir)
                                result = transferer.transfer_file(
                                    source,
                                    destination,
                                    create_symlink=True,
                                    symlink_destination=symlink_dest,
                                )
                                if result.success:
                                    progress.transferred += 1
                                    _record_transfer(
                                        display_name, destination, symlink_dest
                                    )
                                else:
                                    progress.errors += 1
                                    progress.error_files.append(display_name)
                            except Exception as e:
                                logger.warning(
                                    "Erreur transfert %s: %s", source_name, e
                                )
                                progress.errors += 1
                                progress.error_files.append(display_name)
                        progress.conflicts_resolved += 1
                        continue

                    elif choice == "keep_both":
                        stem = destination.stem
                        suffix = destination.suffix
                        destination = destination.with_name(f"{stem} (2){suffix}")
                        if symlink_dest:
                            sym_stem = symlink_dest.stem
                            sym_suffix = symlink_dest.suffix
                            symlink_dest = symlink_dest.with_name(
                                f"{sym_stem} (2){sym_suffix}"
                            )
                        progress.conflicts_resolved += 1

                    else:
                        progress.conflicts_resolved += 1
                        progress.message = f"Conflit passé : {display_name}"
                        await asyncio.sleep(0.1)
                        continue

            # Transfert normal (pas de conflit ou conflit résolu avec keep_both)
            if dry_run:
                progress.transferred += 1
                _record_transfer(display_name, destination, symlink_dest)
                progress.message = f"[Simulation] {display_name} → OK"
                await asyncio.sleep(0.15)
            else:
                try:
                    result = transferer.transfer_file(
                        source,
                        destination,
                        create_symlink=True,
                        symlink_destination=symlink_dest,
                    )
                    if result.success:
                        progress.transferred += 1
                        _record_transfer(display_name, destination, symlink_dest)
                        progress.message = f"Transféré : {display_name}"
                    else:
                        error_msg = result.error or "Erreur inconnue"
                        logger.warning("Échec transfert %s: %s", source_name, error_msg)
                        progress.errors += 1
                        progress.error_files.append(display_name)
                except Exception as e:
                    logger.exception("Erreur transfert %s: %s", source_name, e)
                    progress.errors += 1
                    progress.error_files.append(display_name)

            # Laisser respirer l'event loop
            if i % 2 == 0:
                await asyncio.sleep(0)

        progress.message = "Simulation terminée" if dry_run else "Transfert terminé"
        progress.complete = True

    except Exception as e:
        logger.exception("Erreur lors du transfert web: %s", e)
        progress.error = str(e)
        progress.complete = True


# ═══════════════════════════════════════
# Routes
# ═══════════════════════════════════════


@router.get("/", response_class=HTMLResponse)
async def transfer_index(request: Request):
    """Page principale du transfert — résumé batch."""
    container = request.app.state.container
    validation_service = container.validation_service()

    validated_list = validation_service.list_validated()
    pending_count = len(validation_service.list_pending())

    if not validated_list:
        return templates.TemplateResponse(
            request,
            "transfer/index.html",
            {
                "has_transfers": False,
                "pending_count": pending_count,
                "tree_data": None,
                "transfers_json": "[]",
            },
        )

    # Construire le batch de transferts
    from src.adapters.cli.batch_builder import build_transfers_batch
    from io import StringIO
    from rich.console import Console as RichConsole

    # Utiliser un console silencieux pour supprimer les print Rich
    silent_console = RichConsole(file=StringIO(), quiet=True)
    import src.adapters.cli.batch_builder as bb

    original_console = bb.console
    bb.console = silent_console

    try:
        settings = container.config()
        storage_dir = settings.storage_dir
        video_dir = settings.video_dir

        transfers = await build_transfers_batch(
            validated_list, container, storage_dir, video_dir
        )
    finally:
        bb.console = original_console

    # Stocker le batch pour POST /transfer/start
    request.app.state.transfer_batch = transfers
    request.app.state.transfer_storage_dir = storage_dir
    request.app.state.transfer_video_dir = video_dir

    # Construire les données d'arborescence pour le template
    tree_data = _build_tree_data(transfers, storage_dir, video_dir)

    return templates.TemplateResponse(
        request,
        "transfer/index.html",
        {
            "has_transfers": True,
            "pending_count": pending_count,
            "tree_data": tree_data,
            "transfers_json": "[]",  # Pas besoin de JSON côté client
        },
    )


@router.post("/start", response_class=HTMLResponse)
async def transfer_start(request: Request):
    """Lance le transfert (ou simulation) en arrière-plan."""
    container = request.app.state.container
    dry_run = request.query_params.get("dry_run") == "1"

    # Vérifier qu'un transfert n'est pas déjà en cours
    existing = getattr(request.app.state, "transfer_progress", None)
    if existing and not existing.complete:
        return HTMLResponse(
            '<div class="action-msg action-warning">'
            "Un transfert est déjà en cours."
            "</div>"
        )

    # Récupérer le batch préparé
    transfers = getattr(request.app.state, "transfer_batch", None)
    if not transfers:
        return HTMLResponse(
            '<div class="action-msg action-error">'
            "Aucun transfert préparé. Rechargez la page."
            "</div>"
        )

    # Créer l'état de progression
    progress = TransferProgress()
    progress.dry_run = dry_run
    request.app.state.transfer_progress = progress

    # Lancer en arrière-plan
    task = asyncio.create_task(
        _run_web_transfer(container, transfers, progress, dry_run=dry_run)
    )
    request.app.state.transfer_task = task

    return templates.TemplateResponse(
        request,
        "transfer/_progress.html",
        {"progress": progress},
    )


@router.get("/progress")
async def transfer_progress_sse(request: Request):
    """SSE endpoint pour le suivi de progression du transfert."""
    progress = getattr(request.app.state, "transfer_progress", None)

    async def event_stream():
        if progress is None:
            yield 'event: error\ndata: {"message": "Aucun transfert en cours"}\n\n'
            return

        last_sent = ""
        while not progress.complete:
            # Conflit en attente ?
            if progress.conflict_pending and progress.conflict_data:
                conflict_json = json.dumps(progress.conflict_data, ensure_ascii=False)
                yield f"event: conflict\ndata: {conflict_json}\n\n"
                # Attendre que le conflit soit résolu avant de continuer
                await progress.conflict_event.wait()
                # Petit délai pour laisser le temps au front de se mettre à jour
                await asyncio.sleep(0.3)
                continue

            # Progression normale
            data = json.dumps(
                {
                    "current": progress.current,
                    "total": progress.total,
                    "filename": progress.filename,
                    "message": progress.message,
                    "transferred": progress.transferred,
                    "duplicates": progress.duplicates_ignored,
                },
                ensure_ascii=False,
            )

            if data != last_sent:
                yield f"event: progress\ndata: {data}\n\n"
                last_sent = data

            await asyncio.sleep(0.4)

        # Envoyer le dernier état de progression (compteur final)
        final_progress = json.dumps(
            {
                "current": progress.total,
                "total": progress.total,
                "filename": "",
                "message": progress.message,
                "transferred": progress.transferred,
                "duplicates": progress.duplicates_ignored,
            },
            ensure_ascii=False,
        )
        yield f"event: progress\ndata: {final_progress}\n\n"
        await asyncio.sleep(0.2)

        # Résultat final
        if progress.error:
            error_data = json.dumps({"message": progress.error}, ensure_ascii=False)
            yield f"event: error\ndata: {error_data}\n\n"
        else:
            complete_data = json.dumps(
                {
                    "transferred": progress.transferred,
                    "duplicates_ignored": progress.duplicates_ignored,
                    "conflicts_resolved": progress.conflicts_resolved,
                    "errors": progress.errors,
                    "transferred_files": progress.transferred_files,
                    "transferred_details": progress.transferred_details,
                    "duplicate_files": progress.duplicate_files,
                    "error_files": progress.error_files,
                },
                ensure_ascii=False,
            )
            yield f"event: complete\ndata: {complete_data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/send-back/{pending_id}", response_class=HTMLResponse)
async def send_back(request: Request, pending_id: str):
    """Renvoie un fichier validé en statut pending pour re-validation.

    Pour les séries : renvoie aussi tous les épisodes de la même série
    (même selected_candidate_id) — cascade inverse de l'auto-validation.
    """
    container = request.app.state.container
    validation_service = container.validation_service()
    pending = validation_service.get_pending_by_id(pending_id)

    if pending is None:
        return HTMLResponse(
            '<div class="action-msg action-error">Fichier introuvable.</div>',
            status_code=404,
        )

    candidate_id = pending.selected_candidate_id
    validation_service.reset_to_pending(pending)

    # Cascade inverse pour les séries : renvoyer tous les épisodes
    # ayant le même candidat TVDB (miroir de _auto_validate_series_episodes)
    cascade_count = 0
    if candidate_id:
        validated_list = validation_service.list_validated()
        for other in validated_list:
            if other.id != pending_id and other.selected_candidate_id == candidate_id:
                validation_service.reset_to_pending(other)
                cascade_count += 1

    if cascade_count > 0:
        msg = f"Fichier + {cascade_count} épisode(s) renvoyé(s) en validation."
    else:
        msg = "Fichier renvoyé en validation."

    response = HTMLResponse(
        '<div class="action-msg action-success">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'width="18" height="18"><polyline points="20 6 9 17 4 12"/></svg>'
        f"{msg}"
        "</div>"
    )
    response.headers["HX-Redirect"] = "/transfer"
    return response


@router.post("/resolve-conflict", response_class=HTMLResponse)
async def resolve_conflict(
    request: Request,
    choice: str = Form(...),
):
    """Résout un conflit en attente."""
    progress = getattr(request.app.state, "transfer_progress", None)

    if progress is None or not progress.conflict_pending:
        return HTMLResponse(
            '<div class="action-msg action-warning">Aucun conflit en attente.</div>'
        )

    # Enregistrer le choix et débloquer le transfert
    progress.conflict_choice = choice
    progress.conflict_event.set()

    return HTMLResponse(
        '<div class="action-msg action-success">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'width="18" height="18"><polyline points="20 6 9 17 4 12"/></svg>'
        "Conflit résolu, transfert en cours…"
        "</div>"
    )
