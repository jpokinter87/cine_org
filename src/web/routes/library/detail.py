"""
Routes de détail — fiches film et série.
"""

import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from sqlmodel import select

from ....infrastructure.persistence.database import get_session
from ....infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    MoviePartModel,
    SeriesModel,
    VideoFileModel,
)
from ....services.completeness.quality_profile import build_quality_targets
from ....services.completeness.recompute import recompute_completeness_for_series
from ...deps import templates
from .helpers import (
    _find_movie_file,
    _format_duration,
    _get_storage_genre_info,
    _parse_genres,
    _poster_url,
    _resolution_label,
)

router = APIRouter()


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

        # Charger les parties supplementaires (>= Partie 2)
        parts = session.exec(
            select(MoviePartModel)
            .where(MoviePartModel.movie_id == movie_id)
            .order_by(MoviePartModel.part_number)
        ).all()

    finally:
        session.close()

    # Si pas de file_path en DB, chercher dans video/Films/ par titre
    file_info = None
    if not movie.file_path and not video_file:
        file_info = _find_movie_file(movie.title, movie.year, movie.original_title)
        # Si un VideoFile a ete trouve, l'utiliser pour les infos techniques
        if file_info and file_info.get("video_file"):
            video_file = file_info.pop("video_file")

    # Metadonnees techniques pour les cartouches
    resolution_label = _resolution_label(movie.resolution)
    languages = movie.languages if hasattr(movie, "languages") else []

    # Genre de rangement (prioritaire selon hiérarchie + dossier réel)
    storage_genre, storage_folder = _get_storage_genre_info(genres)

    # Fiche fantôme : ni file_path en base, ni fichier retrouvé sur disque.
    is_phantom = not movie.file_path and video_file is None and file_info is None

    # Partage Jellyfin : ce film est-il le partage actif ?
    share_is_active = False
    if hasattr(request.app.state, "container"):
        active_share = request.app.state.container.share_service().get_active_share()
        share_is_active = bool(
            active_share
            and active_share.media_type == "movie"
            and active_share.media_id == movie.id
        )

    return templates.TemplateResponse(
        request,
        "library/movie_detail.html",
        {
            "movie": movie,
            "movie_id": movie.id,
            "parts": parts,
            "watched": movie.watched,
            "personal_rating": movie.personal_rating,
            "genres": genres,
            "poster_url": poster_url,
            "duration": duration,
            "video_file": video_file,
            "file_info": file_info,
            "resolution_label": resolution_label,
            "languages": languages,
            "storage_genre": storage_genre,
            "storage_folder": storage_folder,
            "is_phantom": is_phantom,
            "share_is_active": share_is_active,
        },
    )


@router.post("/movies/{movie_id}/toggle-watched")
async def toggle_watched(request: Request, movie_id: int):
    """Toggle l'etat watched d'un film et retourne le fragment HTML mis a jour."""
    session = next(get_session())
    try:
        movie = session.get(MovieModel, movie_id)
        if not movie:
            return HTMLResponse("Film non trouvé", status_code=404)
        movie.watched = not movie.watched
        session.add(movie)
        session.commit()
        session.refresh(movie)
        watched = movie.watched
    finally:
        session.close()
    return templates.TemplateResponse(
        request,
        "library/_watched_btn.html",
        {"movie_id": movie_id, "watched": watched},
    )


@router.post("/movies/{movie_id}/rate")
async def rate_movie(request: Request, movie_id: int, rating: int = Form(...)):
    """Met a jour la note personnelle d'un film (toggle off si meme note)."""
    session = next(get_session())
    try:
        movie = session.get(MovieModel, movie_id)
        if not movie:
            return HTMLResponse("Film non trouvé", status_code=404)
        # Toggle off si meme note
        if movie.personal_rating == rating:
            movie.personal_rating = None
        else:
            movie.personal_rating = max(1, min(5, rating))
        session.add(movie)
        session.commit()
        session.refresh(movie)
        current_rating = movie.personal_rating
    finally:
        session.close()
    return templates.TemplateResponse(
        request,
        "library/_star_rating.html",
        {"movie_id": movie_id, "personal_rating": current_rating},
    )


def _quality_targets(episodes, detail: dict | None) -> list[dict]:
    """Formate pour l'affichage les qualités à rechercher (résolution lisible)."""
    targets = []
    for profile in build_quality_targets(episodes, detail):
        parts = []
        if profile.resolution:
            parts.append(_resolution_label(profile.resolution))
        if profile.video_codec:
            parts.append(profile.video_codec)
        if profile.audio_codec:
            parts.append(profile.audio_codec)
        if profile.languages:
            # Français en tête : c'est la langue de référence de la vidéothèque.
            ordered = sorted(
                profile.languages, key=lambda code: (code.lower() != "fr", code)
            )
            parts.append(" + ".join(code.upper() for code in ordered))
        targets.append(
            {
                "scope": profile.scope_label,
                "label": " · ".join(parts),
                "sample_size": profile.sample_size,
                "mixed": profile.mixed,
            }
        )
    return targets


def _parse_completeness_detail(series: SeriesModel) -> dict | None:
    """Décode le détail de complétude persisté (None si absent ou illisible)."""
    if not series.completeness_missing_json:
        return None
    try:
        return json.loads(series.completeness_missing_json)
    except (ValueError, TypeError):
        return None


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

        # Fiche fantôme : aucun épisode ne porte de fichier réel. Permet
        # d'offrir la suppression d'un doublon laissé par un mauvais matching.
        is_phantom = not any(ep.file_path for ep in episodes)

        # Agreger les metadonnees techniques des episodes
        ep_resolutions: set[str] = set()
        ep_codecs_video: set[str] = set()
        ep_codecs_audio: set[str] = set()
        ep_languages: set[str] = set()
        for ep in episodes:
            if ep.resolution:
                ep_resolutions.add(_resolution_label(ep.resolution))
            if ep.codec_video:
                ep_codecs_video.add(ep.codec_video)
            if ep.codec_audio:
                ep_codecs_audio.add(ep.codec_audio)
            for lang in ep.languages:
                ep_languages.add(lang)

        # Détail de complétude (phase série-completeness) pour la fiche série,
        # et qualités à rechercher qui en découlent (session encore ouverte).
        completeness_detail = _parse_completeness_detail(series)
        quality_targets = _quality_targets(episodes, completeness_detail)

    finally:
        session.close()

    # Partage Jellyfin : cette série est-elle le partage actif ?
    share_is_active = False
    if hasattr(request.app.state, "container"):
        active_share = request.app.state.container.share_service().get_active_share()
        share_is_active = bool(
            active_share
            and active_share.media_type == "series"
            and active_share.media_id == series.id
        )

    return templates.TemplateResponse(
        request,
        "library/series_detail.html",
        {
            "series": series,
            "series_id": series.id,
            "completeness_status": series.completeness_status,
            "completeness_detail": completeness_detail,
            "quality_targets": quality_targets,
            "watched": series.watched,
            "personal_rating": series.personal_rating,
            "genres": genres,
            "poster_url": poster_url,
            "seasons": dict(sorted(seasons.items())),
            "total_episodes": total_episodes,
            "ep_resolutions": sorted(ep_resolutions),
            "ep_codecs_video": sorted(ep_codecs_video),
            "ep_codecs_audio": sorted(ep_codecs_audio),
            "ep_languages": sorted(ep_languages),
            "first_episode": episodes[0] if episodes else None,
            "is_phantom": is_phantom,
            "share_is_active": share_is_active,
        },
    )


@router.post("/series/{series_id}/toggle-watched")
async def toggle_series_watched(request: Request, series_id: int):
    """Toggle l'etat watched d'une serie et retourne le fragment HTML mis a jour."""
    session = next(get_session())
    try:
        series = session.get(SeriesModel, series_id)
        if not series:
            return HTMLResponse("Série non trouvée", status_code=404)
        series.watched = not series.watched
        session.add(series)
        session.commit()
        session.refresh(series)
        watched = series.watched
    finally:
        session.close()
    return templates.TemplateResponse(
        request,
        "library/_watched_btn_series.html",
        {"series_id": series_id, "watched": watched},
    )


@router.post("/series/{series_id}/completeness/recheck")
async def recheck_series_completeness(request: Request, series_id: int):
    """Relance la vérification TVDB de complétude et rend le cartouche à jour.

    Le verdict persisté devient périmé dès que la série gagne des épisodes hors
    transfert (ré-association, import manuel) : ce endpoint le recalcule pour
    cette seule série, sans attendre la vérification globale de maintenance.
    """
    session = next(get_session())
    try:
        series = session.get(SeriesModel, series_id)
        if not series:
            return HTMLResponse("Série non trouvée", status_code=404)

        tvdb_client = request.app.state.container.tvdb_client()
        recomputed = await recompute_completeness_for_series(
            session, tvdb_client, [series_id]
        )
        session.refresh(series)
        completeness_status = series.completeness_status
        completeness_detail = _parse_completeness_detail(series)
        episodes = session.exec(
            select(EpisodeModel).where(EpisodeModel.series_id == series_id)
        ).all()
        quality_targets = _quality_targets(episodes, completeness_detail)
    finally:
        session.close()

    return templates.TemplateResponse(
        request,
        "library/_completeness_block.html",
        {
            "series_id": series_id,
            "completeness_status": completeness_status,
            "completeness_detail": completeness_detail,
            "quality_targets": quality_targets,
            "recheck_error": recomputed == 0,
            "badge_oob": True,
        },
    )


@router.post("/series/{series_id}/rate")
async def rate_series(request: Request, series_id: int, rating: int = Form(...)):
    """Met a jour la note personnelle d'une serie (toggle off si meme note)."""
    session = next(get_session())
    try:
        series = session.get(SeriesModel, series_id)
        if not series:
            return HTMLResponse("Série non trouvée", status_code=404)
        if series.personal_rating == rating:
            series.personal_rating = None
        else:
            series.personal_rating = max(1, min(5, rating))
        session.add(series)
        session.commit()
        session.refresh(series)
        current_rating = series.personal_rating
    finally:
        session.close()
    return templates.TemplateResponse(
        request,
        "library/_star_rating_series.html",
        {"series_id": series_id, "personal_rating": current_rating},
    )
