"""Test de TVDBClient.get_all_episodes (agrégation multi-saisons)."""

import pytest

from src.adapters.api.tvdb_client import TVDBClient


@pytest.mark.asyncio
async def test_get_all_episodes_aggregates_seasons(monkeypatch):
    """Agrège les épisodes de toutes les saisons jusqu'à la première vide."""
    client = TVDBClient(api_key="x", cache=None)

    async def fake_ensure_token():
        return None

    async def fake_get_client():
        return object()

    seasons = {
        1: [
            {
                "id": 11,
                "episodeName": "Pilote",
                "airedSeason": 1,
                "airedEpisodeNumber": 1,
                "firstAired": "2019-01-01",
                "overview": "o1",
            },
            {
                "id": 12,
                "episodeName": "Deux",
                "airedSeason": 1,
                "airedEpisodeNumber": 2,
                "firstAired": "2019-01-08",
                "overview": "o2",
            },
        ],
        2: [
            {
                "id": 21,
                "episodeName": "S2E1",
                "airedSeason": 2,
                "airedEpisodeNumber": 1,
                "firstAired": "2020-01-01",
                "overview": "o3",
            },
        ],
    }

    async def fake_raw(self, http_client, series_id, season, language):
        return seasons.get(season, [])

    monkeypatch.setattr(client, "_ensure_token", fake_ensure_token)
    monkeypatch.setattr(client, "_get_client", fake_get_client)
    monkeypatch.setattr(
        TVDBClient, "_fetch_all_season_episodes_raw", fake_raw, raising=True
    )

    episodes = await client.get_all_episodes("999")

    assert len(episodes) == 3
    keys = {(e.season_number, e.episode_number) for e in episodes}
    assert keys == {(1, 1), (1, 2), (2, 1)}
    by_key = {(e.season_number, e.episode_number): e for e in episodes}
    assert by_key[(1, 1)].air_date == "2019-01-01"
    assert by_key[(1, 1)].title == "Pilote"


@pytest.mark.asyncio
async def test_get_all_episodes_skips_none_episode_number(monkeypatch):
    """Un épisode sans numéro est ignoré."""
    client = TVDBClient(api_key="x", cache=None)

    async def fake_ensure_token():
        return None

    async def fake_get_client():
        return object()

    async def fake_raw(self, http_client, series_id, season, language):
        if season == 1:
            return [
                {"id": 1, "airedSeason": 1, "airedEpisodeNumber": None},
                {
                    "id": 2,
                    "airedSeason": 1,
                    "airedEpisodeNumber": 1,
                    "firstAired": "2019-01-01",
                    "episodeName": "ok",
                },
            ]
        return []

    monkeypatch.setattr(client, "_ensure_token", fake_ensure_token)
    monkeypatch.setattr(client, "_get_client", fake_get_client)
    monkeypatch.setattr(
        TVDBClient, "_fetch_all_season_episodes_raw", fake_raw, raising=True
    )

    episodes = await client.get_all_episodes("1")
    assert len(episodes) == 1
    assert episodes[0].episode_number == 1
