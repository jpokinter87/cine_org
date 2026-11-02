"""Tests des réglages Deluge et de la rétention des hardlinks dans Settings."""

from src.config import Settings


def test_hardlink_retention_default_is_90_days():
    """La durée de seed par défaut est de 90 jours."""
    assert Settings(_env_file=None).hardlink_retention_days == 90


def test_deluge_defaults_disabled():
    """Sans identifiants, l'intégration Deluge est inactive."""
    settings = Settings(_env_file=None)
    assert settings.deluge_host == "127.0.0.1"
    assert settings.deluge_port == 58846
    assert settings.deluge_enabled is False


def test_deluge_enabled_with_credentials(monkeypatch):
    """Identifiants renseignés via CINEORG_DELUGE_* → intégration active."""
    monkeypatch.setenv("CINEORG_DELUGE_USERNAME", "localclient")
    monkeypatch.setenv("CINEORG_DELUGE_PASSWORD", "secret")
    monkeypatch.setenv("CINEORG_DELUGE_PORT", "12345")
    settings = Settings(_env_file=None)
    assert settings.deluge_enabled is True
    assert settings.deluge_port == 12345
