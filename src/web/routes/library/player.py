"""
Routes de lecture vidéo intégrée — lancement local ou distant (SSH) et suivi de statut.

Supporte les lectures simultanées sur différents profils.
"""

import html
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from sqlmodel import select

from ....infrastructure.persistence.database import get_session
from ....infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    MoviePartModel,
    SeriesModel,
)
from ....player_profiles import get_active_profile, get_profile_by_name, load_profiles
from ....services.player.dunehd_player import DuneHDPlayer
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


# Stockage des processus en cours pour suivi (PID → (Popen|None, is_remote, profile_name))
# Popen=None correspond aux profils DuneHD (fire-and-forget, pas de process local à poller).
_active_players: dict[int, tuple[Optional[subprocess.Popen], bool, str]] = {}

# Erreurs DuneHD par pid synthétique (consommées par /play-status)
_dunehd_errors: dict[int, str] = {}

# Compteur de pid synthétique pour DuneHD (hors plage des vrais PIDs Linux < 4M)
_dunehd_pid_counter = 10_000_000


def _map_path(local_path: Path, profile: dict) -> str:
    """Remplace le préfixe local par le préfixe distant si configuré."""
    local_prefix = profile.get("local_path_prefix")
    remote_prefix = profile.get("remote_path_prefix")
    if not local_prefix or not remote_prefix:
        return str(local_path)
    path_str = str(local_path)
    if path_str.startswith(local_prefix):
        mapped = remote_prefix + path_str[len(local_prefix):]
        # Chemins UNC Windows : convertir les / en \
        if remote_prefix.startswith("\\\\"):
            mapped = mapped.replace("/", "\\")
        return mapped
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
    remote_prefix = profile.get("remote_path_prefix") or ""
    if remote_prefix.startswith("\\\\"):
        # Windows : SCP du chemin dans le fichier queue lu par mpv_watcher.ps1
        # (SSH echo corrompt les accents, SCP préserve l'UTF-8)
        tmp = Path("/tmp/mpv_queue.txt")
        tmp.write_text(mapped, encoding="utf-8")
        return subprocess.Popen(
            ["scp", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
             str(tmp), f"{user_host}:C:/Apps/mpv_queue.txt"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    remote_cmd = f'{profile["command"]} "{mapped}"'
    return subprocess.Popen(
        ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", user_host, remote_cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _launch_dunehd(profile: dict, file_path: Path) -> int:
    """Envoie l'ordre de lecture à un DuneHD. Retourne un pid synthétique.

    En cas d'erreur API, le message est stocké dans _dunehd_errors[pid] pour
    que /play-status puisse afficher le fragment d'erreur au poll suivant.
    """
    global _dunehd_pid_counter
    _dunehd_pid_counter += 1
    pid = _dunehd_pid_counter

    player = DuneHDPlayer(profile)
    result = player.play(file_path)
    if not result.ok:
        _dunehd_errors[pid] = result.error or "Erreur DuneHD"
    return pid


def _launch_player(
    file_path: Path, profile_name: str | None = None
) -> tuple[int, bool, str]:
    """Lance le lecteur selon le profil spécifié ou actif.

    Retourne (pid, is_remote, profile_name).
    Pour les profils dunehd, le pid est synthétique et la lecture est
    fire-and-forget (pas de process local à suivre).
    """
    if profile_name:
        profile = get_profile_by_name(profile_name)
        if not profile:
            profile = get_active_profile()
    else:
        profile = get_active_profile()

    if profile.get("type") == "dunehd":
        pid = _launch_dunehd(profile, file_path)
        _active_players[pid] = (None, True, profile["name"])
        return pid, True, profile["name"]

    is_remote = (
        profile["target"] == "remote"
        and profile.get("ssh_host")
        and profile.get("ssh_user")
    )
    if is_remote:
        proc = _launch_ssh(profile, file_path)
    else:
        proc = _launch_local(profile["command"], file_path)
    _active_players[proc.pid] = (proc, bool(is_remote), profile["name"])
    return proc.pid, bool(is_remote), profile["name"]


def _play_button_html(entity_type: str, entity_id: int) -> str:
    """Genere le bouton Visionner avec sélecteur de profil si nécessaire."""
    data = load_profiles()
    profiles = data.get("profiles", [])
    active_name = data.get("active", "Local")

    if len(profiles) <= 1:
        # Un seul profil : bouton direct sans popover
        profile = profiles[0] if profiles else {"command": "mpv", "name": "Local"}
        if entity_type == "episodes":
            return (
                f'<button class="lib-episode-play-btn"'
                f' hx-post="/library/episodes/{entity_id}/play"'
                f' hx-swap="outerHTML"'
                f' title="Ouvrir dans {html.escape(profile["command"])}">'
                f'<svg width="14" height="14" viewBox="0 0 24 24" fill="none"'
                f' stroke="currentColor" stroke-width="2">'
                f'<polygon points="5 3 19 12 5 21 5 3"/></svg></button>'
            )
        return (
            f'<button class="play-btn"'
            f' hx-post="/library/{entity_type}/{entity_id}/play"'
            f' hx-swap="outerHTML"'
            f' title="Ouvrir dans {html.escape(profile["command"])}">'
            f'<svg width="12" height="12" viewBox="0 0 24 24" fill="none"'
            f' stroke="currentColor" stroke-width="2">'
            f'<polygon points="5 3 19 12 5 21 5 3"/></svg>'
            f" Visionner</button>"
        )

    # Plusieurs profils : bouton avec popover sélecteur
    play_icon = (
        '<svg width="12" height="12" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2">'
        '<polygon points="5 3 19 12 5 21 5 3"/></svg>'
    )
    play_icon_small = (
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2">'
        '<polygon points="5 3 19 12 5 21 5 3"/></svg>'
    )

    # Icônes cible
    icon_local = (
        '<svg class="play-profile-icon" width="14" height="14" viewBox="0 0 24 24"'
        ' fill="none" stroke="currentColor" stroke-width="2">'
        '<rect x="2" y="3" width="20" height="14" rx="2"/>'
        '<line x1="8" y1="21" x2="16" y2="21"/>'
        '<line x1="12" y1="17" x2="12" y2="21"/></svg>'
    )
    icon_remote = (
        '<svg class="play-profile-icon" width="14" height="14" viewBox="0 0 24 24"'
        ' fill="none" stroke="currentColor" stroke-width="2">'
        '<rect x="2" y="7" width="20" height="15" rx="2"/>'
        '<polyline points="17 2 12 7 7 2"/></svg>'
    )

    # Options du popover
    options_html = ""
    for p in profiles:
        name_esc = html.escape(p["name"])
        icon = icon_remote if p.get("target") == "remote" else icon_local
        default_mark = ' <span class="play-profile-default">(défaut)</span>' if p["name"] == active_name else ""
        css_class = "play-profile-option default" if p["name"] == active_name else "play-profile-option"

        if entity_type == "episodes":
            post_url = f"/library/episodes/{entity_id}/play?profile={html.escape(p['name'])}"
        else:
            post_url = f"/library/{entity_type}/{entity_id}/play?profile={html.escape(p['name'])}"

        options_html += (
            f'<button class="{css_class}"'
            f' hx-post="{post_url}"'
            f' hx-swap="outerHTML" hx-target="closest .play-wrapper"'
            f' onclick="event.stopPropagation()">'
            f'{icon} {name_esc}{default_mark}</button>'
        )

    popover = (
        f'<div class="play-profile-popover">{options_html}</div>'
    )

    toggle = "onclick=\"this.parentElement.classList.toggle('popover-open')\""

    if entity_type == "episodes":
        return (
            f'<span class="play-wrapper play-wrapper-episode">'
            f'<button class="lib-episode-play-btn play-popover-trigger"'
            f' title="Choisir le lecteur" {toggle}>'
            f'{play_icon_small}</button>'
            f'{popover}</span>'
        )

    return (
        f'<span class="play-wrapper">'
        f'<button class="play-btn play-popover-trigger"'
        f' title="Choisir le lecteur" {toggle}>'
        f'{play_icon} Visionner</button>'
        f'{popover}</span>'
    )


def _playing_html(
    pid: int, entity_type: str, entity_id: int, profile_name: str = ""
) -> str:
    """Fragment HTML avec polling status pendant la lecture."""
    label = "Lecture en cours…"
    if profile_name:
        label = f"Lecture en cours… ({html.escape(profile_name)})"
    return (
        f'<span class="play-launched"'
        f' hx-get="/library/play-status/{pid}?entity_type={entity_type}'
        f'&entity_id={entity_id}"'
        f' hx-trigger="load delay:2s"'
        f' hx-swap="outerHTML">'
        f"{label}</span>"
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

    proc, is_remote, profile_name = entry

    # DuneHD (fire-and-forget) : pas de process à poller
    if proc is None:
        _active_players.pop(pid, None)
        error = _dunehd_errors.pop(pid, None)
        if error:
            return HTMLResponse(
                _error_html(f"DuneHD : {error}", entity_type, entity_id)
            )
        return HTMLResponse(_play_button_html(entity_type, entity_id))

    if proc.poll() is None:
        # Processus encore vivant — continuer le polling
        return HTMLResponse(_playing_html(pid, entity_type, entity_id, profile_name))

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
async def movie_play(
    request: Request, movie_id: int, profile: Optional[str] = None
):
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
        return HTMLResponse(_error_html("Fichier vidéo introuvable", "movies", movie_id))

    pid, _, pname = _launch_player(resolved, profile_name=profile)
    return HTMLResponse(_playing_html(pid, "movies", movie_id, pname))


@router.post("/movie-parts/{part_id}/play")
async def movie_part_play(
    request: Request, part_id: int, profile: Optional[str] = None
):
    """Lance le lecteur pour une partie d'un film multi-parties."""
    session = next(get_session())
    try:
        part = session.get(MoviePartModel, part_id)
        if not part:
            return Response(status_code=404)
        file_path = part.file_path or part.symlink_path
    finally:
        session.close()

    resolved = _resolve_video_path(file_path)
    if not resolved:
        return HTMLResponse(
            _error_html("Fichier vidéo introuvable", "movie-parts", part_id)
        )

    pid, _, pname = _launch_player(resolved, profile_name=profile)
    return HTMLResponse(_playing_html(pid, "movie-parts", part_id, pname))


@router.post("/episodes/{episode_id}/play")
async def episode_play(
    request: Request, episode_id: int, profile: Optional[str] = None
):
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
            _error_html("Fichier vidéo introuvable", "episodes", episode_id)
        )

    pid, _, pname = _launch_player(resolved, profile_name=profile)
    return HTMLResponse(_playing_html(pid, "episodes", episode_id, pname))


@router.post("/series/{series_id}/play")
async def series_play(
    request: Request, series_id: int, profile: Optional[str] = None
):
    """Lance le lecteur pour le premier episode disponible d'une serie."""
    session = next(get_session())
    try:
        series = session.get(SeriesModel, series_id)
        if not series:
            return Response(status_code=404)
        # Chercher le premier episode avec fichier (S01E01 en priorite)
        episode = session.exec(
            select(EpisodeModel)
            .where(
                EpisodeModel.series_id == series_id,
                EpisodeModel.file_path.is_not(None),  # type: ignore[union-attr]
            )
            .order_by(EpisodeModel.season_number, EpisodeModel.episode_number)
        ).first()
        if not episode:
            return HTMLResponse(
                _error_html(
                    "Aucun épisode avec fichier disponible", "series", series_id
                )
            )
        file_path = episode.file_path
    finally:
        session.close()

    resolved = _resolve_video_path(file_path)
    if not resolved:
        return HTMLResponse(
            _error_html("Fichier vidéo introuvable", "series", series_id)
        )

    pid, _, pname = _launch_player(resolved, profile_name=profile)
    return HTMLResponse(_playing_html(pid, "series", series_id, pname))
