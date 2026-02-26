"""Tests pour la logique de lecture vidéo (local + SSH + mapping chemins)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.web.routes.library.player import (
    _launch_player,
    _map_path,
)


def _profile(
    command="mpv",
    target="local",
    ssh_host=None,
    ssh_user=None,
    local_path_prefix=None,
    remote_path_prefix=None,
):
    return {
        "name": "Test",
        "command": command,
        "target": target,
        "ssh_host": ssh_host,
        "ssh_user": ssh_user,
        "local_path_prefix": local_path_prefix,
        "remote_path_prefix": remote_path_prefix,
    }


class TestMapPath:
    """Tests du mapping de chemins local → distant."""

    def test_sans_prefixes_retourne_chemin_identique(self):
        """Sans préfixes configurés, le chemin est retourné tel quel."""
        profile = _profile()
        result = _map_path(Path("/home/jp/Videos/storage/Films/Alien.mkv"), profile)
        assert result == "/home/jp/Videos/storage/Films/Alien.mkv"

    def test_mapping_linux_vers_linux(self):
        """Remplacement du préfixe local par le préfixe distant (Linux → Linux)."""
        profile = _profile(local_path_prefix="/home/jp/Videos", remote_path_prefix="/mnt/nas")
        result = _map_path(Path("/home/jp/Videos/storage/Films/Alien.mkv"), profile)
        assert result == "/mnt/nas/storage/Films/Alien.mkv"

    def test_mapping_linux_vers_windows(self):
        """Remplacement du préfixe local par un chemin Windows."""
        profile = _profile(local_path_prefix="/home/jp/Videos", remote_path_prefix="Z:\\Videos")
        result = _map_path(Path("/home/jp/Videos/storage/Films/Alien.mkv"), profile)
        assert result == "Z:\\Videos/storage/Films/Alien.mkv"

    def test_chemin_ne_commence_pas_par_prefixe(self):
        """Si le chemin ne commence pas par le préfixe local, retourne tel quel."""
        profile = _profile(local_path_prefix="/home/jp/Videos", remote_path_prefix="/mnt/nas")
        result = _map_path(Path("/other/path/film.mkv"), profile)
        assert result == "/other/path/film.mkv"

    def test_prefixe_local_seul_sans_distant(self):
        """Si seul le préfixe local est défini, pas de mapping."""
        profile = _profile(local_path_prefix="/home/jp/Videos")
        result = _map_path(Path("/home/jp/Videos/storage/film.mkv"), profile)
        assert result == "/home/jp/Videos/storage/film.mkv"


class TestLaunchPlayer:
    """Tests du lancement du lecteur (local et SSH)."""

    @patch("src.web.routes.library.player.get_active_profile")
    @patch("src.web.routes.library.player.subprocess.Popen")
    def test_local_par_defaut(self, mock_popen, mock_get_profile):
        """Avec target=local, lance le lecteur en local."""
        mock_get_profile.return_value = _profile()

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        pid, is_remote = _launch_player(Path("/home/jp/Videos/film.mkv"))

        assert pid == 12345
        assert is_remote is False
        mock_popen.assert_called_once_with(
            ["mpv", "/home/jp/Videos/film.mkv"],
            stdout=-3,  # subprocess.DEVNULL
            stderr=-3,
        )

    @patch("src.web.routes.library.player.get_active_profile")
    @patch("src.web.routes.library.player.subprocess.Popen")
    def test_vlc_local(self, mock_popen, mock_get_profile):
        """Avec player_command=vlc, lance vlc en local."""
        mock_get_profile.return_value = _profile(command="vlc")

        mock_proc = MagicMock()
        mock_proc.pid = 99
        mock_popen.return_value = mock_proc

        pid, is_remote = _launch_player(Path("/home/jp/Videos/film.mkv"))

        assert pid == 99
        assert is_remote is False
        args = mock_popen.call_args[0][0]
        assert args[0] == "vlc"

    @patch("src.web.routes.library.player.get_active_profile")
    @patch("src.web.routes.library.player.subprocess.Popen")
    def test_ssh_remote(self, mock_popen, mock_get_profile):
        """Avec target=remote et SSH configuré, lance via SSH."""
        mock_get_profile.return_value = _profile(
            target="remote",
            ssh_host="192.168.1.20",
            ssh_user="jp",
            local_path_prefix="/home/jp/Videos",
            remote_path_prefix="/mnt/nas",
        )

        mock_proc = MagicMock()
        mock_proc.pid = 555
        mock_popen.return_value = mock_proc

        pid, is_remote = _launch_player(Path("/home/jp/Videos/storage/Films/Alien.mkv"))

        assert pid == 555
        assert is_remote is True
        args = mock_popen.call_args[0][0]
        assert args[0] == "ssh"
        assert "jp@192.168.1.20" in args
        assert "mpv '/mnt/nas/storage/Films/Alien.mkv'" in args

    @patch("src.web.routes.library.player.get_active_profile")
    @patch("src.web.routes.library.player.subprocess.Popen")
    def test_fallback_local_si_ssh_host_vide(self, mock_popen, mock_get_profile):
        """Avec target=remote mais SSH host vide, fallback en local."""
        mock_get_profile.return_value = _profile(target="remote", ssh_user="jp")

        mock_proc = MagicMock()
        mock_proc.pid = 42
        mock_popen.return_value = mock_proc

        pid, is_remote = _launch_player(Path("/home/jp/Videos/film.mkv"))

        assert pid == 42
        assert is_remote is False
        args = mock_popen.call_args[0][0]
        assert args[0] == "mpv"  # local, pas SSH

    @patch("src.web.routes.library.player.get_active_profile")
    @patch("src.web.routes.library.player.subprocess.Popen")
    def test_fallback_local_si_ssh_user_vide(self, mock_popen, mock_get_profile):
        """Avec target=remote mais SSH user vide, fallback en local."""
        mock_get_profile.return_value = _profile(
            target="remote", ssh_host="192.168.1.20"
        )

        mock_proc = MagicMock()
        mock_proc.pid = 43
        mock_popen.return_value = mock_proc

        pid, is_remote = _launch_player(Path("/home/jp/Videos/film.mkv"))

        assert pid == 43
        assert is_remote is False
