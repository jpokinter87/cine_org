"""
Factory pour la création de PendingValidation.

Module partagé entre le CLI (matching_step.py) et le web (workflow.py)
pour éviter la duplication du code de matching API + scoring.
"""

from typing import Optional

from loguru import logger

from src.core.entities.video import PendingValidation, VideoFile
from src.core.value_objects.parsed_info import MediaType


async def create_pending_validation(
    scan_result,
    matcher,
    tmdb_client,
    tvdb_client,
    max_episode_in_batch: Optional[int] = None,
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
        candidates = await _search_and_score_movie(
            title, year, scan_result.media_info, matcher, tmdb_client
        )
    else:
        candidates = await _search_and_score_series(
            title, year, matcher, tvdb_client
        )

        # Filtrer les candidats incompatibles par nombre d'épisodes
        season = scan_result.parsed_info.season
        episode = scan_result.parsed_info.episode
        if candidates and season and episode:
            filtered = await filter_by_episode_count(
                tvdb_client, candidates, season, episode
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


async def _search_and_score_movie(
    title: str, year: Optional[int], media_info, matcher, tmdb_client
) -> list:
    """Recherche et score les films via TMDB avec enrichissement durée top 3."""
    candidates = []

    if not tmdb_client or not getattr(tmdb_client, "_api_key", None):
        return candidates

    try:
        api_results = await tmdb_client.search(title, year=year)
        duration = None
        if media_info and media_info.duration_seconds:
            duration = media_info.duration_seconds

        # Premier scoring sans durée API
        candidates = matcher.score_results(api_results, title, year, duration)

        # Enrichir les top 3 avec durée et re-scorer
        if candidates and duration:
            from dataclasses import replace

            from src.services.matcher import calculate_movie_score

            enriched = []
            for cand in candidates[:3]:
                try:
                    details = await tmdb_client.get_details(cand.id)
                    if details and details.duration_seconds:
                        new_score = calculate_movie_score(
                            query_title=title,
                            query_year=year,
                            query_duration=duration,
                            candidate_title=cand.title,
                            candidate_year=cand.year,
                            candidate_duration=details.duration_seconds,
                            candidate_original_title=(
                                cand.original_title or details.original_title
                            ),
                        )
                        cand = replace(cand, score=new_score)
                except Exception:
                    pass
                enriched.append(cand)

            candidates = enriched + candidates[3:]
            candidates.sort(key=lambda c: c.score, reverse=True)

    except Exception as e:
        logger.warning(f"Erreur TMDB pour {title}: {e}")

    return candidates


async def _search_and_score_series(
    title: str, year: Optional[int], matcher, tvdb_client
) -> list:
    """Recherche et score les séries via TVDB."""
    candidates = []

    if not tvdb_client or not getattr(tvdb_client, "_api_key", None):
        return candidates

    try:
        api_results = await tvdb_client.search(title, year=year)
        candidates = matcher.score_results(
            api_results, title, year, None, is_series=True
        )
    except Exception as e:
        logger.warning(f"Erreur TVDB pour {title}: {e}")

    return candidates


async def filter_by_episode_count(
    tvdb_client,
    candidates: list,
    season: int,
    episode: int,
) -> list:
    """
    Filtre les candidats séries dont la saison n'a pas assez d'épisodes.

    Élimine les candidats pour lesquels :
    - La saison n'existe pas et le nombre d'épisodes est insuffisant

    En cas d'erreur API ou d'absence de données, le candidat est conservé
    par précaution.

    Args:
        tvdb_client: Client TVDB
        candidates: Liste de SearchResult candidats
        season: Numéro de saison du fichier
        episode: Numéro d'épisode du fichier

    Returns:
        Liste filtrée de SearchResult compatibles
    """
    if not tvdb_client:
        return candidates

    compatible = []
    for candidate in candidates:
        try:
            count = await tvdb_client.get_season_episode_count(
                candidate.id, season
            )
            if count is not None and episode <= count:
                compatible.append(candidate)
            elif count is None:
                # Pas de données pour cette saison → garder par précaution
                compatible.append(candidate)
        except Exception:
            # En cas d'erreur API, conserver le candidat par précaution
            compatible.append(candidate)

    return compatible
