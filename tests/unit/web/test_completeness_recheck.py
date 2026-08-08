"""Tests : revérification de la complétude depuis la fiche série.

Le verdict de complétude est persisté en base ; il devient périmé dès que la
série gagne des épisodes par un autre chemin que le transfert (ré-association,
import manuel). Le bouton du cartouche « Pourquoi cette série est incomplète »
relance la vérification TVDB pour cette seule série et rend le cartouche à jour.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.testclient import TestClient

from src.core.ports.api_clients import EpisodeDetails
from src.infrastructure.persistence.models import EpisodeModel, SeriesModel


def _epd(season: int, episode: int, air_date: str) -> EpisodeDetails:
    return EpisodeDetails(
        id=f"{season}-{episode}",
        title=f"Épisode {episode}",
        season_number=season,
        episode_number=episode,
        overview=None,
        air_date=air_date,
    )


class _StubTVDB:
    """Stub TVDB : retourne des épisodes ou lève une erreur réseau."""

    def __init__(self, episodes: list | None = None, fail: bool = False) -> None:
        self._episodes = episodes or []
        self._fail = fail

    async def get_all_episodes(self, series_id):
        if self._fail:
            raise RuntimeError("TVDB indisponible")
        return self._episodes


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
def make_client(engine, monkeypatch):
    """Fabrique un client de test dont le container expose un TVDB donné."""

    def _factory(tvdb) -> TestClient:
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
        container.tvdb_client.return_value = tvdb
        app.state.container = container
        return TestClient(app)

    return _factory


def _stale_series(engine, owned: int = 3, tvdb_id: int | None = 74805) -> int:
    """Série marquée incomplète alors qu'elle détient `owned` épisodes."""
    with Session(engine) as s:
        series = SeriesModel(
            title="Le Prisonnier",
            year=1967,
            tvdb_id=tvdb_id,
            completeness_status="incomplete",
            has_missing_episodes=True,
            completeness_missing_json=(
                '{"missing_seasons": [], "missing_episodes": '
                '[{"season": 1, "episode": 1, "air_date": "1967-09-29", '
                '"title": "L\'arrivée"}], "expected_aired": 3, "owned": 2, '
                '"source": "tvdb"}'
            ),
        )
        s.add(series)
        s.commit()
        s.refresh(series)
        sid = series.id
        for ep in range(1, owned + 1):
            s.add(
                EpisodeModel(
                    series_id=sid,
                    season_number=1,
                    episode_number=ep,
                    title=f"Épisode {ep}",
                    file_path=f"/storage/s01e{ep:02d}.mkv",
                )
            )
        s.commit()
    return sid


def test_recheck_met_la_serie_a_jour_en_complete(engine, make_client):
    """Tous les épisodes diffusés sont présents → verdict persisté « complete »."""
    sid = _stale_series(engine, owned=3)
    tvdb = _StubTVDB(
        [_epd(1, 1, "1967-09-29"), _epd(1, 2, "1967-10-06"), _epd(1, 3, "1967-10-13")]
    )
    client = make_client(tvdb)

    resp = client.post(f"/library/series/{sid}/completeness/recheck")

    assert resp.status_code == 200
    with Session(engine) as s:
        series = s.get(SeriesModel, sid)
        assert series.completeness_status == "complete"
        assert series.has_missing_episodes is False
    # Le fragment confirme le nouveau verdict et retire le badge « Incomplet ».
    assert "complète" in resp.text
    assert 'id="incomplete-badge-zone"' in resp.text
    assert "badge-incomplete" not in resp.text


def test_recheck_conserve_le_cartouche_si_toujours_incomplete(engine, make_client):
    """Des épisodes manquent encore → cartouche re-rendu avec les manques."""
    sid = _stale_series(engine, owned=2)
    tvdb = _StubTVDB(
        [_epd(1, 1, "1967-09-29"), _epd(1, 2, "1967-10-06"), _epd(1, 3, "1967-10-13")]
    )
    client = make_client(tvdb)

    resp = client.post(f"/library/series/{sid}/completeness/recheck")

    assert resp.status_code == 200
    with Session(engine) as s:
        assert s.get(SeriesModel, sid).completeness_status == "incomplete"
    assert "S01E03" in resp.text
    assert "2 / 3" in resp.text
    assert "badge-incomplete" in resp.text


def test_recheck_signale_l_echec_tvdb_sans_ecraser_le_verdict(engine, make_client):
    """TVDB en erreur → message d'échec, verdict précédent conservé."""
    sid = _stale_series(engine, owned=3)
    client = make_client(_StubTVDB(fail=True))

    resp = client.post(f"/library/series/{sid}/completeness/recheck")

    assert resp.status_code == 200
    with Session(engine) as s:
        assert s.get(SeriesModel, sid).completeness_status == "incomplete"
    assert "échec" in resp.text.lower()


def test_recheck_serie_sans_tvdb_id_non_verifiable(engine, make_client):
    """Sans identifiant TVDB, la complétude n'est pas vérifiable."""
    sid = _stale_series(engine, owned=3, tvdb_id=None)
    client = make_client(_StubTVDB([]))

    resp = client.post(f"/library/series/{sid}/completeness/recheck")

    assert resp.status_code == 200
    with Session(engine) as s:
        assert s.get(SeriesModel, sid).completeness_status is None
    assert "vérifiable" in resp.text


def test_recheck_serie_inexistante_404(engine, make_client):
    """Un id inconnu retourne 404."""
    client = make_client(_StubTVDB([]))
    resp = client.post("/library/series/999999/completeness/recheck")
    assert resp.status_code == 404
