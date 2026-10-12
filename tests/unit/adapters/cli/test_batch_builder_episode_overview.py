"""Le résumé TVDB d'un épisode est conservé à l'import.

Le titre de l'épisode était récupéré sur TVDB mais son résumé était jeté :
19 253 épisodes sur 21 225 n'avaient pas de résumé en base.
"""

from unittest.mock import AsyncMock

import pytest

from src.adapters.cli.batch_builder import _fetch_tvdb_episode_info
from src.core.ports.api_clients import EpisodeDetails, MediaDetails


SERIES = MediaDetails(id="364009", title="Mouche", genres=("Comédie",))


def _tvdb(episode=None, error=None):
    tvdb = AsyncMock()
    tvdb._api_key = "cle"
    tvdb.get_details.return_value = SERIES
    if error:
        tvdb.get_episode_details.side_effect = error
    else:
        tvdb.get_episode_details.return_value = episode
    tvdb.get_season_episode_count.return_value = 6
    return tvdb


@pytest.mark.asyncio
async def test_returns_title_overview_genres_and_count():
    ep = EpisodeDetails(
        id="1",
        title="Épisode 3",
        season_number=1,
        episode_number=3,
        overview="Louise organise son propre anniversaire surprise.",
    )

    info = await _fetch_tvdb_episode_info(_tvdb(ep), "364009", 1, 3)

    assert info == (
        "Épisode 3",
        "Louise organise son propre anniversaire surprise.",
        SERIES,
        6,
    )


@pytest.mark.asyncio
async def test_unknown_episode_keeps_defaults():
    info = await _fetch_tvdb_episode_info(_tvdb(None), "364009", 1, 9)

    assert info == ("", None, SERIES, 6)


@pytest.mark.asyncio
async def test_api_error_is_swallowed():
    info = await _fetch_tvdb_episode_info(
        _tvdb(error=RuntimeError("TVDB indisponible")), "364009", 1, 1
    )

    assert info[0] == "" and info[1] is None


@pytest.mark.asyncio
async def test_without_client_returns_defaults():
    assert await _fetch_tvdb_episode_info(None, "364009", 1, 1) == (
        "",
        None,
        None,
        None,
    )
