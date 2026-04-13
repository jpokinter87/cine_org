"""
Tests du backend DuneHDPlayer : mapping SMB films/séries, appel HTTP,
parsing XML, gestion des erreurs (timeout, API en échec).
"""

from pathlib import Path

import httpx
import pytest
import respx

from src.services.player.dunehd_player import (
    DuneHDMappingError,
    DuneHDPlayer,
    DuneHDResult,
    map_to_smb,
)


DUNE_PROFILE = {
    "name": "DuneSalon",
    "type": "dunehd",
    "ip": "192.168.1.4",
    "smb_movies_prefix": "smb://192.168.1.2/Films",
    "smb_series_prefix": "smb://192.168.1.2/Series TV",
}


_XML_OK = (
    '<?xml version="1.0"?>'
    "<command_result>"
    '<param name="command_status" value="ok"/>'
    '<param name="player_state" value="file_playback"/>'
    "</command_result>"
)

_XML_FAILED = (
    '<?xml version="1.0"?>'
    "<command_result>"
    '<param name="command_status" value="failed"/>'
    '<param name="error_kind" value="unknown_error"/>'
    '<param name="error_description" value="Fichier introuvable"/>'
    '<param name="player_state" value="navigator"/>'
    "</command_result>"
)


# --- Mapping SMB ---------------------------------------------------------


def test_map_to_smb_film_simple() -> None:
    local = Path("/srv/storage/Films/Action/A/Un Film (2020).mkv")
    url = map_to_smb(local, DUNE_PROFILE)
    assert url == "smb://192.168.1.2/Films/Action/A/Un Film (2020).mkv"


def test_map_to_smb_serie_avec_accent() -> None:
    """Le chemin local contient 'Séries' mais le share SMB est 'Series TV'."""
    local = Path(
        "/srv/storage/Séries/A-C/Breaking Bad (2008)/Saison 01/S01E01.mkv"
    )
    url = map_to_smb(local, DUNE_PROFILE)
    assert url == (
        "smb://192.168.1.2/Series TV/A-C/Breaking Bad (2008)/Saison 01/S01E01.mkv"
    )


def test_map_to_smb_preserve_parentheses_et_espaces() -> None:
    local = Path(
        "/storage/Films/Drame/A-G/Ch/La Chasse (2012) MULTi HEVC 1080p.mkv"
    )
    url = map_to_smb(local, DUNE_PROFILE)
    assert url == (
        "smb://192.168.1.2/Films/Drame/A-G/Ch/La Chasse (2012) MULTi HEVC 1080p.mkv"
    )


def test_map_to_smb_accepte_series_sans_accent() -> None:
    """Variante anglaise 'Series' aussi reconnue."""
    local = Path("/srv/storage/Series/A-C/Show (2020)/Saison 01/S01E01.mkv")
    url = map_to_smb(local, DUNE_PROFILE)
    assert url == (
        "smb://192.168.1.2/Series TV/A-C/Show (2020)/Saison 01/S01E01.mkv"
    )


def test_map_to_smb_leve_sur_chemin_non_reconnu() -> None:
    with pytest.raises(DuneHDMappingError):
        map_to_smb(Path("/tmp/random/file.mkv"), DUNE_PROFILE)


def test_map_to_smb_leve_si_prefixe_manquant() -> None:
    profile_sans_series = dict(DUNE_PROFILE)
    profile_sans_series["smb_series_prefix"] = None
    with pytest.raises(DuneHDMappingError):
        map_to_smb(Path("/storage/Séries/A/S/file.mkv"), profile_sans_series)


def test_map_to_smb_prefix_avec_trailing_slash() -> None:
    """Un slash final sur le préfixe ne produit pas de double slash."""
    profile = dict(DUNE_PROFILE)
    profile["smb_movies_prefix"] = "smb://192.168.1.2/Films/"
    url = map_to_smb(Path("/storage/Films/Action/A/Film.mkv"), profile)
    assert url == "smb://192.168.1.2/Films/Action/A/Film.mkv"


# --- DuneHDPlayer : construction -----------------------------------------


def test_dunehd_player_refuse_profil_mpv() -> None:
    mpv_profile = {"type": "mpv", "name": "Local", "command": "mpv"}
    with pytest.raises(ValueError):
        DuneHDPlayer(mpv_profile)


def test_dunehd_player_refuse_ip_vide() -> None:
    profile = dict(DUNE_PROFILE)
    profile["ip"] = None
    with pytest.raises(ValueError):
        DuneHDPlayer(profile)


# --- DuneHDPlayer.play() : succès et erreurs -----------------------------


@respx.mock
def test_play_succes_command_status_ok() -> None:
    route = respx.get("http://192.168.1.4/cgi-bin/do").mock(
        return_value=httpx.Response(200, text=_XML_OK)
    )
    player = DuneHDPlayer(DUNE_PROFILE)
    result = player.play(Path("/storage/Films/Action/A/Film (2020).mkv"))

    assert isinstance(result, DuneHDResult)
    assert result.ok is True
    assert result.player_state == "file_playback"
    assert result.error is None

    # Vérifier l'URL et les paramètres envoyés
    request = route.calls.last.request
    assert request.url.params["cmd"] == "start_file_playback"
    assert request.url.params["media_url"] == (
        "smb://192.168.1.2/Films/Action/A/Film (2020).mkv"
    )


@respx.mock
def test_play_echec_command_status_failed() -> None:
    respx.get("http://192.168.1.4/cgi-bin/do").mock(
        return_value=httpx.Response(200, text=_XML_FAILED)
    )
    player = DuneHDPlayer(DUNE_PROFILE)
    result = player.play(Path("/storage/Films/Action/A/Film.mkv"))

    assert result.ok is False
    assert result.error == "Fichier introuvable"
    assert result.player_state == "navigator"


@respx.mock
def test_play_timeout_reseau() -> None:
    respx.get("http://192.168.1.4/cgi-bin/do").mock(
        side_effect=httpx.TimeoutException("timed out")
    )
    player = DuneHDPlayer(DUNE_PROFILE, timeout=0.1)
    result = player.play(Path("/storage/Films/Action/A/Film.mkv"))

    assert result.ok is False
    assert result.error is not None
    assert "timeout" in result.error.lower()


@respx.mock
def test_play_erreur_reseau_generique() -> None:
    respx.get("http://192.168.1.4/cgi-bin/do").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    player = DuneHDPlayer(DUNE_PROFILE)
    result = player.play(Path("/storage/Films/Action/A/Film.mkv"))

    assert result.ok is False
    assert result.error is not None


@respx.mock
def test_play_status_http_non_200() -> None:
    respx.get("http://192.168.1.4/cgi-bin/do").mock(
        return_value=httpx.Response(500, text="internal error")
    )
    player = DuneHDPlayer(DUNE_PROFILE)
    result = player.play(Path("/storage/Films/Action/A/Film.mkv"))

    assert result.ok is False
    assert "500" in (result.error or "")


def test_play_chemin_non_mappable_retourne_erreur() -> None:
    """Un chemin hors Films/Séries échoue sans appel réseau."""
    player = DuneHDPlayer(DUNE_PROFILE)
    result = player.play(Path("/tmp/orphan/file.mkv"))
    assert result.ok is False
    assert result.error is not None
