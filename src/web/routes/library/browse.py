"""
Route de navigation de la bibliothèque — listing avec filtres et pagination.
"""

import math
from typing import Optional

from fastapi import APIRouter, Request
from sqlmodel import select

from ....infrastructure.persistence.database import get_session
from ....infrastructure.persistence.models import MovieModel, SeriesModel
from ....utils.helpers import title_sort_key
from ...deps import templates
from .helpers import (
    ITEMS_PER_PAGE,
    _best_rating,
    _genre_json_escaped,
    _parse_genres,
    _poster_url,
    _resolution_label,
    _resolution_pixels,
    _title_search_filter,
)

router = APIRouter()


@router.get("/")
async def library_index(
    request: Request,
    type: str = "all",
    genre: Optional[str] = None,
    year: Optional[str] = None,
    q: Optional[str] = None,
    person: Optional[str] = None,
    person_role: Optional[str] = None,
    resolution: Optional[str] = None,
    codec_video: Optional[str] = None,
    codec_audio: Optional[str] = None,
    search_mode: str = "title",
    sort: str = "title",
    order: str = "desc",
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
                movie_stmt = movie_stmt.where(
                    _title_search_filter(MovieModel, q, extended=(search_mode == "extended"))
                )
            if year_int:
                movie_stmt = movie_stmt.where(MovieModel.year == year_int)
            if genre:
                movie_stmt = movie_stmt.where(MovieModel.genres_json.contains(_genre_json_escaped(genre)))
            if person:
                if person_role == "director":
                    movie_stmt = movie_stmt.where(MovieModel.director.contains(person))
                elif person_role == "actor":
                    movie_stmt = movie_stmt.where(MovieModel.cast_json.contains(person))
                else:
                    movie_stmt = movie_stmt.where(
                        MovieModel.director.contains(person)
                        | MovieModel.cast_json.contains(person)
                    )
            if codec_video:
                movie_stmt = movie_stmt.where(MovieModel.codec_video == codec_video)
            if codec_audio:
                movie_stmt = movie_stmt.where(MovieModel.codec_audio == codec_audio)

            movies = session.exec(movie_stmt).all()

            # Filtre resolution cote Python (label converti)
            if resolution:
                movies = [
                    m for m in movies if _resolution_label(m.resolution) == resolution
                ]

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
                        "resolution": m.resolution,
                        "resolution_label": _resolution_label(m.resolution),
                        "codec_video": m.codec_video,
                        "codec_audio": m.codec_audio,
                    }
                )

        # --- Series ---
        # Les filtres techniques (resolution, codec) ne s'appliquent pas aux series
        if (
            type in ("all", "series")
            and not resolution
            and not codec_video
            and not codec_audio
        ):
            series_stmt = select(SeriesModel)
            if q:
                series_stmt = series_stmt.where(
                    _title_search_filter(SeriesModel, q, extended=(search_mode == "extended"))
                )
            if year_int:
                series_stmt = series_stmt.where(SeriesModel.year == year_int)
            if genre:
                series_stmt = series_stmt.where(SeriesModel.genres_json.contains(_genre_json_escaped(genre)))
            if person:
                if person_role == "director":
                    series_stmt = series_stmt.where(
                        SeriesModel.director.contains(person)
                    )
                elif person_role == "actor":
                    series_stmt = series_stmt.where(
                        SeriesModel.cast_json.contains(person)
                    )
                else:
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
                        "resolution": None,
                        "resolution_label": "",
                        "codec_video": None,
                        "codec_audio": None,
                    }
                )

        # --- Tri ---
        descending = order == "desc"
        if sort == "year":
            items.sort(
                key=lambda x: (x["year"] or 0, title_sort_key(x["title"])), reverse=descending
            )
        elif sort == "rating":
            items.sort(
                key=lambda x: (x["rating"] or 0, title_sort_key(x["title"])), reverse=descending
            )
        elif sort == "resolution":
            items.sort(
                key=lambda x: (
                    _resolution_pixels(x.get("resolution")),
                    title_sort_key(x["title"]),
                ),
                reverse=descending,
            )
        elif sort == "codec_video":
            items.sort(
                key=lambda x: (
                    x.get("codec_video") or "",
                    title_sort_key(x["title"]),
                ),
                reverse=descending,
            )
        elif sort == "codec_audio":
            items.sort(
                key=lambda x: (
                    x.get("codec_audio") or "",
                    title_sort_key(x["title"]),
                ),
                reverse=descending,
            )
        else:  # title
            items.sort(key=lambda x: title_sort_key(x["title"]), reverse=descending)

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

        # --- Valeurs distinctes techniques (films uniquement) ---
        raw_resolutions = session.exec(
            select(MovieModel.resolution)
            .where(MovieModel.resolution.is_not(None))
            .distinct()
        ).all()
        # Convertir en labels et deduper
        res_labels: set[str] = set()
        for r in raw_resolutions:
            label = _resolution_label(r)
            if label:
                res_labels.add(label)
        all_resolutions = sorted(
            res_labels,
            key=lambda x: {"4K": 0, "1080p": 1, "720p": 2, "SD": 3}.get(x, 4),
        )

        all_codecs_video = sorted(
            r
            for r in session.exec(
                select(MovieModel.codec_video)
                .where(MovieModel.codec_video.is_not(None))
                .distinct()
            ).all()
            if r
        )

        all_codecs_audio = sorted(
            r
            for r in session.exec(
                select(MovieModel.codec_audio)
                .where(MovieModel.codec_audio.is_not(None))
                .distinct()
            ).all()
            if r
        )

    finally:
        session.close()

    context = {
        "items": page_items,
        "total_items": total_items,
        "page": page,
        "total_pages": total_pages,
        "genres": sorted(all_genres),
        "years": all_years,
        "resolutions": all_resolutions,
        "codecs_video": all_codecs_video,
        "codecs_audio": all_codecs_audio,
        "current_type": type,
        "current_genre": genre,
        "current_year": year_int,
        "current_q": q or "",
        "current_person": person or "",
        "current_person_role": person_role or "",
        "current_resolution": resolution or "",
        "current_codec_video": codec_video or "",
        "current_codec_audio": codec_audio or "",
        "current_search_mode": search_mode,
        "current_sort": sort,
        "current_order": order,
    }

    # Si requete HTMX, retourner filtres + grille (le bloc #library-content)
    if request.headers.get("HX-Request"):
        response = templates.TemplateResponse(request, "library/_content.html", context)
        response.headers["Vary"] = "HX-Request"
        return response

    response = templates.TemplateResponse(request, "library/index.html", context)
    response.headers["Vary"] = "HX-Request"
    return response
