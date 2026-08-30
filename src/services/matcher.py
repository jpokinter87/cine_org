"""
Service de scoring pour le matching de resultats API.

MatcherService calcule les scores de correspondance entre les metadonnees
extraites des noms de fichiers et les resultats de recherche API.

Formules de scoring:
- Films: 50% titre + 25% annee + 25% duree
- Series: 100% titre

Le scoring est deterministe pour des resultats reproductibles.
"""

import re
from dataclasses import replace

from rapidfuzz import fuzz, utils

from src.core.ports.api_clients import SearchResult
from src.utils.helpers import normalize_accents as _normalize_accents

# Nombre a 4 chiffres dans un titre = annee discriminante (ex: "Paris Police 1900").
_YEAR_LIKE_RE = re.compile(r"\b\d{4}\b")

# Plafond de score quand deux titres de series portent des annees distinctes.
# Volontairement bien sous le seuil d'auto-validation (85 %) pour forcer une
# validation manuelle au lieu de confondre deux series homonymes.
_DISTINCT_YEAR_CEILING: float = 50.0


def _year_like_tokens(title: str) -> set[str]:
    """Extrait les nombres a 4 chiffres (annees) presents dans un titre."""
    return set(_YEAR_LIKE_RE.findall(title))


def _calculate_title_score(query_title: str, candidate_title: str) -> float:
    """
    Calculate title similarity score (0-100).

    Uses token_sort_ratio for word-order independence.
    Normalized via default_process (lowercase, strip whitespace).
    Les accents sont normalises pour une comparaison insensible aux diacritiques
    (ex: "Les Evades" vs "Les Évadés" = 100%).
    """
    # Normaliser les accents avant comparaison
    query_normalized = _normalize_accents(query_title)
    candidate_normalized = _normalize_accents(candidate_title)

    return fuzz.token_sort_ratio(
        query_normalized, candidate_normalized, processor=utils.default_process
    )


def _calculate_year_score(
    query_year: int | None, candidate_year: int | None
) -> float:
    """
    Calculate year match score (0-100).

    - Exact match or +/-1 year: 100%
    - Each additional year difference: -25%
    - Missing year (None): 0%
    """
    if query_year is None or candidate_year is None:
        return 0.0

    diff = abs(query_year - candidate_year)

    if diff <= 1:
        return 100.0

    # Each year beyond tolerance reduces by 25%
    penalty = (diff - 1) * 25
    return max(0.0, 100.0 - penalty)


def _calculate_duration_score(
    query_duration: int | None, candidate_duration: int | None
) -> float:
    """
    Calculate duration match score (0-100).

    - Within +/-10%: 100%
    - Each additional 10% deviation: -50%
    - Missing duration (None): 0%
    """
    if query_duration is None or candidate_duration is None:
        return 0.0

    if query_duration == 0:
        return 0.0

    # Calculate percentage difference
    diff_percent = abs(candidate_duration - query_duration) / query_duration * 100

    if diff_percent <= 10:
        return 100.0

    # Each 10% beyond tolerance reduces by 50%
    excess = diff_percent - 10
    penalty = (excess / 10) * 50
    return max(0.0, 100.0 - penalty)


def calculate_movie_score(
    query_title: str,
    query_year: int | None,
    query_duration: int | None,
    candidate_title: str,
    candidate_year: int | None,
    candidate_duration: int | None,
    candidate_original_title: str | None = None,
) -> float:
    """
    Calculate movie match score with adaptive coefficients and bilingual matching.

    Score le titre sur les deux versions (localisee et originale) et garde le meilleur.
    Coefficients adaptatifs selon la disponibilite de la duree:
    - Avec duree: 50% titre + 25% annee + 25% duree
    - Sans duree (fallback): 67% titre + 33% annee

    Args:
        query_title: Title from parsed filename
        query_year: Year from parsed filename (or None)
        query_duration: Duration in seconds from mediainfo (or None)
        candidate_title: Localized title from API result
        candidate_year: Year from API result (or None)
        candidate_duration: Duration from API result (or None)
        candidate_original_title: Original title from API (for bilingual matching)

    Returns:
        Match score from 0.0 to 100.0, rounded to 2 decimals
    """
    # Scorer sur le titre localise
    title_score = _calculate_title_score(query_title, candidate_title)

    # Scorer aussi sur le titre original si disponible, garder le meilleur
    if candidate_original_title:
        original_title_score = _calculate_title_score(query_title, candidate_original_title)
        title_score = max(title_score, original_title_score)

    year_score = _calculate_year_score(query_year, candidate_year)

    # Verifier si la duree est disponible des deux cotes
    duration_available = (
        query_duration is not None
        and query_duration > 0
        and candidate_duration is not None
        and candidate_duration > 0
    )

    if duration_available:
        # Coefficients complets: 50% titre + 25% annee + 25% duree
        duration_score = _calculate_duration_score(query_duration, candidate_duration)
        total = (title_score * 0.50) + (year_score * 0.25) + (duration_score * 0.25)
    else:
        # Fallback sans duree: 67% titre + 33% annee
        total = (title_score * 0.67) + (year_score * 0.33)

    return round(total, 2)


def calculate_series_score(
    query_title: str,
    candidate_title: str,
    candidate_original_title: str | None = None,
) -> float:
    """
    Calculate series match score using 100% title similarity.

    Score le titre sur les deux versions (localisee et originale) et garde le meilleur,
    comme pour les films.

    Args:
        query_title: Title from parsed filename
        candidate_title: Localized title from API result
        candidate_original_title: Original title from API (for bilingual matching)

    Returns:
        Match score from 0.0 to 100.0, rounded to 2 decimals
    """
    score = _series_title_score(query_title, candidate_title)

    if candidate_original_title:
        original_score = _series_title_score(query_title, candidate_original_title)
        score = max(score, original_score)

    return round(score, 2)


def _series_title_score(query_title: str, candidate_title: str) -> float:
    """Score de titre serie avec garde-fou anti-homonymes par annee.

    token_sort_ratio donne ~94 % a deux titres qui ne different que par une
    annee a 4 chiffres ("Paris Police 1905" vs "Paris Police 1900"), au-dessus
    du seuil d'auto-validation. Or ce sont des series distinctes (suites/spin-offs
    "1900/1905/1910", ou "1883" vs "1923"). Quand les deux titres portent des
    annees et qu'elles n'ont aucune valeur en commun, on plafonne le score pour
    basculer en validation manuelle.

    La penalite ne s'applique PAS si une annee n'est presente que d'un seul cote
    (ex: "Doctor Who 2005" vs "Doctor Who") ni aux nombres non-annee (numeros
    d'episode a 2 chiffres, "9-1-1", etc.).
    """
    base = _calculate_title_score(query_title, candidate_title)

    query_years = _year_like_tokens(query_title)
    candidate_years = _year_like_tokens(candidate_title)

    if query_years and candidate_years and query_years.isdisjoint(candidate_years):
        return min(base, _DISTINCT_YEAR_CEILING)

    return base


class MatcherService:
    """
    Service for scoring and ranking API search results.

    Calculates match scores between parsed filename metadata and
    API search results, supporting both movies and TV series.
    """

    MATCH_THRESHOLD: int = 85
    """Score threshold for automatic validation (85%)."""

    def score_results(
        self,
        results: list[SearchResult],
        query_title: str,
        query_year: int | None = None,
        query_duration: int | None = None,
        is_series: bool = False,
    ) -> list[SearchResult]:
        """
        Calculate scores for all results and return sorted by score descending.

        Args:
            results: List of SearchResult from API
            query_title: Title from parsed filename
            query_year: Year from parsed filename (or None)
            query_duration: Duration in seconds (or None)
            is_series: If True, use series scoring (100% title only)

        Returns:
            List of SearchResult with score field populated, sorted descending
        """
        if not results:
            return []

        scored_results = []
        for result in results:
            if is_series:
                score = calculate_series_score(
                    query_title, result.title, result.original_title
                )
            else:
                score = calculate_movie_score(
                    query_title=query_title,
                    query_year=query_year,
                    query_duration=query_duration,
                    candidate_title=result.title,
                    candidate_year=result.year,
                    candidate_duration=None,  # API results don't have duration
                    candidate_original_title=result.original_title,
                )

            # Create new SearchResult with updated score
            scored_result = replace(result, score=score)
            scored_results.append(scored_result)

        # Sort by score descending
        scored_results.sort(key=lambda r: r.score, reverse=True)

        return scored_results
