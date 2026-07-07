"""Tests des réglages de configuration Jellyfin pour le partage (SP3b)."""

from pathlib import Path

from src.config import Settings


def test_jellyfin_sharing_defaults():
    s = Settings()
    assert s.jellyfin_url == "http://localhost:8096"
    assert s.jellyfin_api_key is None
    assert s.jellyfin_partage_dir == Path("/media/Serveur/JellyfinLib/Partage")
    assert s.jellyfin_api_enabled is False


def test_jellyfin_sharing_env_override(monkeypatch):
    monkeypatch.setenv("CINEORG_JELLYFIN_URL", "http://192.168.1.15:8096")
    monkeypatch.setenv("CINEORG_JELLYFIN_API_KEY", "secret")
    monkeypatch.setenv("CINEORG_JELLYFIN_PARTAGE_DIR", "~/jf/Partage")
    s = Settings()
    assert s.jellyfin_url == "http://192.168.1.15:8096"
    assert s.jellyfin_api_key == "secret"
    assert s.jellyfin_partage_dir == Path("~/jf/Partage").expanduser()
    assert s.jellyfin_api_enabled is True
