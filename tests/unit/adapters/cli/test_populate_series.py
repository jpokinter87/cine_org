"""Tests unitaires pour la commande populate-series."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.adapters.cli.commands.import_commands import (
    _EPISODE_RE,
    _EPISODE_TITLE_RE,
    _SEASON_DIR_RE,
    _SERIES_DIR_RE,
    _discover_series_dirs,
    _process_episodes,
    _resolve_symlink_target,
)


class TestSeriesRegex:
    """Tests des regex de parsing."""

    def test_series_dir_with_year(self):
        m = _SERIES_DIR_RE.match("Breaking Bad (2008)")
        assert m
        assert m.group(1) == "Breaking Bad"
        assert m.group(2) == "2008"

    def test_series_dir_with_year_special_chars(self):
        m = _SERIES_DIR_RE.match("The Bridge (2011)")
        assert m
        assert m.group(1) == "The Bridge"

    def test_series_dir_without_year(self):
        assert _SERIES_DIR_RE.match("Breaking Bad") is None

    def test_season_dir_two_digits(self):
        assert _SEASON_DIR_RE.match("Saison 01")

    def test_season_dir_single_digit(self):
        assert _SEASON_DIR_RE.match("Saison 1")

    def test_season_dir_invalid(self):
        assert _SEASON_DIR_RE.match("Season 1") is None

    def test_episode_standard(self):
        m = _EPISODE_RE.search("Futurama - S01E09 - titre.mkv")
        assert m
        assert m.group(1) == "01"
        assert m.group(2) == "09"

    def test_episode_case_insensitive(self):
        m = _EPISODE_RE.search("show.s02e03.multi.mkv")
        assert m
        assert m.group(1) == "02"
        assert m.group(2) == "03"

    def test_episode_title_cineorg_format(self):
        m = _EPISODE_TITLE_RE.search(
            "Futurama - S01E09 - L'Enfer, c'est les autres robots - MULTi 720p AC3 x265.mkv"
        )
        assert m
        assert m.group(1).strip() == "L'Enfer, c'est les autres robots"

    def test_episode_title_french_format(self):
        m = _EPISODE_TITLE_RE.search(
            "Boss - S01E06 - Titre episode - FRENCH 720p BluRay.mkv"
        )
        assert m
        assert m.group(1).strip() == "Titre episode"

    def test_episode_title_no_match_when_missing(self):
        m = _EPISODE_TITLE_RE.search("show.S01E01.MULTi.1080p.mkv")
        assert m is None


class TestDiscoverSeriesDirs:
    """Tests de la decouverte des dossiers series."""

    def test_finds_series_with_season_dirs(self, tmp_path):
        """Detecte un dossier serie contenant Saison XX."""
        root = tmp_path / "Séries"
        root.mkdir()
        cat = root / "Animation"
        cat.mkdir()
        series = cat / "Futurama (1999)"
        series.mkdir()
        (series / "Saison 01").mkdir()
        (series / "Saison 02").mkdir()

        results = _discover_series_dirs(root)
        assert len(results) == 1
        assert results[0][1] == "Futurama"
        assert results[0][2] == 1999

    def test_finds_series_without_year(self, tmp_path):
        """Detecte un dossier serie sans annee."""
        root = tmp_path / "Séries"
        root.mkdir()
        cat = root / "Séries TV"
        cat.mkdir()
        series = cat / "Breaking Bad"
        series.mkdir()
        (series / "Saison 01").mkdir()

        results = _discover_series_dirs(root)
        assert len(results) == 1
        assert results[0][1] == "Breaking Bad"
        assert results[0][2] is None

    def test_finds_nested_series_with_letter_dirs(self, tmp_path):
        """Detecte les series dans une structure avec lettres."""
        root = tmp_path / "Séries"
        root.mkdir()
        cat = root / "Séries TV"
        cat.mkdir()
        letter = cat / "B"
        letter.mkdir()
        series = letter / "Boss (2011)"
        series.mkdir()
        (series / "Saison 01").mkdir()

        results = _discover_series_dirs(root)
        assert len(results) == 1
        assert results[0][1] == "Boss"
        assert results[0][2] == 2011

    def test_ignores_dirs_without_season(self, tmp_path):
        """Ignore les dossiers sans sous-dossier Saison."""
        root = tmp_path / "Séries"
        root.mkdir()
        cat = root / "Animation"
        cat.mkdir()
        series = cat / "SomeDir"
        series.mkdir()
        (series / "extras").mkdir()

        results = _discover_series_dirs(root)
        assert len(results) == 0

    def test_multiple_categories(self, tmp_path):
        """Detecte les series dans plusieurs categories."""
        root = tmp_path / "Séries"
        root.mkdir()

        for cat_name, series_name in [("Animation", "Rick and Morty (2013)"), ("Séries TV", "The Wire (2002)")]:
            cat = root / cat_name
            cat.mkdir()
            series = cat / series_name
            series.mkdir()
            (series / "Saison 01").mkdir()

        results = _discover_series_dirs(root)
        assert len(results) == 2


class TestProcessEpisodes:
    """Tests du traitement des episodes."""

    def test_creates_episodes_from_video_files(self, tmp_path):
        """Cree des episodes depuis les fichiers video."""
        series_dir = tmp_path / "Test Series (2020)"
        series_dir.mkdir()
        s01 = series_dir / "Saison 01"
        s01.mkdir()
        (s01 / "Test Series (2020) - S01E01 - Pilot - MULTi H264 1080p.mkv").touch()
        (s01 / "Test Series (2020) - S01E02 - Second - MULTi H264 1080p.mkv").touch()

        mock_repo = MagicMock()
        mock_repo.get_by_series.return_value = []
        mock_repo._to_model.return_value = MagicMock()

        created, skipped, errors = _process_episodes(
            series_path=series_dir,
            series_id="1",
            episode_repo=mock_repo,
            video_extensions=frozenset({".mkv", ".mp4"}),
            dry_run=False,
        )

        assert created == 2
        assert skipped == 0
        assert errors == 0

    def test_skips_existing_episodes(self, tmp_path):
        """Ignore les episodes deja en base."""
        series_dir = tmp_path / "Test (2020)"
        series_dir.mkdir()
        s01 = series_dir / "Saison 01"
        s01.mkdir()
        (s01 / "Test - S01E01 - MULTi 1080p.mkv").touch()

        mock_repo = MagicMock()
        mock_repo.get_by_series.return_value = [MagicMock()]  # Existe deja

        created, skipped, errors = _process_episodes(
            series_path=series_dir,
            series_id="1",
            episode_repo=mock_repo,
            video_extensions=frozenset({".mkv"}),
            dry_run=False,
        )

        assert created == 0
        assert skipped == 1

    def test_dry_run_does_not_save(self, tmp_path):
        """En dry-run, ne sauvegarde pas en base."""
        series_dir = tmp_path / "Test (2020)"
        series_dir.mkdir()
        s01 = series_dir / "Saison 01"
        s01.mkdir()
        (s01 / "Test - S01E01 - MULTi 1080p.mkv").touch()

        mock_repo = MagicMock()
        mock_repo.get_by_series.return_value = []

        created, skipped, errors = _process_episodes(
            series_path=series_dir,
            series_id="1",
            episode_repo=mock_repo,
            video_extensions=frozenset({".mkv"}),
            dry_run=True,
        )

        assert created == 1
        mock_repo.save.assert_not_called()
        mock_repo._to_model.assert_not_called()

    def test_ignores_non_video_files(self, tmp_path):
        """Ignore les fichiers non-video."""
        series_dir = tmp_path / "Test (2020)"
        series_dir.mkdir()
        s01 = series_dir / "Saison 01"
        s01.mkdir()
        (s01 / "Test - S01E01 - MULTi 1080p.mkv").touch()
        (s01 / "Test - S01E01.nfo").touch()
        (s01 / "Test - S01E01.srt").touch()

        mock_repo = MagicMock()
        mock_repo.get_by_series.return_value = []

        created, skipped, errors = _process_episodes(
            series_path=series_dir,
            series_id="1",
            episode_repo=mock_repo,
            video_extensions=frozenset({".mkv"}),
            dry_run=True,
        )

        assert created == 1
        assert errors == 0

    def test_counts_errors_for_files_without_episode_pattern(self, tmp_path):
        """Compte une erreur pour les fichiers sans SxxExx."""
        series_dir = tmp_path / "Test (2020)"
        series_dir.mkdir()
        s01 = series_dir / "Saison 01"
        s01.mkdir()
        (s01 / "random_video.mkv").touch()

        mock_repo = MagicMock()

        created, skipped, errors = _process_episodes(
            series_path=series_dir,
            series_id="1",
            episode_repo=mock_repo,
            video_extensions=frozenset({".mkv"}),
            dry_run=True,
        )

        assert created == 0
        assert errors == 1

    def test_resolves_symlink_target(self, tmp_path):
        """Resout correctement la cible d'un symlink."""
        target = tmp_path / "storage" / "file.mkv"
        target.parent.mkdir()
        target.touch()

        link = tmp_path / "video" / "file.mkv"
        link.parent.mkdir()
        os.symlink(target, link)

        result = _resolve_symlink_target(link)
        assert result == str(target)

    def test_resolve_non_symlink_returns_none(self, tmp_path):
        """Retourne None pour un fichier non-symlink."""
        f = tmp_path / "file.mkv"
        f.touch()
        result = _resolve_symlink_target(f)
        assert result is None
