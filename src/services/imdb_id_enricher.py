"""
Service d'enrichissement des imdb_id pour les films existants.

Ce service permet de recuperer les imdb_id depuis TMDB (via get_external_ids)
pour les films qui n'ont pas encore cette information en base.
Cela permet ensuite de synchroniser les notes IMDb via la commande imdb sync.
"""

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from src.adapters.imdb.dataset_importer import IMDbDatasetImporter
from src.core.ports.api_clients import IMediaAPIClient
from src.core.ports.repositories import IMovieRepository


class EnrichmentResult(Enum):
    """Resultat de l'enrichissement d'un film."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_FOUND = "not_found"


@dataclass
class ProgressInfo:
    """Information de progression pour le callback."""

    current: int
    total: int
    movie_title: str
    movie_year: Optional[int]
    result: EnrichmentResult
    imdb_id: Optional[str] = None


@dataclass
class EnrichmentStats:
    """Statistiques d'enrichissement des imdb_id."""

    total: int = 0
    enriched: int = 0
    failed: int = 0
    skipped: int = 0
    not_found: int = 0


class ImdbIdEnricherService:
    """
    Service pour enrichir les imdb_id des films existants.

    Recupere les imdb_id depuis l'API TMDB (endpoint /movie/{id}/external_ids)
    pour les films qui n'ont pas cette information en base.
    """

    def __init__(
        self,
        movie_repo: IMovieRepository,
        tmdb_client: IMediaAPIClient,
        imdb_importer: Optional[IMDbDatasetImporter] = None,
    ) -> None:
        """
        Initialise le service d'enrichissement.

        Args:
            movie_repo: Repository des films
            tmdb_client: Client API TMDB (doit implementer get_external_ids)
            imdb_importer: Cache IMDb local (optionnel). Quand fourni, le
                service rattrape aussi imdb_rating/imdb_votes dès que
                l'imdb_id est résolu — évite de devoir lancer une seconde
                commande pour avoir un film complet (aligné sur le workflow
                principal et migrate-nas raw_finalizer).
        """
        self._movie_repo = movie_repo
        self._tmdb_client = tmdb_client
        self._imdb_importer = imdb_importer

    async def enrich_imdb_ids(
        self,
        limit: int = 100,
        rate_limit_seconds: float = 0.25,
        on_progress: Optional[Callable[[ProgressInfo], None]] = None,
    ) -> EnrichmentStats:
        """
        Enrichit les imdb_id pour les films sans cette information.

        Args:
            limit: Nombre maximum de films a enrichir
            rate_limit_seconds: Delai entre les appels API (rate limiting)
            on_progress: Callback appele apres chaque film traite

        Returns:
            Statistiques d'enrichissement
        """
        stats = EnrichmentStats()

        # Recuperer les films sans imdb_id
        movies = self._movie_repo.list_without_imdb_id(limit)
        stats.total = len(movies)

        for i, movie in enumerate(movies):
            # Rate limiting (sauf premier appel)
            if i > 0 and rate_limit_seconds > 0:
                await asyncio.sleep(rate_limit_seconds)

            # Verifier que le film a un tmdb_id
            if movie.tmdb_id is None:
                stats.skipped += 1
                if on_progress:
                    on_progress(ProgressInfo(
                        current=i + 1,
                        total=stats.total,
                        movie_title=movie.title,
                        movie_year=movie.year,
                        result=EnrichmentResult.SKIPPED,
                    ))
                continue

            # Recuperer les IDs externes depuis TMDB
            external_ids = await self._tmdb_client.get_external_ids(str(movie.tmdb_id))

            if external_ids is None:
                stats.failed += 1
                if on_progress:
                    on_progress(ProgressInfo(
                        current=i + 1,
                        total=stats.total,
                        movie_title=movie.title,
                        movie_year=movie.year,
                        result=EnrichmentResult.FAILED,
                    ))
                continue

            # Extraire l'imdb_id
            imdb_id = external_ids.get("imdb_id")

            if imdb_id is None:
                stats.not_found += 1
                if on_progress:
                    on_progress(ProgressInfo(
                        current=i + 1,
                        total=stats.total,
                        movie_title=movie.title,
                        movie_year=movie.year,
                        result=EnrichmentResult.NOT_FOUND,
                    ))
                continue

            # Mettre a jour le film avec l'imdb_id
            movie.imdb_id = imdb_id

            # Rattrape aussi imdb_rating/imdb_votes depuis le cache local
            # quand un importer est fourni — sans ça, l'utilisateur doit
            # lancer une seconde commande (et la note risque de rester None
            # pour les œuvres absentes du snapshot IMDb).
            if self._imdb_importer is not None:
                try:
                    rating_data = self._imdb_importer.get_rating(imdb_id)
                except Exception:
                    rating_data = None
                if rating_data:
                    movie.imdb_rating, movie.imdb_votes = rating_data

            # Sauvegarder
            self._movie_repo.save(movie)
            stats.enriched += 1

            if on_progress:
                on_progress(ProgressInfo(
                    current=i + 1,
                    total=stats.total,
                    movie_title=movie.title,
                    movie_year=movie.year,
                    result=EnrichmentResult.SUCCESS,
                    imdb_id=imdb_id,
                ))

        return stats
