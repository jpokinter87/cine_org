"""
Detection des oeuvres deja presentes dans la base CineOrg (mode raw).

Pour eviter de re-rapatrier des fichiers physiques alors que l'oeuvre est
deja en DB CineOrg avec un file_path valide (cas typique : meme contenu
deja transfere depuis une autre source — encodage different mais oeuvre
identique). Le bucket ALREADY_IN_LIBRARY permet de les skipper.

Approche : on prend le top candidate du MatchOutcome (meme en AMBIGUOUS,
le top a souvent le bon tmdb_id/tvdb_id), on lookup en DB par cet ID, et
on verifie qu'un fichier est associe (file_path non null).
"""

from __future__ import annotations

from typing import Optional

from src.core.ports.api_clients import SearchResult
from src.core.ports.parser import IFilenameParser
from src.core.value_objects.parsed_info import MediaType
from src.infrastructure.persistence.repositories.episode_repository import (
    SQLModelEpisodeRepository,
)
from src.infrastructure.persistence.repositories.movie_repository import (
    SQLModelMovieRepository,
)
from src.infrastructure.persistence.repositories.series_repository import (
    SQLModelSeriesRepository,
)
from src.services.migration._helpers import safe_int
from src.services.migration.dataclasses import MigrationCandidate
from src.services.migration.matching import MatchOutcome


class LibraryPresenceChecker:
    """
    Determine si l'oeuvre identifiee est deja en bibliotheque CineOrg.

    Args:
        movie_repo: Repository Movie (lookup par tmdb_id).
        series_repo: Repository Series (lookup par tmdb_id ou tvdb_id).
        episode_repo: Repository Episode (lookup par series_id+season+episode).
        parser: Parser de noms de fichiers pour extraire saison/episode.
    """

    def __init__(
        self,
        *,
        movie_repo: SQLModelMovieRepository,
        series_repo: SQLModelSeriesRepository,
        episode_repo: SQLModelEpisodeRepository,
        parser: IFilenameParser,
    ) -> None:
        self._movie_repo = movie_repo
        self._series_repo = series_repo
        self._episode_repo = episode_repo
        self._parser = parser

    def find_existing_path(
        self, candidate: MigrationCandidate, outcome: MatchOutcome
    ) -> Optional[str]:
        """Retourne le file_path en DB si l'oeuvre est deja rapatriee, sinon None.

        On utilise le top candidate de outcome (MATCHED ou AMBIGUOUS) pour
        identifier l'oeuvre. Pour les series, on extrait saison/episode du
        filename via le parser et on lookup l'EpisodeModel correspondant.
        """
        if not outcome.top_results:
            return None
        top = outcome.top_results[0]
        parsed = self._parser.parse(candidate.symlink_path.name)
        if self._is_series(top, parsed, candidate):
            return self._check_series(top, parsed)
        return self._check_movie(top)

    @staticmethod
    def _is_series(
        top: SearchResult, parsed, candidate: MigrationCandidate
    ) -> bool:
        if parsed.media_type == MediaType.SERIES:
            return True
        if top.source == "tvdb" or top.source == "tmdb_tv":
            return True
        media_root = (candidate.media_root or "").lower()
        return media_root.startswith("seri") or media_root.startswith("séri")

    def _check_movie(self, top: SearchResult) -> Optional[str]:
        if not top.source.startswith("tmdb"):
            return None
        tmdb_id = safe_int(top.id)
        if tmdb_id is None:
            return None
        movie = self._movie_repo.get_by_tmdb_id(tmdb_id)
        if movie is None or not movie.file_path:
            return None
        return movie.file_path

    def _check_series(self, top: SearchResult, parsed) -> Optional[str]:
        if parsed.season is None or parsed.episode is None:
            return None
        ext_id = safe_int(top.id)
        if ext_id is None:
            return None
        series = None
        if top.source == "tvdb":
            series = self._series_repo.get_by_tvdb_id(ext_id)
        elif top.source.startswith("tmdb"):
            series = self._series_repo.get_by_tmdb_id(ext_id)
        if series is None or series.id is None:
            return None
        episodes = self._episode_repo.get_by_series(
            str(series.id), parsed.season, parsed.episode
        )
        for ep in episodes:
            if ep.file_path:
                return ep.file_path
        return None
