"""
Route de navigation de la bibliothèque — listing avec filtres et pagination.
"""

import math
from datetime import datetime
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
    _effective_poster_url,
    _poster_url,
    _resolution_label,
    _resolution_pixels,
    _title_search_filter,
)

# Normalisation des genres anglais/composés vers le français
_GENRE_NORMALIZE: dict[str, str | None] = {
    "Drama": "Drame",
    "Family": "Familial",
    "Fantasy": "Fantastique",
    "Mystery": "Mystère",
    "Action & Adventure": "Action",
    "War & Politics": "Guerre",
    "Science-Fiction & Fantastique": "Science-Fiction",
    "Kids": "Animation",
    "Soap": None,
    "Talk": None,
    "Sport": None,
}

# Table inverse : français → liste de variantes anglaises
_GENRE_VARIANTS: dict[str, list[str]] = {}
for _en, _fr in _GENRE_NORMALIZE.items():
    if _fr is not None:
        _GENRE_VARIANTS.setdefault(_fr, []).append(_en)

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
    language: Optional[str] = None,
    no_file: Optional[str] = None,
    no_poster: Optional[str] = None,
    incomplete_series: Optional[str] = None,
    missing_episodes: Optional[str] = None,
    missing_seasons: Optional[str] = None,
    search_mode: str = "title",
    unwatched: Optional[str] = None,
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
        # Filtres propres aux séries : dès qu'un est actif, aucun film ne doit
        # apparaître (sinon « Tous » les laisse passer).
        series_only_filter = (
            incomplete_series == "1"
            or missing_episodes == "1"
            or missing_seasons == "1"
        )
        items = []

        # --- Films ---
        # « Séries incomplètes » est un filtre propre aux séries : quand il est
        # actif, aucun film ne doit apparaître (sinon « Tous » les laisse passer).
        if type in ("all", "movie") and not series_only_filter:
            movie_stmt = select(MovieModel)
            if q:
                movie_stmt = movie_stmt.where(
                    _title_search_filter(
                        MovieModel, q, extended=(search_mode == "extended")
                    )
                )
            if year_int:
                movie_stmt = movie_stmt.where(MovieModel.year == year_int)
            if genre:
                from sqlalchemy import or_ as sa_or

                genre_conditions = [
                    MovieModel.genres_json.contains(_genre_json_escaped(genre))
                ]
                for variant in _GENRE_VARIANTS.get(genre, []):
                    genre_conditions.append(
                        MovieModel.genres_json.contains(_genre_json_escaped(variant))
                    )
                movie_stmt = movie_stmt.where(sa_or(*genre_conditions))
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
            if language:
                movie_stmt = movie_stmt.where(
                    MovieModel.languages_json.contains(f'"{language}"')
                )
            if no_file == "1":
                movie_stmt = movie_stmt.where(MovieModel.file_path.is_(None))
            if no_poster == "1":
                movie_stmt = movie_stmt.where(MovieModel.poster_path.is_(None))
            if unwatched == "1":
                movie_stmt = movie_stmt.where(MovieModel.watched == False)  # noqa: E712

            movies = session.exec(movie_stmt).all()

            # Filtre resolution cote Python (label converti)
            if resolution:
                movies = [
                    m for m in movies if _resolution_label(m.resolution) == resolution
                ]

            for m in movies:
                rating = _best_rating(m.vote_average, m.imdb_rating)
                # Label langue compact pour badge grille
                langs = _parse_genres(m.languages_json)  # réutilise le parser JSON
                if len(langs) > 1:
                    lang_label = "Multi"
                elif langs:
                    lang_label = langs[0].upper()
                else:
                    lang_label = ""
                items.append(
                    {
                        "id": m.id,
                        "type": "movie",
                        "title": m.title,
                        "year": m.year,
                        "genres": _parse_genres(m.genres_json),
                        "poster_url": _effective_poster_url(
                            m.poster_override, m.poster_path
                        ),
                        "rating": rating,
                        "rating_source": "IMDb"
                        if m.imdb_rating is not None
                        else "TMDB",
                        "resolution": m.resolution,
                        "resolution_label": _resolution_label(m.resolution),
                        "codec_video": m.codec_video,
                        "codec_audio": m.codec_audio,
                        "language_label": lang_label,
                        "watched": m.watched,
                        "created_at": m.created_at,
                        "collection_name": m.collection_name,
                        "collection_id": m.collection_id,
                    }
                )

        # --- Series ---
        # Les filtres techniques (resolution, codec, langue) ne s'appliquent pas aux series
        if (
            type in ("all", "series")
            and not resolution
            and not codec_video
            and not codec_audio
            and not language
            and not no_file
        ):
            series_stmt = select(SeriesModel)
            if q:
                series_stmt = series_stmt.where(
                    _title_search_filter(
                        SeriesModel, q, extended=(search_mode == "extended")
                    )
                )
            if year_int:
                series_stmt = series_stmt.where(SeriesModel.year == year_int)
            if genre:
                from sqlalchemy import or_ as sa_or

                genre_conditions_s = [
                    SeriesModel.genres_json.contains(_genre_json_escaped(genre))
                ]
                for variant in _GENRE_VARIANTS.get(genre, []):
                    genre_conditions_s.append(
                        SeriesModel.genres_json.contains(_genre_json_escaped(variant))
                    )
                series_stmt = series_stmt.where(sa_or(*genre_conditions_s))
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

            if no_poster == "1":
                series_stmt = series_stmt.where(SeriesModel.poster_path.is_(None))
            if unwatched == "1":
                series_stmt = series_stmt.where(SeriesModel.watched == False)  # noqa: E712
            if incomplete_series == "1":
                series_stmt = series_stmt.where(
                    SeriesModel.completeness_status == "incomplete"
                )
            if missing_episodes == "1" or missing_seasons == "1":
                from sqlalchemy import or_ as sa_or

                granular_conditions = []
                if missing_episodes == "1":
                    granular_conditions.append(
                        SeriesModel.has_missing_episodes == True  # noqa: E712
                    )
                if missing_seasons == "1":
                    granular_conditions.append(
                        SeriesModel.has_missing_seasons == True  # noqa: E712
                    )
                series_stmt = series_stmt.where(sa_or(*granular_conditions))

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
                        "poster_url": _effective_poster_url(
                            s.poster_override, s.poster_path
                        ),
                        "rating": rating,
                        "rating_source": "IMDb"
                        if s.imdb_rating is not None
                        else "TMDB",
                        "resolution": None,
                        "resolution_label": "",
                        "codec_video": None,
                        "codec_audio": None,
                        "watched": s.watched,
                        "created_at": s.created_at,
                        "completeness_status": s.completeness_status,
                    }
                )

        # --- Tri ---
        descending = order == "desc"
        if sort == "year":
            items.sort(
                key=lambda x: (x["year"] or 0, title_sort_key(x["title"])),
                reverse=descending,
            )
        elif sort == "rating":
            items.sort(
                key=lambda x: (x["rating"] or 0, title_sort_key(x["title"])),
                reverse=descending,
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
        elif sort == "created_at":
            items.sort(
                key=lambda x: (
                    x.get("created_at") or datetime.min,
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

        # --- Genres distincts pour le filtre (normalisés EN→FR) ---
        raw_genres: set[str] = set()
        all_movie_genres = session.exec(
            select(MovieModel.genres_json).where(MovieModel.genres_json.is_not(None))
        ).all()
        for gj in all_movie_genres:
            raw_genres.update(_parse_genres(gj))
        all_series_genres = session.exec(
            select(SeriesModel.genres_json).where(SeriesModel.genres_json.is_not(None))
        ).all()
        for gj in all_series_genres:
            raw_genres.update(_parse_genres(gj))

        # Normaliser : remplacer les variantes anglaises par le français
        all_genres: set[str] = set()
        for g in raw_genres:
            if g in _GENRE_NORMALIZE:
                normalized = _GENRE_NORMALIZE[g]
                if normalized is not None:
                    all_genres.add(normalized)
            else:
                all_genres.add(g)

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

        # --- Langues distinctes pour le filtre ---
        import json as _json

        raw_langs: set[str] = set()
        all_movie_langs = session.exec(
            select(MovieModel.languages_json).where(
                MovieModel.languages_json.is_not(None)
            )
        ).all()
        for lj in all_movie_langs:
            try:
                raw_langs.update(_json.loads(lj))
            except (ValueError, TypeError):
                pass
        all_languages = sorted(raw_langs)

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
        "languages": all_languages,
        "current_type": type,
        "current_genre": genre,
        "current_year": year_int,
        "current_q": q or "",
        "current_person": person or "",
        "current_person_role": person_role or "",
        "current_resolution": resolution or "",
        "current_codec_video": codec_video or "",
        "current_codec_audio": codec_audio or "",
        "current_language": language or "",
        "current_no_file": no_file == "1",
        "current_no_poster": no_poster == "1",
        "current_incomplete_series": incomplete_series == "1",
        "current_missing_episodes": missing_episodes == "1",
        "current_missing_seasons": missing_seasons == "1",
        "current_search_mode": search_mode,
        "current_unwatched": unwatched == "1",
        "current_sort": sort,
        "current_order": order,
    }

    # Vérifier si l'utilisateur est sur la machine maître (pour bouton suppression)
    client_host = request.client.host if request.client else ""
    context["is_local"] = client_host in {"127.0.0.1", "::1", "localhost"}

    # Si requete HTMX, retourner filtres + grille (le bloc #library-content)
    if request.headers.get("HX-Request"):
        response = templates.TemplateResponse(request, "library/_content.html", context)
        response.headers["Vary"] = "HX-Request"
        return response

    response = templates.TemplateResponse(request, "library/index.html", context)
    response.headers["Vary"] = "HX-Request"
    return response
