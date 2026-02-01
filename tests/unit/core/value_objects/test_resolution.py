"""
Tests unitaires pour Resolution.

Tests TDD pour le calcul du label de résolution.
"""

import pytest

from src.core.value_objects.media_info import Resolution


class TestResolutionLabel:
    """Tests pour Resolution.label."""

    # --- Résolutions 4K ---
    def test_resolution_4k_standard(self) -> None:
        """Résolution 4K standard (3840x2160)."""
        resolution = Resolution(width=3840, height=2160)
        assert resolution.label == "4K"

    def test_resolution_4k_cinema(self) -> None:
        """Résolution 4K cinéma (format 2.35:1)."""
        resolution = Resolution(width=3840, height=1600)
        assert resolution.label == "4K"

    def test_resolution_4k_by_width(self) -> None:
        """Résolution 4K détectée par largeur (>= 3800)."""
        resolution = Resolution(width=3800, height=1500)
        assert resolution.label == "4K"

    # --- Résolutions 1080p ---
    def test_resolution_1080p_standard(self) -> None:
        """Résolution 1080p standard (1920x1080)."""
        resolution = Resolution(width=1920, height=1080)
        assert resolution.label == "1080p"

    def test_resolution_1080p_cinema_wide(self) -> None:
        """Résolution 1080p cinéma large (2.35:1)."""
        resolution = Resolution(width=1920, height=800)
        assert resolution.label == "1080p"

    def test_resolution_1080p_by_width(self) -> None:
        """Résolution 1080p détectée par largeur (>= 1900)."""
        resolution = Resolution(width=1900, height=800)
        assert resolution.label == "1080p"

    def test_resolution_1080p_old_format_4_3(self) -> None:
        """Résolution 1080p format 4:3 ancien (1440x1080)."""
        resolution = Resolution(width=1440, height=1080)
        assert resolution.label == "1080p"

    def test_resolution_1080p_height_1056(self) -> None:
        """Résolution 1080p avec hauteur 1056 (format recadré)."""
        # Cas réel : Le Plaisir (1952) - 1392x1056
        resolution = Resolution(width=1392, height=1056)
        assert resolution.label == "1080p"

    def test_resolution_1080p_height_1056_narrow(self) -> None:
        """Résolution 1080p avec hauteur 1056 largeur réduite."""
        # Cas réel : Préparez vos mouchoirs (1978) - 1296x1056
        resolution = Resolution(width=1296, height=1056)
        assert resolution.label == "1080p"

    def test_resolution_1080p_height_1000(self) -> None:
        """Résolution 1080p seuil bas de hauteur (>= 1000)."""
        resolution = Resolution(width=1280, height=1000)
        assert resolution.label == "1080p"

    # --- Résolutions 720p ---
    def test_resolution_720p_standard(self) -> None:
        """Résolution 720p standard (1280x720)."""
        resolution = Resolution(width=1280, height=720)
        assert resolution.label == "720p"

    def test_resolution_720p_cinema(self) -> None:
        """Résolution 720p cinéma (format large)."""
        resolution = Resolution(width=1280, height=544)
        assert resolution.label == "720p"

    def test_resolution_720p_by_width(self) -> None:
        """Résolution 720p détectée par largeur (>= 1260)."""
        resolution = Resolution(width=1260, height=500)
        assert resolution.label == "720p"

    def test_resolution_720p_height_960(self) -> None:
        """Résolution 720p+ mais sous le seuil 1080p (hauteur 960)."""
        # 960 < 1000 mais > 720 -> 720p
        resolution = Resolution(width=1280, height=960)
        assert resolution.label == "720p"

    # --- Résolutions SD ---
    def test_resolution_sd_dvd(self) -> None:
        """Résolution SD DVD (720x576 PAL)."""
        resolution = Resolution(width=720, height=576)
        assert resolution.label == "SD"

    def test_resolution_sd_ntsc(self) -> None:
        """Résolution SD NTSC (720x480)."""
        resolution = Resolution(width=720, height=480)
        assert resolution.label == "SD"

    def test_resolution_sd_old(self) -> None:
        """Résolution SD ancienne (640x480)."""
        resolution = Resolution(width=640, height=480)
        assert resolution.label == "SD"
