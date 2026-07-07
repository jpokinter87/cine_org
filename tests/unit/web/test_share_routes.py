"""Tests des endpoints /share (Partager / Départager + bandeau)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.infrastructure.persistence.models import ShareSessionModel
from src.services.share.exceptions import ShareConflict
from src.web.app import app


@pytest.fixture
def fake_service(monkeypatch):
    service = MagicMock()
    service.start_share = AsyncMock()
    service.stop_share = AsyncMock()
    service.get_active_share = MagicMock(return_value=None)
    container = MagicMock()
    container.share_service = MagicMock(return_value=service)
    previous = getattr(app.state, "container", None)
    app.state.container = container
    yield service
    app.state.container = previous


def test_status_empty_when_no_share(fake_service):
    with TestClient(app) as client:
        resp = client.get("/share/status")
    assert resp.status_code == 200
    assert "share-banner" in resp.text


def test_status_shows_title_when_active(fake_service):
    fake_service.get_active_share.return_value = ShareSessionModel(
        media_type="movie", media_id=1, title="Inception", folder_name="Inception (2010)"
    )
    with TestClient(app) as client:
        resp = client.get("/share/status")
    assert "Inception" in resp.text
    assert "Départager" in resp.text


def test_share_success_returns_unshare_button(fake_service):
    fake_service.start_share.return_value = ShareSessionModel(
        media_type="movie", media_id=5, title="X", folder_name="X (2000)"
    )
    with TestClient(app) as client:
        resp = client.post("/share/movies/5")
    assert resp.status_code == 200
    assert "Départager" in resp.text
    fake_service.start_share.assert_awaited_with("movie", 5, replace=False)


def test_share_conflict_returns_confirm_overlay(fake_service):
    active = ShareSessionModel(media_type="series", media_id=9, title="Autre", folder_name="Autre (2020)")
    fake_service.start_share.side_effect = ShareConflict(active)
    with TestClient(app) as client:
        resp = client.post("/share/movies/5")
    assert resp.status_code == 200
    assert "Remplacer" in resp.text  # overlay de confirmation
    assert "Autre" in resp.text


def test_stop_returns_share_button(fake_service):
    with TestClient(app) as client:
        resp = client.post("/share/stop")
    assert resp.status_code == 200
    fake_service.stop_share.assert_awaited()
