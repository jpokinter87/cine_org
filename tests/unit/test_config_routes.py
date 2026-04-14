"""
Tests des routes HTMX de configuration des profils lecteur.

Couvre :
- Validation des champs dunehd (ip, préfixes SMB)
- Rétrocompatibilité mpv (comportement inchangé)
- Création, édition, persistance des profils via TestClient FastAPI
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from src import player_profiles
from src.web.routes.config import router as config_router


@pytest.fixture
def isolated_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isole player_profiles.json dans un tmp_path pour chaque test."""
    profiles_file = tmp_path / "player_profiles.json"
    monkeypatch.setattr(player_profiles, "_PROFILES_FILE", profiles_file)
    return profiles_file


@pytest.fixture
def client(isolated_profiles: Path) -> TestClient:
    """Client de test minimal avec uniquement le router de config."""
    app = FastAPI()
    app.include_router(config_router)
    return TestClient(app)


# ── Validation dunehd ────────────────────────────────────────────────


def test_add_dunehd_profile_complet_cree_le_profil(
    client: TestClient, isolated_profiles: Path
) -> None:
    """Un POST add dunehd valide crée effectivement le profil."""
    response = client.post(
        "/config/player-profiles/add",
        data={
            "name": "DuneSalon",
            "type": "dunehd",
            "ip": "192.168.1.4",
            "smb_movies_prefix": "smb://192.168.1.2/Films",
            "smb_series_prefix": "smb://192.168.1.2/Series TV",
        },
    )
    assert response.status_code == 200

    profile = player_profiles.get_profile_by_name("DuneSalon")
    assert profile is not None
    assert profile["type"] == "dunehd"
    assert profile["ip"] == "192.168.1.4"
    assert profile["smb_movies_prefix"] == "smb://192.168.1.2/Films"
    assert profile["smb_series_prefix"] == "smb://192.168.1.2/Series TV"


def test_add_dunehd_sans_ip_rejete(client: TestClient) -> None:
    """IP vide pour un profil dunehd → erreur + pas de création."""
    response = client.post(
        "/config/player-profiles/add",
        data={
            "name": "DuneSalon",
            "type": "dunehd",
            "ip": "",
            "smb_movies_prefix": "smb://192.168.1.2/Films",
            "smb_series_prefix": "smb://192.168.1.2/Series TV",
        },
    )
    assert response.status_code == 200
    assert "IP du Dune est requise" in response.text
    assert player_profiles.get_profile_by_name("DuneSalon") is None


def test_add_dunehd_ip_invalide_rejete(client: TestClient) -> None:
    """IP au mauvais format → erreur."""
    response = client.post(
        "/config/player-profiles/add",
        data={
            "name": "DuneSalon",
            "type": "dunehd",
            "ip": "pas-une-ip",
            "smb_movies_prefix": "smb://192.168.1.2/Films",
            "smb_series_prefix": "smb://192.168.1.2/Series TV",
        },
    )
    assert response.status_code == 200
    assert "format attendu" in response.text
    assert player_profiles.get_profile_by_name("DuneSalon") is None


def test_add_dunehd_prefixe_smb_invalide_rejete(client: TestClient) -> None:
    """Préfixe ne commençant pas par smb:// → erreur."""
    response = client.post(
        "/config/player-profiles/add",
        data={
            "name": "DuneSalon",
            "type": "dunehd",
            "ip": "192.168.1.4",
            "smb_movies_prefix": "http://192.168.1.2/Films",
            "smb_series_prefix": "smb://192.168.1.2/Series TV",
        },
    )
    assert response.status_code == 200
    assert "smb://" in response.text
    assert player_profiles.get_profile_by_name("DuneSalon") is None


def test_add_dunehd_sans_smb_series_rejete(client: TestClient) -> None:
    """Préfixe SMB séries absent → erreur."""
    response = client.post(
        "/config/player-profiles/add",
        data={
            "name": "DuneSalon",
            "type": "dunehd",
            "ip": "192.168.1.4",
            "smb_movies_prefix": "smb://192.168.1.2/Films",
            "smb_series_prefix": "",
        },
    )
    assert response.status_code == 200
    assert "SMB séries" in response.text
    assert player_profiles.get_profile_by_name("DuneSalon") is None


# ── Compatibilité mpv ───────────────────────────────────────────────


def test_add_mpv_profile_cree_le_profil(client: TestClient) -> None:
    """Un POST add mpv classique continue de fonctionner."""
    response = client.post(
        "/config/player-profiles/add",
        data={
            "name": "Xubuntu Salon",
            "type": "mpv",
            "command": "mpv",
            "target": "remote",
            "ssh_host": "192.168.1.20",
            "ssh_user": "jp",
            "local_path_prefix": "/home/jp/Videos",
            "remote_path_prefix": "/mnt/nas",
        },
    )
    assert response.status_code == 200
    profile = player_profiles.get_profile_by_name("Xubuntu Salon")
    assert profile is not None
    assert profile["type"] == "mpv"
    assert profile["ssh_host"] == "192.168.1.20"
    assert profile["ssh_user"] == "jp"
    assert profile["ip"] is None


def test_add_mpv_sans_type_utilise_defaut_mpv(client: TestClient) -> None:
    """Si `type` est absent du form, on retombe sur mpv (rétrocompat)."""
    response = client.post(
        "/config/player-profiles/add",
        data={
            "name": "LegacyProfile",
            "command": "mpv",
            "target": "local",
        },
    )
    assert response.status_code == 200
    profile = player_profiles.get_profile_by_name("LegacyProfile")
    assert profile is not None
    assert profile["type"] == "mpv"


def test_add_mpv_remote_sans_ssh_host_rejete(client: TestClient) -> None:
    """Target remote sans ssh_host → erreur."""
    response = client.post(
        "/config/player-profiles/add",
        data={
            "name": "Incomplet",
            "type": "mpv",
            "command": "mpv",
            "target": "remote",
            "ssh_host": "",
            "ssh_user": "jp",
        },
    )
    assert response.status_code == 200
    assert "hôte SSH" in response.text.lower() or "SSH" in response.text
    assert player_profiles.get_profile_by_name("Incomplet") is None


# ── Edition ─────────────────────────────────────────────────────────


def test_edit_profile_dunehd_change_ip(client: TestClient) -> None:
    """Édition d'un profil dunehd : l'IP est mise à jour."""
    # Créer d'abord
    client.post(
        "/config/player-profiles/add",
        data={
            "name": "DuneSalon",
            "type": "dunehd",
            "ip": "192.168.1.4",
            "smb_movies_prefix": "smb://192.168.1.2/Films",
            "smb_series_prefix": "smb://192.168.1.2/Series TV",
        },
    )
    # Éditer
    response = client.post(
        "/config/player-profiles/DuneSalon/edit",
        data={
            "name": "DuneSalon",
            "type": "dunehd",
            "ip": "192.168.1.5",
            "smb_movies_prefix": "smb://192.168.1.2/Films",
            "smb_series_prefix": "smb://192.168.1.2/Series TV",
        },
    )
    assert response.status_code == 200
    profile = player_profiles.get_profile_by_name("DuneSalon")
    assert profile is not None
    assert profile["ip"] == "192.168.1.5"


def test_edit_profile_dunehd_ip_invalide_rejete(client: TestClient) -> None:
    """Édition avec IP invalide : erreur, profil inchangé."""
    client.post(
        "/config/player-profiles/add",
        data={
            "name": "DuneSalon",
            "type": "dunehd",
            "ip": "192.168.1.4",
            "smb_movies_prefix": "smb://192.168.1.2/Films",
            "smb_series_prefix": "smb://192.168.1.2/Series TV",
        },
    )
    response = client.post(
        "/config/player-profiles/DuneSalon/edit",
        data={
            "name": "DuneSalon",
            "type": "dunehd",
            "ip": "not-an-ip",
            "smb_movies_prefix": "smb://192.168.1.2/Films",
            "smb_series_prefix": "smb://192.168.1.2/Series TV",
        },
    )
    assert response.status_code == 200
    assert "format attendu" in response.text
    # IP reste inchangée
    profile = player_profiles.get_profile_by_name("DuneSalon")
    assert profile["ip"] == "192.168.1.4"
