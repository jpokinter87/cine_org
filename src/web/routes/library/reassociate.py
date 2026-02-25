"""
Routes de ré-association TMDB — correction manuelle des associations films et séries.
"""

import json
from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlmodel import select

from ....infrastructure.persistence.database import get_session
from ....infrastructure.persistence.models import (
    ConfirmedAssociationModel,
    MovieModel,
    SeriesModel,
)
from ...deps import templates
from ..quality import _remove_from_cache as _remove_from_quality_cache
from .helpers import (
    _duration_indicator,
    _find_movie_file,
    _format_duration,
    _get_file_duration,
    _get_local_series_counts,
    _poster_url,
    _series_indicator,
)

router = APIRouter()


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

        # Marquer comme confirmé (exclure des futurs scans qualité)
        existing = session.exec(
            select(ConfirmedAssociationModel).where(
                ConfirmedAssociationModel.entity_type == "movie",
                ConfirmedAssociationModel.entity_id == movie_id,
            )
        ).first()
        if not existing:
            session.add(ConfirmedAssociationModel(
                entity_type="movie", entity_id=movie_id,
            ))

        session.add(movie)
        session.commit()
    finally:
        session.close()

    _remove_from_quality_cache("movie", movie_id)

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
            from ....adapters.api.retry import request_with_retry

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
        candidates.sort(key=lambda c: abs((c["nb_episodes"] or 9999) - local_episodes))

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

        # Marquer comme confirmé (exclure des futurs scans qualité)
        existing = session.exec(
            select(ConfirmedAssociationModel).where(
                ConfirmedAssociationModel.entity_type == "series",
                ConfirmedAssociationModel.entity_id == series_id,
            )
        ).first()
        if not existing:
            session.add(ConfirmedAssociationModel(
                entity_type="series", entity_id=series_id,
            ))

        session.add(series)
        session.commit()
    finally:
        session.close()

    _remove_from_quality_cache("series", series_id)

    response = Response(status_code=200)
    response.headers["HX-Redirect"] = f"/library/series/{series_id}"
    return response
