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
from src.core.ports.api_clients import MediaDetails
from src.services.migration.matching import (
    DefaultDetailsFetcher,
    MatchKind,
    MigrationMatcher,
    _truncate_title_at_first_number,
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
    """Top1 ≥ 85 mais top2 trop proche (gap < 5) ET année non discriminante → AMBIGUOUS."""
    matcher = _make_matcher(
        parsed=_parsed("Match", year=2020),
        tmdb_results=[
            _result("1", "Match", year=2020),
            _result("2", "Match", year=2020),  # même titre+année → pas de tie-break
        ],
        ambiguity_gap=5.0,
    )
    cand = _candidate("Match_2020.mkv")

    out = await matcher.match(cand)

    # Les deux candidats vont scorer très haut et serré → ambigu (tie-break inutile).
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
    """Pour un film, on n'appelle ni search_tv ni TVDB.

    On fait deux appels TMDB search : un avec `year=` et un avec la query
    "{title} {year}" (helper partagé avec le workflow — TMDB ignore le
    param year et range mieux quand l'année est dans le texte).
    """
    matcher = _make_matcher(
        parsed=_parsed("Avatar", year=2009, media_type=MediaType.MOVIE),
        tmdb_results=[_result("19995", "Avatar", year=2009)],
    )
    cand = _candidate("Avatar (2009).mkv", media_root="Films")

    await matcher.match(cand)

    assert matcher._tmdb.search.call_count == 2
    matcher._tmdb.search_tv.assert_not_called()
    matcher._tvdb.search.assert_not_called()


@pytest.mark.asyncio
async def test_series_uses_tvdb_first_skips_tmdb_when_tvdb_hits():
    """Pour une série, TVDB d'abord. Si TVDB rend des résultats, on ne
    touche pas à TMDB (évite la fausse ambiguïté quand la même série
    remonte via les deux providers avec score ~100)."""
    matcher = _make_matcher(
        parsed=_parsed("Lost", year=2004, media_type=MediaType.SERIES),
        tmdb_tv_results=[_result("4607", "Lost", year=2004, source="tmdb_tv")],
        tvdb_results=[_result("73739", "Lost", year=2004, source="tvdb")],
    )
    cand = _candidate("Lost.S01E01.mkv", media_root="Séries")

    out = await matcher.match(cand)

    matcher._tvdb.search.assert_called_once()
    matcher._tmdb.search_tv.assert_not_called()
    matcher._tmdb.search.assert_not_called()
    assert out.kind == MatchKind.MATCHED
    assert out.selected is not None
    assert out.selected.source == "tvdb"


@pytest.mark.asyncio
async def test_series_fallback_tmdb_when_tvdb_empty():
    """Si TVDB rend 0 résultat, on fallback sur TMDB search_tv."""
    matcher = _make_matcher(
        parsed=_parsed("Yellowstone", year=2018, media_type=MediaType.SERIES),
        tmdb_tv_results=[
            _result("73586", "Yellowstone", year=2018, source="tmdb_tv")
        ],
        tvdb_results=[],
    )
    cand = _candidate("Yellowstone.S01E01.mkv", media_root="Séries")

    out = await matcher.match(cand)

    matcher._tvdb.search.assert_called_once()
    matcher._tmdb.search_tv.assert_called_once()
    assert out.kind == MatchKind.MATCHED
    assert out.selected is not None
    assert out.selected.source == "tmdb_tv"


@pytest.mark.asyncio
async def test_series_inferred_from_media_root_when_parsed_unknown():
    """Si le parser dit UNKNOWN, on regarde media_root pour décider series/film."""
    matcher = _make_matcher(
        parsed=_parsed("Lost", year=2004, media_type=MediaType.UNKNOWN),
        tvdb_results=[_result("73739", "Lost", year=2004, source="tvdb")],
    )
    cand = _candidate("Lost (2004).mkv", media_root="Séries")

    await matcher.match(cand)

    matcher._tvdb.search.assert_called_once()
    matcher._tmdb.search.assert_not_called()


# ---- DefaultDetailsFetcher : routage par source ---------------------------


@pytest.mark.asyncio
async def test_fetcher_tvdb_source_uses_tmdb_find_by_tvdb_id():
    """Pour source=tvdb, on traverse TMDB via /find?external_source=tvdb_id
    afin de récupérer le vote_average (TVDB v3 ne l'expose pas)."""
    tmdb = MagicMock()
    tmdb.find_by_tvdb_id = AsyncMock(
        return_value=MediaDetails(
            id="123", title="Arde Madrid", vote_average=8.3
        )
    )
    tvdb = MagicMock()
    tvdb.get_details = AsyncMock()

    fetcher = DefaultDetailsFetcher(tmdb_client=tmdb, tvdb_client=tvdb)
    details = await fetcher.fetch(media_id="343089", source="tvdb")

    tmdb.find_by_tvdb_id.assert_awaited_once_with("343089")
    tvdb.get_details.assert_not_called()
    assert details is not None
    assert details.vote_average == 8.3


@pytest.mark.asyncio
async def test_fetcher_tvdb_falls_back_to_tvdb_when_tmdb_not_found():
    """Si TMDB ne connaît pas le tvdb_id, on retombe sur tvdb.get_details
    (sans vote_average — bucket UNRATED, comportement legacy)."""
    tmdb = MagicMock()
    tmdb.find_by_tvdb_id = AsyncMock(return_value=None)
    tvdb_details = MediaDetails(id="999", title="Old Show")
    tvdb = MagicMock()
    tvdb.get_details = AsyncMock(return_value=tvdb_details)

    fetcher = DefaultDetailsFetcher(tmdb_client=tmdb, tvdb_client=tvdb)
    details = await fetcher.fetch(media_id="999", source="tvdb")

    tmdb.find_by_tvdb_id.assert_awaited_once()
    tvdb.get_details.assert_awaited_once_with("999")
    assert details is tvdb_details
    assert details.vote_average is None


@pytest.mark.asyncio
async def test_fetcher_tmdb_tv_source_uses_get_tv_details_directly():
    """Pour source=tmdb_tv, on appelle directement get_tv_details."""
    tmdb = MagicMock()
    tmdb.get_tv_details = AsyncMock(
        return_value=MediaDetails(id="73586", title="Yellowstone", vote_average=8.6)
    )
    tmdb.find_by_tvdb_id = AsyncMock()
    tvdb = MagicMock()
    tvdb.get_details = AsyncMock()

    fetcher = DefaultDetailsFetcher(tmdb_client=tmdb, tvdb_client=tvdb)
    details = await fetcher.fetch(media_id="73586", source="tmdb_tv")

    tmdb.get_tv_details.assert_awaited_once_with("73586")
    tmdb.find_by_tvdb_id.assert_not_called()
    tvdb.get_details.assert_not_called()
    assert details.vote_average == 8.6


@pytest.mark.asyncio
async def test_fetcher_tmdb_movie_source_uses_get_details():
    """Pour source=tmdb (film), on appelle directement get_details."""
    tmdb = MagicMock()
    tmdb.get_details = AsyncMock(
        return_value=MediaDetails(id="19995", title="Avatar", vote_average=7.6)
    )
    tvdb = MagicMock()

    fetcher = DefaultDetailsFetcher(tmdb_client=tmdb, tvdb_client=tvdb)
    details = await fetcher.fetch(media_id="19995", source="tmdb")

    tmdb.get_details.assert_awaited_once_with("19995")
    assert details.vote_average == 7.6


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


# ---- Tie-break par année --------------------------------------------------


@pytest.mark.asyncio
async def test_tiebreak_by_year_resolves_ambiguous_when_one_year_matches():
    """Top1 et top2 scorent 100, mais un seul match l'année parsée → MATCHED."""
    matcher = _make_matcher(
        parsed=_parsed("The Leftovers", year=2014, media_type=MediaType.SERIES),
        tmdb_tv_results=[
            _result("4607", "The Leftovers", year=2014, source="tmdb_tv"),
            _result("9999", "The Leftovers", year=2018, source="tmdb_tv"),
        ],
    )
    cand = _candidate("The.Leftovers.2014.S03E01.mkv", media_root="Séries")

    out = await matcher.match(cand)

    assert out.kind == MatchKind.MATCHED
    assert out.selected is not None
    assert out.selected.id == "4607"
    assert out.selected.year == 2014


@pytest.mark.asyncio
async def test_tiebreak_returns_ambiguous_when_multiple_year_matches():
    """Si plusieurs candidats matchent la même année → AMBIGUOUS (pas de gain)."""
    matcher = _make_matcher(
        parsed=_parsed("Match", year=2020),
        tmdb_results=[
            _result("1", "Match", year=2020),
            _result("2", "Match", year=2020),
        ],
    )
    cand = _candidate("Match.2020.mkv")

    out = await matcher.match(cand)

    assert out.kind == MatchKind.AMBIGUOUS


@pytest.mark.asyncio
async def test_tiebreak_disabled_when_query_year_missing():
    """Sans année parsée, on ne peut pas trier → AMBIGUOUS classique."""
    matcher = _make_matcher(
        parsed=_parsed("Match", year=None),
        tmdb_results=[
            _result("1", "Match", year=2020),
            _result("2", "Match", year=2018),
        ],
    )
    cand = _candidate("Match.mkv")

    out = await matcher.match(cand)

    assert out.kind == MatchKind.AMBIGUOUS


# ---- Fallback titre tronqué pour NO_RESULTS ------------------------------


def test_truncate_title_returns_segment_before_first_number():
    """Tronque au premier mot purement numérique (1-3 chiffres)."""
    assert (
        _truncate_title_at_first_number("Rivalité de génies 02 Edison Tesla")
        == "Rivalité de génies"
    )
    assert (
        _truncate_title_at_first_number("Cosmos 13 Voyage to the Edge")
        == "Cosmos"
    )


def test_truncate_title_returns_none_when_no_number():
    assert _truncate_title_at_first_number("Avatar") is None
    assert _truncate_title_at_first_number("The Matrix Reloaded") is None


def test_truncate_title_handles_empty_or_only_number():
    assert _truncate_title_at_first_number("") is None
    # "42" : pas d'espace avant le nombre → pas tronqué (titre commence par)
    assert _truncate_title_at_first_number("42") is None


def test_truncate_title_preserves_year_like_numbers_in_middle():
    """Une année (4 chiffres) ne doit pas déclencher la troncature."""
    # "Movie 2015 Edition" : 2015 a 4 chiffres → pas tronqué
    assert _truncate_title_at_first_number("Movie 2015 Edition") is None


@pytest.mark.asyncio
async def test_movie_fallback_truncated_title_when_first_search_empty():
    """Si la recherche initiale TMDB est vide (les 2 variantes), retenter
    avec le titre tronqué (qui passe lui aussi par les 2 variantes)."""
    matcher = _make_matcher(
        parsed=_parsed("Rivalité de génies 02 Edison Tesla", year=2015),
        tmdb_results=[],
    )
    # 1ère recherche (titre+year=2015) → vide
    # 2e recherche ("titre 2015") → vide
    # 3e recherche (titre tronqué + year=2015) → 1 match
    # 4e recherche ("titre tronqué 2015") → 1 match (dédupliqué par id)
    matcher._tmdb.search = AsyncMock(
        side_effect=[
            [],
            [],
            [_result("123", "Rivalité de génies", year=2015)],
            [_result("123", "Rivalité de génies", year=2015)],
        ]
    )
    cand = _candidate("Rivalité.de.génies.02.Edison.Tesla.2015.mkv")

    out = await matcher.match(cand)

    assert matcher._tmdb.search.call_count == 4
    # Premier appel : titre original
    assert matcher._tmdb.search.call_args_list[0].args[0] == (
        "Rivalité de génies 02 Edison Tesla"
    )
    # Troisième appel : titre tronqué
    assert matcher._tmdb.search.call_args_list[2].args[0] == "Rivalité de génies"
    # Top1 score >= 85 (titre exact) → MATCHED.
    assert out.kind == MatchKind.MATCHED


@pytest.mark.asyncio
async def test_movie_no_fallback_when_no_number_in_title():
    """Pas de chiffre dans le titre → pas de retry tronqué (mais on fait
    quand même la double recherche TMDB search + "{title} {year}")."""
    matcher = _make_matcher(
        parsed=_parsed("Avatar", year=2009),
        tmdb_results=[],
    )
    matcher._tmdb.search = AsyncMock(return_value=[])
    cand = _candidate("Avatar.2009.mkv")

    out = await matcher.match(cand)

    # 2 appels (search + "title year") mais pas de 3e avec titre tronqué.
    assert matcher._tmdb.search.call_count == 2
    assert out.kind == MatchKind.NO_RESULTS


@pytest.mark.asyncio
async def test_series_fallback_truncated_title_when_first_search_empty():
    """Mode séries : fallback titre tronqué passe lui aussi par
    TVDB-then-TMDB. Ici, le titre original est vide partout, le titre
    tronqué match via TMDB après que TVDB ait rendu vide."""
    matcher = _make_matcher(
        parsed=_parsed(
            "Cosmos 13 Voyage", year=2014, media_type=MediaType.SERIES
        ),
    )
    # TVDB : vide pour titre original puis pour titre tronqué (4 appels au total
    # — 2 pour chaque tentative parce que filter_by_episode_count est appelé
    # uniquement après scoring, mais ici sans candidats).
    matcher._tvdb.search = AsyncMock(side_effect=[[], []])
    matcher._tmdb.search_tv = AsyncMock(
        side_effect=[
            [],  # titre original "Cosmos 13 Voyage" → vide
            [_result("4607", "Cosmos", year=2014, source="tmdb_tv")],
        ]
    )
    cand = _candidate("Cosmos.13.S01E01.mkv", media_root="Séries")

    out = await matcher.match(cand)

    # TVDB appelé pour les deux tentatives, TMDB appelé en fallback les deux fois
    assert matcher._tvdb.search.call_count == 2
    assert matcher._tmdb.search_tv.call_count == 2
    assert matcher._tmdb.search_tv.call_args_list[1].args[0] == "Cosmos"
    assert out.kind == MatchKind.MATCHED


@pytest.mark.asyncio
async def test_no_fallback_when_first_search_already_returns_results():
    """Si la 1re recherche trouve déjà, pas de fallback titre tronqué.

    On fait quand même la double recherche TMDB (search + "{title} {year}")
    parce que c'est le comportement workflow, mais pas la troncature.
    """
    matcher = _make_matcher(
        parsed=_parsed("Test 02 Episode", year=2020),
        tmdb_results=[_result("1", "Test 02 Episode", year=2020)],
    )
    cand = _candidate("Test.02.Episode.2020.mkv")

    await matcher.match(cand)
    # 2 appels (search + "title year") mais pas de 3e avec titre tronqué.
    assert matcher._tmdb.search.call_count == 2


@pytest.mark.asyncio
async def test_tiebreak_ignores_candidates_below_threshold():
    """Si un candidat <85 match l'année mais pas le top1 ≥85 → AMBIGUOUS (pas de promotion d'un mauvais match)."""
    matcher = _make_matcher(
        parsed=_parsed("Foo", year=2019),
        tmdb_results=[
            _result("1", "Foo", year=2020, score=0),  # top1 ~95% (titre exact)
            _result("2", "Foo", year=2020, score=0),  # top2 ~95% (collision)
            _result("3", "Random", year=2019, score=0),  # match année mais titre nul → score bas
        ],
    )
    cand = _candidate("Foo.2019.mkv")

    out = await matcher.match(cand)

    # Top1 et Top2 trop serrés ET aucun avec score >=85 ne match 2019 → AMBIGUOUS
    assert out.kind == MatchKind.AMBIGUOUS
