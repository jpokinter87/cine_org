"""
Tests pour MigrationMatcher (etape 2 — mode raw).

Le matcher prend un fichier physique decouvert sur un vieux NAS, parse le
nom, interroge TMDB (films) ou TMDB+TVDB (series), score les resultats
via MatcherService, et retourne un MatchOutcome (MATCHED / AMBIGUOUS /
NO_RESULTS).

Les clients API et le parser sont mockes : ce module teste l'orchestration
et la classification, pas les services sous-jacents.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.ports.api_clients import SearchResult
from src.core.value_objects.parsed_info import MediaType, ParsedFilename
from src.services.matcher import MatcherService
from src.services.migration.dataclasses import MigrationCandidate
from src.services.migration.matching import (
    MatchKind,
    MatchOutcome,
    MigrationMatcher,
    candidates_to_dicts,
)


# ---- Fixtures -------------------------------------------------------------


def _candidate(
    name: str,
    *,
    media_root: str = "Films",
    relative_category: str = "Drame/D",
    is_symlink: bool = False,
) -> MigrationCandidate:
    return MigrationCandidate(
        symlink_path=Path(f"/old_nas/{media_root}/{name}"),
        target_path=Path(f"/old_nas/{media_root}/{name}"),
        media_root=media_root,
        relative_category=relative_category,
        size_bytes=1_000_000_000,
        is_broken=False,
        already_on_destination=False,
        is_symlink=is_symlink,
    )


def _parsed(
    title: str,
    *,
    year: int | None = None,
    media_type: MediaType = MediaType.MOVIE,
    season: int | None = None,
    episode: int | None = None,
) -> ParsedFilename:
    return ParsedFilename(
        title=title,
        year=year,
        media_type=media_type,
        season=season,
        episode=episode,
    )


def _result(
    rid: str,
    title: str,
    *,
    year: int | None = None,
    score: float = 0.0,
    source: str = "tmdb",
    original_title: str | None = None,
) -> SearchResult:
    return SearchResult(
        id=rid,
        title=title,
        original_title=original_title,
        year=year,
        score=score,
        source=source,
    )


def _make_matcher(
    *,
    parsed: ParsedFilename,
    tmdb_results: list[SearchResult] | None = None,
    tmdb_tv_results: list[SearchResult] | None = None,
    tvdb_results: list[SearchResult] | None = None,
    threshold: float = 85.0,
    ambiguity_gap: float = 5.0,
) -> MigrationMatcher:
    parser = MagicMock()
    parser.parse.return_value = parsed

    tmdb = MagicMock()
    tmdb.search = AsyncMock(return_value=tmdb_results or [])
    tmdb.search_tv = AsyncMock(return_value=tmdb_tv_results or [])

    tvdb = MagicMock()
    tvdb.search = AsyncMock(return_value=tvdb_results or [])

    return MigrationMatcher(
        parser=parser,
        tmdb_client=tmdb,
        tvdb_client=tvdb,
        matcher_service=MatcherService(),
        threshold=threshold,
        ambiguity_gap=ambiguity_gap,
    )


# ---- Classification MATCHED / AMBIGUOUS / NO_RESULTS ----------------------


@pytest.mark.asyncio
async def test_matched_when_unique_strong_score():
    """Un seul candidat avec score >= 85, runner-up loin → MATCHED."""
    matcher = _make_matcher(
        parsed=_parsed("Avatar", year=2009),
        tmdb_results=[
            _result("19995", "Avatar", year=2009),
            _result("9999", "Avatar 2", year=2022),
        ],
    )
    cand = _candidate("Avatar (2009).mkv")

    out = await matcher.match(cand)

    assert out.kind == MatchKind.MATCHED
    assert out.selected is not None
    assert out.selected.id == "19995"
    assert out.selected.score >= 85
    assert len(out.top_results) == 2


@pytest.mark.asyncio
async def test_ambiguous_when_top_score_below_threshold():
    """Meilleur score < seuil → AMBIGUOUS, selected reste None."""
    matcher = _make_matcher(
        parsed=_parsed("Vraiment Specifique Tres Long Titre", year=2020),
        tmdb_results=[
            # Titre completement different → score titre tres bas.
            _result("1", "Autre Truc", year=2020),
        ],
    )
    cand = _candidate("Vraiment_Specifique.mkv")

    out = await matcher.match(cand)

    assert out.kind == MatchKind.AMBIGUOUS
    assert out.selected is None
    assert len(out.top_results) == 1


@pytest.mark.asyncio
async def test_ambiguous_when_runner_up_too_close():
    """Top1 ≥ 85 mais top2 trop proche (gap < 5) → AMBIGUOUS."""
    matcher = _make_matcher(
        parsed=_parsed("Match", year=2020),
        tmdb_results=[
            _result("1", "Match", year=2020),
            _result("2", "Match", year=2021),  # même titre, année voisine
        ],
        ambiguity_gap=5.0,
    )
    cand = _candidate("Match_2020.mkv")

    out = await matcher.match(cand)

    # Les deux candidats vont scorer très haut et serré → ambigu.
    assert out.kind == MatchKind.AMBIGUOUS
    assert len(out.top_results) == 2


@pytest.mark.asyncio
async def test_no_results_when_api_returns_empty():
    """Aucun résultat API → NO_RESULTS, top vide."""
    matcher = _make_matcher(
        parsed=_parsed("Film Inexistant", year=2024),
        tmdb_results=[],
    )
    cand = _candidate("Film_Inexistant.mkv")

    out = await matcher.match(cand)

    assert out.kind == MatchKind.NO_RESULTS
    assert out.top_results == []
    assert out.selected is None


@pytest.mark.asyncio
async def test_no_results_when_parsed_title_empty():
    """Titre parsé vide → pas d'appel API, NO_RESULTS direct."""
    matcher = _make_matcher(
        parsed=_parsed("", year=2020),  # titre vide
        tmdb_results=[_result("1", "Test", year=2020, score=99)],
    )
    cand = _candidate("???.mkv")

    out = await matcher.match(cand)

    assert out.kind == MatchKind.NO_RESULTS
    # Le client TMDB ne doit pas être appelé quand le titre est vide.
    matcher._tmdb.search.assert_not_called()


# ---- Routage Films vs Séries ----------------------------------------------


@pytest.mark.asyncio
async def test_movie_uses_tmdb_search_only():
    """Pour un film, on n'appelle ni search_tv ni TVDB."""
    matcher = _make_matcher(
        parsed=_parsed("Avatar", year=2009, media_type=MediaType.MOVIE),
        tmdb_results=[_result("19995", "Avatar", year=2009)],
    )
    cand = _candidate("Avatar (2009).mkv", media_root="Films")

    await matcher.match(cand)

    matcher._tmdb.search.assert_called_once()
    matcher._tmdb.search_tv.assert_not_called()
    matcher._tvdb.search.assert_not_called()


@pytest.mark.asyncio
async def test_series_merges_tmdb_tv_and_tvdb():
    """Pour une série, on agrège search_tv (TMDB) + search (TVDB)."""
    matcher = _make_matcher(
        parsed=_parsed("Lost", year=2004, media_type=MediaType.SERIES),
        tmdb_tv_results=[_result("4607", "Lost", year=2004, source="tmdb_tv")],
        tvdb_results=[_result("73739", "Lost", year=2004, source="tvdb")],
    )
    cand = _candidate("Lost.S01E01.mkv", media_root="Séries")

    out = await matcher.match(cand)

    matcher._tmdb.search_tv.assert_called_once()
    matcher._tvdb.search.assert_called_once()
    matcher._tmdb.search.assert_not_called()
    # Au moins un des deux doit ressortir en MATCHED ou AMBIGUOUS.
    assert out.kind in (MatchKind.MATCHED, MatchKind.AMBIGUOUS)
    assert len(out.top_results) >= 1


@pytest.mark.asyncio
async def test_series_inferred_from_media_root_when_parsed_unknown():
    """Si le parser dit UNKNOWN, on regarde media_root pour décider series/film."""
    matcher = _make_matcher(
        parsed=_parsed("Lost", year=2004, media_type=MediaType.UNKNOWN),
        tmdb_tv_results=[_result("4607", "Lost", year=2004, source="tmdb_tv")],
    )
    cand = _candidate("Lost (2004).mkv", media_root="Séries")

    await matcher.match(cand)

    matcher._tmdb.search_tv.assert_called_once()
    matcher._tmdb.search.assert_not_called()


# ---- candidates_to_dicts (sérialisation JSON) -----------------------------


def test_candidates_to_dicts_maps_tmdb_id_for_tmdb_source():
    results = [
        _result("19995", "Avatar", year=2009, score=95.0, source="tmdb"),
    ]

    out = candidates_to_dicts(results)

    assert out == [
        {
            "title": "Avatar",
            "year": 2009,
            "score": 95.0,
            "source": "tmdb",
            "tmdb_id": 19995,
        }
    ]


def test_candidates_to_dicts_maps_tvdb_id_for_tvdb_source():
    results = [
        _result("73739", "Lost", year=2004, score=100.0, source="tvdb"),
    ]

    out = candidates_to_dicts(results)

    assert out == [
        {
            "title": "Lost",
            "year": 2004,
            "score": 100.0,
            "source": "tvdb",
            "tvdb_id": 73739,
        }
    ]


def test_candidates_to_dicts_includes_original_title_when_different():
    results = [
        _result(
            "1",
            "Les Évadés",
            year=1994,
            score=100.0,
            source="tmdb",
            original_title="The Shawshank Redemption",
        ),
    ]

    out = candidates_to_dicts(results)

    assert out[0]["original_title"] == "The Shawshank Redemption"


def test_candidates_to_dicts_omits_id_when_unparseable():
    results = [
        _result("not-a-number", "Anomalie", year=2020, source="tmdb"),
    ]

    out = candidates_to_dicts(results)

    assert "tmdb_id" in out[0]
    assert out[0]["tmdb_id"] is None
