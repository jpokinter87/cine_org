"""Tests du ShareSessionRepository (table d'état du partage Jellyfin)."""

from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine

from src.infrastructure.persistence.repositories.share_session_repository import (
    ShareSessionRepository,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_no_active_share_initially():
    repo = ShareSessionRepository(_session())
    assert repo.get_active() is None


def test_start_then_get_active():
    repo = ShareSessionRepository(_session())
    model = repo.start(
        media_type="movie",
        media_id=42,
        title="Inception",
        folder_name="Inception (2010)",
    )
    assert model.is_active is True
    active = repo.get_active()
    assert active is not None
    assert active.media_id == 42
    assert active.title == "Inception"


def test_touch_played_updates_timestamp():
    repo = ShareSessionRepository(_session())
    model = repo.start(
        media_type="series", media_id=7, title="Gomorra", folder_name="Gomorra (2014)"
    )
    when = datetime(2026, 6, 30, 21, 0, 0)
    repo.touch_played(model, when)
    assert repo.get_active().last_played_at == when


def test_deactivate_clears_active():
    repo = ShareSessionRepository(_session())
    model = repo.start(
        media_type="movie", media_id=1, title="X", folder_name="X (2000)"
    )
    repo.deactivate(model)
    assert repo.get_active() is None
