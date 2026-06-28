"""
Tests du schéma et de la persistance des profils lecteur (mpv + dunehd).

Couvre la rétrocompatibilité : profils existants sans champ `type` reçoivent
`"mpv"` par défaut, et les nouveaux champs dunehd (ip, smb_movies_prefix,
smb_series_prefix) sont préservés au roundtrip JSON.
"""

import json
from pathlib import Path

import pytest

from src import player_profiles


@pytest.fixture
def isolated_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isole le fichier player_profiles.json dans un tmp_path pour chaque test."""
    profiles_file = tmp_path / "player_profiles.json"
    monkeypatch.setattr(player_profiles, "_PROFILES_FILE", profiles_file)
    return profiles_file


def test_ensure_profile_adds_default_type_mpv() -> None:
    """Un profil legacy sans champ `type` reçoit `"mpv"` par défaut."""
    legacy = {
        "name": "Xubuntu Salon",
        "command": "mpv",
        "target": "remote",
        "ssh_host": "192.168.1.20",
        "ssh_user": "jp",
    }
    ensured = player_profiles._ensure_profile(legacy)
    assert ensured["type"] == "mpv"
    assert ensured["ssh_host"] == "192.168.1.20"
    assert ensured["ssh_user"] == "jp"
    assert ensured["ip"] is None
    assert ensured["smb_movies_prefix"] is None
    assert ensured["smb_series_prefix"] is None


def test_ensure_profile_preserves_dunehd_fields() -> None:
    """Un profil dunehd conserve ip et les préfixes SMB."""
    dunehd = {
        "name": "DuneSalon",
        "type": "dunehd",
        "ip": "192.168.1.4",
        "smb_movies_prefix": "smb://192.168.1.2/Films",
        "smb_series_prefix": "smb://192.168.1.2/Series TV",
    }
    ensured = player_profiles._ensure_profile(dunehd)
    assert ensured["type"] == "dunehd"
    assert ensured["ip"] == "192.168.1.4"
    assert ensured["smb_movies_prefix"] == "smb://192.168.1.2/Films"
    assert ensured["smb_series_prefix"] == "smb://192.168.1.2/Series TV"


def test_load_profiles_reads_legacy_file_without_type(
    isolated_profiles: Path,
) -> None:
    """Un JSON sur disque sans `type` est chargé avec `type="mpv"` par défaut."""
    isolated_profiles.write_text(
        json.dumps(
            {
                "active": "Local",
                "profiles": [
                    {
                        "name": "Local",
                        "command": "mpv",
                        "target": "local",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    data = player_profiles.load_profiles()
    assert data["profiles"][0]["name"] == "Local"
    # _ensure_profile n'est pas appelé par load_profiles, mais get_active_profile() l'applique
    active = player_profiles.get_active_profile()
    assert active["type"] == "mpv"


def test_save_and_load_dunehd_profile_roundtrip(isolated_profiles: Path) -> None:
    """Un profil dunehd persiste tous ses champs après save + load."""
    dunehd = {
        "name": "DuneSalon",
        "type": "dunehd",
        "ip": "192.168.1.4",
        "smb_movies_prefix": "smb://192.168.1.2/Films",
        "smb_series_prefix": "smb://192.168.1.2/Series TV",
    }
    player_profiles.add_profile(dunehd)

    reloaded = player_profiles.get_profile_by_name("DuneSalon")
    assert reloaded is not None
    assert reloaded["type"] == "dunehd"
    assert reloaded["ip"] == "192.168.1.4"
    assert reloaded["smb_movies_prefix"] == "smb://192.168.1.2/Films"
    assert reloaded["smb_series_prefix"] == "smb://192.168.1.2/Series TV"


def test_add_dunehd_profile_coexists_with_mpv(isolated_profiles: Path) -> None:
    """Ajouter un profil dunehd ne casse pas le profil Local par défaut."""
    player_profiles.load_profiles()  # Force la création du fichier par défaut
    player_profiles.add_profile(
        {
            "name": "DuneSalon",
            "type": "dunehd",
            "ip": "192.168.1.4",
            "smb_movies_prefix": "smb://192.168.1.2/Films",
            "smb_series_prefix": "smb://192.168.1.2/Series TV",
        }
    )
    data = player_profiles.load_profiles()
    names = {p["name"] for p in data["profiles"]}
    assert "Local" in names
    assert "DuneSalon" in names

    local = player_profiles.get_profile_by_name("Local")
    dune = player_profiles.get_profile_by_name("DuneSalon")
    assert local["type"] == "mpv"
    assert dune["type"] == "dunehd"


def test_update_profile_preserves_dunehd_fields(isolated_profiles: Path) -> None:
    """update_profile() conserve les nouveaux champs au lieu de les écraser."""
    player_profiles.add_profile(
        {
            "name": "DuneSalon",
            "type": "dunehd",
            "ip": "192.168.1.4",
            "smb_movies_prefix": "smb://192.168.1.2/Films",
            "smb_series_prefix": "smb://192.168.1.2/Series TV",
        }
    )
    player_profiles.update_profile(
        "DuneSalon",
        {
            "name": "DuneSalon",
            "type": "dunehd",
            "ip": "192.168.1.5",  # Changement d'IP
            "smb_movies_prefix": "smb://192.168.1.2/Films",
            "smb_series_prefix": "smb://192.168.1.2/Series TV",
        },
    )
    updated = player_profiles.get_profile_by_name("DuneSalon")
    assert updated["ip"] == "192.168.1.5"
    assert updated["type"] == "dunehd"


def test_legacy_mpv_profile_still_works(isolated_profiles: Path) -> None:
    """Les profils mpv (SSH) existants restent fonctionnels sans modification."""
    player_profiles.add_profile(
        {
            "name": "Xubuntu Salon",
            "command": "mpv",
            "target": "remote",
            "ssh_host": "192.168.1.20",
            "ssh_user": "jp",
            "local_path_prefix": "/home/jp/Videos",
            "remote_path_prefix": "/mnt/nas",
        }
    )
    profile = player_profiles.get_profile_by_name("Xubuntu Salon")
    assert profile is not None
    assert profile["type"] == "mpv"
    assert profile["ssh_host"] == "192.168.1.20"
    assert profile["ip"] is None


def test_get_personal_profiles_exclut_dunehd(monkeypatch):
    """get_personal_profiles ne renvoie que les profils personnes/écrans (hors DuneHD)."""
    import src.player_profiles as pp

    fake = {
        "active": "Local",
        "profiles": [
            {"name": "Local", "type": "mpv", "target": "local"},
            {"name": "Willow", "type": "mpv", "target": "remote"},
            {"name": "Salon", "type": "dunehd", "target": "remote"},
        ],
    }
    monkeypatch.setattr(pp, "load_profiles", lambda: fake)

    names = [p["name"] for p in pp.get_personal_profiles()]
    assert names == ["Local", "Willow"]
    assert "Salon" not in names
