"""
Routes de la bibliotheque — navigation films et series.

Affiche la collection avec filtres, recherche, pagination et pages de detail.
"""

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Optional

import subprocess

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlmodel import select

from ...infrastructure.persistence.database import get_session
from ...infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    SeriesModel,
    VideoFileModel,
)
from ..deps import templates

router = APIRouter(prefix="/library")

ITEMS_PER_PAGE = 24


def _parse_genres(genres_json: str | None) -> list[str]:
    """Parse le champ genres_json en liste de strings."""
    if genres_json:
        try:
            return json.loads(genres_json)
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def _format_duration(seconds: int | None) -> str:
    """Formate une duree en secondes en 'Xh XXmin'."""
    if not seconds:
        return ""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes:02d}min"
    return f"{minutes}min"


def _poster_url(poster_path: str | None) -> str | None:
    """Construit l'URL poster TMDB."""
    if poster_path:
        if poster_path.startswith("http"):
            return poster_path
        return f"https://image.tmdb.org/t/p/w300{poster_path}"
    return None


def _best_rating(vote_average: float | None, imdb_rating: float | None) -> float | None:
    """Retourne la meilleure note disponible : IMDb en priorite, sinon TMDB."""
    if imdb_rating is not None:
        return imdb_rating
    return vote_average


@router.get("/")
async def library_index(
    request: Request,
    type: str = "all",
    genre: Optional[str] = None,
    year: Optional[str] = None,
    q: Optional[str] = None,
    person: Optional[str] = None,
    sort: str = "title",
    order: str = "asc",
    page: int = 1,
):
    """Page principale de la bibliotheque avec filtres et pagination."""
    # Convertir year en int (le formulaire envoie "" quand vide)
    year_int: int | None = None
    if year:
        try:
            year_int = int(year)
        except (ValueError, TypeError):
            pass

    session = next(get_session())
    try:
        items = []

        # --- Films ---
        if type in ("all", "movie"):
            movie_stmt = select(MovieModel)
            if q:
                movie_stmt = movie_stmt.where(MovieModel.title.contains(q))
            if year_int:
                movie_stmt = movie_stmt.where(MovieModel.year == year_int)
            if genre:
                movie_stmt = movie_stmt.where(MovieModel.genres_json.contains(genre))
            if person:
                movie_stmt = movie_stmt.where(
                    MovieModel.director.contains(person)
                    | MovieModel.cast_json.contains(person)
                )

            movies = session.exec(movie_stmt).all()
            for m in movies:
                rating = _best_rating(m.vote_average, m.imdb_rating)
                items.append(
                    {
                        "id": m.id,
                        "type": "movie",
                        "title": m.title,
                        "year": m.year,
                        "genres": _parse_genres(m.genres_json),
                        "poster_url": _poster_url(m.poster_path),
                        "rating": rating,
                        "rating_source": "IMDb"
                        if m.imdb_rating is not None
                        else "TMDB",
                    }
                )

        # --- Series ---
        if type in ("all", "series"):
            series_stmt = select(SeriesModel)
            if q:
                series_stmt = series_stmt.where(SeriesModel.title.contains(q))
            if year_int:
                series_stmt = series_stmt.where(SeriesModel.year == year_int)
            if genre:
                series_stmt = series_stmt.where(SeriesModel.genres_json.contains(genre))
            if person:
                series_stmt = series_stmt.where(
                    SeriesModel.director.contains(person)
                    | SeriesModel.cast_json.contains(person)
                )

            all_series = session.exec(series_stmt).all()
            for s in all_series:
                rating = _best_rating(s.vote_average, s.imdb_rating)
                items.append(
                    {
                        "id": s.id,
                        "type": "series",
                        "title": s.title,
                        "year": s.year,
                        "genres": _parse_genres(s.genres_json),
                        "poster_url": _poster_url(s.poster_path),
                        "rating": rating,
                        "rating_source": "IMDb"
                        if s.imdb_rating is not None
                        else "TMDB",
                    }
                )

        # --- Tri ---
        descending = order == "desc"
        if sort == "year":
            items.sort(
                key=lambda x: (x["year"] or 0, x["title"].lower()), reverse=descending
            )
        elif sort == "rating":
            items.sort(
                key=lambda x: (x["rating"] or 0, x["title"].lower()), reverse=descending
            )
        else:  # title
            items.sort(key=lambda x: x["title"].lower(), reverse=descending)

        # --- Pagination ---
        total_items = len(items)
        total_pages = max(1, math.ceil(total_items / ITEMS_PER_PAGE))
        page = max(1, min(page, total_pages))
        start = (page - 1) * ITEMS_PER_PAGE
        page_items = items[start : start + ITEMS_PER_PAGE]

        # --- Genres distincts pour le filtre ---
        all_genres: set[str] = set()
        all_movie_genres = session.exec(
            select(MovieModel.genres_json).where(MovieModel.genres_json.is_not(None))
        ).all()
        for gj in all_movie_genres:
            all_genres.update(_parse_genres(gj))
        all_series_genres = session.exec(
            select(SeriesModel.genres_json).where(SeriesModel.genres_json.is_not(None))
        ).all()
        for gj in all_series_genres:
            all_genres.update(_parse_genres(gj))

        # --- Annees distinctes pour le filtre ---
        movie_years = session.exec(
            select(MovieModel.year).where(MovieModel.year.is_not(None)).distinct()
        ).all()
        series_years = session.exec(
            select(SeriesModel.year).where(SeriesModel.year.is_not(None)).distinct()
        ).all()
        all_years = sorted(set(movie_years + series_years), reverse=True)

    finally:
        session.close()

    context = {
        "items": page_items,
        "total_items": total_items,
        "page": page,
        "total_pages": total_pages,
        "genres": sorted(all_genres),
        "years": all_years,
        "current_type": type,
        "current_genre": genre,
        "current_year": year_int,
        "current_q": q or "",
        "current_person": person or "",
        "current_sort": sort,
        "current_order": order,
    }

    # Si requete HTMX, retourner filtres + grille (le bloc #library-content)
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "library/_content.html", context)

    return templates.TemplateResponse(request, "library/index.html", context)


def _find_movie_file(title: str, year: int | None) -> dict | None:
    """
    Recherche le fichier d'un film dans video/Films/ par titre et annee.

    Utilise un glob sur l'annee pour limiter le scan, puis compare les titres
    de maniere tolerante (caracteres speciaux ignores).

    Returns:
        Dict avec symlink_path et storage_path, ou None si non trouve
    """
    from ...config import Settings

    try:
        settings = Settings()
        video_dir = Path(settings.video_dir) / "Films"
    except Exception:
        return None

    if not video_dir.exists():
        return None

    if not year:
        return None

    # Normaliser le titre pour comparaison souple
    def _normalize(s: str) -> str:
        """Retire les caracteres speciaux pour comparaison."""
        return "".join(c.lower() for c in s if c.isalnum() or c == " ").strip()

    norm_title = _normalize(title)
    year_str = f"({year})"

    # Glob sur l'annee pour limiter le scan
    for f in video_dir.rglob(f"*{year_str}*"):
        if not f.is_file():
            continue
        # Extraire le titre du nom de fichier (avant "(annee)")
        fname = f.name
        idx = fname.find(year_str)
        if idx <= 0:
            continue
        file_title = fname[:idx].strip()
        if _normalize(file_title) == norm_title:
            try:
                storage_path = str(f.resolve()) if f.is_symlink() else None
            except OSError:
                storage_path = None
            return {
                "symlink_path": str(f),
                "storage_path": storage_path,
            }

    return None


@router.get("/movies/{movie_id}")
async def movie_detail(request: Request, movie_id: int):
    """Page de detail d'un film."""
    session = next(get_session())
    try:
        movie = session.get(MovieModel, movie_id)
        if not movie:
            return templates.TemplateResponse(
                request,
                "library/not_found.html",
                {"entity_type": "film", "entity_id": movie_id},
                status_code=404,
            )

        genres = _parse_genres(movie.genres_json)
        poster_url = _poster_url(movie.poster_path)
        duration = _format_duration(movie.duration_seconds)

        # Chercher le VideoFile associe pour les infos symlink/technique
        video_file = None
        if movie.file_path:
            video_file = session.exec(
                select(VideoFileModel).where(VideoFileModel.path == movie.file_path)
            ).first()

    finally:
        session.close()

    # Si pas de file_path en DB, chercher dans video/Films/ par titre
    file_info = None
    if not movie.file_path and not video_file:
        file_info = _find_movie_file(movie.title, movie.year)

    return templates.TemplateResponse(
        request,
        "library/movie_detail.html",
        {
            "movie": movie,
            "genres": genres,
            "poster_url": poster_url,
            "duration": duration,
            "video_file": video_file,
            "file_info": file_info,
        },
    )


@router.get("/series/{series_id}")
async def series_detail(request: Request, series_id: int):
    """Page de detail d'une serie avec episodes groupes par saison."""
    session = next(get_session())
    try:
        series = session.get(SeriesModel, series_id)
        if not series:
            return templates.TemplateResponse(
                request,
                "library/not_found.html",
                {"entity_type": "série", "entity_id": series_id},
                status_code=404,
            )

        genres = _parse_genres(series.genres_json)
        poster_url = _poster_url(series.poster_path)

        # Charger les episodes groupes par saison
        episodes = session.exec(
            select(EpisodeModel)
            .where(EpisodeModel.series_id == series_id)
            .order_by(EpisodeModel.season_number, EpisodeModel.episode_number)
        ).all()

        # Grouper par saison
        seasons: dict[int, list] = {}
        for ep in episodes:
            if ep.season_number not in seasons:
                seasons[ep.season_number] = []
            seasons[ep.season_number].append(ep)

        total_episodes = len(episodes)

    finally:
        session.close()

    return templates.TemplateResponse(
        request,
        "library/series_detail.html",
        {
            "series": series,
            "genres": genres,
            "poster_url": poster_url,
            "seasons": dict(sorted(seasons.items())),
            "total_episodes": total_episodes,
        },
    )


# ────────────────────────────────────────────────────────────────────
# Lecture video integree
# ────────────────────────────────────────────────────────────────────


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


# ────────────────────────────────────────────────────────────────────
# Routes de re-association TMDB (correction manuelle)
# ────────────────────────────────────────────────────────────────────


def _get_file_duration(movie: "MovieModel") -> int | None:
    """
    Extrait la duree reelle d'un fichier video via mediainfo.

    Strategie : file_path en DB, sinon resolution du symlink via _find_movie_file.
    """
    from ...adapters.parsing.mediainfo_extractor import MediaInfoExtractor

    # 1. file_path direct en DB
    physical_path = movie.file_path

    # 2. Sinon, trouver le symlink dans video/ et resoudre vers le storage
    if not physical_path:
        file_info = _find_movie_file(movie.title, movie.year)
        if file_info:
            physical_path = file_info.get("storage_path") or file_info.get(
                "symlink_path"
            )

    if not physical_path:
        return None

    path = Path(physical_path)
    # Si c'est un symlink, resoudre vers le fichier physique
    if path.is_symlink():
        path = path.resolve()
    if not path.exists():
        return None

    try:
        info = MediaInfoExtractor().extract(path)
        return info.duration_seconds if info else None
    except Exception:
        return None


def _duration_indicator(local_seconds: int | None, tmdb_seconds: int | None) -> dict:
    """
    Compare les durees locale et TMDB, retourne un indicateur visuel.

    Memes seuils que le CLI (candidate_display._get_duration_color) :
    - < 5 min : vert (coherent)
    - 5-15 min : jaune (ecart modere)
    - >= 15 min : rouge (tres different)
    """
    if not local_seconds or not tmdb_seconds:
        return {"show": False}

    diff = abs(local_seconds - tmdb_seconds)
    if diff < 5 * 60:
        return {"show": True, "css": "duration-match", "label": "Durée cohérente"}
    elif diff < 15 * 60:
        return {"show": True, "css": "duration-warn", "label": "Écart modéré"}
    else:
        return {
            "show": True,
            "css": "duration-danger",
            "label": "Durée très différente",
        }


def _series_indicator(
    local_seasons: int | None,
    local_episodes: int | None,
    tmdb_seasons: int | None,
    tmdb_episodes: int | None,
) -> dict:
    """Compare saisons/episodes locaux et TMDB pour indicateur de confiance."""
    if not local_episodes or not tmdb_episodes:
        return {"show": False}

    ep_diff = abs(local_episodes - tmdb_episodes)
    season_match = local_seasons == tmdb_seasons if local_seasons and tmdb_seasons else True

    if ep_diff == 0 and season_match:
        return {"show": True, "css": "duration-match", "label": "Correspondance exacte"}
    elif ep_diff <= 3 and season_match:
        return {"show": True, "css": "duration-match", "label": "Très proche"}
    elif ep_diff <= 10:
        return {"show": True, "css": "duration-warn", "label": "Écart modéré"}
    else:
        return {"show": True, "css": "duration-danger", "label": "Très différent"}


def _get_local_series_counts(series_id: int) -> tuple[int, int]:
    """Compte les saisons et episodes locaux depuis la DB."""
    session = next(get_session())
    try:
        episodes = session.exec(
            select(EpisodeModel).where(EpisodeModel.series_id == series_id)
        ).all()
        if not episodes:
            return 0, 0
        seasons = set()
        for ep in episodes:
            seasons.add(ep.season_number)
        return len(seasons), len(episodes)
    finally:
        session.close()


@router.get("/movies/{movie_id}/reassociate")
async def movie_reassociate_overlay(request: Request, movie_id: int):
    """Retourne le fragment HTML de l'overlay de recherche pour un film."""
    session = next(get_session())
    try:
        movie = session.get(MovieModel, movie_id)
        if not movie:
            return HTMLResponse("<p>Film non trouvé</p>", status_code=404)
    finally:
        session.close()

    # Duree reelle du fichier via mediainfo (pas la duree TMDB en DB)
    file_duration = _get_file_duration(movie)

    return templates.TemplateResponse(
        request,
        "library/_reassociate_overlay.html",
        {
            "entity_id": movie_id,
            "entity_type": "movie",
            "title": movie.title,
            "year": movie.year,
            "current_tmdb_id": movie.tmdb_id,
            "local_duration_seconds": file_duration,
        },
    )


@router.get("/movies/{movie_id}/reassociate/search")
async def movie_reassociate_search(request: Request, movie_id: int, q: str = ""):
    """Recherche TMDB films et retourne les resultats enrichis."""
    if not q.strip():
        return HTMLResponse("<p class='reassociate-empty'>Saisissez un titre</p>")

    container = request.app.state.container
    tmdb_client = container.tmdb_client()

    # Recuperer le film en DB
    session = next(get_session())
    try:
        movie = session.get(MovieModel, movie_id)
        current_tmdb_id = movie.tmdb_id if movie else None
    finally:
        session.close()

    # Duree reelle du fichier via mediainfo (seule source fiable)
    local_duration = _get_file_duration(movie) if movie else None

    # Recherche TMDB
    results = await tmdb_client.search(q)

    # Enrichir chaque resultat (max 8) avec les details
    candidates = []
    for sr in results[:8]:
        details = await tmdb_client.get_details(sr.id)
        indicator = _duration_indicator(
            local_duration, details.duration_seconds if details else None
        )
        candidates.append(
            {
                "tmdb_id": sr.id,
                "title": details.title if details else sr.title,
                "original_title": details.original_title
                if details
                else sr.original_title,
                "year": details.year if details else sr.year,
                "overview": details.overview if details else None,
                "poster_url": _poster_url(details.poster_url)
                if details and details.poster_url
                else None,
                "director": details.director if details else None,
                "tmdb_duration": _format_duration(details.duration_seconds)
                if details and details.duration_seconds
                else None,
                "tmdb_duration_seconds": details.duration_seconds if details else None,
                "duration_indicator": indicator,
                "is_current": str(current_tmdb_id) == sr.id
                if current_tmdb_id
                else False,
            }
        )

    # Trier par pertinence : ecart de duree le plus faible en premier
    if local_duration:
        candidates.sort(
            key=lambda c: abs((c["tmdb_duration_seconds"] or 999999) - local_duration)
        )

    return templates.TemplateResponse(
        request,
        "library/_reassociate_results.html",
        {
            "candidates": candidates,
            "entity_id": movie_id,
            "entity_type": "movie",
            "local_duration": _format_duration(local_duration),
            "local_duration_seconds": local_duration,
        },
    )


@router.post("/movies/{movie_id}/reassociate")
async def movie_reassociate_apply(
    request: Request,
    movie_id: int,
    tmdb_id: str = Form(...),
):
    """Applique la re-association d'un film avec un nouveau resultat TMDB."""
    container = request.app.state.container
    tmdb_client = container.tmdb_client()

    # Recuperer les details complets
    details = await tmdb_client.get_details(tmdb_id)
    if not details:
        return HTMLResponse("<p>Résultat TMDB non trouvé</p>", status_code=404)

    # Recuperer l'imdb_id
    ext_ids = await tmdb_client.get_external_ids(tmdb_id)
    imdb_id = ext_ids.get("imdb_id") if ext_ids else None

    # Mettre a jour le MovieModel
    session = next(get_session())
    try:
        movie = session.get(MovieModel, movie_id)
        if not movie:
            return HTMLResponse("<p>Film non trouvé</p>", status_code=404)

        movie.tmdb_id = int(tmdb_id)
        movie.imdb_id = imdb_id
        movie.title = details.title
        movie.original_title = details.original_title
        movie.year = details.year
        movie.genres_json = json.dumps(list(details.genres)) if details.genres else None
        movie.duration_seconds = details.duration_seconds
        movie.overview = details.overview
        movie.poster_path = details.poster_url
        movie.director = details.director
        movie.cast_json = json.dumps(list(details.cast)) if details.cast else None
        movie.vote_average = details.vote_average
        movie.vote_count = details.vote_count
        movie.updated_at = datetime.utcnow()

        # Tenter de relier le fichier physique via le symlink video/
        if not movie.file_path:
            file_info = _find_movie_file(details.title, details.year)
            if file_info:
                movie.file_path = file_info.get("storage_path") or file_info.get(
                    "symlink_path"
                )

        session.add(movie)
        session.commit()
    finally:
        session.close()

    response = Response(status_code=200)
    response.headers["HX-Redirect"] = f"/library/movies/{movie_id}"
    return response


@router.get("/series/{series_id}/reassociate")
async def series_reassociate_overlay(request: Request, series_id: int):
    """Retourne le fragment HTML de l'overlay de recherche pour une serie."""
    session = next(get_session())
    try:
        series = session.get(SeriesModel, series_id)
        if not series:
            return HTMLResponse("<p>Série non trouvée</p>", status_code=404)
    finally:
        session.close()

    local_seasons, local_episodes = _get_local_series_counts(series_id)

    return templates.TemplateResponse(
        request,
        "library/_reassociate_overlay.html",
        {
            "entity_id": series_id,
            "entity_type": "series",
            "title": series.title,
            "year": series.year,
            "current_tmdb_id": series.tmdb_id,
            "local_duration_seconds": None,
            "local_seasons": local_seasons,
            "local_episodes": local_episodes,
        },
    )


@router.get("/series/{series_id}/reassociate/search")
async def series_reassociate_search(request: Request, series_id: int, q: str = ""):
    """Recherche TMDB series et retourne les resultats enrichis."""
    if not q.strip():
        return HTMLResponse("<p class='reassociate-empty'>Saisissez un titre</p>")

    container = request.app.state.container
    tmdb_client = container.tmdb_client()

    # Recuperer le tmdb_id actuel pour marquage
    session = next(get_session())
    try:
        series = session.get(SeriesModel, series_id)
        current_tmdb_id = series.tmdb_id if series else None
    finally:
        session.close()

    # Compter saisons/episodes locaux
    local_seasons, local_episodes = _get_local_series_counts(series_id)

    # Recherche TMDB TV
    results = await tmdb_client.search_tv(q)

    # Enrichir chaque resultat avec les details
    candidates = []
    for sr in results[:8]:
        details = await tmdb_client.get_tv_details(sr.id)

        # Recuperer number_of_seasons / number_of_episodes via appel brut
        # (non expose par MediaDetails, on accede au cache TMDB)
        nb_seasons = None
        nb_episodes = None
        try:
            client = tmdb_client._get_client()
            from ...adapters.api.retry import request_with_retry

            resp = await request_with_retry(
                client, "GET", f"/tv/{sr.id}", params={"language": "fr-FR"}
            )
            tv_data = resp.json()
            nb_seasons = tv_data.get("number_of_seasons")
            nb_episodes = tv_data.get("number_of_episodes")
        except Exception:
            pass

        indicator = _series_indicator(
            local_seasons, local_episodes, nb_seasons, nb_episodes
        )

        candidates.append(
            {
                "tmdb_id": sr.id,
                "title": details.title if details else sr.title,
                "original_title": details.original_title
                if details
                else sr.original_title,
                "year": details.year if details else sr.year,
                "overview": details.overview if details else None,
                "poster_url": _poster_url(details.poster_url)
                if details and details.poster_url
                else None,
                "director": details.director if details else None,
                "nb_seasons": nb_seasons,
                "nb_episodes": nb_episodes,
                "series_indicator": indicator,
                "is_current": str(current_tmdb_id) == sr.id
                if current_tmdb_id
                else False,
            }
        )

    # Trier par proximite du nombre d'episodes
    if local_episodes:
        candidates.sort(
            key=lambda c: abs((c["nb_episodes"] or 9999) - local_episodes)
        )

    return templates.TemplateResponse(
        request,
        "library/_reassociate_results.html",
        {
            "candidates": candidates,
            "entity_id": series_id,
            "entity_type": "series",
            "local_duration": None,
            "local_duration_seconds": None,
            "local_seasons": local_seasons,
            "local_episodes": local_episodes,
        },
    )


@router.post("/series/{series_id}/reassociate")
async def series_reassociate_apply(
    request: Request,
    series_id: int,
    tmdb_id: str = Form(...),
):
    """Applique la re-association d'une serie avec un nouveau resultat TMDB."""
    container = request.app.state.container
    tmdb_client = container.tmdb_client()

    # Recuperer les details complets
    details = await tmdb_client.get_tv_details(tmdb_id)
    if not details:
        return HTMLResponse("<p>Résultat TMDB non trouvé</p>", status_code=404)

    # Recuperer l'imdb_id
    ext_ids = await tmdb_client.get_tv_external_ids(tmdb_id)
    imdb_id = ext_ids.get("imdb_id") if ext_ids else None

    # Mettre a jour le SeriesModel
    session = next(get_session())
    try:
        series = session.get(SeriesModel, series_id)
        if not series:
            return HTMLResponse("<p>Série non trouvée</p>", status_code=404)

        series.tmdb_id = int(tmdb_id)
        series.imdb_id = imdb_id
        series.tvdb_id = (
            None  # L'association change, l'ancien tvdb_id n'est plus valide
        )
        series.title = details.title
        series.original_title = details.original_title
        series.year = details.year
        series.genres_json = (
            json.dumps(list(details.genres)) if details.genres else None
        )
        series.overview = details.overview
        series.poster_path = details.poster_url
        series.director = details.director
        series.cast_json = json.dumps(list(details.cast)) if details.cast else None
        series.vote_average = details.vote_average
        series.vote_count = details.vote_count
        series.updated_at = datetime.utcnow()

        session.add(series)
        session.commit()
    finally:
        session.close()

    response = Response(status_code=200)
    response.headers["HX-Redirect"] = f"/library/series/{series_id}"
    return response
