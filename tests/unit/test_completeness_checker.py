"""Tests du calcul de complétude (CompletenessChecker.compute)."""

from datetime import date

import pytest

from src.core.ports.api_clients import EpisodeDetails
from src.services.completeness.completeness_checker import CompletenessChecker


class _StubTVDB:
    """Client TVDB minimal : renvoie une liste figée d'épisodes."""

    def __init__(self, episodes):
        self._episodes = episodes

    async def get_all_episodes(self, series_id):
        return self._episodes


def _ep(season, episode, air_date, title="t"):
    return EpisodeDetails(
        id=f"{season}-{episode}",
        title=title,
        season_number=season,
        episode_number=episode,
        overview=None,
        air_date=air_date,
    )


TODAY = date(2026, 6, 23)


@pytest.mark.asyncio
async def test_complete_when_all_aired_owned():
    """Aucun manquant → complete."""
    tvdb = _StubTVDB([_ep(1, 1, "2019-01-01"), _ep(1, 2, "2019-01-08")])
    checker = CompletenessChecker(tvdb)
    result = await checker.compute("1", owned={(1, 1), (1, 2)}, today=TODAY)
    assert result.status == "complete"
    assert result.missing_seasons == []
    assert result.missing_episodes == []
    assert result.expected_aired == 2
    assert result.owned == 2


@pytest.mark.asyncio
async def test_internal_hole_is_incomplete():
    """Un épisode du milieu manquant → incomplete + détail."""
    tvdb = _StubTVDB(
        [_ep(1, 1, "2019-01-01"), _ep(1, 2, "2019-01-08"), _ep(1, 3, "2019-01-15")]
    )
    checker = CompletenessChecker(tvdb)
    result = await checker.compute("1", owned={(1, 1), (1, 3)}, today=TODAY)
    assert result.status == "incomplete"
    assert result.missing_seasons == []
    assert [(m.season, m.episode) for m in result.missing_episodes] == [(1, 2)]


@pytest.mark.asyncio
async def test_interrupted_tail_is_incomplete():
    """Téléchargement arrêté : épisodes diffusés suivants manquants."""
    tvdb = _StubTVDB(
        [_ep(1, 1, "2019-01-01"), _ep(1, 2, "2019-01-08"), _ep(1, 3, "2019-01-15")]
    )
    checker = CompletenessChecker(tvdb)
    result = await checker.compute("1", owned={(1, 1)}, today=TODAY)
    assert result.status == "incomplete"
    assert [(m.season, m.episode) for m in result.missing_episodes] == [(1, 2), (1, 3)]


@pytest.mark.asyncio
async def test_future_episodes_not_counted():
    """Épisode à date future ou sans date → non compté."""
    tvdb = _StubTVDB(
        [_ep(1, 1, "2019-01-01"), _ep(1, 2, "2099-01-01"), _ep(1, 3, None)]
    )
    checker = CompletenessChecker(tvdb)
    result = await checker.compute("1", owned={(1, 1)}, today=TODAY)
    assert result.status == "complete"
    assert result.expected_aired == 1


@pytest.mark.asyncio
async def test_season_zero_and_episode_zero_excluded():
    """Saison 0 et épisode 0 (SxxE00) exclus de l'attendu."""
    tvdb = _StubTVDB(
        [_ep(0, 1, "2018-01-01"), _ep(1, 0, "2018-12-01"), _ep(1, 1, "2019-01-01")]
    )
    checker = CompletenessChecker(tvdb)
    result = await checker.compute("1", owned=set(), today=TODAY)
    assert result.expected_aired == 1
    assert result.status == "incomplete"
    assert [(m.season, m.episode) for m in result.missing_episodes] == [(1, 1)]


@pytest.mark.asyncio
async def test_fully_missing_season_listed_separately():
    """Une saison sans aucun épisode détenu apparaît dans missing_seasons."""
    tvdb = _StubTVDB(
        [
            _ep(1, 1, "2019-01-01"),
            _ep(2, 1, "2020-01-01"),
            _ep(2, 2, "2020-01-08"),
        ]
    )
    checker = CompletenessChecker(tvdb)
    result = await checker.compute("1", owned={(1, 1)}, today=TODAY)
    assert result.status == "incomplete"
    assert result.missing_seasons == [2]
    assert result.missing_episodes == []


@pytest.mark.asyncio
async def test_no_aired_episodes_is_complete():
    """Série sans épisode diffusé (toutes dates futures) → complete."""
    tvdb = _StubTVDB([_ep(1, 1, "2099-01-01")])
    checker = CompletenessChecker(tvdb)
    result = await checker.compute("1", owned=set(), today=TODAY)
    assert result.status == "complete"
    assert result.expected_aired == 0
