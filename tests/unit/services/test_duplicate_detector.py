"""
Tests unitaires pour DuplicateDetector.

Vérifie :
- Détection de doublons par titre normalisé (films et séries)
- Cas Gomorra : titre sans année vs titre avec année
- Pas de faux positifs sur titres différents
- Comparaison de qualité avec recommandation
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.services.duplicate_detector import (
    DuplicateDetector,
    DuplicateMatch,
)


@pytest.fixture
def video_dir(tmp_path: Path) -> Path:
    """Crée une structure video/ de test."""
    video = tmp_path / "video"
    video.mkdir()
    return video


@pytest.fixture
def detector() -> DuplicateDetector:
    return DuplicateDetector()


class TestDetectDuplicateFilms:
    """Détection de doublons pour les films."""

    def test_detect_exact_title_different_year(
        self, detector: DuplicateDetector, video_dir: Path
    ):
        """Gomorra (sans année) existe, on transfère Gomorra (2014)."""
        # Créer un dossier existant sans année
        films_dir = video_dir / "Films" / "Drame" / "G-H" / "Gomorra"
        films_dir.mkdir(parents=True)
        # Créer un fichier vidéo existant
        (films_dir / "Gomorra.mkv").write_bytes(b"\x00" * 1024)

        result = detector.detect_duplicate(
            title="Gomorra",
            year=2014,
            video_dir=video_dir,
            is_series=False,
        )

        assert result is not None
        assert result.existing_title == "Gomorra"
        assert "Gomorra" in str(result.existing_dir)

    def test_detect_exact_title_same_name(
        self, detector: DuplicateDetector, video_dir: Path
    ):
        """Matrix (1999) existe, on transfère Matrix (1999) — même titre avec fichiers."""
        films_dir = video_dir / "Films" / "Action" / "M-N" / "Matrix (1999)"
        films_dir.mkdir(parents=True)
        (films_dir / "Matrix (1999) Multi H265 1080p.mkv").write_bytes(b"\x00" * 2048)

        result = detector.detect_duplicate(
            title="Matrix",
            year=1999,
            video_dir=video_dir,
            is_series=False,
        )

        assert result is not None
        assert "Matrix" in result.existing_title

    def test_no_match_different_title(
        self, detector: DuplicateDetector, video_dir: Path
    ):
        """Pas de faux positif sur des titres différents."""
        films_dir = video_dir / "Films" / "Action" / "A-B" / "Avatar (2009)"
        films_dir.mkdir(parents=True)
        (films_dir / "Avatar.mkv").write_bytes(b"\x00" * 1024)

        result = detector.detect_duplicate(
            title="Alien",
            year=1979,
            video_dir=video_dir,
            is_series=False,
        )

        assert result is None

    def test_no_match_empty_video_dir(
        self, detector: DuplicateDetector, video_dir: Path
    ):
        """Pas de match si le répertoire Films/ n'existe pas."""
        result = detector.detect_duplicate(
            title="Matrix",
            year=1999,
            video_dir=video_dir,
            is_series=False,
        )

        assert result is None

    def test_detect_with_article_difference(
        self, detector: DuplicateDetector, video_dir: Path
    ):
        """'Matrix' vs 'The Matrix' — articles ignorés."""
        films_dir = video_dir / "Films" / "Action" / "M-N" / "The Matrix (1999)"
        films_dir.mkdir(parents=True)
        (films_dir / "The Matrix.mkv").write_bytes(b"\x00" * 1024)

        result = detector.detect_duplicate(
            title="Matrix",
            year=1999,
            video_dir=video_dir,
            is_series=False,
        )

        assert result is not None


class TestDetectDuplicateSeries:
    """Détection de doublons pour les séries."""

    def test_detect_series_year_mismatch(
        self, detector: DuplicateDetector, video_dir: Path
    ):
        """Gomorra (sans année) existe en séries, on transfère Gomorra (2014)."""
        series_dir = video_dir / "Series" / "TV" / "G-H" / "Ga-Ha" / "Gomorra"
        series_dir.mkdir(parents=True)
        saison = series_dir / "Saison 01"
        saison.mkdir()
        (saison / "Gomorra S01E01.mkv").write_bytes(b"\x00" * 1024)

        result = detector.detect_duplicate(
            title="Gomorra",
            year=2014,
            video_dir=video_dir,
            is_series=True,
        )

        assert result is not None
        assert result.existing_title == "Gomorra"

    def test_detect_series_same_name_existing_episodes(
        self, detector: DuplicateDetector, video_dir: Path
    ):
        """Série existe avec le même nom et des épisodes — conflit."""
        series_dir = (
            video_dir / "Series" / "TV" / "G-H" / "Ga-Ha" / "Gomorra (2014)"
        )
        series_dir.mkdir(parents=True)
        saison = series_dir / "Saison 01"
        saison.mkdir()
        (saison / "Gomorra (2014) - S01E01.mkv").write_bytes(b"\x00" * 1024)
        (saison / "Gomorra (2014) - S01E02.mkv").write_bytes(b"\x00" * 1024)

        result = detector.detect_duplicate(
            title="Gomorra",
            year=2014,
            video_dir=video_dir,
            is_series=True,
        )

        assert result is not None
        assert len(result.existing_files) == 2

    def test_no_match_different_series(
        self, detector: DuplicateDetector, video_dir: Path
    ):
        """Pas de faux positif entre séries différentes."""
        series_dir = (
            video_dir / "Series" / "TV" / "B-C" / "Ba-Ca" / "Breaking Bad (2008)"
        )
        series_dir.mkdir(parents=True)
        saison = series_dir / "Saison 01"
        saison.mkdir()
        (saison / "Breaking Bad S01E01.mkv").write_bytes(b"\x00" * 1024)

        result = detector.detect_duplicate(
            title="Better Call Saul",
            year=2015,
            video_dir=video_dir,
            is_series=True,
        )

        assert result is None


class TestPartialSeasons:
    """Détection de saisons partielles — les nouvelles saisons ne sont pas des doublons."""

    def test_existing_seasons_collected(
        self, detector: DuplicateDetector, video_dir: Path
    ):
        """Les saisons existantes sont collectées dans le DuplicateMatch."""
        series_dir = (
            video_dir / "Series" / "TV" / "B-C" / "Bureau des Legendes (2015)"
        )
        series_dir.mkdir(parents=True)
        for s in [1, 2, 3]:
            saison = series_dir / f"Saison {s:02d}"
            saison.mkdir()
            (saison / f"BDL S{s:02d}E01.mkv").write_bytes(b"\x00" * 1024)

        result = detector.detect_duplicate(
            title="Bureau des Legendes",
            year=2015,
            video_dir=video_dir,
            is_series=True,
        )

        assert result is not None
        assert result.existing_seasons == {1, 2, 3}

    def test_metadata_extracted_from_filename(
        self, detector: DuplicateDetector, video_dir: Path
    ):
        """Résolution et codecs extraits du nom de fichier standardisé."""
        films_dir = video_dir / "Films" / "Action" / "M-N" / "Matrix (1999)"
        films_dir.mkdir(parents=True)
        (films_dir / "Matrix (1999) FR DTS x265 1080p.mkv").write_bytes(
            b"\x00" * 2048
        )

        result = detector.detect_duplicate(
            title="Matrix",
            year=1999,
            video_dir=video_dir,
            is_series=False,
        )

        assert result is not None
        assert len(result.existing_files) == 1
        f = result.existing_files[0]
        assert f.resolution == "1080p"
        assert f.video_codec == "x265"
        assert f.audio_codec == "DTS"

    def test_bitrate_in_breakdown(self, detector: DuplicateDetector):
        """Le breakdown contient le bitrate calculé et influence le score."""
        from src.services.transferer import ExistingFileInfo

        # 2 Go pour 54 min → ~5 Mb/s (score 65)
        existing_files = [
            ExistingFileInfo(
                path=Path("/fake/old.mkv"),
                size_bytes=2_000_000_000,
                resolution="1080p",
                video_codec="HEVC",
                audio_codec="AAC",
                duration_seconds=3240,
            )
        ]
        # 450 Mo pour 54 min → ~1.1 Mb/s (score 35)
        new_file = ExistingFileInfo(
            path=Path("/fake/new.mkv"),
            size_bytes=450_000_000,
            resolution="1080p",
            video_codec="HEVC",
            audio_codec="AAC",
            duration_seconds=3240,
        )

        comparison = detector.compare_quality(existing_files, new_file)
        assert comparison.existing_breakdown["video_bitrate"] != "?"
        assert comparison.new_breakdown["video_bitrate"] != "?"
        # L'ancien a un bien meilleur débit → score supérieur
        assert comparison.existing_score > comparison.new_score
        assert comparison.recommended == "old"


class TestCompareQuality:
    """Comparaison de qualité entre versions."""

    def test_new_better_quality(self, detector: DuplicateDetector):
        """Le nouveau (1080p HEVC) est meilleur que l'ancien (720p H264)."""
        from src.services.transferer import ExistingFileInfo

        existing_files = [
            ExistingFileInfo(
                path=Path("/fake/old.mkv"),
                size_bytes=700_000_000,
                resolution="720p",
                video_codec="H.264",
                audio_codec="AC3",
            )
        ]
        new_file = ExistingFileInfo(
            path=Path("/fake/new.mkv"),
            size_bytes=1_500_000_000,
            resolution="1080p",
            video_codec="HEVC",
            audio_codec="DTS",
        )

        comparison = detector.compare_quality(existing_files, new_file)

        assert comparison.recommended == "new"
        assert comparison.new_score > comparison.existing_score

    def test_old_better_quality(self, detector: DuplicateDetector):
        """L'ancien (4K HEVC) est meilleur que le nouveau (720p H264)."""
        from src.services.transferer import ExistingFileInfo

        existing_files = [
            ExistingFileInfo(
                path=Path("/fake/old.mkv"),
                size_bytes=5_000_000_000,
                resolution="4K",
                video_codec="HEVC",
                audio_codec="TrueHD",
            )
        ]
        new_file = ExistingFileInfo(
            path=Path("/fake/new.mkv"),
            size_bytes=400_000_000,
            resolution="720p",
            video_codec="H.264",
            audio_codec="AAC",
        )

        comparison = detector.compare_quality(existing_files, new_file)

        assert comparison.recommended == "old"
        assert comparison.existing_score > comparison.new_score

    def test_equal_quality_prefers_new(self, detector: DuplicateDetector):
        """À qualité égale, recommander le nouveau (plus récent)."""
        from src.services.transferer import ExistingFileInfo

        existing_files = [
            ExistingFileInfo(
                path=Path("/fake/old.mkv"),
                size_bytes=1_500_000_000,
                resolution="1080p",
                video_codec="HEVC",
                audio_codec="AC3",
            )
        ]
        new_file = ExistingFileInfo(
            path=Path("/fake/new.mkv"),
            size_bytes=1_500_000_000,
            resolution="1080p",
            video_codec="HEVC",
            audio_codec="AC3",
        )

        comparison = detector.compare_quality(existing_files, new_file)

        assert comparison.recommended == "new"


class TestMissingEpisodeNotDuplicate:
    """Un épisode manquant ajouté à une série existante n'est PAS un doublon.

    Bug critique corrigé : ajouter S01E06 à une série qui a S01E01-E05
    ne doit pas marquer l'épisode comme doublon (et donc sandbox toute la série).
    """

    def test_missing_episode_not_duplicate(
        self, detector: DuplicateDetector, video_dir: Path
    ):
        """Épisode S01E06 manquant dans une série qui a S01E01-E05."""
        series_dir = (
            video_dir
            / "Series"
            / "Animation"
            / "K-L"
            / "Love, Death & Robots (2019)"
        )
        saison = series_dir / "Saison 01"
        saison.mkdir(parents=True)
        for ep in range(1, 6):
            (saison / f"Love, Death & Robots (2019) - S01E{ep:02d}.mkv").write_bytes(
                b"\x00" * 1024
            )

        result = detector.detect_duplicate(
            title="Love, Death & Robots",
            year=2019,
            video_dir=video_dir,
            is_series=True,
        )

        assert result is not None
        assert result.existing_episodes is not None
        assert "S01E06" not in result.existing_episodes
        assert "S01E01" in result.existing_episodes

    def test_existing_episode_is_duplicate(
        self, detector: DuplicateDetector, video_dir: Path
    ):
        """Épisode S01E01 existe déjà → c'est un vrai doublon."""
        series_dir = (
            video_dir
            / "Series"
            / "Animation"
            / "K-L"
            / "Love, Death & Robots (2019)"
        )
        saison = series_dir / "Saison 01"
        saison.mkdir(parents=True)
        (saison / "Love, Death & Robots (2019) - S01E01.mkv").write_bytes(
            b"\x00" * 1024
        )

        result = detector.detect_duplicate(
            title="Love, Death & Robots",
            year=2019,
            video_dir=video_dir,
            is_series=True,
        )

        assert result is not None
        assert result.existing_episodes is not None
        assert "S01E01" in result.existing_episodes

    def test_existing_episodes_collected(
        self, detector: DuplicateDetector, video_dir: Path
    ):
        """Les identifiants SxxExx sont correctement collectés."""
        series_dir = video_dir / "Series" / "TV" / "B" / "Big Mouth (2022)"
        saison1 = series_dir / "Saison 01"
        saison1.mkdir(parents=True)
        saison2 = series_dir / "Saison 02"
        saison2.mkdir(parents=True)
        (saison1 / "Big Mouth (2022) - S01E01.mkv").write_bytes(b"\x00" * 1024)
        (saison1 / "Big Mouth (2022) - S01E02.mkv").write_bytes(b"\x00" * 1024)
        (saison2 / "Big Mouth (2022) - S02E01.mkv").write_bytes(b"\x00" * 1024)

        result = detector.detect_duplicate(
            title="Big Mouth",
            year=2022,
            video_dir=video_dir,
            is_series=True,
        )

        assert result is not None
        assert result.existing_episodes == {"S01E01", "S01E02", "S02E01"}
