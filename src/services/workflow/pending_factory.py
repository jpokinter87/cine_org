"""
Factory pour la création de PendingValidation.

Module partagé entre le CLI (matching_step.py) et le web (workflow.py)
pour éviter la duplication du code de matching API + scoring.

Les helpers de matching/scoring/filtrage sont définis dans
``src/services/api_matching.py`` (partagés avec le package migration).
Ce module les réexporte pour préserver l'API historique.
"""

from typing import Optional

from src.core.entities.video import PendingValidation, VideoFile
from src.core.value_objects.parsed_info import MediaType
from src.services.api_matching import (
    _lookup_override_count,
    filter_by_episode_count,
    search_and_score_movie as _search_and_score_movie_impl,
    search_and_score_series as _search_and_score_series_impl,
)

__all__ = [
    "create_pending_validation",
    "filter_by_episode_count",
    "_lookup_override_count",
]


async def create_pending_validation(
    scan_result,
    matcher,
    tmdb_client,
    tvdb_client,
    max_episode_in_batch: Optional[int] = None,
    series_cache: Optional[dict[tuple[str, Optional[int]], list]] = None,
    session=None,
) -> tuple[VideoFile, PendingValidation]:
    """
    Crée un VideoFile et PendingValidation à partir d'un résultat de scan.

    Effectue la recherche API (TMDB/TVDB), le scoring, l'enrichissement
    durée (top 3 films) et le filtrage par nombre d'épisodes (séries).

    Args:
        scan_result: Résultat de scan contenant video_file, parsed_info, media_info
        matcher: Service de scoring (MatcherService)
        tmdb_client: Client TMDB (films)
        tvdb_client: Client TVDB (séries)
        max_episode_in_batch: Numéro max d'épisode dans le batch (CLI uniquement)
        series_cache: Cache mémoire partagé entre appels pour éviter les
            recherches API redondantes sur le même titre de série.
            Clé = (titre_lower, année), valeur = candidats scorés.

    Returns:
        Tuple (VideoFile, PendingValidation)
    """
    video_file = VideoFile(
        path=scan_result.video_file.path,
        filename=scan_result.video_file.filename,
        media_info=scan_result.media_info,
    )

    title = scan_result.parsed_info.title
    year = scan_result.parsed_info.year
    candidates = []

    if scan_result.detected_type == MediaType.MOVIE:
        candidates = await _search_and_score_movie_impl(
            title, year, scan_result.media_info, matcher, tmdb_client
        )
    else:
        candidates = await _search_and_score_series_impl(
            title, year, matcher, tvdb_client, series_cache
        )

        # Filtrer les candidats incompatibles par nombre d'épisodes
        season = scan_result.parsed_info.season
        episode = scan_result.parsed_info.episode
        if candidates and season is not None and episode is not None:
            from loguru import logger

            filtered = await filter_by_episode_count(
                tvdb_client, candidates, season, episode, session=session
            )
            if filtered:
                candidates = filtered
            else:
                logger.warning(
                    "Tous les candidats éliminés par episode count pour "
                    f"{scan_result.video_file.filename}, conservation des originaux"
                )

    # Convertir en dict pour stockage
    candidates_data = [
        {
            "id": c.id,
            "title": c.title,
            "year": c.year,
            "score": c.score,
            "source": c.source,
        }
        for c in candidates
    ]

    pending = PendingValidation(
        video_file=video_file,
        candidates=candidates_data,
    )

    return video_file, pending
