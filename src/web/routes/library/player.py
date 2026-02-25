"""
Routes de lecture vidéo intégrée — lancement mpv et suivi de statut.
"""

import subprocess
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from ....infrastructure.persistence.database import get_session
from ....infrastructure.persistence.models import EpisodeModel, MovieModel
from .helpers import _find_movie_file

router = APIRouter()


def _resolve_video_path(file_path: str | None) -> Path | None:
    """Resout un chemin video (symlink ou direct) vers le fichier physique."""
    if not file_path:
        return None
    path = Path(file_path)
    if path.is_symlink():
        path = path.resolve()
    return path if path.exists() else None


# Stockage des processus mpv en cours pour suivi
_active_players: dict[int, subprocess.Popen] = {}


def _launch_player(file_path: Path) -> int:
    """Lance mpv en arriere-plan et retourne le PID."""
    proc = subprocess.Popen(
        ["mpv", str(file_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _active_players[proc.pid] = proc
    return proc.pid


def _play_button_html(entity_type: str, entity_id: int) -> str:
    """Genere le bouton Visionner pour un film ou episode."""
    if entity_type == "episodes":
        return (
            f'<button class="lib-episode-play-btn"'
            f' hx-post="/library/episodes/{entity_id}/play"'
            f' hx-swap="outerHTML"'
            f' title="Ouvrir dans mpv">'
            f'<svg width="14" height="14" viewBox="0 0 24 24" fill="none"'
            f' stroke="currentColor" stroke-width="2">'
            f'<polygon points="5 3 19 12 5 21 5 3"/></svg></button>'
        )
    return (
        f'<button class="play-btn"'
        f' hx-post="/library/{entity_type}/{entity_id}/play"'
        f' hx-swap="outerHTML"'
        f' title="Ouvrir dans mpv">'
        f'<svg width="12" height="12" viewBox="0 0 24 24" fill="none"'
        f' stroke="currentColor" stroke-width="2">'
        f'<polygon points="5 3 19 12 5 21 5 3"/></svg>'
        f" Visionner</button>"
    )


def _playing_html(pid: int, entity_type: str, entity_id: int) -> str:
    """Fragment HTML avec polling status pendant la lecture mpv."""
    return (
        f'<span class="play-launched"'
        f' hx-get="/library/play-status/{pid}?entity_type={entity_type}'
        f'&entity_id={entity_id}"'
        f' hx-trigger="load delay:2s"'
        f' hx-swap="outerHTML">'
        f"Lecture en cours…</span>"
    )


@router.get("/play-status/{pid}")
async def play_status(
    request: Request, pid: int, entity_type: str = "", entity_id: int = 0
):
    """Verifie si mpv tourne encore ; sinon retourne le bouton Visionner."""
    proc = _active_players.get(pid)
    if proc and proc.poll() is None:
        # Processus encore vivant — continuer le polling
        return HTMLResponse(_playing_html(pid, entity_type, entity_id))

    # mpv termine — nettoyer et restaurer le bouton
    _active_players.pop(pid, None)
    return HTMLResponse(_play_button_html(entity_type, entity_id))


@router.post("/movies/{movie_id}/play")
async def movie_play(request: Request, movie_id: int):
    """Lance mpv pour visionner un film."""
    session = next(get_session())
    try:
        movie = session.get(MovieModel, movie_id)
        if not movie:
            return Response(status_code=404)
        file_path = movie.file_path
        title = movie.title
        year = movie.year
    finally:
        session.close()

    resolved = _resolve_video_path(file_path)
    if not resolved:
        file_info = _find_movie_file(title, year)
        if file_info:
            resolved = _resolve_video_path(
                file_info.get("storage_path") or file_info.get("symlink_path")
            )

    if not resolved:
        return HTMLResponse(
            "<p class='reassociate-empty'>Fichier vidéo introuvable</p>",
            status_code=404,
        )

    pid = _launch_player(resolved)
    return HTMLResponse(_playing_html(pid, "movies", movie_id))


@router.post("/episodes/{episode_id}/play")
async def episode_play(request: Request, episode_id: int):
    """Lance mpv pour visionner un episode."""
    session = next(get_session())
    try:
        episode = session.get(EpisodeModel, episode_id)
        if not episode:
            return Response(status_code=404)
        file_path = episode.file_path
    finally:
        session.close()

    resolved = _resolve_video_path(file_path)
    if not resolved:
        return HTMLResponse(
            "<p class='reassociate-empty'>Fichier vidéo introuvable</p>",
            status_code=404,
        )

    pid = _launch_player(resolved)
    return HTMLResponse(_playing_html(pid, "episodes", episode_id))
