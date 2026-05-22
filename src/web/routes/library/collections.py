"""
Route des collections/sagas — affiche les films groupés par collection TMDB
ou par collection locale (P5 courts-métrages).
"""

import math
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import select

from ....core.entities.local_collection import LocalCollection
from ....infrastructure.persistence.database import get_session
from ....infrastructure.persistence.models import LocalCollectionModel, MovieModel
from ....infrastructure.persistence.repositories.local_collection_repository import (
    SQLModelLocalCollectionRepository,
)
from ....services.short_reclassifier import ShortReclassifier
from ....utils.helpers import title_sort_key
from ...deps import templates
from .helpers import _best_rating, _parse_genres, _poster_url

COLLECTIONS_PER_PAGE = 24

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}

router = APIRouter()


class CollectionAssignItem(BaseModel):
    """Élément à rattacher à une collection locale."""

    type: str  # "movie" | "series"
    id: int


@router.get("/collections")
async def collections_index(
    request: Request,
    q: Optional[str] = None,
    sort: str = "name",
    page: int = 1,
):
    """Page des collections/sagas avec leurs films.

    Liste fusionnée :
    * Collections TMDB (``MovieModel.collection_id > 0``)
    * Collections locales P4 (``LocalCollectionModel`` ayant au moins un film)
    """
    session = next(get_session())
    try:
        collections = _collect_tmdb_collections(session) + _collect_local_collections(
            session
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


@router.get("/collections/local/{collection_id}")
async def collection_detail_local(request: Request, collection_id: int):
    """Détail d'une collection locale (P4) avec tous ses films."""
    session = next(get_session())
    try:
        coll = session.get(LocalCollectionModel, collection_id)
        if coll is None:
            return templates.TemplateResponse(
                request,
                "library/not_found.html",
                {"entity_type": "collection", "entity_id": collection_id},
                status_code=404,
            )

        movies_models = session.exec(
            select(MovieModel)
            .where(MovieModel.local_collection_id == collection_id)
            .order_by(MovieModel.year)
        ).all()

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
            "collection_name": coll.name,
            "collection_id": collection_id,
            "items": items,
            "total_items": len(items),
            "total_pages": 1,
            "page": 1,
        },
    )


@router.post("/collection-batch")
async def collection_batch(request: Request):
    """Rattache des films sélectionnés à une collection locale (find-or-create)
    et déplace les symlinks des courts vers ``Films/Courts/{collection}/``.

    Réservé à la machine maître (modification DB + filesystem). Les items
    ``series`` sont ignorés : seuls les films portent ``local_collection_id``.
    """
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCAL_HOSTS:
        return JSONResponse(
            {"error": "Action autorisée uniquement depuis la machine maître."},
            status_code=403,
        )

    body = await request.json()
    collection_name = (body.get("collection_name") or "").strip()
    if not collection_name:
        return JSONResponse({"error": "Nom de collection requis."}, status_code=400)

    items = [CollectionAssignItem(**it) for it in body.get("items", [])]
    movie_ids = [it.id for it in items if it.type == "movie"]
    if not movie_ids:
        return JSONResponse(
            {"assigned": 0, "moved": 0, "errors": [], "collection_id": None}
        )

    settings = request.app.state.container.config()
    session = next(get_session())
    try:
        repo = SQLModelLocalCollectionRepository(session)
        collection = repo.get_by_name(collection_name) or repo.save(
            LocalCollection(name=collection_name)
        )

        assigned = 0
        for movie_id in movie_ids:
            movie = session.get(MovieModel, movie_id)
            if movie is None:
                continue
            movie.local_collection_id = collection.id
            session.add(movie)
            assigned += 1
        session.commit()

        moved = 0
        errors: list[str] = []
        reclassifier = ShortReclassifier(
            session,
            settings.video_dir,
            settings.short_film_duration_threshold_seconds,
        )
        target_ids = set(movie_ids)
        for candidate in reclassifier.find_candidates():
            if candidate.model.id not in target_ids:
                continue
            result = reclassifier.apply(candidate)
            if result.moved:
                moved += 1
            elif result.error:
                errors.append(result.error)
    finally:
        session.close()

    return JSONResponse(
        {
            "assigned": assigned,
            "moved": moved,
            "errors": errors,
            "collection_id": collection.id,
        }
    )


def _collect_tmdb_collections(session) -> list[dict]:
    """Liste les collections TMDB (collection_id > 0) avec poster + plage d'années."""
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

    collections: list[dict] = []
    for collection_id, collection_name, movie_count in rows:
        first_movie = session.exec(
            select(MovieModel)
            .where(MovieModel.collection_id == collection_id)
            .order_by(MovieModel.year)
            .limit(1)
        ).first()
        entry = {
            "id": collection_id,
            "name": collection_name or "Collection inconnue",
            "count": movie_count,
            "type": "tmdb",
            "url": f"/library/collections/{collection_id}",
            "poster_url": _poster_url(first_movie.poster_path) if first_movie else None,
            "year_range": None,
        }
        if first_movie:
            last_movie = session.exec(
                select(MovieModel)
                .where(MovieModel.collection_id == collection_id)
                .order_by(MovieModel.year.desc())
                .limit(1)
            ).first()
            if first_movie.year and last_movie and last_movie.year:
                if first_movie.year == last_movie.year:
                    entry["year_range"] = str(first_movie.year)
                else:
                    entry["year_range"] = f"{first_movie.year}–{last_movie.year}"
        collections.append(entry)
    return collections


def _collect_local_collections(session) -> list[dict]:
    """Liste les collections locales ayant au moins un film associé (P4)."""
    stmt = (
        select(
            LocalCollectionModel,
            func.count(MovieModel.id).label("movie_count"),
        )
        .join(MovieModel, MovieModel.local_collection_id == LocalCollectionModel.id)
        .group_by(LocalCollectionModel.id)
    )
    rows = session.exec(stmt).all()

    collections: list[dict] = []
    for coll, movie_count in rows:
        if not movie_count:
            continue
        first_movie = session.exec(
            select(MovieModel)
            .where(MovieModel.local_collection_id == coll.id)
            .order_by(MovieModel.year)
            .limit(1)
        ).first()
        entry = {
            "id": coll.id,
            "name": coll.name,
            "count": int(movie_count),
            "type": "local",
            "url": f"/library/collections/local/{coll.id}",
            "poster_url": _poster_url(first_movie.poster_path) if first_movie else None,
            "year_range": None,
        }
        if first_movie:
            last_movie = session.exec(
                select(MovieModel)
                .where(MovieModel.local_collection_id == coll.id)
                .order_by(MovieModel.year.desc())
                .limit(1)
            ).first()
            if first_movie.year and last_movie and last_movie.year:
                if first_movie.year == last_movie.year:
                    entry["year_range"] = str(first_movie.year)
                else:
                    entry["year_range"] = f"{first_movie.year}–{last_movie.year}"
        collections.append(entry)
    return collections
