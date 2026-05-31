"""Tests du resolveur d'equivalent TMDB par identifiant externe.

resolve_tmdb_tv_by_external_id privilegie les identifiants externes (tvdb_id,
puis imdb_id) a la recherche par titre, qui echoue pour les titres traduits.
strip_trailing_year normalise un titre du type « Utopia (2020) ».
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.core.ports.api_clients import SearchResult
from src.services.series_enricher import (
    resolve_tmdb_tv_by_external_id,
    strip_trailing_year,
)


def _result(id_: str) -> SearchResult:
    return SearchResult(id=id_, title="Detectorists", year=2014, source="tmdb")


@pytest.mark.asyncio
async def test_resolution_par_tvdb_id_n_appelle_pas_search_tv():
    """Avec un tvdb_id, on resout via find_by_external_id sans recherche titre."""
    client = MagicMock()
    client.find_by_external_id = AsyncMock(return_value=[_result("61828")])
    client.search_tv = AsyncMock(return_value=[])

    best = await resolve_tmdb_tv_by_external_id(client, tvdb_id=280847)

    assert best is not None
    assert best.id == "61828"
    client.find_by_external_id.assert_awaited_once_with("280847", "tvdb_id")
    client.search_tv.assert_not_called()


@pytest.mark.asyncio
async def test_repli_sur_imdb_id_quand_pas_de_tvdb():
    """Sans tvdb_id, on tente l'imdb_id."""
    client = MagicMock()
    client.find_by_external_id = AsyncMock(return_value=[_result("61828")])

    best = await resolve_tmdb_tv_by_external_id(client, imdb_id="tt4082744")

    assert best is not None
    assert best.id == "61828"
    client.find_by_external_id.assert_awaited_once_with("tt4082744", "imdb_id")


@pytest.mark.asyncio
async def test_echec_tvdb_bascule_sur_imdb():
    """Si la resolution tvdb_id echoue, on essaie l'imdb_id."""
    client = MagicMock()

    async def fake_find(external_id, source):
        if source == "tvdb_id":
            raise RuntimeError("boom")
        return [_result("61828")]

    client.find_by_external_id = AsyncMock(side_effect=fake_find)

    best = await resolve_tmdb_tv_by_external_id(
        client, tvdb_id=280847, imdb_id="tt4082744"
    )

    assert best is not None
    assert best.id == "61828"
    assert client.find_by_external_id.await_count == 2


@pytest.mark.asyncio
async def test_sans_identifiant_retourne_none():
    """Sans identifiant externe, retourne None sans appeler l'API."""
    client = MagicMock()
    client.find_by_external_id = AsyncMock()

    best = await resolve_tmdb_tv_by_external_id(client)

    assert best is None
    client.find_by_external_id.assert_not_called()


@pytest.mark.asyncio
async def test_resultat_vide_retourne_none():
    """Si find_by_external_id ne renvoie rien, retourne None."""
    client = MagicMock()
    client.find_by_external_id = AsyncMock(return_value=[])

    best = await resolve_tmdb_tv_by_external_id(client, tvdb_id=999999)

    assert best is None


def test_strip_trailing_year_retire_annee_finale():
    """« Utopia (2020) » -> « Utopia »."""
    assert strip_trailing_year("Utopia (2020)") == "Utopia"


def test_strip_trailing_year_sans_annee_inchange():
    """Un titre sans annee finale n'est pas modifie."""
    assert strip_trailing_year("Detectorists") == "Detectorists"


def test_strip_trailing_year_garde_parentheses_non_annee():
    """Une parenthese non-annee en fin de titre est conservee."""
    assert strip_trailing_year("Archer (2009) Vice") == "Archer (2009) Vice"
