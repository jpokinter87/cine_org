"""
Service d'enrichissement TMDB pour les series TV existantes.

Recherche les series par titre+annee sur TMDB, puis recupere les details
complets (poster, notes, genres, createurs, acteurs).
"""

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from src.adapters.api.tmdb_client import TMDBClient
from src.core.entities.media import Series
from src.core.ports.repositories import ISeriesRepository


class EnrichmentResult(str, Enum):
    """Resultat d'enrichissement pour une serie."""

    SUCCESS = "success"
    NOT_FOUND = "not_found"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ProgressInfo:
    """Information de progression pour le callback."""

    current: int
    total: int
    series_title: str
    series_year: Optional[int]
    result: EnrichmentResult
    tmdb_id: Optional[str] = None


@dataclass
class SeriesEnrichmentStats:
    """Statistiques d'enrichissement des series."""

    total: int = 0
    enriched: int = 0
    not_found: int = 0
    failed: int = 0
    skipped: int = 0


class SeriesEnricherService:
    """
    Service pour enrichir les metadonnees TMDB des series existantes.

    Recherche chaque serie par titre sur TMDB TV, puis recupere les
    details complets (poster, notes, genres, createurs, acteurs).
    """

    def __init__(
        self,
        series_repo: ISeriesRepository,
        tmdb_client: TMDBClient,
    ) -> None:
        self._series_repo = series_repo
        self._tmdb_client = tmdb_client

    async def enrich_series(
        self,
        series_list: list[Series],
        rate_limit_seconds: float = 0.3,
        on_progress: Optional[Callable[[ProgressInfo], None]] = None,
    ) -> SeriesEnrichmentStats:
        """
        Enrichit les metadonnees TMDB pour une liste de series.

        Args:
            series_list: Series a enrichir
            rate_limit_seconds: Delai entre les appels API
            on_progress: Callback de progression optionnel

        Returns:
            Statistiques d'enrichissement
        """
        stats = SeriesEnrichmentStats(total=len(series_list))

        for i, series in enumerate(series_list):
            if i > 0 and rate_limit_seconds > 0:
                await asyncio.sleep(rate_limit_seconds)

            result = await self._enrich_one(series)

            if on_progress:
                on_progress(ProgressInfo(
                    current=i + 1,
                    total=stats.total,
                    series_title=series.title,
                    series_year=series.year,
                    result=result,
                    tmdb_id=None,
                ))

            if result == EnrichmentResult.SUCCESS:
                stats.enriched += 1
            elif result == EnrichmentResult.NOT_FOUND:
                stats.not_found += 1
            elif result == EnrichmentResult.FAILED:
                stats.failed += 1
            else:
                stats.skipped += 1

        return stats

    async def _enrich_one(self, series: Series) -> EnrichmentResult:
        """Enrichit une seule serie depuis TMDB."""
        try:
            # Rechercher la serie par titre
            results = await self._tmdb_client.search_tv(series.title, year=series.year)

            if not results:
                return EnrichmentResult.NOT_FOUND

            # Prendre le meilleur resultat (filtrer par annee si disponible)
            best = self._pick_best_match(results, series.title, series.year)
            if not best:
                return EnrichmentResult.NOT_FOUND

            # Recuperer les details complets
            details = await self._tmdb_client.get_tv_details(best.id)
            if not details:
                return EnrichmentResult.NOT_FOUND

            # Sauvegarder le tmdb_id
            series.tmdb_id = int(best.id)

            # Mettre a jour la serie avec les donnees TMDB
            if details.poster_url:
                series.poster_path = details.poster_url
            if details.vote_average is not None:
                series.vote_average = details.vote_average
            if details.vote_count is not None:
                series.vote_count = details.vote_count
            if details.genres:
                series.genres = details.genres
            if details.overview:
                series.overview = details.overview
            if details.original_title:
                series.original_title = details.original_title
            if details.director:
                series.director = details.director
            if details.cast:
                series.cast = details.cast

            # Recuperer l'imdb_id via les IDs externes TMDB
            if not series.imdb_id:
                ext_ids = await self._tmdb_client.get_tv_external_ids(best.id)
                if ext_ids and ext_ids.get("imdb_id"):
                    series.imdb_id = ext_ids["imdb_id"]

            self._series_repo.save(series)
            return EnrichmentResult.SUCCESS

        except Exception:
            return EnrichmentResult.FAILED

    def _pick_best_match(
        self,
        results: list,
        title: str,
        year: Optional[int],
    ):
        """Selectionne le meilleur resultat de recherche."""
        title_lower = title.lower().strip()

        # Priorite 1 : titre exact + meme annee
        if year:
            for r in results:
                r_title = r.title.lower().strip()
                if r_title == title_lower and r.year == year:
                    return r

        # Priorite 2 : titre exact (sans annee)
        for r in results:
            r_title = r.title.lower().strip()
            if r_title == title_lower:
                return r

        # Priorite 3 : titre original exact + meme annee
        if year:
            for r in results:
                if r.original_title and r.original_title.lower().strip() == title_lower and r.year == year:
                    return r

        # Priorite 4 : titre original exact
        for r in results:
            if r.original_title and r.original_title.lower().strip() == title_lower:
                return r

        # Priorite 5 : meme annee parmi les premiers resultats
        if year:
            for r in results[:3]:
                if r.year == year:
                    return r

        # Fallback : premier resultat
        return results[0] if results else None
