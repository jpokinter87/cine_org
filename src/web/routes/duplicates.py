"""Routes web pour la detection des doublons."""

import json
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlmodel import select

from src.infrastructure.persistence.models import MovieModel, TrashModel, VideoFileModel
from src.adapters.cli.commands.duplicates_command import (
    _build_media_info,
    _format_languages,
    _format_resolution,
    _format_size,
    _load_whitelist,
    _save_whitelist,
    _WHITELIST_PATH,
)
from src.infrastructure.persistence.database import get_session
from src.services.quality_scorer import calculate_quality_score

from ..deps import templates

router = APIRouter(prefix="/duplicates", tags=["duplicates"])


def _fetch_duplicate_groups() -> tuple[list[dict], list[dict], dict]:
    """Detecte les doublons et separe en groupes normaux vs whitelistes."""
    session = next(get_session())
    try:
        rows = session.execute(
            text("""
                SELECT tmdb_id, COUNT(*) as cnt, GROUP_CONCAT(id) as ids
                FROM movies
                WHERE tmdb_id IS NOT NULL AND file_path IS NOT NULL
                GROUP BY tmdb_id
                HAVING COUNT(*) > 1
                ORDER BY cnt DESC
            """)
        ).fetchall()

        whitelist_data = _load_whitelist(_WHITELIST_PATH)
        whitelisted_ids = set(whitelist_data.get("whitelist", []))

        duplicate_groups = []
        whitelisted_groups = []
        total_recoverable = 0

        for row in rows:
            tmdb_id = row[0]
            count = row[1]
            movie_ids = [int(mid) for mid in row[2].split(",")]

            movies_data = []
            for mid in movie_ids:
                movie_row = session.execute(
                    text("""
                        SELECT id, title, year, file_path, resolution, codec_video,
                               codec_audio, languages_json, file_size_bytes,
                               duration_seconds, poster_path
                        FROM movies WHERE id = :mid
                    """),
                    {"mid": mid},
                ).fetchone()

                if not movie_row:
                    continue

                mi = _build_media_info(movie_row[4], movie_row[5], movie_row[6])
                score = calculate_quality_score(mi, movie_row[8] or 0, movie_row[9])

                movies_data.append(
                    {
                        "id": movie_row[0],
                        "title": movie_row[1],
                        "year": movie_row[2],
                        "file_path": movie_row[3],
                        "file_name": movie_row[3].split("/")[-1]
                        if movie_row[3]
                        else "?",
                        "resolution": _format_resolution(movie_row[4]),
                        "codec_video": movie_row[5] or "?",
                        "codec_audio": movie_row[6] or "?",
                        "languages": _format_languages(movie_row[7]),
                        "size": _format_size(movie_row[8]),
                        "size_bytes": movie_row[8] or 0,
                        "score": score.total,
                        "score_detail": score.breakdown,
                        "poster_path": movie_row[10],
                    }
                )

            if not movies_data:
                continue

            movies_sorted = sorted(movies_data, key=lambda m: m["score"], reverse=True)
            best_score = movies_sorted[0]["score"]
            # Marquer "best" uniquement s'il y a un vrai gagnant (pas d'égalité)
            scores_equal = all(m["score"] == best_score for m in movies_sorted)
            for m in movies_sorted:
                m["is_best"] = (
                    not scores_equal and m["score"] == best_score and best_score > 0
                )

            # Détecter si toutes les copies pointent sur le même fichier physique
            unique_paths = set(m["file_path"] for m in movies_sorted if m["file_path"])
            same_file = len(unique_paths) == 1

            group = {
                "tmdb_id": tmdb_id,
                "count": count,
                "title": movies_sorted[0]["title"],
                "year": movies_sorted[0]["year"],
                "poster_path": movies_sorted[0]["poster_path"],
                "movies": movies_sorted,
                "same_file": same_file,
            }

            if tmdb_id in whitelisted_ids:
                group["note"] = whitelist_data.get("notes", {}).get(str(tmdb_id), "")
                whitelisted_groups.append(group)
            else:
                duplicate_groups.append(group)
                for m in movies_sorted[1:]:
                    total_recoverable += m["size_bytes"]

        stats = {
            "total_groups": len(duplicate_groups),
            "total_files": sum(g["count"] for g in duplicate_groups),
            "total_recoverable": _format_size(total_recoverable)
            if total_recoverable > 0
            else None,
            "total_whitelisted": len(whitelisted_groups),
        }

        return duplicate_groups, whitelisted_groups, stats
    finally:
        session.close()


@router.get("/", response_class=HTMLResponse)
async def duplicates_page(request: Request):
    """Page principale des doublons."""
    duplicate_groups, whitelisted_groups, stats = _fetch_duplicate_groups()
    return templates.TemplateResponse(
        request,
        "duplicates/index.html",
        {
            "duplicate_groups": duplicate_groups,
            "whitelisted_groups": whitelisted_groups,
            "stats": stats,
        },
    )


@router.post("/whitelist-add", response_class=HTMLResponse)
async def whitelist_add(request: Request, tmdb_id: int = Form(...)):
    """Ajoute un tmdb_id a la whitelist."""
    wl = _load_whitelist(_WHITELIST_PATH)
    if tmdb_id not in wl["whitelist"]:
        wl["whitelist"].append(tmdb_id)
        _save_whitelist(_WHITELIST_PATH, wl)

    duplicate_groups, whitelisted_groups, stats = _fetch_duplicate_groups()
    return templates.TemplateResponse(
        request,
        "duplicates/_results.html",
        {
            "duplicate_groups": duplicate_groups,
            "whitelisted_groups": whitelisted_groups,
            "stats": stats,
        },
    )


@router.post("/whitelist-remove", response_class=HTMLResponse)
async def whitelist_remove(request: Request, tmdb_id: int = Form(...)):
    """Retire un tmdb_id de la whitelist."""
    wl = _load_whitelist(_WHITELIST_PATH)
    if tmdb_id in wl["whitelist"]:
        wl["whitelist"].remove(tmdb_id)
        wl["notes"].pop(str(tmdb_id), None)
        _save_whitelist(_WHITELIST_PATH, wl)

    duplicate_groups, whitelisted_groups, stats = _fetch_duplicate_groups()
    return templates.TemplateResponse(
        request,
        "duplicates/_results.html",
        {
            "duplicate_groups": duplicate_groups,
            "whitelisted_groups": whitelisted_groups,
            "stats": stats,
        },
    )


_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _serialize_model(model) -> str:
    """Serialise un SQLModel en JSON pour restauration depuis la corbeille."""
    data = {}
    for col in model.__class__.__table__.columns:
        val = getattr(model, col.name)
        if val is not None and hasattr(val, "isoformat"):
            val = val.isoformat()
        data[col.name] = val
    return json.dumps(data, ensure_ascii=False)


@router.post("/delete", response_class=HTMLResponse)
async def delete_duplicate(request: Request, movie_id: int = Form(...)):
    """Supprime un doublon (vers la corbeille) et rafraichit la page."""
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return HTMLResponse(
            "<p>Suppression autorisée uniquement depuis la machine maître.</p>",
            status_code=403,
        )

    container = request.app.state.container
    file_system = container.file_system()
    session = next(get_session())
    try:
        movie = session.get(MovieModel, movie_id)
        if movie:
            metadata = _serialize_model(movie)

            # Vérifier si d'autres MovieModel partagent le même file_path
            # (doublon DB vs fichiers physiques distincts)
            other_with_same_path = 0
            if movie.file_path:
                other_with_same_path = (
                    session.execute(
                        text(
                            "SELECT COUNT(*) FROM movies "
                            "WHERE file_path = :fp AND id != :mid"
                        ),
                        {"fp": movie.file_path, "mid": movie.id},
                    ).scalar()
                    or 0
                )

            if other_with_same_path == 0 and movie.file_path:
                # Fichiers distincts : supprimer symlink + VideoFileModel
                vf = session.exec(
                    select(VideoFileModel).where(VideoFileModel.path == movie.file_path)
                ).first()
                if vf:
                    if vf.symlink_path:
                        file_system.remove_symlink(Path(vf.symlink_path))
                    session.delete(vf)
            # Sinon doublon DB : ne pas toucher au symlink/VideoFile
            # car l'autre MovieModel en a encore besoin

            # Corbeille
            trash = TrashModel(
                entity_type="movie",
                original_id=movie.id,
                metadata_json=metadata,
                deletion_reason="duplicate_cleanup",
            )
            session.add(trash)
            session.delete(movie)
            session.commit()
    finally:
        session.close()

    duplicate_groups, whitelisted_groups, stats = _fetch_duplicate_groups()
    return templates.TemplateResponse(
        request,
        "duplicates/_results.html",
        {
            "duplicate_groups": duplicate_groups,
            "whitelisted_groups": whitelisted_groups,
            "stats": stats,
        },
    )
