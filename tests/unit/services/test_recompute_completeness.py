"""Tests : recalcul de la complétude des séries après un transfert."""

from __future__ import annotations

from datetime import date

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.core.ports.api_clients import EpisodeDetails
from src.infrastructure.persistence.models import EpisodeModel, SeriesModel
from src.services.completeness.recompute import recompute_completeness_for_series


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _epd(season, episode, air_date):
    return EpisodeDetails(
        id=f"{season}-{episode}", title="t", season_number=season,
        episode_number=episode, overview=None, air_date=air_date,
    )


class _StubTVDB:
    """Stub TVDB comptant les appels get_all_episodes par série."""

    def __init__(self, episodes_by_id: dict, raise_for: set | None = None):
        self._episodes_by_id = episodes_by_id
        self._raise_for = raise_for or set()
        self.calls: list[str] = []

    async def get_all_episodes(self, series_id):
        self.calls.append(str(series_id))
        if str(series_id) in self._raise_for:
            raise RuntimeError("TVDB down")
        return self._episodes_by_id.get(str(series_id), [])


def _add_series(session, tvdb_id, owned_episodes):
    """Crée une série + ses épisodes détenus (avec file_path)."""
    series = SeriesModel(title="S", tvdb_id=tvdb_id, completeness_status="incomplete")
    session.add(series)
    session.commit()
    session.refresh(series)
    for s, e in owned_episodes:
        session.add(
            EpisodeModel(
                series_id=series.id, season_number=s, episode_number=e,
                title=f"e{e}", file_path=f"/s/{s}x{e}.mkv",
            )
        )
    session.commit()
    return series.id


@pytest.mark.asyncio
async def test_recalcul_nominal_passe_complete():
    """Série dont tous les épisodes attendus sont détenus → status complete."""
    engine = _make_engine()
    with Session(engine) as session:
        sid = _add_series(session, 42, [(1, 1), (1, 2)])
        tvdb = _StubTVDB({"42": [_epd(1, 1, "2019-01-01"), _epd(1, 2, "2019-01-08")]})

        count = await recompute_completeness_for_series(
            session, tvdb, [sid], today=date(2026, 6, 23)
        )

        assert count == 1
        series = session.get(SeriesModel, sid)
        assert series.completeness_status == "complete"
        assert series.has_missing_episodes is False
        assert series.has_missing_seasons is False


@pytest.mark.asyncio
async def test_dedoublonnage_un_seul_appel_par_serie():
    """series_id répétés → get_all_episodes appelé une seule fois par série."""
    engine = _make_engine()
    with Session(engine) as session:
        sid = _add_series(session, 42, [(1, 1)])
        tvdb = _StubTVDB({"42": [_epd(1, 1, "2019-01-01")]})

        count = await recompute_completeness_for_series(
            session, tvdb, [sid, sid, sid], today=date(2026, 6, 23)
        )

        assert count == 1
        assert tvdb.calls == ["42"]


@pytest.mark.asyncio
async def test_series_id_inexistant_ignore():
    """Un series_id absent est ignoré sans crash."""
    engine = _make_engine()
    with Session(engine) as session:
        tvdb = _StubTVDB({})
        count = await recompute_completeness_for_series(
            session, tvdb, [999999], today=date(2026, 6, 23)
        )
        assert count == 0
        assert tvdb.calls == []


@pytest.mark.asyncio
async def test_echec_tvdb_isole_les_autres_continuent():
    """Une série en erreur TVDB n'interrompt pas les autres, pas de propagation."""
    engine = _make_engine()
    with Session(engine) as session:
        sid_ok = _add_series(session, 10, [(1, 1)])
        sid_ko = _add_series(session, 20, [(1, 1)])
        tvdb = _StubTVDB(
            {"10": [_epd(1, 1, "2019-01-01")], "20": [_epd(1, 1, "2019-01-01")]},
            raise_for={"20"},
        )

        count = await recompute_completeness_for_series(
            session, tvdb, [sid_ok, sid_ko], today=date(2026, 6, 23)
        )

        assert count == 1
        assert session.get(SeriesModel, sid_ok).completeness_status == "complete"


@pytest.mark.asyncio
async def test_liste_vide_retourne_zero():
    """Aucun series_id → retour 0, aucun appel TVDB."""
    engine = _make_engine()
    with Session(engine) as session:
        tvdb = _StubTVDB({})
        count = await recompute_completeness_for_series(
            session, tvdb, [], today=date(2026, 6, 23)
        )
        assert count == 0
        assert tvdb.calls == []
