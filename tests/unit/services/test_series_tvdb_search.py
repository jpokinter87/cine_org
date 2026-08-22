"""Tests : recherche de series par nom directement sur TVDB.

L'API TVDB v4 a restaure la recherche par nom (/search?query=&type=series) que
la v3 avait retiree. Le detour par TMDB (search_tv + get_tv_external_ids pour
resoudre le tvdb_id) n'a donc plus lieu d'etre : les candidats sortent de TVDB
avec leur identifiant natif, et tout l'aval (episodes, completude) reste sur
TVDB par ID comme auparavant.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.core.ports.api_clients import MediaDetails, SearchResult
from src.services.workflow.pending_factory import _search_and_score_series


def _tvdb_cand(cid: str, title: str, year: int | None = 2023) -> SearchResult:
    return SearchResult(id=cid, title=title, year=year, source="tvdb")


class _StubMatcher:
    """Renvoie les resultats tels quels (deja tries) en leur posant un score."""

    def score_results(
        self,
        results,
        query_title,
        query_year=None,
        query_duration=None,
        is_series=False,
    ):
        for i, r in enumerate(results):
            r.score = 100.0 - i
        return list(results)


def _tvdb_stub(results: list[SearchResult]) -> AsyncMock:
    """Client TVDB simule : recherche + details non documentaires."""
    tvdb = AsyncMock()
    tvdb._api_key = "x" * 32
    tvdb.search = AsyncMock(return_value=results)
    tvdb.get_details = AsyncMock(
        return_value=MediaDetails(id="1", title="X", genres=("Drama",))
    )
    return tvdb


@pytest.mark.asyncio
async def test_recherche_directe_sur_tvdb():
    """Les candidats viennent de TVDB : source=tvdb, id = identifiant TVDB."""
    tvdb = _tvdb_stub([_tvdb_cand("403245", "Silo")])

    result = await _search_and_score_series(
        "Silo", None, _StubMatcher(), tvdb, series_cache={}
    )

    assert len(result) == 1
    assert result[0].source == "tvdb"
    assert result[0].id == "403245"
    assert result[0].title == "Silo"
    tvdb.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_filtre_par_annee():
    """Un candidat dont l'annee diverge du fichier est ecarte."""
    tvdb = _tvdb_stub([_tvdb_cand("1", "Silo", 2023), _tvdb_cand("2", "Silo", 2017)])

    result = await _search_and_score_series(
        "Silo", 2023, _StubMatcher(), tvdb, series_cache={}
    )

    assert [c.id for c in result] == ["1"]


@pytest.mark.asyncio
async def test_bornage_8_candidats():
    """Le nombre de candidats proposes reste borne, comme avant la bascule."""
    tvdb = _tvdb_stub([_tvdb_cand(str(i), f"S{i}") for i in range(12)])

    result = await _search_and_score_series(
        "S", None, _StubMatcher(), tvdb, series_cache={}
    )

    assert len(result) == 8


@pytest.mark.asyncio
async def test_sans_cle_tvdb():
    """Pas de cle TVDB -> liste vide (garde alignee sur le chemin film)."""
    tvdb = AsyncMock()
    tvdb._api_key = None

    result = await _search_and_score_series("X", None, _StubMatcher(), tvdb)

    assert result == []


@pytest.mark.asyncio
async def test_erreur_tvdb_renvoie_liste_vide():
    """Une erreur TVDB n'interrompt pas le workflow."""
    tvdb = AsyncMock()
    tvdb._api_key = "x" * 32
    tvdb.search = AsyncMock(side_effect=RuntimeError("API down"))

    result = await _search_and_score_series(
        "X", None, _StubMatcher(), tvdb, series_cache={}
    )

    assert result == []


@pytest.mark.asyncio
async def test_cache_memoire_evite_les_recherches_redondantes():
    """Deux episodes de la meme serie ne declenchent qu'une recherche."""
    tvdb = _tvdb_stub([_tvdb_cand("403245", "Silo")])
    cache: dict = {}

    await _search_and_score_series(
        "Silo", 2023, _StubMatcher(), tvdb, series_cache=cache
    )
    await _search_and_score_series(
        "Silo", 2023, _StubMatcher(), tvdb, series_cache=cache
    )

    assert tvdb.search.await_count == 1


@pytest.mark.asyncio
async def test_filtre_documentaire_applique():
    """Les series documentaires restent ecartees apres la bascule."""
    tvdb = _tvdb_stub([_tvdb_cand("9", "Doc")])
    tvdb.get_details = AsyncMock(
        return_value=MediaDetails(id="9", title="Doc", genres=("Documentary",))
    )

    result = await _search_and_score_series(
        "Doc", None, _StubMatcher(), tvdb, series_cache={}
    )

    assert result == []
