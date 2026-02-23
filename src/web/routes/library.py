"""
Routes de la bibliotheque — navigation films et series.

Affiche la collection avec filtres, recherche, pagination et pages de detail.
"""

import json
import math
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
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

            movies = session.exec(movie_stmt).all()
            for m in movies:
                rating = _best_rating(m.vote_average, m.imdb_rating)
                items.append({
                    "id": m.id,
                    "type": "movie",
                    "title": m.title,
                    "year": m.year,
                    "genres": _parse_genres(m.genres_json),
                    "poster_url": _poster_url(m.poster_path),
                    "rating": rating,
                    "rating_source": "IMDb" if m.imdb_rating is not None else "TMDB",
                })

        # --- Series ---
        if type in ("all", "series"):
            series_stmt = select(SeriesModel)
            if q:
                series_stmt = series_stmt.where(SeriesModel.title.contains(q))
            if year_int:
                series_stmt = series_stmt.where(SeriesModel.year == year_int)
            if genre:
                series_stmt = series_stmt.where(SeriesModel.genres_json.contains(genre))

            all_series = session.exec(series_stmt).all()
            for s in all_series:
                rating = _best_rating(s.vote_average, s.imdb_rating)
                items.append({
                    "id": s.id,
                    "type": "series",
                    "title": s.title,
                    "year": s.year,
                    "genres": _parse_genres(s.genres_json),
                    "poster_url": _poster_url(s.poster_path),
                    "rating": rating,
                    "rating_source": "IMDb" if s.imdb_rating is not None else "TMDB",
                })

        # --- Tri ---
        descending = order == "desc"
        if sort == "year":
            items.sort(key=lambda x: (x["year"] or 0, x["title"].lower()), reverse=descending)
        elif sort == "rating":
            items.sort(key=lambda x: (x["rating"] or 0, x["title"].lower()), reverse=descending)
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
        "current_sort": sort,
        "current_order": order,
    }

    # Si requete HTMX, retourner filtres + grille (le bloc #library-content)
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request, "library/_content.html", context
        )

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
