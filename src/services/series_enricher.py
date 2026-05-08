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
from src.adapters.imdb.dataset_importer import IMDbDatasetImporter
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


def pick_best_tv_match(results: list, title: str, year: Optional[int]):
    """
    Selectionne le meilleur resultat TMDB TV pour un titre+annee donnes.

    Reutilise par batch_builder pour les nouvelles series et par
    SeriesEnricherService pour le backfill.

    Priorites :
        1. Titre exact + meme annee
        2. Titre exact (sans annee)
        3. Titre original exact + meme annee
        4. Titre original exact
        5. Meme annee parmi les 3 premiers resultats
        6. Premier resultat (fallback)
    """
    title_lower = title.lower().strip()

    if year:
        for r in results:
            if r.title.lower().strip() == title_lower and r.year == year:
                return r

    for r in results:
        if r.title.lower().strip() == title_lower:
            return r

    if year:
        for r in results:
            if (
                r.original_title
                and r.original_title.lower().strip() == title_lower
                and r.year == year
            ):
                return r

    for r in results:
        if r.original_title and r.original_title.lower().strip() == title_lower:
            return r

    if year:
        for r in results[:3]:
            if r.year == year:
                return r

    return results[0] if results else None


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
        imdb_importer: Optional[IMDbDatasetImporter] = None,
    ) -> None:
        self._series_repo = series_repo
        self._tmdb_client = tmdb_client
        # Optionnel : si fourni, on lit aussi imdb_rating + imdb_votes depuis le cache local
        # apres avoir recupere l'imdb_id via TMDB (evite un imdb sync separe pour les series).
        self._imdb_importer = imdb_importer

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
            best = pick_best_tv_match(results, series.title, series.year)
            if not best:
                return EnrichmentResult.NOT_FOUND

            # Recuperer les details complets
            details = await self._tmdb_client.get_tv_details(best.id)
            if not details:
                return EnrichmentResult.NOT_FOUND

            # Sauvegarder le tmdb_id
            series.tmdb_id = int(best.id)

            # Mettre a jour la serie avec les donnees TMDB.
            # Phase 42-02 : les champs poster/overview/director/cast ne
            # sont pas ecrases si l'utilisateur a protege la fiche.
            preserve = bool(series.preserve_overrides)
            if not preserve and details.poster_url:
                series.poster_path = details.poster_url
            if details.vote_average is not None:
                series.vote_average = details.vote_average
            if details.vote_count is not None:
                series.vote_count = details.vote_count
            if details.genres:
                series.genres = details.genres
            if not preserve and details.overview:
                series.overview = details.overview
            if details.original_title:
                series.original_title = details.original_title
            if not preserve and details.director:
                series.director = details.director
            if not preserve and details.cast:
                series.cast = details.cast

            # Recuperer l'imdb_id via les IDs externes TMDB
            if not series.imdb_id:
                ext_ids = await self._tmdb_client.get_tv_external_ids(best.id)
                if ext_ids and ext_ids.get("imdb_id"):
                    series.imdb_id = ext_ids["imdb_id"]

            # Notes IMDb depuis le cache local (si importer fourni et imdb_id connu).
            # Permet d'eviter une commande imdb sync supplementaire pour les series.
            if self._imdb_importer and series.imdb_id:
                rating_data = self._imdb_importer.get_rating(series.imdb_id)
                if rating_data:
                    series.imdb_rating, series.imdb_votes = rating_data

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
        """Conserve pour compat externe : delegue a la fonction module-level."""
        return pick_best_tv_match(results, title, year)
