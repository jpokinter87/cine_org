"""Tests du réglage jellyfin_dir dans Settings."""

from pathlib import Path

from src.config import Settings


def test_jellyfin_dir_default():
    """Par défaut, jellyfin_dir vaut /media/Serveur/JellyfinLib."""
    settings = Settings()
    assert settings.jellyfin_dir == Path("/media/Serveur/JellyfinLib")


def test_jellyfin_dir_env_override(monkeypatch):
    """CINEORG_JELLYFIN_DIR surcharge la valeur et étend ~."""
    monkeypatch.setenv("CINEORG_JELLYFIN_DIR", "~/JellyfinTest")
    settings = Settings()
    assert settings.jellyfin_dir == Path.home() / "JellyfinTest"
