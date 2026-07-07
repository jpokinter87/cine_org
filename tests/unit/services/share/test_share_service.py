from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.infrastructure.persistence.models import MovieModel
from src.infrastructure.persistence.repositories.share_session_repository import (
    ShareSessionRepository,
)
from src.services.share.exceptions import ShareConflict, ShareError
from src.services.share.share_service import ShareService


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _movie(session, tmp_path) -> MovieModel:
    f = tmp_path / "film.mkv"
    f.write_bytes(b"x")
    m = MovieModel(
        title="Inception", year=2010, tmdb_id=1, file_path=str(f), symlink_path=None
    )
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def _service(session, tmp_path, *, funnel=None, jellyfin=None) -> ShareService:
    return ShareService(
        session=session,
        partage_dir=tmp_path / "Partage",
        jellyfin_client=jellyfin or AsyncMock(),
        funnel=funnel
        or MagicMock(
            enable=MagicMock(return_value=True),
            disable=MagicMock(return_value=True),
            is_on=MagicMock(return_value=False),
        ),
        idle_timeout=timedelta(minutes=30),
        hard_cap=timedelta(hours=6),
    )


@pytest.mark.asyncio
async def test_start_share_movie_records_state_and_enables_funnel(tmp_path):
    session = _session()
    m = _movie(session, tmp_path)
    funnel = MagicMock(
        enable=MagicMock(return_value=True), disable=MagicMock(return_value=True)
    )
    jellyfin = AsyncMock()
    service = _service(session, tmp_path, funnel=funnel, jellyfin=jellyfin)

    active = await service.start_share("movie", m.id)

    assert active.title == "Inception"
    funnel.enable.assert_called_once()
    jellyfin.refresh_library.assert_awaited()  # Partage Films rafraîchie
    assert (tmp_path / "Partage" / "Films" / "Inception (2010)" / "movie.nfo").exists()


@pytest.mark.asyncio
async def test_start_when_active_without_replace_raises_conflict(tmp_path):
    session = _session()
    m = _movie(session, tmp_path)
    service = _service(session, tmp_path)
    await service.start_share("movie", m.id)
    with pytest.raises(ShareConflict):
        await service.start_share("movie", m.id)


@pytest.mark.asyncio
async def test_start_with_replace_tears_down_previous(tmp_path):
    session = _session()
    m = _movie(session, tmp_path)
    funnel = MagicMock(
        enable=MagicMock(return_value=True), disable=MagicMock(return_value=True)
    )
    service = _service(session, tmp_path, funnel=funnel)
    await service.start_share("movie", m.id)
    await service.start_share("movie", m.id, replace=True)
    # un seul actif
    assert ShareSessionRepository(session).get_active() is not None


@pytest.mark.asyncio
async def test_stop_share_disables_funnel_and_clears(tmp_path):
    session = _session()
    m = _movie(session, tmp_path)
    funnel = MagicMock(
        enable=MagicMock(return_value=True), disable=MagicMock(return_value=True)
    )
    service = _service(session, tmp_path, funnel=funnel)
    await service.start_share("movie", m.id)
    await service.stop_share()
    assert ShareSessionRepository(session).get_active() is None
    funnel.disable.assert_called()
    assert not (tmp_path / "Partage" / "Films").exists()


@pytest.mark.asyncio
async def test_tick_hard_cap_tears_down(tmp_path):
    session = _session()
    m = _movie(session, tmp_path)
    service = _service(session, tmp_path)
    active = await service.start_share("movie", m.id)
    later = active.started_at + timedelta(hours=6, minutes=1)
    result = await service.run_monitor_tick(later)
    assert result == "hard_cap"
    assert ShareSessionRepository(session).get_active() is None


@pytest.mark.asyncio
async def test_tick_idle_tears_down_when_no_playback(tmp_path):
    session = _session()
    m = _movie(session, tmp_path)
    jellyfin = AsyncMock()
    jellyfin.get_active_sessions.return_value = []  # personne ne lit
    service = _service(session, tmp_path, jellyfin=jellyfin)
    active = await service.start_share("movie", m.id)
    later = active.started_at + timedelta(minutes=31)
    result = await service.run_monitor_tick(later)
    assert result == "idle"
    assert ShareSessionRepository(session).get_active() is None


@pytest.mark.asyncio
async def test_tick_playing_keeps_share_and_touches(tmp_path):
    session = _session()
    m = _movie(session, tmp_path)
    jellyfin = AsyncMock()
    jellyfin.get_active_sessions.return_value = [
        {"NowPlayingItem": {"Path": str(tmp_path / "Partage" / "Films" / "x.mkv")}}
    ]
    service = _service(session, tmp_path, jellyfin=jellyfin)
    active = await service.start_share("movie", m.id)
    later = active.started_at + timedelta(minutes=31)
    result = await service.run_monitor_tick(later)
    assert result is None
    assert ShareSessionRepository(session).get_active() is not None


@pytest.mark.asyncio
async def test_reconcile_startup_disables_orphan_funnel(tmp_path):
    session = _session()
    funnel = MagicMock(
        is_on=MagicMock(return_value=True), disable=MagicMock(return_value=True)
    )
    service = _service(session, tmp_path, funnel=funnel)
    await service.reconcile_on_startup()  # aucun partage actif mais funnel allumé
    funnel.disable.assert_called_once()


@pytest.mark.asyncio
async def test_teardown_deactivates_in_db_even_if_jellyfin_refresh_fails(tmp_path):
    # B1 : un Jellyfin injoignable au démontage ne doit pas laisser un partage
    # « fantôme » actif en base (bandeau bloqué, Départager qui rejoue l'échec).
    session = _session()
    m = _movie(session, tmp_path)
    funnel = MagicMock(
        enable=MagicMock(return_value=True), disable=MagicMock(return_value=True)
    )
    jellyfin = AsyncMock()
    service = _service(session, tmp_path, funnel=funnel, jellyfin=jellyfin)
    await service.start_share("movie", m.id)  # refresh OK au démarrage
    jellyfin.refresh_library.side_effect = RuntimeError("jellyfin down")
    await service.stop_share()
    assert ShareSessionRepository(session).get_active() is None
    funnel.disable.assert_called()


@pytest.mark.asyncio
async def test_start_share_raises_share_error_when_jellyfin_unreachable(tmp_path):
    # B2 : une erreur réseau Jellyfin pendant « Partager » doit remonter en
    # ShareError (message propre, pas de 500) et laisser un état nettoyé.
    session = _session()
    m = _movie(session, tmp_path)
    funnel = MagicMock(
        enable=MagicMock(return_value=True), disable=MagicMock(return_value=True)
    )
    jellyfin = AsyncMock()
    jellyfin.refresh_library.side_effect = RuntimeError("jellyfin down")
    service = _service(session, tmp_path, funnel=funnel, jellyfin=jellyfin)
    with pytest.raises(ShareError):
        await service.start_share("movie", m.id)
    assert ShareSessionRepository(session).get_active() is None
    funnel.enable.assert_not_called()
    assert not (tmp_path / "Partage" / "Films").exists()


@pytest.mark.asyncio
async def test_tick_playing_detected_with_remapped_docker_prefix(tmp_path):
    # R1 : Jellyfin (conteneur Docker) peut remonter un préfixe de montage
    # différent de l'hôte ; la détection de lecture doit rester robuste tant que
    # la structure .../<Partage>/Films|Series/ est préservée.
    session = _session()
    m = _movie(session, tmp_path)
    jellyfin = AsyncMock()
    jellyfin.get_active_sessions.return_value = [
        {
            "NowPlayingItem": {
                "Path": "/data/JellyfinLib/Partage/Films/Inception (2010)/Inception (2010).mkv"
            }
        }
    ]
    service = _service(session, tmp_path, jellyfin=jellyfin)
    active = await service.start_share("movie", m.id)
    later = active.started_at + timedelta(minutes=31)
    result = await service.run_monitor_tick(later)
    assert result is None
    assert ShareSessionRepository(session).get_active() is not None
