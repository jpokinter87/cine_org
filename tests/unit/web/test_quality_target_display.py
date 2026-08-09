"""Tests : affichage de la qualité à rechercher dans le cartouche de complétude.

Savoir qu'il manque « S01E03 » ne dit pas en quelle version le chercher : le
cartouche affiche la qualité dominante des épisodes déjà présents.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.testclient import TestClient

from src.core.ports.api_clients import EpisodeDetails
from src.infrastructure.persistence.models import EpisodeModel, SeriesModel


class _StubTVDB:
    async def get_all_episodes(self, series_id):
        return [
            EpisodeDetails(
                id=f"1-{n}",
                title=f"Épisode {n}",
                season_number=1,
                episode_number=n,
                overview=None,
                air_date="1967-09-29",
            )
            for n in (1, 2, 3)
        ]


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def client(engine, monkeypatch):
    from src.infrastructure.persistence import database as db_mod
    from src.web.routes.library import detail as detail_mod

    def _fake_get_session():
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(db_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(detail_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(detail_mod.router, prefix="/library")
    container = MagicMock()
    container.tvdb_client.return_value = _StubTVDB()
    container.share_service.return_value.get_active_share.return_value = None
    app.state.container = container
    return TestClient(app)


def _incomplete_series(engine, episodes: list[dict]) -> int:
    """Série incomplète (S01E03 manquant) détenant les épisodes donnés."""
    with Session(engine) as s:
        series = SeriesModel(
            title="Le Prisonnier",
            year=1967,
            tvdb_id=74805,
            completeness_status="incomplete",
            has_missing_episodes=True,
            completeness_missing_json=json.dumps(
                {
                    "missing_seasons": [],
                    "missing_episodes": [
                        {
                            "season": 1,
                            "episode": 3,
                            "air_date": "1967-10-13",
                            "title": "A, B et C",
                        }
                    ],
                    "expected_aired": 3,
                    "owned": 2,
                    "source": "tvdb",
                }
            ),
        )
        s.add(series)
        s.commit()
        s.refresh(series)
        sid = series.id
        for spec in episodes:
            s.add(
                EpisodeModel(
                    series_id=sid,
                    season_number=spec.get("season", 1),
                    episode_number=spec["episode"],
                    title=f"Épisode {spec['episode']}",
                    resolution=spec.get("resolution", "1920x1080"),
                    codec_video=spec.get("video", "x264"),
                    codec_audio=spec.get("audio", "AC3"),
                    languages_json=json.dumps(spec.get("languages", ["fr", "en"])),
                    file_path=f"/storage/s01e{spec['episode']:02d}.mkv",
                )
            )
        s.commit()
    return sid


def test_series_detail_shows_quality_target(engine, client):
    """La fiche affiche la qualité dominante des épisodes détenus."""
    sid = _incomplete_series(engine, [{"episode": 1}, {"episode": 2}])

    resp = client.get(f"/library/series/{sid}")

    assert resp.status_code == 200
    assert "Qualité à rechercher" in resp.text
    assert "1080p" in resp.text
    assert "x264" in resp.text
    assert "FR + EN" in resp.text


def test_quality_target_survives_recheck(engine, client):
    """Le fragment renvoyé par « Revérifier » porte aussi la qualité cible."""
    sid = _incomplete_series(engine, [{"episode": 1}, {"episode": 2}])

    resp = client.post(f"/library/series/{sid}/completeness/recheck")

    assert resp.status_code == 200
    assert "Qualité à rechercher" in resp.text
    assert "1080p" in resp.text


def test_heterogeneous_series_is_flagged(engine, client):
    """Une série de qualité hétérogène est signalée comme telle."""
    sid = _incomplete_series(
        engine,
        [
            {"episode": 1, "resolution": "1920x1080"},
            {"episode": 2, "resolution": "1280x720"},
        ],
    )

    resp = client.get(f"/library/series/{sid}")

    assert "qualité hétérogène" in resp.text


def test_no_target_without_technical_metadata(engine, client):
    """Sans métadonnées techniques, aucun encart n'est affiché."""
    sid = _incomplete_series(
        engine,
        [
            {
                "episode": 1,
                "resolution": None,
                "video": None,
                "audio": None,
                "languages": [],
            }
        ],
    )

    resp = client.get(f"/library/series/{sid}")

    assert resp.status_code == 200
    assert "Qualité à rechercher" not in resp.text
