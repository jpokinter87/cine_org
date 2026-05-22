"""
Helpers partagés pour le matching API (TMDB/TVDB).

Module commun au workflow standard (`process` via pending_factory) et au
package migration (matcher des fichiers découverts sur un vieux NAS).

Fonctions exposées :
- `search_and_score_movie(title, year, media_info, matcher, tmdb_client)` :
  double recherche TMDB + enrichissement durée TMDB sur le top 10 +
  tri par écart de durée (tie-break par score). Retourne les candidats
  scorés avec la formule complète (50/25/25 ou 67/33 fallback).
- `search_and_score_series(title, year, matcher, tvdb_client, series_cache)` :
  recherche TVDB + scoring 100 % titre, avec cache mémoire par
  (titre, année) pour éviter les recherches redondantes quand plusieurs
  épisodes de la même série sont traités dans le même batch.
- `filter_by_episode_count(tvdb_client, candidates, season, episode, session)` :
  filtre les candidats séries dont la saison n'a pas assez d'épisodes
  (consulte SeasonOverrideModel si `session` fournie).
- `_lookup_override_count(session, candidate_id, season)` : helper privé
  qui retourne `episode_count` de l'override SeasonOverrideModel, ou None.

Retour d'expérience workflow : l'enrichissement durée TMDB + tri par
écart de durée corrige ~80 % des cas où le score seul se trompait
(homonymes, courts-métrages, traductions FR éloignées du titre parsé).
"""

from __future__ import annotations

from typing import Optional

from loguru import logger
from sqlmodel import Session


async def search_and_score_movie(
    title: str,
    year: Optional[int],
    media_info,
    matcher,
    tmdb_client,
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
        if media_info and getattr(media_info, "duration_seconds", None):
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


async def search_and_score_series(
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
    session: Optional[Session] = None,
) -> list:
    """
    Filtre les candidats séries dont la saison n'a pas assez d'épisodes.

    Élimine les candidats pour lesquels :
    - La saison n'existe pas et le nombre d'épisodes est insuffisant

    En cas d'erreur API ou d'absence de données, le candidat est conservé
    par précaution.

    Si ``session`` est fourni, un éventuel ``SeasonOverrideModel`` pour
    ``(candidate.id, season)`` est consulté et le count retenu est
    ``max(count_tvdb, override.episode_count)`` (découpage local plus
    large que le canon TVDB).

    Args:
        tvdb_client: Client TVDB
        candidates: Liste de SearchResult candidats
        season: Numéro de saison du fichier
        episode: Numéro d'épisode du fichier
        session: Session SQLModel optionnelle pour consulter les overrides
            (comportement rétro-compatible quand None).

    Returns:
        Liste filtrée de SearchResult compatibles
    """
    if not tvdb_client:
        return candidates

    compatible = []
    for candidate in candidates:
        try:
            count = await tvdb_client.get_season_episode_count(candidate.id, season)

            if session is not None:
                override_count = _lookup_override_count(session, candidate.id, season)
                if override_count is not None:
                    count = max(count or 0, override_count)

            if count is not None and episode <= count:
                compatible.append(candidate)
            elif count is None:
                # Pas de données pour cette saison → garder par précaution
                compatible.append(candidate)
        except Exception:
            # En cas d'erreur API, conserver le candidat par précaution
            compatible.append(candidate)

    return compatible


def _lookup_override_count(
    session: Session, candidate_id, season: int
) -> Optional[int]:
    """Retourne ``episode_count`` de l'override si présent, None sinon.

    Import local de ``SeasonOverrideModel`` pour éviter les cycles
    d'imports entre ``services`` et ``infrastructure.persistence``.
    """
    try:
        tvdb_id = int(candidate_id)
    except (TypeError, ValueError):
        return None

    from sqlmodel import select

    from src.infrastructure.persistence.models import SeasonOverrideModel

    override = session.exec(
        select(SeasonOverrideModel).where(
            SeasonOverrideModel.tvdb_id == tvdb_id,
            SeasonOverrideModel.season_number == season,
        )
    ).first()
    return override.episode_count if override is not None else None
