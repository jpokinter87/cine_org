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
    series_cache: Optional[dict[tuple[str, Optional[int]], list]] = None,
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
        candidates = await _search_and_score_movie(
            title, year, scan_result.media_info, matcher, tmdb_client
        )
    else:
        candidates = await _search_and_score_series(
            title, year, matcher, tvdb_client, series_cache
        )

        # Filtrer les candidats incompatibles par nombre d'épisodes
        season = scan_result.parsed_info.season
        episode = scan_result.parsed_info.episode
        if candidates and season is not None and episode is not None:
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
    """Recherche et score les films via TMDB.

    Stratégie alignée sur la réassociation (UI) : quand la durée locale est
    connue (mediainfo), enrichir systématiquement le top 10 TMDB avec
    `get_details()` pour récupérer la durée TMDB, puis trier par écart
    de durée primaire (avec score comme tie-break).

    Retour d'expérience : tri par durée → candidat correct en #1 dans
    ~80% des cas où le score seul se trompait (homonymes, courts-métrages,
    traductions FR éloignées du titre parsé).
    """
    candidates = []

    if not tmdb_client or not getattr(tmdb_client, "_api_key", None):
        return candidates

    try:
        api_results = await tmdb_client.search(title, year=year)
        # TMDB ignore le paramètre year ; on complète avec une requête
        # "{title} {year}" (TMDB parse l'année du texte de la query et la
        # prend en compte dans le ranking). Capture les films peu populaires
        # noyés dans les homonymes (ex: Lamb 2021 islandais, pop 2.5).
        if year is not None:
            year_query = f"{title} {year}"
            year_results = await tmdb_client.search(year_query)
            if year_results:
                seen = {r.id for r in api_results}
                for r in year_results:
                    if r.id not in seen:
                        api_results.append(r)
                        seen.add(r.id)
        duration = None
        if media_info and media_info.duration_seconds:
            duration = media_info.duration_seconds

        # Premier scoring sans durée API (fallback 67/33 titre/année)
        candidates = matcher.score_results(api_results, title, year, duration)

        if candidates and duration:
            from dataclasses import replace

            from src.services.matcher import calculate_movie_score

            MAX_ENRICH = 10
            # Durées TMDB collectées durant l'enrichissement
            tmdb_durations: dict[str, int] = {}

            enriched = []
            for cand in candidates[:MAX_ENRICH]:
                try:
                    details = await tmdb_client.get_details(cand.id)
                    if details and details.duration_seconds:
                        tmdb_durations[cand.id] = details.duration_seconds
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

            candidates = enriched + candidates[MAX_ENRICH:]

            # Tri principal : écart de durée absolu (comme la réassociation).
            # Tie-break : score décroissant. Les candidats sans durée TMDB
            # (get_details échoué ou durée=0) reculent en fin de liste.
            def _sort_key(c):
                d = tmdb_durations.get(c.id)
                if d is None:
                    return (float("inf"), -c.score)
                return (abs(d - duration), -c.score)

            candidates.sort(key=_sort_key)
        elif candidates:
            # Pas de durée locale : conserver le tri par score existant.
            candidates.sort(key=lambda c: c.score, reverse=True)

    except Exception as e:
        logger.warning(f"Erreur TMDB pour {title}: {e}")

    return candidates


async def _search_and_score_series(
    title: str,
    year: Optional[int],
    matcher,
    tvdb_client,
    series_cache: Optional[dict[tuple[str, Optional[int]], list]] = None,
) -> list:
    """Recherche et score les séries via TVDB.

    Utilise un cache mémoire par (titre, année) pour éviter les recherches
    API et le scoring redondants quand plusieurs épisodes de la même série
    sont traités dans le même batch.
    """
    # Vérifier le cache mémoire (recherche + scoring déjà faits pour ce titre)
    cache_key = (title.lower(), year) if title else None
    if series_cache is not None and cache_key and cache_key in series_cache:
        logger.debug(f"Cache mémoire série hit pour '{title}' ({year})")
        return series_cache[cache_key]

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

    # Stocker dans le cache mémoire pour les prochains épisodes
    if series_cache is not None and cache_key:
        series_cache[cache_key] = candidates

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
            count = await tvdb_client.get_season_episode_count(candidate.id, season)
            if count is not None and episode <= count:
                compatible.append(candidate)
            elif count is None:
                # Pas de données pour cette saison → garder par précaution
                compatible.append(candidate)
        except Exception:
            # En cas d'erreur API, conserver le candidat par précaution
            compatible.append(candidate)

    return compatible
