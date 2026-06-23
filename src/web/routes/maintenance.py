"""
Routes de la page de maintenance.

Affiche les diagnostics d'integrite et de nettoyage de la videotheque
avec progression SSE en temps reel. Permet l'execution des corrections
depuis le web (cleanup fix, repair symlinks) avec restriction localhost.
Inclut la gestion de la corbeille (liste, restauration, vidage)
et du sandbox (isolation des fichiers orphelins).

Scope limite aux Films et Series uniquement.
"""

import asyncio
import json
import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from loguru import logger
from sqlmodel import select

from ..deps import templates
from ...services.sandbox_service import SandboxService

router = APIRouter()

# Sous-dossiers du storage à analyser (films et séries uniquement)
_SCOPED_SUBDIRS = ("Films", "Series", "Documentaires")

# Adresses considerees comme locales (machine maitre)
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}

# Cache en memoire des resultats d'analyse (evite de rescanner 30K fichiers)
_analysis_cache: dict[str, object] = {}


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


def _get_sandbox_service(container) -> SandboxService:
    """Construit le SandboxService depuis le container."""
    settings = container.config()
    return container.sandbox_service(
        sandbox_dir=settings.resolved_sandbox_dir,
        storage_dir=settings.storage_dir,
        downloads_dir=settings.downloads_dir,
    )


def _format_size(size_bytes: int) -> str:
    """Formate une taille en octets en unité lisible."""
    if size_bytes < 1024:
        return f"{size_bytes} o"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} Ko"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} Mo"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} Go"


@router.get("/maintenance")
async def maintenance_page(request: Request):
    """Page principale de maintenance avec section corbeille et sandbox."""
    from ...infrastructure.persistence.database import get_session
    from ...infrastructure.persistence.models import TrashModel

    container = request.app.state.container
    client_host = request.client.host if request.client else ""
    is_local = client_host in _LOCAL_HOSTS

    # Charger les elements de la corbeille
    session = next(get_session())
    try:
        items_raw = session.exec(
            select(TrashModel).order_by(TrashModel.deleted_at.desc())
        ).all()

        trash_items = []
        episode_counts: dict[int, int] = {}
        for t in items_raw:
            if t.entity_type == "episode":
                meta = t.entity_metadata
                series_trash_id = meta.get("_series_trash_id")
                if series_trash_id:
                    episode_counts[series_trash_id] = (
                        episode_counts.get(series_trash_id, 0) + 1
                    )
                continue
            meta = t.entity_metadata
            trash_items.append(
                {
                    "id": t.id,
                    "entity_type": t.entity_type,
                    "title": meta.get("title", "Sans titre"),
                    "year": meta.get("year"),
                    "deleted_at": t.deleted_at,
                }
            )

        for item in trash_items:
            if item["entity_type"] == "series":
                item["episode_count"] = episode_counts.get(item["id"], 0)
    finally:
        session.close()

    # Charger les fichiers sandbox
    sandbox_svc = _get_sandbox_service(container)
    sandboxed_files = sandbox_svc.list_sandboxed()
    sandbox_total_size = sum(f.size for f in sandboxed_files)
    sandbox_items = [
        {
            "path": str(f.path),
            "name": f.name,
            "size": _format_size(f.size),
            "size_bytes": f.size,
            "modified": f.modified.strftime("%d/%m/%Y"),
            "original_path": _relative_from_root(f.original_path),
        }
        for f in sandboxed_files
    ]

    return templates.TemplateResponse(
        request,
        "maintenance/index.html",
        {
            "is_local": is_local,
            "trash_items": trash_items,
            "trash_count": len(trash_items),
            "sandbox_items": sandbox_items,
            "sandbox_count": len(sandbox_items),
            "sandbox_total_size": _format_size(sandbox_total_size),
        },
    )


# ---------------------------------------------------------------------------
# SSE — Diagnostic d'intégrité
# ---------------------------------------------------------------------------


def _check_ghost_entries(checker):
    """Exécute la vérification des entrées fantômes (sync)."""
    from ...services.integrity import IntegrityReport

    report = IntegrityReport()
    checker._check_ghost_entries(report)
    return report.issues


def _build_symlink_target_index(video_dir: Path):
    """Construit l'index des cibles de symlinks dans video/.

    Scanne recursivement tous les symlinks et resout leurs cibles.

    Returns:
        Tuple (set des chemins cibles resolus, dict cible_str → symlink_path)
    """
    from ...utils.constants import VIDEO_EXTENSIONS

    targets: set[str] = set()
    target_to_symlink: dict[str, Path] = {}

    if not video_dir or not video_dir.exists():
        return targets, target_to_symlink

    for entry in video_dir.rglob("*"):
        if entry.is_symlink():
            try:
                target = entry.resolve()
                if target.suffix.lower() in VIDEO_EXTENSIONS:
                    target_str = str(target)
                    targets.add(target_str)
                    target_to_symlink[target_str] = entry
            except OSError:
                continue  # symlink casse, ignore ici
    return targets, target_to_symlink


def _check_orphan_files(storage_dir: Path, symlink_targets: set[str]):
    """Recherche les fichiers physiques non cibles par un symlink dans video/.

    Approche basee sur les symlinks (plus fiable que la comparaison DB).
    Un fichier est orphelin s'il existe dans storage/ mais n'est la cible
    d'aucun symlink dans video/.
    """
    from ...services.integrity import IntegrityIssue, IssueType
    from ...utils.constants import VIDEO_EXTENSIONS

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
            if str(video_file) not in symlink_targets:
                issues.append(
                    IntegrityIssue(type=IssueType.ORPHAN_FILE, path=video_file)
                )
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
    """SSE endpoint : diagnostic d'integrite avec progression par phase."""
    container = request.app.state.container
    settings = container.config()
    client_host = request.client.host if request.client else ""
    is_local = client_host in _LOCAL_HOSTS

    checker = container.integrity_checker(
        storage_dir=settings.storage_dir,
        video_dir=settings.video_dir,
    )

    phases = [
        ("ghost", "Vérification des entrées fantômes"),
        ("index", "Indexation des symlinks vidéo"),
        ("orphan", "Recherche des fichiers orphelins (storage vs symlinks)"),
        ("symlinks", "Détection des symlinks cassés"),
    ]

    async def event_stream():
        all_issues = []

        # Phase 1 — entrées fantômes
        yield _sse_progress(1, len(phases), phases[0][1])
        issues = await asyncio.to_thread(_check_ghost_entries, checker)
        all_issues.extend(issues)

        # Phase 2 — indexation des symlinks (cibles resolues)
        yield _sse_progress(2, len(phases), phases[1][1])
        symlink_targets, target_to_symlink = await asyncio.to_thread(
            _build_symlink_target_index, settings.video_dir
        )

        # Phase 3 — fichiers orphelins (storage sans symlink pointant dessus)
        yield _sse_progress(3, len(phases), phases[2][1])
        issues = await asyncio.to_thread(
            _check_orphan_files, settings.storage_dir, symlink_targets
        )
        all_issues.extend(issues)

        # Phase 4 — symlinks cassés (scopé Films + Séries)
        yield _sse_progress(4, len(phases), phases[3][1])
        issues = await asyncio.to_thread(_check_broken_symlinks, checker)

        # Filtrer les séquelles : symlinks cassés dont le même film/épisode
        # a déjà un symlink valide ailleurs dans video/.
        # Films : clé = titre+année (insensible langue/codec).
        # Épisodes : clé = titre normalisé + SxxExx (insensible année/codec).
        _EP_RE = re.compile(
            r"^(.+?)\s*(?:\(\d{4}\)\s*)?-\s*(S\d{2}E\d{2})", re.IGNORECASE
        )
        _FILM_RE = re.compile(r"^(.+?)\s*\((\d{4})\)")
        # Format scene : Title.Year. ou Title Year. (points comme séparateurs)
        _SCENE_RE = re.compile(r"^(.+?)[.\s](\d{4})[.\s]")

        def _stale_key(name: str) -> str | None:
            # Épisode d'abord (plus spécifique)
            m = _EP_RE.match(name)
            if m:
                title = re.sub(r"\s+", " ", m.group(1).strip()).lower()
                return f"{title}|{m.group(2).upper()}"
            # Film : Titre (Année)
            m = _FILM_RE.match(name)
            if m:
                return f"{m.group(1).strip().lower()}|{m.group(2)}"
            # Fallback : format scene Titre.Année. ou Titre Année.
            m = _SCENE_RE.match(name)
            if m:
                title = m.group(1).replace(".", " ").strip().lower()
                return f"{title}|{m.group(2)}"
            return None

        # Clés de tous les symlinks valides
        working_keys: set[str] = set()
        for symlink_path in target_to_symlink.values():
            key = _stale_key(Path(symlink_path).name)
            if key:
                working_keys.add(key)

        stale_cleaned = 0
        for issue in issues:
            broken_key = _stale_key(issue.path.name)
            if broken_key and broken_key in working_keys:
                # Séquelle — supprimer le symlink cassé silencieusement
                try:
                    issue.path.unlink()
                    stale_cleaned += 1
                except OSError:
                    all_issues.append(issue)
            else:
                all_issues.append(issue)

        if stale_cleaned:
            logger.info(
                "{} symlink(s) résiduels supprimés (homonyme valide existant)",
                stale_cleaned,
            )

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
                "fichiers dans storage/ non ciblés par un symlink dans video/"
            )
        if broken:
            suggestions.append(
                f"Pour {len(broken)} symlink(s) cassé(s) : "
                "<code>cineorg repair-links</code> pour les réparer"
            )

        # Preparer les donnees template (tous les elements, scroll CSS)
        ghost_entries = [
            {
                "path": _relative_from_root(i.path),
                "full_path": str(i.path),
                "details": i.details,
            }
            for i in ghost
        ]

        # Grouper les orphelins par branche (1er sous-dossier sous Films/Series/...)
        orphan_branches: dict[str, list[dict]] = {}
        for i in orphans:
            parts = Path(i.path).parts
            branch = "Autre"
            for idx, part in enumerate(parts):
                if part in _SCOPED_SUBDIRS and idx + 1 < len(parts):
                    branch = f"{part}/{parts[idx + 1]}"
                    break
            orphan_branches.setdefault(branch, []).append(
                {"path": _relative_from_root(i.path), "full_path": str(i.path)}
            )
        # Trier par nombre decroissant de fichiers
        orphan_branches_sorted = sorted(
            orphan_branches.items(), key=lambda x: len(x[1]), reverse=True
        )

        broken_symlinks = [
            {
                "path": _relative_from_root(i.path),
                "full_path": str(i.path),
                "details": i.details,
            }
            for i in broken
        ]

        # Cacher les resultats bruts pour reutilisation par le fix
        _analysis_cache["check_ghost"] = ghost
        _analysis_cache["check_orphans"] = orphans
        _analysis_cache["check_broken"] = broken
        _analysis_cache["check_symlink_index"] = target_to_symlink

        html = templates.env.get_template("maintenance/_check_results.html").render(
            has_issues=len(all_issues) > 0,
            total_issues=len(all_issues),
            ghost_entries=ghost_entries,
            orphan_branches=orphan_branches_sorted,
            broken_symlinks=broken_symlinks,
            ghost_total=len(ghost),
            orphan_total=len(orphans),
            broken_total=len(broken),
            suggestions=suggestions if all_issues else [],
            is_local=is_local,
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
# SSE — Vérification de complétude des séries (TVDB)
# ---------------------------------------------------------------------------


@router.get("/maintenance/completeness")
async def run_completeness_sse(request: Request):
    """SSE endpoint : vérification de complétude des séries (TVDB)."""
    from datetime import date

    from ...infrastructure.persistence.database import get_session
    from ...infrastructure.persistence.models import SeriesModel
    from ...services.completeness.completeness_checker import (
        CompletenessChecker,
        check_series_model,
    )

    container = request.app.state.container
    tvdb_client = container.tvdb_client()
    checker = CompletenessChecker(tvdb_client)
    today = date.today()

    async def event_stream():
        session = next(get_session())
        try:
            series_list = session.exec(select(SeriesModel)).all()
            total = len(series_list)
            tally = {"complete": 0, "incomplete": 0, "unverifiable": 0}

            yield _sse_progress(0, total, "Initialisation…")

            for i, series in enumerate(series_list):
                yield _sse_progress(i + 1, total, series.title)
                try:
                    verdict = await check_series_model(
                        session, checker, series, today
                    )
                except Exception as e:
                    logger.warning(
                        "Complétude : échec sur '{}' : {}", series.title, e
                    )
                    verdict = "unverifiable"
                tally[verdict] = tally.get(verdict, 0) + 1

            html = (
                '<div class="maint-result-card">'
                "<h3>Vérification terminée</h3>"
                f"<p><strong>{tally['incomplete']}</strong> série(s) incomplète(s), "
                f"<strong>{tally['complete']}</strong> complète(s), "
                f"<strong>{tally['unverifiable']}</strong> non vérifiable(s).</p>"
                '<p><a href="/library/?type=series&incomplete_series=1">'
                "Voir les séries incomplètes</a></p>"
                "</div>"
            )
            yield _sse_complete(html)
        finally:
            session.close()

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
    client_host = request.client.host if request.client else ""
    is_local = client_host in _LOCAL_HOSTS

    phases_info = [
        "Construction de l'index des fichiers",
        "Détection des symlinks cassés",
        "Recherche des symlinks mal placés",
        "Détection des doublons",
        "Détection des doublons cross-genre",
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

        # Phase 5 : doublons cross-genre
        yield _sse_progress(5, len(phases_info), phases_info[4])
        cross_genre_raw = await asyncio.to_thread(
            cleanup_svc._scan_cross_genre_duplicates, video_dir
        )

        # Phase 6 : surdimensionnés
        yield _sse_progress(6, len(phases_info), phases_info[5])
        oversized_raw = await asyncio.to_thread(
            cleanup_svc._scan_oversized_dirs, video_dir, max_per_dir
        )

        # Phase 7 : vides
        yield _sse_progress(7, len(phases_info), phases_info[6])
        empty_raw = await asyncio.to_thread(cleanup_svc._scan_empty_dirs, video_dir)

        # Cacher le rapport pour reutilisation par le fix
        _analysis_cache["cleanup_report"] = {
            "broken": broken_raw,
            "misplaced": misplaced_raw,
            "duplicates": duplicates_raw,
            "cross_genre": cross_genre_raw,
            "oversized": oversized_raw,
            "empty": empty_raw,
            "repair_svc": repair_svc,
            "cleanup_svc": cleanup_svc,
        }

        # Construire les données template
        has_issues = bool(
            broken_raw
            or misplaced_raw
            or duplicates_raw
            or cross_genre_raw
            or oversized_raw
            or empty_raw
        )
        total_issues = (
            len(broken_raw)
            + len(misplaced_raw)
            + len(duplicates_raw)
            + len(cross_genre_raw)
            + len(oversized_raw)
            + len(empty_raw)
        )

        broken = [
            {
                "path": _relative_from_root(b.symlink_path),
                "full_path": str(b.symlink_path),
                "score": f"{b.candidate_score:.0f}" if b.best_candidate else None,
                "candidate": _relative_from_root(b.best_candidate)
                if b.best_candidate
                else None,
            }
            for b in broken_raw
        ]
        misplaced = [
            {
                "path": _relative_from_root(m.symlink_path),
                "title": m.media_title or _truncate_path(m.symlink_path, 1),
                "current": _relative_from_root(m.current_dir),
                "expected": _relative_from_root(m.expected_dir),
            }
            for m in misplaced_raw
        ]
        duplicates = [
            {
                "target": _relative_from_root(d.target_path),
                "keep": _relative_from_root(d.keep),
                "remove": [_relative_from_root(r) for r in d.remove],
                "remove_count": len(d.remove),
            }
            for d in duplicates_raw
        ]
        cross_genre = [
            {
                "keep": _relative_from_root(cg.keep),
                "keep_genre": cg.keep_genre,
                "remove": [
                    {"path": _relative_from_root(r), "genre": g}
                    for r, g in zip(cg.remove, cg.remove_genres)
                ],
                "remove_count": len(cg.remove),
            }
            for cg in cross_genre_raw
        ]
        oversized = [
            {
                "path": _relative_from_root(o.parent_dir),
                "count": o.current_count,
                "max": o.max_allowed,
            }
            for o in oversized_raw
        ]
        empty = [{"path": _relative_from_root(e)} for e in empty_raw]

        html = templates.env.get_template("maintenance/_cleanup_results.html").render(
            has_issues=has_issues,
            total_issues=total_issues,
            broken=broken,
            misplaced=misplaced,
            duplicates=duplicates,
            cross_genre=cross_genre,
            oversized=oversized,
            empty=empty,
            broken_total=len(broken_raw),
            misplaced_total=len(misplaced_raw),
            duplicates_total=len(duplicates_raw),
            cross_genre_total=len(cross_genre_raw),
            oversized_total=len(oversized_raw),
            empty_total=len(empty_raw),
            is_local=is_local,
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
# SSE — Execution des corrections cleanup
# ---------------------------------------------------------------------------


def _run_cleanup_fix(container, settings):
    """Execute les 6 phases correctives du cleanup (sync, pour asyncio.to_thread)."""
    from ...services.cleanup.dataclasses import CleanupReport, CleanupResult

    # Reutiliser le cache d'analyse si disponible
    cached = _analysis_cache.pop("cleanup_report", None)
    if cached:
        cleanup_svc = cached["cleanup_svc"]
        report = CleanupReport(
            video_dir=settings.video_dir,
            broken_symlinks=cached["broken"],
            misplaced_symlinks=cached["misplaced"],
            duplicate_symlinks=cached["duplicates"],
            cross_genre_duplicates=cached.get("cross_genre", []),
            oversized_dirs=cached["oversized"],
            empty_dirs=cached["empty"],
        )
    else:
        repair_svc = container.repair_service(
            storage_dir=settings.storage_dir,
            video_dir=settings.video_dir,
            trash_dir=settings.storage_dir / ".trash",
        )
        repair_svc.build_file_index()
        cleanup_svc = container.cleanup_service(repair_service=repair_svc)
        video_dir = settings.video_dir
        max_per_dir = settings.max_files_per_subdir
        report = cleanup_svc.analyze(video_dir, max_per_dir=max_per_dir)

    results = {}
    total_result = CleanupResult()

    # Phase 1 : Reparer symlinks casses (score >= 90%)
    if report.broken_symlinks:
        repairable = [
            b
            for b in report.broken_symlinks
            if b.best_candidate and b.candidate_score >= 90.0
        ]
        unrepairable = [
            b
            for b in report.broken_symlinks
            if b.best_candidate is None or b.candidate_score < 90.0
        ]

        if repairable:
            r = cleanup_svc.repair_broken_symlinks(repairable, min_score=90.0)
            total_result.repaired_symlinks += r.repaired_symlinks
            total_result.failed_repairs += r.failed_repairs
            total_result.errors.extend(r.errors)
            results["repaired"] = [
                {
                    "path": _relative_from_root(b.symlink_path),
                    "target": _relative_from_root(b.best_candidate),
                }
                for b in repairable
                if b.best_candidate
            ]

        # Phase 2 : Supprimer symlinks irreparables
        if unrepairable:
            r = cleanup_svc.delete_broken_symlinks(unrepairable)
            total_result.broken_symlinks_deleted += r.broken_symlinks_deleted
            total_result.errors.extend(r.errors)
            results["deleted_broken"] = [
                {"path": _relative_from_root(b.symlink_path)} for b in unrepairable
            ]

    # Phase 3 : Deplacer symlinks mal places
    if report.misplaced_symlinks:
        r = cleanup_svc.fix_misplaced_symlinks(report.misplaced_symlinks)
        total_result.moved_symlinks += r.moved_symlinks
        total_result.errors.extend(r.errors)
        results["moved"] = [
            {
                "path": _relative_from_root(m.symlink_path),
                "from": _relative_from_root(m.current_dir),
                "to": _relative_from_root(m.expected_dir),
            }
            for m in report.misplaced_symlinks
        ]

    # Phase 4 : Supprimer doublons
    if report.duplicate_symlinks:
        r = cleanup_svc.fix_duplicate_symlinks(report.duplicate_symlinks)
        total_result.duplicate_symlinks_removed += r.duplicate_symlinks_removed
        total_result.errors.extend(r.errors)
        dup_details = []
        for d in report.duplicate_symlinks:
            for link in d.remove:
                dup_details.append(
                    {
                        "path": _relative_from_root(link),
                        "kept": _relative_from_root(d.keep),
                    }
                )
        results["duplicates_removed"] = dup_details

    # Phase 5 : Supprimer doublons cross-genre
    if report.cross_genre_duplicates:
        r = cleanup_svc.fix_cross_genre_duplicates(report.cross_genre_duplicates)
        total_result.cross_genre_removed += r.cross_genre_removed
        total_result.errors.extend(r.errors)
        cg_details = []
        for cg in report.cross_genre_duplicates:
            for link, genre in zip(cg.remove, cg.remove_genres):
                cg_details.append(
                    {
                        "path": _relative_from_root(link),
                        "genre": genre,
                        "kept": _relative_from_root(cg.keep),
                        "kept_genre": cg.keep_genre,
                    }
                )
        results["cross_genre_removed"] = cg_details

    # Phase 6 : Subdiviser repertoires surdimensionnes
    if report.oversized_dirs:
        r = cleanup_svc.subdivide_oversized_dirs(report.oversized_dirs)
        total_result.subdivisions_created += r.subdivisions_created
        total_result.symlinks_redistributed += r.symlinks_redistributed
        total_result.errors.extend(r.errors)
        results["subdivided"] = [
            {
                "path": _relative_from_root(p.parent_dir),
                "count": p.current_count,
            }
            for p in report.oversized_dirs
        ]

    # Phase 7 : Nettoyer repertoires vides
    if report.empty_dirs:
        r = cleanup_svc.clean_empty_dirs(report.empty_dirs)
        total_result.empty_dirs_removed += r.empty_dirs_removed
        total_result.errors.extend(r.errors)
        results["empty_removed"] = [
            {"path": _relative_from_root(d)} for d in report.empty_dirs
        ]

    return total_result, results


@router.get("/maintenance/cleanup/fix")
async def run_cleanup_fix_sse(request: Request):
    """SSE endpoint : execute les corrections cleanup avec progression."""
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return HTMLResponse(
            "<p>Corrections autorisees uniquement depuis la machine maitre.</p>",
            status_code=403,
        )

    container = request.app.state.container
    settings = container.config()

    fix_phases = [
        "Analyse et reparation des symlinks casses",
        "Suppression des symlinks irreparables",
        "Deplacement des symlinks mal places",
        "Suppression des doublons",
        "Subdivision des repertoires surdimensionnes",
        "Nettoyage des repertoires vides",
    ]

    async def event_stream():
        for i, label in enumerate(fix_phases, 1):
            yield _sse_progress(i, len(fix_phases), label)
            if i == 1:
                total_result, details = await asyncio.to_thread(
                    _run_cleanup_fix, container, settings
                )
            else:
                await asyncio.sleep(0.05)

        html = templates.env.get_template(
            "maintenance/_cleanup_fix_results.html"
        ).render(
            result=total_result,
            details=details,
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
# Corbeille — Restauration et vidage depuis la page maintenance
# ---------------------------------------------------------------------------


@router.post("/maintenance/trash/{trash_id}/restore", response_class=HTMLResponse)
async def maintenance_restore_trash(request: Request, trash_id: int):
    """Restaure un element depuis la corbeille (redirige vers maintenance)."""
    from ...infrastructure.persistence.database import get_session
    from ...infrastructure.persistence.models import (
        EpisodeModel,
        MovieModel,
        SeriesModel,
        TrashModel,
    )
    from ...web.routes.library.trash import _apply_metadata

    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return HTMLResponse(
            '<div class="action-msg action-error">Restauration autorisee uniquement depuis la machine maitre.</div>',
            status_code=403,
        )

    session = next(get_session())
    try:
        trash = session.get(TrashModel, trash_id)
        if not trash:
            return HTMLResponse(
                '<div class="action-msg action-error">Element introuvable.</div>',
                status_code=404,
            )

        meta = trash.entity_metadata

        if trash.entity_type == "movie":
            movie = MovieModel()
            _apply_metadata(movie, meta, exclude={"id"})
            session.add(movie)

        elif trash.entity_type == "series":
            series = SeriesModel()
            _apply_metadata(series, meta, exclude={"id"})
            session.add(series)
            session.flush()
            new_series_id = series.id

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

    # Retourner le HTML vide (htmx swap outerHTML la supprime)
    return HTMLResponse("")


@router.post("/maintenance/trash/empty", response_class=HTMLResponse)
async def maintenance_empty_trash(request: Request):
    """Vide definitivement la corbeille depuis la page maintenance."""
    from ...infrastructure.persistence.database import get_session
    from ...infrastructure.persistence.models import TrashModel

    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return HTMLResponse(
            '<div class="action-msg action-error">Vidage autorise uniquement depuis la machine maitre.</div>',
            status_code=403,
        )

    container = request.app.state.container
    file_system = container.file_system()

    session = next(get_session())
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
        '<div class="maint-trash-empty-state">'
        "Corbeille vidée — "
        f"{deleted_files} fichier(s) supprimé(s) définitivement."
        "</div>"
    )
    response.headers["HX-Trigger"] = "trashEmptied"
    return response


# ---------------------------------------------------------------------------
# SSE — Reparation des symlinks casses (integrite)
# ---------------------------------------------------------------------------


def _run_check_fix_symlinks(container, settings):
    """Repare les symlinks casses detectes par l'integrite (sync).

    Utilise le cache d'analyse si disponible pour eviter de rescanner
    les 30K+ fichiers. Seul le build_file_index est necessaire pour
    le matching de candidats.
    """
    from ...services.cleanup.dataclasses import CleanupResult

    repair_svc = container.repair_service(
        storage_dir=settings.storage_dir,
        video_dir=settings.video_dir,
        trash_dir=settings.storage_dir / ".trash",
    )
    repair_svc.build_file_index()

    # Reutiliser le cache d'analyse si disponible (evite find_broken_symlinks)
    cached_broken = _analysis_cache.pop("check_broken", None)
    if cached_broken:
        # Le cache contient des IntegrityIssue, extraire les paths
        scoped_broken = [issue.path for issue in cached_broken]
    else:
        all_broken = repair_svc.find_broken_symlinks()
        scoped_broken = [
            link
            for link in all_broken
            if any(
                f"/{sd}/" in str(link) or str(link).endswith(f"/{sd}")
                for sd in _SCOPED_SUBDIRS
            )
        ]

    result = CleanupResult()
    repaired_details = []
    skipped = 0

    for link in scoped_broken:
        candidates = repair_svc.find_possible_targets(link)
        if not candidates or candidates[0][1] < 90.0:
            skipped += 1
            continue
        best_target, best_score = candidates[0]
        try:
            success = repair_svc.repair_symlink(link, best_target)
            if success:
                result.repaired_symlinks += 1
                repaired_details.append(
                    {
                        "path": _relative_from_root(link),
                        "target": _relative_from_root(best_target),
                        "score": f"{best_score:.0f}",
                    }
                )
            else:
                result.failed_repairs += 1
        except Exception as e:
            result.failed_repairs += 1
            result.errors.append(f"Reparation echouee {link}: {e}")

    return result, repaired_details, skipped


@router.get("/maintenance/check/fix-symlinks")
async def run_check_fix_symlinks_sse(request: Request):
    """SSE endpoint : repare les symlinks casses detectes par l'integrite."""
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return HTMLResponse(
            "<p>Corrections autorisees uniquement depuis la machine maitre.</p>",
            status_code=403,
        )

    container = request.app.state.container
    settings = container.config()

    async def event_stream():
        yield _sse_progress(1, 2, "Indexation et detection des symlinks casses")
        result, details, skipped = await asyncio.to_thread(
            _run_check_fix_symlinks, container, settings
        )
        yield _sse_progress(2, 2, "Reparation terminee")

        html = templates.env.get_template("maintenance/_check_fix_results.html").render(
            result=result,
            details=details,
            skipped=skipped,
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
# POST — Purge des entrees fantomes (integrite)
# ---------------------------------------------------------------------------


def _run_purge_ghosts(container):
    """Supprime les entrees fantomes de la DB (sync).

    Les fantomes sont des VideoFileModel dont le path pointe vers un fichier
    inexistant. Le champ details de l'IntegrityIssue contient 'ID BDD: {id}'.
    """
    from sqlmodel import Session

    from ...infrastructure.persistence.database import get_engine
    from ...infrastructure.persistence.models import VideoFileModel

    cached = _analysis_cache.get("check_ghost", [])
    if not cached:
        return 0, []

    session = Session(get_engine())
    purged = []
    try:
        for issue in cached:
            # Extraire l'ID depuis details "ID BDD: 123"
            model = None
            if issue.details and issue.details.startswith("ID BDD: "):
                try:
                    db_id = int(issue.details.split(": ", 1)[1])
                    model = session.get(VideoFileModel, db_id)
                except (ValueError, IndexError):
                    pass

            # Fallback : chercher par path
            if model is None:
                from sqlmodel import select

                path_str = str(issue.path)
                stmt = select(VideoFileModel).where(VideoFileModel.path == path_str)
                model = session.exec(stmt).first()

            if model:
                session.delete(model)
                purged.append(_relative_from_root(issue.path))
        session.commit()
    finally:
        session.close()

    _analysis_cache.pop("check_ghost", None)
    return len(purged), purged


@router.get("/maintenance/check/purge-ghosts")
async def purge_ghosts_sse(request: Request):
    """SSE endpoint : supprime les entrees fantomes de la DB."""
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return HTMLResponse(
            "<p>Corrections autorisees uniquement depuis la machine maitre.</p>",
            status_code=403,
        )

    container = request.app.state.container

    async def event_stream():
        yield _sse_progress(1, 1, "Suppression des entrees fantomes")
        count, details = await asyncio.to_thread(_run_purge_ghosts, container)

        html = templates.env.get_template("maintenance/_purge_results.html").render(
            action="entrees fantomes supprimees de la base",
            count=count,
            details=details,
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
# POST — Purge des fichiers orphelins de la DB (integrite)
# ---------------------------------------------------------------------------


def _run_purge_orphans():
    """Supprime les references DB aux fichiers orphelins (sync).

    Les fichiers orphelins sont des fichiers physiques non references dans
    MovieModel/EpisodeModel. On ne supprime pas les fichiers physiques,
    seulement les VideoFileModel correspondants s'ils existent.
    Note : la plupart des orphelins n'ont PAS de VideoFileModel (c'est
    justement le probleme). Ici on nettoie le cache d'analyse.
    """
    cached = _analysis_cache.pop("check_orphans", None)
    if not cached:
        return 0, []

    # Les fichiers orphelins sont deja hors de la DB (pas dans MovieModel/EpisodeModel).
    # Rien a supprimer en DB. On retourne juste le nombre pour info.
    return len(cached), []


# ---------------------------------------------------------------------------
# Reconciliation DB — enrichir MovieModel/EpisodeModel avec symlink_path
# ---------------------------------------------------------------------------


def _ensure_symlink_path_columns():
    """Ajoute la colonne symlink_path aux tables movies et episodes si absente."""
    from sqlalchemy import text

    from ...infrastructure.persistence.database import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        for table in ("movies", "episodes"):
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN symlink_path TEXT"))
                conn.commit()
            except Exception:
                conn.rollback()  # colonne deja existante


def _run_reconcile_db(dry_run: bool = True):
    """Reconcilie la DB avec l'index des symlinks (sync).

    Pour chaque symlink dans video/, resout la cible et associe le chemin
    du symlink au MovieModel ou EpisodeModel correspondant via file_path.

    Args:
        dry_run: Si True, retourne seulement le plan sans modifier la DB.

    Returns:
        Tuple (movies_count, episodes_count, details_list)
    """
    from sqlmodel import Session, select

    from ...infrastructure.persistence.database import get_engine
    from ...infrastructure.persistence.models import EpisodeModel, MovieModel

    cached_index = _analysis_cache.get("check_symlink_index")
    if not cached_index:
        return (
            0,
            0,
            [],
            "Lancez d'abord l'analyse d'integrite pour indexer les symlinks.",
        )

    if not dry_run:
        _ensure_symlink_path_columns()

    session = Session(get_engine())
    movies_updated = 0
    episodes_updated = 0
    details = []

    try:
        # Charger tous les file_path → model_id pour movies et episodes
        movie_paths: dict[str, int] = {}
        for row in session.exec(
            select(MovieModel.id, MovieModel.file_path).where(
                MovieModel.file_path.is_not(None)  # type: ignore[union-attr]
            )
        ):
            movie_paths[row.file_path] = row.id

        episode_paths: dict[str, int] = {}
        for row in session.exec(
            select(EpisodeModel.id, EpisodeModel.file_path).where(
                EpisodeModel.file_path.is_not(None)  # type: ignore[union-attr]
            )
        ):
            episode_paths[row.file_path] = row.id

        for target_str, symlink_path in cached_index.items():
            symlink_str = str(symlink_path)

            if target_str in movie_paths:
                if dry_run:
                    details.append(
                        {
                            "type": "film",
                            "file": _relative_from_root(target_str),
                            "symlink": _relative_from_root(symlink_path),
                        }
                    )
                    movies_updated += 1
                else:
                    model = session.get(MovieModel, movie_paths[target_str])
                    if model and model.symlink_path != symlink_str:
                        model.symlink_path = symlink_str
                        session.add(model)
                        movies_updated += 1
                        details.append(
                            {
                                "type": "film",
                                "file": _relative_from_root(target_str),
                                "symlink": _relative_from_root(symlink_path),
                            }
                        )

            elif target_str in episode_paths:
                if dry_run:
                    details.append(
                        {
                            "type": "episode",
                            "file": _relative_from_root(target_str),
                            "symlink": _relative_from_root(symlink_path),
                        }
                    )
                    episodes_updated += 1
                else:
                    model = session.get(EpisodeModel, episode_paths[target_str])
                    if model and model.symlink_path != symlink_str:
                        model.symlink_path = symlink_str
                        session.add(model)
                        episodes_updated += 1
                        details.append(
                            {
                                "type": "episode",
                                "file": _relative_from_root(target_str),
                                "symlink": _relative_from_root(symlink_path),
                            }
                        )

        if not dry_run:
            session.commit()
    finally:
        session.close()

    return movies_updated, episodes_updated, details, None


@router.get("/maintenance/check/reconcile-db")
async def reconcile_db_sse(request: Request):
    """SSE endpoint : dry-run de la reconciliation DB (symlink_path)."""
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return HTMLResponse(
            "<p>Corrections autorisees uniquement depuis la machine maitre.</p>",
            status_code=403,
        )

    async def event_stream():
        yield _sse_progress(1, 1, "Reconciliation DB — analyse (dry-run)")
        movies, episodes, details, error = await asyncio.to_thread(
            _run_reconcile_db, True
        )

        html = templates.env.get_template("maintenance/_reconcile_results.html").render(
            dry_run=True,
            movies_count=movies,
            episodes_count=episodes,
            details=details,
            error=error,
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


@router.get("/maintenance/check/reconcile-db-apply")
async def reconcile_db_apply_sse(request: Request):
    """SSE endpoint : applique la reconciliation DB (symlink_path)."""
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return HTMLResponse(
            "<p>Corrections autorisees uniquement depuis la machine maitre.</p>",
            status_code=403,
        )

    async def event_stream():
        yield _sse_progress(1, 1, "Reconciliation DB — ecriture des symlink_path")
        movies, episodes, details, error = await asyncio.to_thread(
            _run_reconcile_db, False
        )

        html = templates.env.get_template("maintenance/_reconcile_results.html").render(
            dry_run=False,
            movies_count=movies,
            episodes_count=episodes,
            details=details,
            error=error,
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
# Sandbox — Isolation, suppression et réinjection des fichiers orphelins
# ---------------------------------------------------------------------------


@router.get("/maintenance/sandbox/move-orphans")
async def sandbox_move_orphans_sse(request: Request):
    """SSE endpoint : déplace les fichiers orphelins vers le sandbox avec progression."""
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return HTMLResponse(
            "<p>Action autorisee uniquement depuis la machine maitre.</p>",
            status_code=403,
        )

    container = request.app.state.container

    # Récupérer les orphelins depuis le cache d'analyse
    cached_orphans = _analysis_cache.get("check_orphans", [])
    if not cached_orphans:
        # Pas d'orphelins : envoyer un complete immédiat
        async def empty_stream():
            html = "<div class=\"sandbox-msg sandbox-msg-warn\">Aucun orphelin en cache. Lancez d'abord l'analyse d'intégrité.</div>"
            yield _sse_complete(html)

        return StreamingResponse(
            empty_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    orphan_paths = [issue.path for issue in cached_orphans]
    total = len(orphan_paths)
    sandbox_svc = _get_sandbox_service(container)

    # Déplacer par lots pour émettre la progression SSE
    BATCH_SIZE = 10

    async def event_stream():
        moved_count = 0
        yield _sse_progress(0, total, "Démarrage...")

        for i in range(0, total, BATCH_SIZE):
            batch = orphan_paths[i : i + BATCH_SIZE]
            moved = await asyncio.to_thread(sandbox_svc.sandbox_orphans, batch)
            moved_count += moved
            yield _sse_progress(
                min(i + BATCH_SIZE, total),
                total,
                f"{moved_count} fichier(s) déplacé(s)",
            )

        # Invalider le cache orphelins
        _analysis_cache.pop("check_orphans", None)

        # Construire le HTML final
        sandboxed = sandbox_svc.list_sandboxed()
        total_size = sum(f.size for f in sandboxed)
        sandbox_items = [
            {
                "path": str(f.path),
                "name": f.name,
                "size": _format_size(f.size),
                "size_bytes": f.size,
                "modified": f.modified.strftime("%d/%m/%Y"),
                "original_path": _relative_from_root(f.original_path),
            }
            for f in sandboxed
        ]

        html = templates.env.get_template("maintenance/_sandbox_section.html").render(
            sandbox_items=sandbox_items,
            sandbox_count=len(sandbox_items),
            sandbox_total_size=_format_size(total_size),
            is_local=True,
            flash_message=f"{moved_count} fichier(s) déplacé(s) vers le sandbox.",
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


@router.post("/maintenance/sandbox/delete", response_class=HTMLResponse)
async def sandbox_delete(request: Request):
    """Supprime définitivement les fichiers sélectionnés du sandbox."""
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return HTMLResponse(
            '<div class="action-msg action-error">Action autorisee uniquement depuis la machine maitre.</div>',
            status_code=403,
        )

    container = request.app.state.container
    form = await request.form()
    selected = form.getlist("selected")
    if not selected:
        return HTMLResponse(
            '<div class="sandbox-msg sandbox-msg-warn">Aucun fichier selectionne.</div>'
        )

    paths = [Path(p) for p in selected]
    sandbox_svc = _get_sandbox_service(container)
    deleted = await asyncio.to_thread(sandbox_svc.delete_files, paths)

    # Retourner la section mise à jour
    sandboxed = sandbox_svc.list_sandboxed()
    total_size = sum(f.size for f in sandboxed)
    sandbox_items = [
        {
            "path": str(f.path),
            "name": f.name,
            "size": _format_size(f.size),
            "size_bytes": f.size,
            "modified": f.modified.strftime("%d/%m/%Y"),
            "original_path": _relative_from_root(f.original_path),
        }
        for f in sandboxed
    ]

    html = templates.env.get_template("maintenance/_sandbox_section.html").render(
        sandbox_items=sandbox_items,
        sandbox_count=len(sandbox_items),
        sandbox_total_size=_format_size(total_size),
        is_local=True,
        flash_message=f"{deleted} fichier(s) supprimé(s) définitivement.",
    )
    return HTMLResponse(html)


@router.post("/maintenance/sandbox/reinject", response_class=HTMLResponse)
async def sandbox_reinject(request: Request):
    """Réinjecte les fichiers sélectionnés dans le répertoire downloads."""
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return HTMLResponse(
            '<div class="action-msg action-error">Action autorisee uniquement depuis la machine maitre.</div>',
            status_code=403,
        )

    container = request.app.state.container
    form = await request.form()
    selected = form.getlist("selected")
    if not selected:
        return HTMLResponse(
            '<div class="sandbox-msg sandbox-msg-warn">Aucun fichier selectionne.</div>'
        )

    paths = [Path(p) for p in selected]
    sandbox_svc = _get_sandbox_service(container)
    reinjected = await asyncio.to_thread(sandbox_svc.reinject_files, paths)

    # Retourner la section mise à jour
    sandboxed = sandbox_svc.list_sandboxed()
    total_size = sum(f.size for f in sandboxed)
    sandbox_items = [
        {
            "path": str(f.path),
            "name": f.name,
            "size": _format_size(f.size),
            "size_bytes": f.size,
            "modified": f.modified.strftime("%d/%m/%Y"),
            "original_path": _relative_from_root(f.original_path),
        }
        for f in sandboxed
    ]

    html = templates.env.get_template("maintenance/_sandbox_section.html").render(
        sandbox_items=sandbox_items,
        sandbox_count=len(sandbox_items),
        sandbox_total_size=_format_size(total_size),
        is_local=True,
        flash_message=f"{reinjected} fichier(s) réinjecté(s) dans les téléchargements.",
    )
    return HTMLResponse(html)
