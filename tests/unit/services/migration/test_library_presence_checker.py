"""
Tests pour LibraryPresenceChecker (étape 2 de l'amélioration matcher).

Le checker court-circuite la classification mode raw pour les œuvres
déjà en DB CineOrg avec un file_path valide (déjà rapatriées via une
autre source). Évite les transferts redondants.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from src.core.entities.media import Episode, Movie, Series
from src.core.ports.api_clients import SearchResult
from src.core.value_objects.parsed_info import MediaType, ParsedFilename
from src.services.migration.dataclasses import MigrationCandidate
from src.services.migration.library_presence_checker import (
    LibraryPresenceChecker,
)
from src.services.migration.matching import MatchKind, MatchOutcome


# ---- Fixtures -------------------------------------------------------------


def _candidate(name: str, *, media_root: str = "Films") -> MigrationCandidate:
    return MigrationCandidate(
        symlink_path=Path(f"/old/{media_root}/{name}"),
        target_path=Path(f"/old/{media_root}/{name}"),
        media_root=media_root,
        relative_category="",
        size_bytes=1_000_000,
        is_broken=False,
        already_on_destination=False,
        is_symlink=False,
    )


def _outcome(top: SearchResult, *, kind: MatchKind = MatchKind.MATCHED) -> MatchOutcome:
    return MatchOutcome(
        kind=kind,
        top_results=[top],
        selected=top if kind == MatchKind.MATCHED else None,
    )


def _make_checker(
    *,
    movie_in_db: Movie | None = None,
    series_in_db: Series | None = None,
    episodes_in_db: list[Episode] | None = None,
    parsed: ParsedFilename | None = None,
) -> LibraryPresenceChecker:
    movie_repo = MagicMock()
    movie_repo.get_by_tmdb_id.return_value = movie_in_db

    series_repo = MagicMock()
    series_repo.get_by_tvdb_id.return_value = series_in_db
    series_repo.get_by_tmdb_id.return_value = series_in_db

    episode_repo = MagicMock()
    episode_repo.get_by_series.return_value = episodes_in_db or []

    parser = MagicMock()
    parser.parse.return_value = parsed or ParsedFilename(
        title="Avatar", year=2009, media_type=MediaType.MOVIE
    )

    return LibraryPresenceChecker(
        movie_repo=movie_repo,
        series_repo=series_repo,
        episode_repo=episode_repo,
        parser=parser,
    )


# ---- Films ---------------------------------------------------------------


def test_movie_in_db_with_file_path_returns_existing_path():
    movie = Movie(
        id="42", tmdb_id=19995, title="Avatar", year=2009,
        file_path="/storage/Films/SF/A/Avatar (2009).mkv",
    )
    checker = _make_checker(movie_in_db=movie)
    cand = _candidate("Avatar.2009.mkv")
    outcome = _outcome(SearchResult(id="19995", title="Avatar", year=2009, source="tmdb"))

    assert (
        checker.find_existing_path(cand, outcome)
        == "/storage/Films/SF/A/Avatar (2009).mkv"
    )
    checker._movie_repo.get_by_tmdb_id.assert_called_once_with(19995)


def test_movie_in_db_without_file_path_returns_none():
    """Le Movie est en DB mais pas de fichier → on ne skippe pas (oeuvre orpheline)."""
    movie = Movie(id="42", tmdb_id=19995, title="Avatar", year=2009, file_path=None)
    checker = _make_checker(movie_in_db=movie)
    cand = _candidate("Avatar.2009.mkv")
    outcome = _outcome(SearchResult(id="19995", title="Avatar", year=2009, source="tmdb"))

    assert checker.find_existing_path(cand, outcome) is None


def test_movie_not_in_db_returns_none():
    checker = _make_checker(movie_in_db=None)
    cand = _candidate("Avatar.2009.mkv")
    outcome = _outcome(SearchResult(id="19995", title="Avatar", year=2009, source="tmdb"))

    assert checker.find_existing_path(cand, outcome) is None


# ---- Séries --------------------------------------------------------------


def test_series_episode_in_db_with_file_path_returns_existing():
    series = Series(id="7", tvdb_id=73739, title="Lost", year=2004)
    episode = Episode(
        id="55", series_id="7", season_number=1, episode_number=1,
        file_path="/storage/Séries/L/Lost (2004)/Saison 01/Lost (2004) - S01E01.mkv",
    )
    checker = _make_checker(
        series_in_db=series,
        episodes_in_db=[episode],
        parsed=ParsedFilename(
            title="Lost", year=2004, media_type=MediaType.SERIES, season=1, episode=1
        ),
    )
    cand = _candidate("Lost.S01E01.mkv", media_root="Séries")
    outcome = _outcome(
        SearchResult(id="73739", title="Lost", year=2004, source="tvdb")
    )

    result = checker.find_existing_path(cand, outcome)
    assert result is not None
    assert "Lost (2004) - S01E01.mkv" in result


def test_series_in_db_but_episode_not_yet_returns_none():
    series = Series(id="7", tvdb_id=73739, title="Lost", year=2004)
    checker = _make_checker(
        series_in_db=series,
        episodes_in_db=[],  # pas d'épisode en DB
        parsed=ParsedFilename(
            title="Lost", year=2004, media_type=MediaType.SERIES, season=1, episode=1
        ),
    )
    cand = _candidate("Lost.S01E01.mkv", media_root="Séries")
    outcome = _outcome(
        SearchResult(id="73739", title="Lost", year=2004, source="tvdb")
    )

    assert checker.find_existing_path(cand, outcome) is None


def test_series_via_tmdb_tv_source():
    """Match par source tmdb_tv → lookup get_by_tmdb_id sur series_repo."""
    series = Series(id="7", tmdb_id=4607, title="Lost", year=2004)
    episode = Episode(
        id="55", series_id="7", season_number=1, episode_number=1,
        file_path="/storage/Lost/E1.mkv",
    )
    checker = _make_checker(
        series_in_db=series,
        episodes_in_db=[episode],
        parsed=ParsedFilename(
            title="Lost", year=2004, media_type=MediaType.SERIES, season=1, episode=1
        ),
    )
    cand = _candidate("Lost.S01E01.mkv", media_root="Séries")
    outcome = _outcome(
        SearchResult(id="4607", title="Lost", year=2004, source="tmdb_tv")
    )

    assert checker.find_existing_path(cand, outcome) is not None
    checker._series_repo.get_by_tmdb_id.assert_called_with(4607)


def test_series_without_season_episode_returns_none():
    """Sans saison/épisode parsable, on ne peut pas localiser l'épisode → skip."""
    checker = _make_checker(
        parsed=ParsedFilename(
            title="Lost", media_type=MediaType.SERIES, season=None, episode=None
        ),
    )
    cand = _candidate("Lost.mkv", media_root="Séries")
    outcome = _outcome(
        SearchResult(id="73739", title="Lost", source="tvdb")
    )

    assert checker.find_existing_path(cand, outcome) is None


def test_works_with_ambiguous_outcome_using_top_candidate():
    """Même en AMBIGUOUS, on peut utiliser le top candidate pour identifier l'œuvre."""
    movie = Movie(
        id="42", tmdb_id=19995, title="Avatar", year=2009,
        file_path="/storage/Avatar.mkv",
    )
    checker = _make_checker(movie_in_db=movie)
    cand = _candidate("Avatar.2009.mkv")
    # AMBIGUOUS : pas de selected, mais top_results contient le bon match.
    outcome = MatchOutcome(
        kind=MatchKind.AMBIGUOUS,
        top_results=[
            SearchResult(id="19995", title="Avatar", year=2009, source="tmdb"),
            SearchResult(id="9999", title="Avatar", year=2018, source="tmdb"),
        ],
        selected=None,
    )

    assert checker.find_existing_path(cand, outcome) == "/storage/Avatar.mkv"


def test_no_top_results_returns_none():
    checker = _make_checker()
    cand = _candidate("Mystère.mkv")
    outcome = MatchOutcome(kind=MatchKind.NO_RESULTS, top_results=[])

    assert checker.find_existing_path(cand, outcome) is None
