"""
Matcher pour le mode raw du package migration.

Pour un fichier physique decouvert sur un vieux NAS pre-CineOrg, identifie
l'oeuvre correspondante via TMDB (films) ou TMDB+TVDB (series) en
reutilisant `MatcherService` (scoring + seuil 85%).

Le matcher ne touche pas a la base : il retourne un `MatchOutcome` qui sera
exploite par le plan_builder (etape 3) pour decider entre :
- MATCHED : un unique candidat avec score >= 85, autres bien en dessous →
  bucket MIGRATE/LOW_RATED/UNRATED selon la note (rating_resolver).
- AMBIGUOUS : meilleur score < 85, ou plusieurs candidats serres → bucket
  NEEDS_VALIDATION (CSV pour retraitement via `process`).
- NO_RESULTS : aucune piste API → bucket NEEDS_VALIDATION.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.adapters.api.tmdb_client import TMDBClient
from src.adapters.api.tvdb_client import TVDBClient
from src.core.ports.api_clients import SearchResult
from src.core.ports.parser import IFilenameParser
from src.core.value_objects.parsed_info import MediaType, ParsedFilename
from src.services.matcher import MatcherService
from src.services.migration.dataclasses import MigrationCandidate


# Ecart minimal entre le top-1 et le top-2 pour considerer le match unique.
# En dessous, deux candidats sont juges "trop serres" → AMBIGUOUS.
_AMBIGUITY_GAP = 5.0


class MatchKind(str, Enum):
    """Verdict du MigrationMatcher pour un candidat raw."""

    MATCHED = "matched"  # Un seul candidat domine avec score >= 85
    AMBIGUOUS = "ambiguous"  # Score insuffisant ou candidats trop serres
    NO_RESULTS = "no_results"  # Aucun resultat API


@dataclass
class MatchOutcome:
    """Resultat du matching pour un candidat raw."""

    kind: MatchKind
    top_results: list[SearchResult]  # Top 5 max, tries score decroissant
    selected: Optional[SearchResult] = None  # Defini ssi kind == MATCHED


class MigrationMatcher:
    """
    Identifie un fichier physique via TMDB/TVDB.

    Args:
        parser: Parseur guessit pour extraire titre/annee/saison/episode.
        tmdb_client: Client TMDB (films + series via search_tv).
        tvdb_client: Client TVDB (series uniquement).
        matcher_service: Service de scoring (reutilise score_results).
        threshold: Seuil de matching (defaut 85, parite avec workflow standard).
        ambiguity_gap: Ecart top1-top2 sous lequel le match est ambigu.
        max_top: Nombre max de candidats conserves dans MatchOutcome.top_results.
    """

    def __init__(
        self,
        parser: IFilenameParser,
        tmdb_client: TMDBClient,
        tvdb_client: TVDBClient,
        matcher_service: MatcherService,
        threshold: float = 85.0,
        ambiguity_gap: float = _AMBIGUITY_GAP,
        max_top: int = 5,
    ) -> None:
        self._parser = parser
        self._tmdb = tmdb_client
        self._tvdb = tvdb_client
        self._scorer = matcher_service
        self._threshold = threshold
        self._gap = ambiguity_gap
        self._max_top = max_top

    async def match(self, candidate: MigrationCandidate) -> MatchOutcome:
        """Identifie l'oeuvre derriere un fichier physique."""
        parsed = self._parser.parse(candidate.symlink_path.name)
        media_type = self._guess_media_type(candidate, parsed)

        if media_type == MediaType.SERIES:
            scored = await self._search_and_score_series(parsed)
        else:
            scored = await self._search_and_score_movie(parsed)

        top = scored[: self._max_top]
        return self._classify(top, query_year=parsed.year)

    async def _search_and_score_movie(
        self, parsed: ParsedFilename
    ) -> list[SearchResult]:
        """Recherche film + scoring, avec fallback titre tronqué si vide."""
        if not parsed.title:
            return []
        results = await self._tmdb.search(parsed.title, year=parsed.year)
        if results:
            return self._scorer.score_results(
                results,
                query_title=parsed.title,
                query_year=parsed.year,
                is_series=False,
            )
        # Fallback : guessit peut "avaler" un n° d'épisode dans le titre
        # (ex: "Rivalité de génies 02 Edison Tesla"). On retente avec le
        # titre tronqué avant le premier nombre, et on score avec ce titre
        # tronqué pour que le scoring soit cohérent avec la recherche.
        truncated = _truncate_title_at_first_number(parsed.title)
        if truncated and truncated != parsed.title:
            fallback = await self._tmdb.search(truncated, year=parsed.year)
            return self._scorer.score_results(
                fallback,
                query_title=truncated,
                query_year=parsed.year,
                is_series=False,
            )
        return []

    async def _search_and_score_series(
        self, parsed: ParsedFilename
    ) -> list[SearchResult]:
        """Recherche série (TMDB+TVDB) + scoring, avec fallback titre tronqué."""
        if not parsed.title:
            return []
        merged = await self._search_series_for_title(parsed.title, parsed.year)
        if merged:
            return self._scorer.score_results(
                merged,
                query_title=parsed.title,
                query_year=parsed.year,
                is_series=True,
            )
        truncated = _truncate_title_at_first_number(parsed.title)
        if truncated and truncated != parsed.title:
            fallback = await self._search_series_for_title(
                truncated, parsed.year
            )
            return self._scorer.score_results(
                fallback,
                query_title=truncated,
                query_year=parsed.year,
                is_series=True,
            )
        return []

    async def _search_series_for_title(
        self, title: str, year: Optional[int]
    ) -> list[SearchResult]:
        """Fusionne les resultats TMDB (search_tv) et TVDB pour un titre série."""
        merged: list[SearchResult] = []
        tmdb_results = await self._tmdb.search_tv(title, year=year)
        merged.extend(tmdb_results)
        tvdb_results = await self._tvdb.search(title, year=year)
        merged.extend(tvdb_results)
        return merged

    def _classify(
        self,
        top: list[SearchResult],
        *,
        query_year: Optional[int] = None,
    ) -> MatchOutcome:
        if not top:
            return MatchOutcome(kind=MatchKind.NO_RESULTS, top_results=[])

        best = top[0]
        if best.score < self._threshold:
            return MatchOutcome(kind=MatchKind.AMBIGUOUS, top_results=top)

        # Verifie l'ecart avec le runner-up.
        if len(top) >= 2 and (best.score - top[1].score) < self._gap:
            # Tie-break par annee : si exactement un candidat (parmi ceux >= seuil)
            # match query_year, on le retient. Sinon AMBIGUOUS.
            if query_year is not None:
                year_matched = [
                    r
                    for r in top
                    if r.score >= self._threshold and r.year == query_year
                ]
                if len(year_matched) == 1:
                    return MatchOutcome(
                        kind=MatchKind.MATCHED,
                        top_results=top,
                        selected=year_matched[0],
                    )
            return MatchOutcome(kind=MatchKind.AMBIGUOUS, top_results=top)

        return MatchOutcome(
            kind=MatchKind.MATCHED, top_results=top, selected=best
        )

    @staticmethod
    def _guess_media_type(
        candidate: MigrationCandidate, parsed: ParsedFilename
    ) -> MediaType:
        """Deduit le type media depuis parsed ou le segment racine source."""
        if parsed.media_type != MediaType.UNKNOWN:
            return parsed.media_type
        media_root = (candidate.media_root or "").lower()
        if media_root.startswith("seri") or media_root.startswith("séri"):
            return MediaType.SERIES
        if media_root.startswith("anim"):
            return MediaType.SERIES
        return MediaType.MOVIE


class DefaultDetailsFetcher:
    """Implementation par defaut du _DetailsFetcher Protocol.

    Cable sur les clients TMDB/TVDB existants. Utilise par le plan_builder
    en mode raw pour recuperer le vote_average d'un match TMDB/TVDB.
    """

    def __init__(
        self,
        tmdb_client: TMDBClient,
        tvdb_client: TVDBClient,
    ) -> None:
        self._tmdb = tmdb_client
        self._tvdb = tvdb_client

    async def fetch(
        self, *, media_id: str, source: str
    ):
        if source == "tmdb":
            return await self._tmdb.get_details(media_id)
        if source == "tmdb_tv":
            return await self._tmdb.get_tv_details(media_id)
        if source == "tvdb":
            return await self._tvdb.get_details(media_id)
        return None


def candidates_to_dicts(
    results: list[SearchResult],
) -> list[dict]:
    """Convertit une liste de SearchResult en dicts JSON-serialisables.

    Utilise par MatchInfo.top_candidates (champ persiste dans plan.json) et
    par le CSV NEEDS_VALIDATION (etape 3).
    """
    out: list[dict] = []
    for r in results:
        entry: dict = {
            "title": r.title,
            "year": r.year,
            "score": r.score,
            "source": r.source,
        }
        # Le mappage id → tmdb_id/tvdb_id depend de la source.
        if r.source.startswith("tmdb"):
            entry["tmdb_id"] = _safe_int(r.id)
        elif r.source == "tvdb":
            entry["tvdb_id"] = _safe_int(r.id)
        if r.original_title and r.original_title != r.title:
            entry["original_title"] = r.original_title
        out.append(entry)
    return out


def _safe_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# Pattern : un mot constitué uniquement de 1 à 3 chiffres, entouré d'espaces
# (ou en début/fin de chaine). Capture les n° d'épisode "avalés" dans le
# titre par guessit (ex: "Rivalité de génies 02 Edison Tesla").
_EPISODE_NUMBER_PATTERN = re.compile(r"\s\d{1,3}(\s|$)")


def _truncate_title_at_first_number(title: str) -> Optional[str]:
    """Tronque le titre avant le premier 'mot' purement numérique (1-3 chiffres).

    Sert de fallback quand la recherche API retourne vide : guessit peut
    avoir absorbé un numéro d'épisode dans le titre. Retourne None si
    aucun nombre détecté ou si le titre tronqué serait vide.
    """
    if not title:
        return None
    match = _EPISODE_NUMBER_PATTERN.search(title)
    if match is None:
        return None
    truncated = title[: match.start()].strip()
    return truncated or None
