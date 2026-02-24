"""
Routes de la page de maintenance.

Affiche les diagnostics d'intégrité et de nettoyage de la vidéothèque
en mode lecture seule avec progression SSE en temps réel.
Les actions correctives restent dans le CLI.

Scope limité aux Films et Séries uniquement.
"""

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..deps import templates

router = APIRouter()

# Sous-dossiers du storage à analyser (films et séries uniquement)
_SCOPED_SUBDIRS = ("Films", "Séries")


def _truncate_path(path: Path | str, segments: int = 3) -> str:
    """Tronque un chemin en ne gardant que les N derniers segments."""
    parts = Path(path).parts
    if len(parts) <= segments:
        return str(path)
    return ".../" + "/".join(parts[-segments:])


def _relative_from_root(path: Path | str) -> str:
    """Retourne le chemin relatif depuis Films/ ou Séries/ (inclus)."""
    parts = Path(path).parts
    for i, part in enumerate(parts):
        if part in _SCOPED_SUBDIRS:
            return "/".join(parts[i:])
    # Fallback : derniers 4 segments
    if len(parts) > 4:
        return ".../" + "/".join(parts[-4:])
    return str(path)


def _escape_json(s: str) -> str:
    """Échappe une chaîne pour inclusion dans du JSON SSE."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _sse_progress(phase: int, total: int, label: str) -> str:
    """Construit un événement SSE de progression."""
    data = json.dumps(
        {"phase": phase, "total": total, "label": label},
        ensure_ascii=False,
    )
    return f"event: progress\ndata: {data}\n\n"


def _sse_complete(html: str) -> str:
    """Construit un événement SSE de fin avec le HTML résultat."""
    return (
        f"event: complete\ndata: {json.dumps({'html': html}, ensure_ascii=False)}\n\n"
    )


# ---------------------------------------------------------------------------
# Page principale
# ---------------------------------------------------------------------------


@router.get("/maintenance")
async def maintenance_page(request: Request):
    """Page principale de maintenance."""
    return templates.TemplateResponse(request, "maintenance/index.html", {})


# ---------------------------------------------------------------------------
# SSE — Diagnostic d'intégrité
# ---------------------------------------------------------------------------


def _check_ghost_entries(checker):
    """Exécute la vérification des entrées fantômes (sync)."""
    from ...services.integrity import IntegrityReport

    report = IntegrityReport()
    checker._check_ghost_entries(report)
    return report.issues


def _check_orphan_files(storage_dir: Path):
    """Recherche les fichiers physiques non référencés par les tables movies/episodes."""
    from sqlmodel import Session, select

    from ...infrastructure.persistence.database import get_engine
    from ...infrastructure.persistence.models import EpisodeModel, MovieModel
    from ...services.integrity import IntegrityIssue, IssueType
    from ...utils.constants import VIDEO_EXTENSIONS

    session = Session(get_engine())

    # Construire un set de tous les file_path connus en DB
    known_paths: set[str] = set()
    for fp in session.exec(
        select(MovieModel.file_path).where(MovieModel.file_path.is_not(None))
    ):  # type: ignore[union-attr]
        known_paths.add(fp)
    for fp in session.exec(
        select(EpisodeModel.file_path).where(EpisodeModel.file_path.is_not(None))
    ):  # type: ignore[union-attr]
        known_paths.add(fp)

    issues: list[IntegrityIssue] = []
    for subdir_name in _SCOPED_SUBDIRS:
        subdir = storage_dir / subdir_name
        if not subdir.exists():
            continue
        for video_file in subdir.rglob("*"):
            if video_file.is_dir() or video_file.is_symlink():
                continue
            if video_file.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            if str(video_file) not in known_paths:
                issues.append(
                    IntegrityIssue(type=IssueType.ORPHAN_FILE, path=video_file)
                )
    session.close()
    return issues


def _check_broken_symlinks(checker):
    """Détecte les symlinks cassés dans video/ (sync)."""
    from ...services.integrity import IntegrityIssue, IssueType

    issues: list[IntegrityIssue] = []
    if not checker._video_dir or not checker._video_dir.exists():
        return issues

    # Limiter aux sous-dossiers Films/ et Séries/ du video_dir
    for subdir_name in _SCOPED_SUBDIRS:
        subdir = checker._video_dir / subdir_name
        if not subdir.exists():
            continue
        broken_links = checker._file_system.find_broken_links(subdir)
        for link in broken_links:
            try:
                original_target = link.readlink()
            except OSError:
                original_target = Path("<inconnu>")
            issues.append(
                IntegrityIssue(
                    type=IssueType.BROKEN_SYMLINK,
                    path=link,
                    details=str(original_target),
                )
            )
    return issues


@router.get("/maintenance/check")
async def run_check_sse(request: Request):
    """SSE endpoint : diagnostic d'intégrité avec progression par phase."""
    container = request.app.state.container
    settings = container.config()

    checker = container.integrity_checker(
        storage_dir=settings.storage_dir,
        video_dir=settings.video_dir,
    )

    phases = [
        ("ghost", "Vérification des entrées fantômes"),
        ("orphan", "Recherche des fichiers orphelins (Films + Séries)"),
        ("symlinks", "Détection des symlinks cassés (Films + Séries)"),
    ]

    async def event_stream():
        all_issues = []

        # Phase 1 — entrées fantômes
        yield _sse_progress(1, len(phases), phases[0][1])
        issues = await asyncio.to_thread(_check_ghost_entries, checker)
        all_issues.extend(issues)

        # Phase 2 — fichiers orphelins (compare storage vs MovieModel/EpisodeModel)
        yield _sse_progress(2, len(phases), phases[1][1])
        issues = await asyncio.to_thread(_check_orphan_files, settings.storage_dir)
        all_issues.extend(issues)

        # Phase 3 — symlinks cassés (scopé Films + Séries)
        yield _sse_progress(3, len(phases), phases[2][1])
        issues = await asyncio.to_thread(_check_broken_symlinks, checker)
        all_issues.extend(issues)

        # Construire les suggestions
        ghost = [i for i in all_issues if i.type.value == "ghost_entry"]
        orphans = [i for i in all_issues if i.type.value == "orphan_file"]
        broken = [i for i in all_issues if i.type.value == "broken_symlink"]

        suggestions = []
        if ghost:
            suggestions.append(
                f"Pour {len(ghost)} entrée(s) fantôme(s) : "
                "vérifier si les fichiers ont été déplacés ou supprimés"
            )
        if orphans:
            suggestions.append(
                f"Pour {len(orphans)} fichier(s) orphelin(s) : "
                "<code>cineorg import</code> pour les ajouter à la BDD"
            )
        if broken:
            suggestions.append(
                f"Pour {len(broken)} symlink(s) cassé(s) : "
                "<code>cineorg repair-links</code> pour les réparer"
            )

        # Préparer les données template (limiter à MAX_DISPLAY éléments)
        max_display = 50
        ghost_entries = [
            {
                "path": _relative_from_root(i.path),
                "full_path": str(i.path),
                "details": i.details,
            }
            for i in ghost[:max_display]
        ]
        orphan_files = [
            {"path": _relative_from_root(i.path), "full_path": str(i.path)}
            for i in orphans[:max_display]
        ]
        broken_symlinks = [
            {
                "path": _relative_from_root(i.path),
                "full_path": str(i.path),
                "details": i.details,
            }
            for i in broken[:max_display]
        ]

        html = templates.env.get_template("maintenance/_check_results.html").render(
            has_issues=len(all_issues) > 0,
            total_issues=len(all_issues),
            ghost_entries=ghost_entries,
            orphan_files=orphan_files,
            broken_symlinks=broken_symlinks,
            ghost_total=len(ghost),
            orphan_total=len(orphans),
            broken_total=len(broken),
            max_display=max_display,
            suggestions=suggestions if all_issues else [],
        )

        yield _sse_complete(html)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# SSE — Analyse nettoyage
# ---------------------------------------------------------------------------


@router.get("/maintenance/cleanup")
async def run_cleanup_sse(request: Request):
    """SSE endpoint : analyse cleanup avec progression par phase."""
    container = request.app.state.container
    settings = container.config()

    phases_info = [
        "Construction de l'index des fichiers",
        "Détection des symlinks cassés",
        "Recherche des symlinks mal placés",
        "Détection des doublons",
        "Vérification des répertoires surdimensionnés",
        "Recherche des répertoires vides",
    ]

    async def event_stream():
        # Phase 1 : construire l'index
        yield _sse_progress(1, len(phases_info), phases_info[0])

        repair_svc = container.repair_service(
            storage_dir=settings.storage_dir,
            video_dir=settings.video_dir,
            trash_dir=settings.storage_dir / ".trash",
        )
        await asyncio.to_thread(repair_svc.build_file_index)

        cleanup_svc = container.cleanup_service(repair_service=repair_svc)
        video_dir = settings.video_dir
        max_per_dir = settings.max_files_per_subdir

        # Phase 2 : symlinks cassés
        yield _sse_progress(2, len(phases_info), phases_info[1])
        broken_raw = await asyncio.to_thread(
            cleanup_svc._scan_broken_symlinks, video_dir
        )

        # Phase 3 : symlinks mal placés
        yield _sse_progress(3, len(phases_info), phases_info[2])
        misplaced_result = await asyncio.to_thread(
            cleanup_svc._scan_misplaced_symlinks, video_dir
        )
        if isinstance(misplaced_result, tuple):
            misplaced_raw, _ = misplaced_result
        else:
            misplaced_raw = misplaced_result

        # Phase 4 : doublons
        yield _sse_progress(4, len(phases_info), phases_info[3])
        duplicates_raw = await asyncio.to_thread(
            cleanup_svc._scan_duplicate_symlinks, video_dir
        )

        # Phase 5 : surdimensionnés
        yield _sse_progress(5, len(phases_info), phases_info[4])
        oversized_raw = await asyncio.to_thread(
            cleanup_svc._scan_oversized_dirs, video_dir, max_per_dir
        )

        # Phase 6 : vides
        yield _sse_progress(6, len(phases_info), phases_info[5])
        empty_raw = await asyncio.to_thread(cleanup_svc._scan_empty_dirs, video_dir)

        # Construire les données template
        has_issues = bool(
            broken_raw or misplaced_raw or duplicates_raw or oversized_raw or empty_raw
        )
        total_issues = (
            len(broken_raw)
            + len(misplaced_raw)
            + len(duplicates_raw)
            + len(oversized_raw)
            + len(empty_raw)
        )

        max_display = 50
        broken = [
            {
                "path": _relative_from_root(b.symlink_path),
                "full_path": str(b.symlink_path),
                "score": f"{b.candidate_score:.0f}" if b.best_candidate else None,
                "candidate": _relative_from_root(b.best_candidate)
                if b.best_candidate
                else None,
            }
            for b in broken_raw[:max_display]
        ]
        misplaced = [
            {
                "path": _relative_from_root(m.symlink_path),
                "title": m.media_title or _truncate_path(m.symlink_path, 1),
                "current": _relative_from_root(m.current_dir),
                "expected": _relative_from_root(m.expected_dir),
            }
            for m in misplaced_raw[:max_display]
        ]
        duplicates = [
            {
                "target": _relative_from_root(d.target_path),
                "keep": _relative_from_root(d.keep),
                "remove": [_relative_from_root(r) for r in d.remove],
                "remove_count": len(d.remove),
            }
            for d in duplicates_raw[:max_display]
        ]
        oversized = [
            {
                "path": _relative_from_root(o.parent_dir),
                "count": o.current_count,
                "max": o.max_allowed,
            }
            for o in oversized_raw[:max_display]
        ]
        empty = [{"path": _relative_from_root(e)} for e in empty_raw[:max_display]]

        html = templates.env.get_template("maintenance/_cleanup_results.html").render(
            has_issues=has_issues,
            total_issues=total_issues,
            broken=broken,
            misplaced=misplaced,
            duplicates=duplicates,
            oversized=oversized,
            empty=empty,
            broken_total=len(broken_raw),
            misplaced_total=len(misplaced_raw),
            duplicates_total=len(duplicates_raw),
            oversized_total=len(oversized_raw),
            empty_total=len(empty_raw),
            max_display=max_display,
        )

        yield _sse_complete(html)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
