"""Tests : le type du média se décide sur le FICHIER, pas sur la source API.

Régression corrigée : `is_series = candidate_source == "tvdb"` faisait basculer
dans la branche « film » tout épisode validé via l'onglet ID IMDB, qui produit
un candidat de source `tmdb_tv`. Résultat observé sur « Miracle Workers » :
un film fantôme portant l'ID TV de TMDB, au lieu des épisodes S01E01..E05.

La source `tmdb_tv` reste légitime pour un **film** classé en série sur TMDB
(cas « Tout le bleu du ciel ») : ce chemin ne doit pas régresser.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.cli.batch_builder import resolve_media_type

_EPISODE = "Miracle.Workers.2019.S01E01.Multi.1080p.AMZN.WEB-DL.H.264-Papaya.mkv"
_FILM = "Tout le bleu du ciel (2025) MULTi 1080p WEB H264.mkv"


@pytest.fixture
def tmdb_client():
    client = MagicMock()
    client._api_key = "test_key"
    client.get_tv_external_ids = AsyncMock(return_value={"tvdb_id": 342818})
    return client


@pytest.mark.asyncio
async def test_source_tvdb_inchangee(tmdb_client):
    """Un candidat TVDB est une série, sans appel API supplémentaire."""
    result = await resolve_media_type("tvdb", "342818", _EPISODE, tmdb_client)

    assert result == (True, "tvdb", "342818")
    tmdb_client.get_tv_external_ids.assert_not_called()


@pytest.mark.asyncio
async def test_tmdb_tv_sur_episode_bascule_en_serie(tmdb_client):
    """tmdb_tv + fichier SxxExx → série, réécrite sur l'ID TVDB."""
    result = await resolve_media_type("tmdb_tv", "78950", _EPISODE, tmdb_client)

    assert result == (True, "tvdb", "342818")
    tmdb_client.get_tv_external_ids.assert_awaited_once_with("78950")


@pytest.mark.asyncio
async def test_tmdb_tv_sur_film_reste_un_film(tmdb_client):
    """Non-régression : film classé série sur TMDB, sans SxxExx → film."""
    result = await resolve_media_type("tmdb_tv", "259622", _FILM, tmdb_client)

    assert result == (False, "tmdb_tv", "259622")
    tmdb_client.get_tv_external_ids.assert_not_called()


@pytest.mark.asyncio
async def test_episode_sans_tvdb_id_est_bloque(tmdb_client):
    """Pas de tvdb_id → on bloque plutôt que de créer un film fantôme."""
    tmdb_client.get_tv_external_ids = AsyncMock(return_value={"tvdb_id": None})

    assert await resolve_media_type("tmdb_tv", "78950", _EPISODE, tmdb_client) is None


@pytest.mark.asyncio
async def test_episode_erreur_api_est_bloque(tmdb_client):
    """Erreur API → on bloque : ranger un épisode en film est irréversible."""
    tmdb_client.get_tv_external_ids = AsyncMock(side_effect=RuntimeError("API down"))

    assert await resolve_media_type("tmdb_tv", "78950", _EPISODE, tmdb_client) is None


@pytest.mark.asyncio
async def test_episode_sans_client_tmdb_est_bloque():
    """Sans client TMDB, le tvdb_id est irrécupérable → blocage."""
    assert await resolve_media_type("tmdb_tv", "78950", _EPISODE, None) is None


@pytest.mark.asyncio
async def test_source_tmdb_reste_un_film(tmdb_client):
    """Choix explicite d'un film : on n'écrase pas la décision de l'utilisateur."""
    result = await resolve_media_type("tmdb", "550", _EPISODE, tmdb_client)

    assert result == (False, "tmdb", "550")
