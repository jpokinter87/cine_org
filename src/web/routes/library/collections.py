"""
Route des collections/sagas — affiche les films groupés par collection TMDB.
"""

import math
from typing import Optional

from fastapi import APIRouter, Request
from sqlalchemy import func
from sqlmodel import select

from ....infrastructure.persistence.database import get_session
from ....infrastructure.persistence.models import MovieModel
from ....utils.helpers import title_sort_key
from ...deps import templates
from .helpers import _best_rating, _parse_genres, _poster_url

COLLECTIONS_PER_PAGE = 24

router = APIRouter()


@router.get("/collections")
async def collections_index(
    request: Request,
    q: Optional[str] = None,
    sort: str = "name",
    page: int = 1,
):
    """Page des collections/sagas avec leurs films."""
    session = next(get_session())
    try:
        # Récupérer toutes les collections distinctes (collection_id > 0)
        stmt = (
            select(
                MovieModel.collection_id,
                MovieModel.collection_name,
                func.count(MovieModel.id).label("movie_count"),
            )
            .where(MovieModel.collection_id > 0)
            .group_by(MovieModel.collection_id, MovieModel.collection_name)
        )

        rows = session.exec(stmt).all()

        collections = []
        for collection_id, collection_name, movie_count in rows:
            # Récupérer le premier film de la collection pour le poster
            first_movie = session.exec(
                select(MovieModel)
                .where(MovieModel.collection_id == collection_id)
                .order_by(MovieModel.year)
                .limit(1)
            ).first()

            collections.append(
                {
                    "id": collection_id,
                    "name": collection_name or "Collection inconnue",
                    "count": movie_count,
                    "poster_url": _poster_url(first_movie.poster_path)
                    if first_movie
                    else None,
                    "year_range": None,  # rempli ci-dessous
                }
            )

            # Plage d'années
            if first_movie:
                last_movie = session.exec(
                    select(MovieModel)
                    .where(MovieModel.collection_id == collection_id)
                    .order_by(MovieModel.year.desc())
                    .limit(1)
                ).first()
                if first_movie.year and last_movie and last_movie.year:
                    if first_movie.year == last_movie.year:
                        collections[-1]["year_range"] = str(first_movie.year)
                    else:
                        collections[-1]["year_range"] = (
                            f"{first_movie.year}–{last_movie.year}"
                        )

        # Filtre recherche
        if q:
            q_lower = q.lower()
            collections = [c for c in collections if q_lower in c["name"].lower()]

        # Tri
        total_collections = len(collections)
        if sort == "count":
            collections.sort(key=lambda c: (-c["count"], title_sort_key(c["name"])))
        else:  # name
            collections.sort(key=lambda c: title_sort_key(c["name"]))

        # Pagination
        total_pages = max(1, math.ceil(total_collections / COLLECTIONS_PER_PAGE))
        page = max(1, min(page, total_pages))
        start = (page - 1) * COLLECTIONS_PER_PAGE
        page_collections = collections[start : start + COLLECTIONS_PER_PAGE]

    finally:
        session.close()

    context = {
        "collections": page_collections,
        "total_collections": total_collections,
        "page": page,
        "total_pages": total_pages,
        "current_q": q or "",
        "current_sort": sort,
    }

    if request.headers.get("HX-Request"):
        response = templates.TemplateResponse(
            request, "library/collections/_content.html", context
        )
        response.headers["Vary"] = "HX-Request"
        return response

    response = templates.TemplateResponse(
        request, "library/collections/index.html", context
    )
    response.headers["Vary"] = "HX-Request"
    return response


@router.get("/collections/{collection_id}")
async def collection_detail(request: Request, collection_id: int):
    """Détail d'une collection avec tous ses films."""
    session = next(get_session())
    try:
        movies_models = session.exec(
            select(MovieModel)
            .where(MovieModel.collection_id == collection_id)
            .order_by(MovieModel.year)
        ).all()

        if not movies_models:
            return templates.TemplateResponse(
                request,
                "library/not_found.html",
                {"entity_type": "collection", "entity_id": collection_id},
                status_code=404,
            )

        collection_name = movies_models[0].collection_name or "Collection inconnue"

        items = []
        for m in movies_models:
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
                    "rating_source": "IMDb" if m.imdb_rating is not None else "TMDB",
                    "watched": m.watched,
                }
            )

    finally:
        session.close()

    return templates.TemplateResponse(
        request,
        "library/collections/detail.html",
        {
            "collection_name": collection_name,
            "collection_id": collection_id,
            "items": items,
            "total_items": len(items),
            "total_pages": 1,
            "page": 1,
        },
    )
