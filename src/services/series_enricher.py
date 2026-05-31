"""
Service d'enrichissement TMDB pour les series TV existantes.

Recherche les series par titre+annee sur TMDB, puis recupere les details
complets (poster, notes, genres, createurs, acteurs).
"""

import asyncio
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from loguru import logger

from src.adapters.api.tmdb_client import TMDBClient
from src.adapters.imdb.dataset_importer import IMDbDatasetImporter
from src.core.entities.media import Series
from src.core.ports.api_clients import SearchResult
from src.core.ports.repositories import IEpisodeRepository, ISeriesRepository

# Annee entre parentheses en fin de titre (ex: « Utopia (2020) »), utilisee comme
# desambiguisateur en base mais qui parasite la recherche TMDB par titre.
_TRAILING_YEAR_RE = re.compile(r"\s*\(\d{4}\)\s*$")


def strip_trailing_year(title: str) -> str:
    """
    Retire une annee entre parentheses en fin de titre.

    « Utopia (2020) » -> « Utopia ». Permet une recherche TMDB par titre plus
    fiable pour les series dont le titre stocke embarque l'annee.
    """
    return _TRAILING_YEAR_RE.sub("", title).strip()


async def resolve_tmdb_tv_by_external_id(
    tmdb_client,
    *,
    tvdb_id: Optional[int] = None,
    imdb_id: Optional[str] = None,
) -> Optional[SearchResult]:
    """
    Resout l'equivalent TMDB d'une serie via ses identifiants externes.

    Privilegie les identifiants externes (tvdb_id puis imdb_id) a la recherche
    par titre : le titre stocke est souvent traduit (ex: « Les Detectoristes »)
    et ne matche pas la recherche TMDB, alors que /find par tvdb_id reussit.

    Chaque strategie est isolee : un echec sur l'une n'empeche pas d'essayer
    la suivante.

    Args:
        tmdb_client: Client TMDB (doit exposer find_by_external_id)
        tvdb_id: ID TVDB de la serie (prioritaire)
        imdb_id: ID IMDb de la serie (repli)

    Returns:
        Le meilleur SearchResult TMDB, ou None si aucun identifiant ne resout.
    """
    candidates: list[tuple[str, str]] = []
    if tvdb_id is not None:
        candidates.append((str(tvdb_id), "tvdb_id"))
    if imdb_id:
        candidates.append((imdb_id, "imdb_id"))

    for external_id, source in candidates:
        try:
            results = await tmdb_client.find_by_external_id(external_id, source)
        except Exception as exc:
            logger.debug(
                "Echec resolution TMDB par {} {} : {}", source, external_id, exc
            )
            continue
        if results:
            return results[0]

    return None


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

    Reutilise par batch_builder (nouvelles series) et SeriesEnricherService (backfill).

    Strategie quand `year` est fournie :
        1. Titre exact + meme annee
        2. Titre original exact + meme annee
        3. Meme annee dans le top 3 (titre approximatif)
        Sinon -> None (refus explicite)

    Strategie sans `year` (mode degraded) :
        1. Titre exact
        2. Titre original exact
        3. Premier resultat (fallback)

    IMPORTANT : quand `year` est fournie, on n'accepte JAMAIS un resultat dont
    l'annee ne correspond pas. Ce garde-fou empeche les associations
    catastrophiques entre homonymes (ex: "Flashback 2011" Game Show associe par
    erreur a Flashback 2025, ou "Shameless 2004" UK confondu avec Shameless US 2011).
    """
    title_lower = title.lower().strip()

    if year:
        # Mode strict : annee obligatoire
        for r in results:
            if r.title.lower().strip() == title_lower and r.year == year:
                return r
        for r in results:
            if (
                r.original_title
                and r.original_title.lower().strip() == title_lower
                and r.year == year
            ):
                return r
        for r in results[:3]:
            if r.year == year:
                return r
        return None

    # Mode degraded : pas d'annee, on prend le titre exact ou le premier
    for r in results:
        if r.title.lower().strip() == title_lower:
            return r
    for r in results:
        if r.original_title and r.original_title.lower().strip() == title_lower:
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
        episode_repo: Optional[IEpisodeRepository] = None,
    ) -> None:
        self._series_repo = series_repo
        self._tmdb_client = tmdb_client
        # Optionnel : si fourni, on lit aussi imdb_rating + imdb_votes depuis le cache local
        # apres avoir recupere l'imdb_id via TMDB (evite un imdb sync separe pour les series).
        self._imdb_importer = imdb_importer
        # Optionnel : si fourni, on filtre les candidats TMDB incompatibles avec
        # les episodes deja en base (garde-fou anti-homonymes — ex: Shameless UK
        # ne doit pas etre choisi pour une serie dont la S01 a 12 episodes en DB).
        self._episode_repo = episode_repo

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
                on_progress(
                    ProgressInfo(
                        current=i + 1,
                        total=stats.total,
                        series_title=series.title,
                        series_year=series.year,
                        result=result,
                        tmdb_id=None,
                    )
                )

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
            # Priorite aux identifiants externes (tvdb_id, imdb_id) : evite
            # l'echec de la recherche par titre quand le titre stocke est traduit
            # (ex: « Les Detectoristes » vs « Detectorists »).
            best = await resolve_tmdb_tv_by_external_id(
                self._tmdb_client,
                tvdb_id=series.tvdb_id,
                imdb_id=series.imdb_id,
            )

            if best is None:
                # Repli : recherche par titre normalise (sans « (AAAA) » final).
                query = strip_trailing_year(series.title)
                results = await self._tmdb_client.search_tv(query, year=series.year)

                if not results:
                    return EnrichmentResult.NOT_FOUND

                # Garde-fou anti-homonymes : si on a deja des episodes en base et
                # qu'il reste plusieurs candidats, ecarter ceux dont les saisons
                # cote TMDB n'ont pas assez d'episodes pour couvrir ce qu'on a en DB.
                if (
                    len(results) > 1
                    and series.id is not None
                    and self._episode_repo is not None
                ):
                    results = await self._filter_by_episode_counts(results, series.id)
                    if not results:
                        return EnrichmentResult.NOT_FOUND

                # Prendre le meilleur resultat (filtrer par annee si disponible)
                best = pick_best_tv_match(results, query, series.year)
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

            # Repli : TMDB ne fournit pas toujours d'imdb_id (series non
            # anglophones, ex. quebecoises). On retrouve alors le tconst via la
            # table locale imdb_akas par titre (garde-fou anti-homonymes inclus).
            if not series.imdb_id and self._imdb_importer:
                tconst = self._imdb_importer.find_tconst_by_title(series.title)
                if tconst:
                    series.imdb_id = tconst

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

    async def _filter_by_episode_counts(self, results: list, series_id: str) -> list:
        """
        Ecarte les candidats TMDB dont les saisons n'ont pas assez d'episodes
        pour couvrir ce qui est deja stocke en base pour la serie.

        Exemple : la serie en base a 12 episodes en S01. Un candidat TMDB qui
        ne propose que 7 episodes en S01 (ex: Shameless UK) est forcement le
        mauvais — on le retire.

        Args:
            results: Candidats TMDB renvoyes par search_tv
            series_id: ID interne de la serie en base

        Returns:
            Sous-liste des candidats compatibles avec les comptes DB. Si la DB
            n'a pas encore d'episodes (cas peu probable), on renvoie la liste
            originale (pas de signal pour filtrer).
        """
        eps = self._episode_repo.get_by_series(series_id)
        db_max_per_season: dict[int, int] = {}
        for e in eps:
            s = e.season_number
            ep_num = e.episode_number or 0
            if s is not None and s >= 1:
                db_max_per_season[s] = max(db_max_per_season.get(s, 0), ep_num)
        if not db_max_per_season:
            return results

        compatible: list = []
        for r in results:
            try:
                counts = await self._tmdb_client.get_tv_seasons_episode_counts(r.id)
            except Exception:
                counts = {}
            if all(
                counts.get(season, 0) >= min_required
                for season, min_required in db_max_per_season.items()
            ):
                compatible.append(r)
        return compatible
