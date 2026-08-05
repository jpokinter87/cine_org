"""Tests : recherche de séries via TMDB + résolution du tvdb_id.

La recherche par nom TVDB v3 (/search/series?name=) a été retirée (404). On
cherche désormais via TMDB (search_tv) puis on résout le tvdb_id via
get_tv_external_ids pour garder tout l'aval (épisodes, complétude) sur TVDB.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.core.ports.api_clients import SearchResult
from src.services.workflow.pending_factory import (
    _resolve_tvdb_candidates,
    _search_and_score_series,
)


def _tmdb_cand(cid: str, title: str, score: float) -> SearchResult:
    return SearchResult(id=cid, title=title, year=2023, score=score, source="tmdb")


@pytest.mark.asyncio
async def test_resolution_nominale():
    """Un candidat TMDB avec tvdb_id devient un candidat source=tvdb, id=tvdb_id."""
    tmdb = AsyncMock()
    tmdb.get_tv_external_ids = AsyncMock(
        return_value={"imdb_id": "tt14688458", "tvdb_id": 403245}
    )
    scored = [_tmdb_cand("125988", "Silo", 100.0)]

    result = await _resolve_tvdb_candidates(scored, tmdb)

    assert len(result) == 1
    assert result[0].source == "tvdb"
    assert result[0].id == "403245"
    assert result[0].title == "Silo"
    assert result[0].score == 100.0


@pytest.mark.asyncio
async def test_ecarte_sans_tvdb_id():
    """Un résultat TMDB sans tvdb_id (None) est écarté."""
    tmdb = AsyncMock()
    tmdb.get_tv_external_ids = AsyncMock(
        return_value={"imdb_id": "tt1", "tvdb_id": None}
    )
    result = await _resolve_tvdb_candidates([_tmdb_cand("1", "Obscure", 100.0)], tmdb)
    assert result == []


@pytest.mark.asyncio
async def test_ecarte_si_external_ids_none():
    """get_tv_external_ids renvoyant None (404) → candidat écarté."""
    tmdb = AsyncMock()
    tmdb.get_tv_external_ids = AsyncMock(return_value=None)
    result = await _resolve_tvdb_candidates([_tmdb_cand("1", "X", 100.0)], tmdb)
    assert result == []


@pytest.mark.asyncio
async def test_bornage_8_candidats():
    """Seuls les 8 meilleurs candidats sont résolus (get_tv_external_ids ≤ 8 appels)."""
    tmdb = AsyncMock()
    tmdb.get_tv_external_ids = AsyncMock(
        return_value={"imdb_id": "tt1", "tvdb_id": 999}
    )
    scored = [_tmdb_cand(str(i), f"S{i}", 100.0 - i) for i in range(12)]

    result = await _resolve_tvdb_candidates(scored, tmdb)

    assert tmdb.get_tv_external_ids.await_count == 8
    assert len(result) == 8


@pytest.mark.asyncio
async def test_erreur_external_ids_ecarte_et_continue():
    """Une erreur sur un candidat l'écarte sans interrompre les autres."""
    tmdb = AsyncMock()

    async def _ext(cid):
        if cid == "boom":
            raise RuntimeError("API down")
        return {"imdb_id": "tt1", "tvdb_id": 555}

    tmdb.get_tv_external_ids = AsyncMock(side_effect=_ext)
    scored = [_tmdb_cand("boom", "Boom", 100.0), _tmdb_cand("ok", "Ok", 90.0)]

    result = await _resolve_tvdb_candidates(scored, tmdb)

    assert [c.id for c in result] == ["555"]
    assert result[0].source == "tvdb"


class _StubMatcher:
    """Renvoie les résultats tels quels (déjà triés) en leur posant un score."""

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


@pytest.mark.asyncio
async def test_search_and_score_series_bout_en_bout():
    """search_tv -> score -> résolution tvdb_id -> filtre doc : candidats source=tvdb."""
    tmdb = AsyncMock()
    tmdb._api_key = "x" * 32
    tmdb.search_tv = AsyncMock(
        return_value=[
            SearchResult(id="125988", title="Silo", year=2023, source="tmdb"),
            SearchResult(id="777", title="Silo Autre", year=2017, source="tmdb"),
        ]
    )

    async def _ext(cid):
        return {"tvdb_id": 403245} if cid == "125988" else {"tvdb_id": None}

    tmdb.get_tv_external_ids = AsyncMock(side_effect=_ext)

    # tvdb_client : uniquement utilisé par filter_documentary_series (get_details)
    from src.core.ports.api_clients import MediaDetails

    tvdb = AsyncMock()
    tvdb.get_details = AsyncMock(
        return_value=MediaDetails(id="403245", title="Silo", genres=("Drama",))
    )

    result = await _search_and_score_series(
        "Silo", None, _StubMatcher(), tmdb, tvdb, series_cache={}
    )

    assert len(result) == 1
    assert result[0].source == "tvdb"
    assert result[0].id == "403245"
    tmdb.search_tv.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_and_score_series_sans_cle_tmdb():
    """Pas de clé TMDB -> liste vide (garde alignée sur le chemin film)."""
    tmdb = AsyncMock()
    tmdb._api_key = None
    result = await _search_and_score_series(
        "X", None, _StubMatcher(), tmdb, AsyncMock()
    )
    assert result == []
