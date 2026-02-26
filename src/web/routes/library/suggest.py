"""
Route de suggestion — "Surprends-moi" pour proposer un film ou série à regarder.

Historique de navigation :
- history : liste ordonnée des items vus ("movie:1,series:3,movie:7")
- pos : position courante dans l'historique (0-indexé)
- Flèche droite : avance (réutilise l'historique ou tire un nouveau)
- Flèche gauche : recule dans l'historique
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


def _build_item(m, item_type: str) -> dict:
    """Construit le dict d'un candidat à partir d'un MovieModel ou SeriesModel."""
    rating = _best_rating(m.vote_average, m.imdb_rating)
    return {
        "id": m.id,
        "type": item_type,
        "title": m.title,
        "year": m.year,
        "genres": _parse_genres(m.genres_json),
        "poster_url": _poster_url(m.poster_path),
        "rating": rating,
        "rating_source": "IMDb" if m.imdb_rating is not None else "TMDB",
        "overview": m.overview or "",
        "duration": _format_duration(m.duration_seconds) if item_type == "movie" else "",
        "watched": m.watched,
        "personal_rating": m.personal_rating,
    }


def _parse_history(history: str) -> list[str]:
    """Parse le paramètre history en liste de clés 'type:id'."""
    return [t.strip() for t in history.split(",") if t.strip() and ":" in t]


def _history_ids(items: list[str]) -> tuple[set[int], set[int]]:
    """Extrait les sets d'IDs films et séries depuis l'historique."""
    movie_ids: set[int] = set()
    series_ids: set[int] = set()
    for token in items:
        kind, val = token.split(":", 1)
        try:
            item_id = int(val)
        except ValueError:
            continue
        if kind == "movie":
            movie_ids.add(item_id)
        elif kind == "series":
            series_ids.add(item_id)
    return movie_ids, series_ids


def _fetch_item(session, key: str) -> dict | None:
    """Charge un item depuis la DB par sa clé 'type:id'."""
    if ":" not in key:
        return None
    kind, val = key.split(":", 1)
    try:
        item_id = int(val)
    except ValueError:
        return None
    if kind == "movie":
        obj = session.get(MovieModel, item_id)
        return _build_item(obj, "movie") if obj else None
    elif kind == "series":
        obj = session.get(SeriesModel, item_id)
        return _build_item(obj, "series") if obj else None
    return None


@router.get("/suggest")
async def suggest(
    request: Request,
    genre: Optional[str] = None,
    max_duration: Optional[str] = None,
    min_rating: Optional[str] = None,
    type: str = "all",
    history: Optional[str] = None,
    pos: Optional[str] = None,
):
    """Page 'Surprends-moi' — suggestion aléatoire avec historique navigable."""
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

    # Parser l'historique et la position
    history_items = _parse_history(history) if history else []
    pos_int: int | None = None
    if pos:
        try:
            pos_int = int(pos)
        except (ValueError, TypeError):
            pass

    session = next(get_session())
    try:
        result = None
        navigating = False

        # --- Navigation dans l'historique existant ---
        if pos_int is not None and 0 <= pos_int < len(history_items):
            result = _fetch_item(session, history_items[pos_int])
            navigating = True

        # --- Construire la liste des candidats (pour tirage ou comptage) ---
        candidates = []

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
            for m in session.exec(movie_stmt).all():
                item = _build_item(m, "movie")
                if min_rating_float and (item["rating"] is None or item["rating"] < min_rating_float):
                    continue
                candidates.append(item)

        if type in ("all", "series"):
            series_stmt = select(SeriesModel).where(_eligible_filter(SeriesModel))
            if genre:
                series_stmt = series_stmt.where(
                    SeriesModel.genres_json.contains(_genre_json_escaped(genre))
                )
            for s in session.exec(series_stmt).all():
                item = _build_item(s, "series")
                if min_rating_float and (item["rating"] is None or item["rating"] < min_rating_float):
                    continue
                candidates.append(item)

        # --- Tirage aléatoire (si pas en navigation) ---
        if not result:
            excluded_movie_ids, excluded_series_ids = _history_ids(history_items)
            filtered = [
                c for c in candidates
                if not (
                    (c["type"] == "movie" and c["id"] in excluded_movie_ids)
                    or (c["type"] == "series" and c["id"] in excluded_series_ids)
                )
            ]
            pool = filtered if filtered else candidates
            result = random.choice(pool) if pool else None

        # --- Genres distincts pour le filtre ---
        all_genres: set[str] = set()
        for gj in session.exec(
            select(MovieModel.genres_json).where(MovieModel.genres_json.is_not(None))
        ).all():
            all_genres.update(_parse_genres(gj))
        for gj in session.exec(
            select(SeriesModel.genres_json).where(SeriesModel.genres_json.is_not(None))
        ).all():
            all_genres.update(_parse_genres(gj))

    finally:
        session.close()

    # --- Mettre à jour l'historique ---
    if result and not navigating:
        current_key = f"{result['type']}:{result['id']}"
        # Tronquer l'historique après la position courante avant d'ajouter
        # (évite un historique incohérent si on tire un nouveau depuis le milieu)
        if pos_int is not None and 0 <= pos_int < len(history_items) - 1:
            history_items = history_items[: pos_int + 1]
        history_items.append(current_key)
        current_pos = len(history_items) - 1
    elif navigating and pos_int is not None:
        current_pos = pos_int
    else:
        current_pos = 0

    history_str = ",".join(history_items)
    has_forward_history = current_pos < len(history_items) - 1

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
            "history": history_str,
            "pos": current_pos,
            "can_go_back": current_pos > 0,
            "can_go_forward": True,
            "has_forward_history": has_forward_history,
        },
    )
