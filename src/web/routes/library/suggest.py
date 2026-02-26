"""
Route de suggestion — "Surprends-moi" pour proposer un film ou série à regarder.
"""

import random
from typing import Optional

from fastapi import APIRouter, Request
from sqlalchemy import or_
from sqlmodel import select

from ....infrastructure.persistence.database import get_session
from ....infrastructure.persistence.models import MovieModel, SeriesModel
from ...deps import templates
from .helpers import (
    _best_rating,
    _format_duration,
    _genre_json_escaped,
    _parse_genres,
    _poster_url,
)

router = APIRouter()


def _eligible_filter(model_class):
    """Filtre d'éligibilité : non-vus OU déjà vus avec note >= 4."""
    return or_(
        model_class.watched == False,  # noqa: E712
        (model_class.watched == True) & (model_class.personal_rating >= 4),  # noqa: E712
    )


@router.get("/suggest")
async def suggest(
    request: Request,
    genre: Optional[str] = None,
    max_duration: Optional[str] = None,
    min_rating: Optional[str] = None,
    type: str = "all",
):
    """Page 'Surprends-moi' — suggestion aléatoire d'un film ou série."""
    # Parser max_duration et min_rating (le formulaire envoie "" quand vide)
    max_duration_int: int | None = None
    if max_duration:
        try:
            max_duration_int = int(max_duration)
        except (ValueError, TypeError):
            pass

    min_rating_float: float | None = None
    if min_rating:
        try:
            min_rating_float = float(min_rating)
        except (ValueError, TypeError):
            pass

    session = next(get_session())
    try:
        candidates = []

        # --- Films éligibles ---
        if type in ("all", "movie"):
            movie_stmt = select(MovieModel).where(_eligible_filter(MovieModel))
            if genre:
                movie_stmt = movie_stmt.where(
                    MovieModel.genres_json.contains(_genre_json_escaped(genre))
                )
            if max_duration_int:
                movie_stmt = movie_stmt.where(
                    MovieModel.duration_seconds <= max_duration_int * 60
                )
            movies = session.exec(movie_stmt).all()
            for m in movies:
                rating = _best_rating(m.vote_average, m.imdb_rating)
                if min_rating_float and (rating is None or rating < min_rating_float):
                    continue
                candidates.append(
                    {
                        "id": m.id,
                        "type": "movie",
                        "title": m.title,
                        "year": m.year,
                        "genres": _parse_genres(m.genres_json),
                        "poster_url": _poster_url(m.poster_path),
                        "rating": rating,
                        "rating_source": "IMDb" if m.imdb_rating is not None else "TMDB",
                        "overview": m.overview or "",
                        "duration": _format_duration(m.duration_seconds),
                        "watched": m.watched,
                        "personal_rating": m.personal_rating,
                    }
                )

        # --- Séries éligibles ---
        if type in ("all", "series"):
            series_stmt = select(SeriesModel).where(_eligible_filter(SeriesModel))
            if genre:
                series_stmt = series_stmt.where(
                    SeriesModel.genres_json.contains(_genre_json_escaped(genre))
                )
            # max_duration ne s'applique pas aux séries
            all_series = session.exec(series_stmt).all()
            for s in all_series:
                rating = _best_rating(s.vote_average, s.imdb_rating)
                if min_rating_float and (rating is None or rating < min_rating_float):
                    continue
                candidates.append(
                    {
                        "id": s.id,
                        "type": "series",
                        "title": s.title,
                        "year": s.year,
                        "genres": _parse_genres(s.genres_json),
                        "poster_url": _poster_url(s.poster_path),
                        "rating": rating,
                        "rating_source": "IMDb" if s.imdb_rating is not None else "TMDB",
                        "overview": s.overview or "",
                        "duration": "",
                        "watched": s.watched,
                        "personal_rating": s.personal_rating,
                    }
                )

        # --- Suggestion aléatoire ---
        result = random.choice(candidates) if candidates else None

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

    finally:
        session.close()

    return templates.TemplateResponse(
        request,
        "library/suggest.html",
        {
            "result": result,
            "genres": sorted(all_genres),
            "current_genre": genre or "",
            "current_max_duration": max_duration_int or "",
            "current_min_rating": min_rating or "",
            "current_type": type,
            "total_candidates": len(candidates),
        },
    )
