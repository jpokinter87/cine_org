"""
Routes de lecture vidéo intégrée — lancement local ou distant (SSH) et suivi de statut.
"""

import subprocess
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from ....player_profiles import get_active_profile
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


# Stockage des processus en cours pour suivi (PID → (Popen, is_remote))
_active_players: dict[int, tuple[subprocess.Popen, bool]] = {}


def _map_path(local_path: Path, profile: dict) -> str:
    """Remplace le préfixe local par le préfixe distant si configuré."""
    local_prefix = profile.get("local_path_prefix")
    remote_prefix = profile.get("remote_path_prefix")
    if not local_prefix or not remote_prefix:
        return str(local_path)
    path_str = str(local_path)
    if path_str.startswith(local_prefix):
        return remote_prefix + path_str[len(local_prefix):]
    return path_str


def _launch_local(command: str, file_path: Path) -> subprocess.Popen:
    """Lance le lecteur en local."""
    return subprocess.Popen(
        [command, str(file_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _launch_ssh(profile: dict, file_path: Path) -> subprocess.Popen:
    """Lance le lecteur sur une machine distante via SSH."""
    mapped = _map_path(file_path, profile)
    user_host = f"{profile['ssh_user']}@{profile['ssh_host']}"
    remote_cmd = f"{profile['command']} '{mapped}'"
    return subprocess.Popen(
        ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", user_host, remote_cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _launch_player(file_path: Path) -> tuple[int, bool]:
    """Lance le lecteur selon le profil actif. Retourne (pid, is_remote)."""
    profile = get_active_profile()
    is_remote = (
        profile["target"] == "remote"
        and profile.get("ssh_host")
        and profile.get("ssh_user")
    )
    if is_remote:
        proc = _launch_ssh(profile, file_path)
    else:
        proc = _launch_local(profile["command"], file_path)
    _active_players[proc.pid] = (proc, bool(is_remote))
    return proc.pid, bool(is_remote)


def _play_button_html(entity_type: str, entity_id: int) -> str:
    """Genere le bouton Visionner pour un film ou episode."""
    profile = get_active_profile()
    player_label = profile["command"]
    if entity_type == "episodes":
        return (
            f'<button class="lib-episode-play-btn"'
            f' hx-post="/library/episodes/{entity_id}/play"'
            f' hx-swap="outerHTML"'
            f' title="Ouvrir dans {player_label}">'
            f'<svg width="14" height="14" viewBox="0 0 24 24" fill="none"'
            f' stroke="currentColor" stroke-width="2">'
            f'<polygon points="5 3 19 12 5 21 5 3"/></svg></button>'
        )
    return (
        f'<button class="play-btn"'
        f' hx-post="/library/{entity_type}/{entity_id}/play"'
        f' hx-swap="outerHTML"'
        f' title="Ouvrir dans {player_label}">'
        f'<svg width="12" height="12" viewBox="0 0 24 24" fill="none"'
        f' stroke="currentColor" stroke-width="2">'
        f'<polygon points="5 3 19 12 5 21 5 3"/></svg>'
        f" Visionner</button>"
    )


def _playing_html(pid: int, entity_type: str, entity_id: int) -> str:
    """Fragment HTML avec polling status pendant la lecture."""
    return (
        f'<span class="play-launched"'
        f' hx-get="/library/play-status/{pid}?entity_type={entity_type}'
        f'&entity_id={entity_id}"'
        f' hx-trigger="load delay:2s"'
        f' hx-swap="outerHTML">'
        f"Lecture en cours…</span>"
    )


def _error_html(message: str, entity_type: str, entity_id: int) -> str:
    """Fragment HTML pour erreur de lecture (SSH échoué, etc.)."""
    return (
        f'<span class="play-error"'
        f' hx-get="/library/play-status/0?entity_type={entity_type}'
        f'&entity_id={entity_id}"'
        f' hx-trigger="load delay:4s"'
        f' hx-swap="outerHTML">'
        f"{message}</span>"
    )


@router.get("/play-status/{pid}")
async def play_status(
    request: Request, pid: int, entity_type: str = "", entity_id: int = 0
):
    """Verifie si le lecteur tourne encore ; sinon retourne le bouton Visionner."""
    if pid == 0:
        # PID 0 = erreur affichée temporairement, restaurer le bouton
        return HTMLResponse(_play_button_html(entity_type, entity_id))

    entry = _active_players.get(pid)
    if not entry:
        return HTMLResponse(_play_button_html(entity_type, entity_id))

    proc, is_remote = entry
    if proc.poll() is None:
        # Processus encore vivant — continuer le polling
        return HTMLResponse(_playing_html(pid, entity_type, entity_id))

    # Processus terminé — nettoyer
    _active_players.pop(pid, None)

    # Vérifier les erreurs SSH
    if is_remote and proc.returncode != 0:
        stderr_output = ""
        if proc.stderr:
            stderr_output = proc.stderr.read().decode("utf-8", errors="replace").strip()
        if "Connection refused" in stderr_output or "Connection timed out" in stderr_output:
            msg = "Connexion SSH refusée"
        elif "Permission denied" in stderr_output:
            msg = "Authentification SSH refusée"
        elif "Could not resolve hostname" in stderr_output:
            msg = "Hôte SSH introuvable"
        else:
            msg = f"Erreur lecture (code {proc.returncode})"
        return HTMLResponse(_error_html(msg, entity_type, entity_id))

    return HTMLResponse(_play_button_html(entity_type, entity_id))


@router.post("/movies/{movie_id}/play")
async def movie_play(request: Request, movie_id: int):
    """Lance le lecteur pour visionner un film."""
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

    pid, _ = _launch_player(resolved)
    return HTMLResponse(_playing_html(pid, "movies", movie_id))


@router.post("/episodes/{episode_id}/play")
async def episode_play(request: Request, episode_id: int):
    """Lance le lecteur pour visionner un episode."""
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

    pid, _ = _launch_player(resolved)
    return HTMLResponse(_playing_html(pid, "episodes", episode_id))
