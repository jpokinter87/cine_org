"""
Routes de détail — fiches film et série.
"""

from fastapi import APIRouter, Request
from sqlmodel import select

from ....infrastructure.persistence.database import get_session
from ....infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    SeriesModel,
    VideoFileModel,
)
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
            "resolution_label": resolution_label,
            "languages": languages,
            "storage_genre": storage_genre,
            "storage_folder": storage_folder,
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
            "ep_resolutions": sorted(ep_resolutions),
            "ep_codecs_video": sorted(ep_codecs_video),
            "ep_codecs_audio": sorted(ep_codecs_audio),
            "ep_languages": sorted(ep_languages),
            "first_episode": episodes[0] if episodes else None,
        },
    )
