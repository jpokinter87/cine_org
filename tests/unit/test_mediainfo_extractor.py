"""
Tests unitaires pour MediaInfoExtractor.

Tests pour valider l'extraction des metadonnees techniques
depuis les fichiers video avec pymediainfo.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.adapters.parsing.mediainfo_extractor import MediaInfoExtractor
from src.core.value_objects.media_info import (
    AudioCodec,
    Language,
    MediaInfo,
    Resolution,
    VideoCodec,
)


@pytest.fixture
def extractor() -> MediaInfoExtractor:
    """Instance de l'extracteur pour les tests."""
    return MediaInfoExtractor()


@pytest.fixture
def mock_video_track_1080p() -> MagicMock:
    """Mock d'une piste video 1080p HEVC."""
    mock = MagicMock()
    mock.track_type = "Video"
    mock.width = 1920
    mock.height = 1080
    mock.format = "HEVC"
    mock.format_profile = "Main 10"
    return mock


@pytest.fixture
def mock_general_track_2h() -> MagicMock:
    """Mock d'une piste generale avec duree 2 heures."""
    mock = MagicMock()
    mock.track_type = "General"
    mock.duration = 7200000  # 2 heures en ms
    return mock


class TestMediaInfoExtractorResolution:
    """Tests pour l'extraction de la resolution."""

    def test_extracts_1080p_resolution(
        self,
        extractor: MediaInfoExtractor,
        mock_video_track_1080p: MagicMock,
        mock_general_track_2h: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test extraction d'une resolution 1080p."""
        # Creer un fichier factice pour passer le check exists()
        fake_video = tmp_path / "video.mkv"
        fake_video.touch()

        mock_media_info = MagicMock()
        mock_media_info.tracks = [mock_general_track_2h, mock_video_track_1080p]

        with patch(
            "src.adapters.parsing.mediainfo_extractor.PyMediaInfo.parse"
        ) as mock_parse:
            mock_parse.return_value = mock_media_info

            result = extractor.extract(fake_video)

        assert result is not None
        assert result.resolution is not None
        assert result.resolution.width == 1920
        assert result.resolution.height == 1080
        assert result.resolution.label == "1080p"

    def test_extracts_4k_resolution(
        self,
        extractor: MediaInfoExtractor,
        mock_general_track_2h: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test extraction d'une resolution 4K."""
        fake_video = tmp_path / "video.mkv"
        fake_video.touch()

        mock_video_track = MagicMock()
        mock_video_track.track_type = "Video"
        mock_video_track.width = 3840
        mock_video_track.height = 2160
        mock_video_track.format = "HEVC"
        mock_video_track.format_profile = None

        mock_media_info = MagicMock()
        mock_media_info.tracks = [mock_general_track_2h, mock_video_track]

        with patch(
            "src.adapters.parsing.mediainfo_extractor.PyMediaInfo.parse"
        ) as mock_parse:
            mock_parse.return_value = mock_media_info

            result = extractor.extract(fake_video)

        assert result is not None
        assert result.resolution is not None
        assert result.resolution.label == "4K"


class TestMediaInfoExtractorCodecs:
    """Tests pour l'extraction des codecs."""

    def test_normalizes_video_codec_hevc_to_x265(
        self,
        extractor: MediaInfoExtractor,
        mock_video_track_1080p: MagicMock,
        mock_general_track_2h: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test normalisation du codec video HEVC vers x265."""
        fake_video = tmp_path / "video.mkv"
        fake_video.touch()

        mock_media_info = MagicMock()
        mock_media_info.tracks = [mock_general_track_2h, mock_video_track_1080p]

        with patch(
            "src.adapters.parsing.mediainfo_extractor.PyMediaInfo.parse"
        ) as mock_parse:
            mock_parse.return_value = mock_media_info

            result = extractor.extract(fake_video)

        assert result is not None
        assert result.video_codec is not None
        assert result.video_codec.name == "x265"
        assert result.video_codec.profile == "Main 10"

    def test_normalizes_video_codec_avc_to_x264(
        self,
        extractor: MediaInfoExtractor,
        mock_general_track_2h: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test normalisation du codec video AVC vers x264."""
        fake_video = tmp_path / "video.mkv"
        fake_video.touch()

        mock_video_track = MagicMock()
        mock_video_track.track_type = "Video"
        mock_video_track.width = 1920
        mock_video_track.height = 1080
        mock_video_track.format = "AVC"
        mock_video_track.format_profile = "High"

        mock_media_info = MagicMock()
        mock_media_info.tracks = [mock_general_track_2h, mock_video_track]

        with patch(
            "src.adapters.parsing.mediainfo_extractor.PyMediaInfo.parse"
        ) as mock_parse:
            mock_parse.return_value = mock_media_info

            result = extractor.extract(fake_video)

        assert result is not None
        assert result.video_codec is not None
        assert result.video_codec.name == "x264"

    def test_normalizes_audio_codec_ac3(
        self,
        extractor: MediaInfoExtractor,
        mock_video_track_1080p: MagicMock,
        mock_general_track_2h: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test normalisation du codec audio AC-3 vers AC3."""
        fake_video = tmp_path / "video.mkv"
        fake_video.touch()

        mock_audio_track = MagicMock()
        mock_audio_track.track_type = "Audio"
        mock_audio_track.format = "AC-3"
        mock_audio_track.channel_s = 6
        mock_audio_track.language = "en"

        mock_media_info = MagicMock()
        mock_media_info.tracks = [
            mock_general_track_2h,
            mock_video_track_1080p,
            mock_audio_track,
        ]

        with patch(
            "src.adapters.parsing.mediainfo_extractor.PyMediaInfo.parse"
        ) as mock_parse:
            mock_parse.return_value = mock_media_info

            result = extractor.extract(fake_video)

        assert result is not None
        assert len(result.audio_codecs) == 1
        assert result.audio_codecs[0].name == "AC3"
        assert result.audio_codecs[0].channels == "5.1"


class TestMediaInfoExtractorDuration:
    """Tests pour l'extraction de la duree."""

    def test_converts_duration_ms_to_seconds(
        self,
        extractor: MediaInfoExtractor,
        mock_video_track_1080p: MagicMock,
        mock_general_track_2h: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test conversion de la duree de millisecondes en secondes."""
        fake_video = tmp_path / "video.mkv"
        fake_video.touch()

        mock_media_info = MagicMock()
        mock_media_info.tracks = [mock_general_track_2h, mock_video_track_1080p]

        with patch(
            "src.adapters.parsing.mediainfo_extractor.PyMediaInfo.parse"
        ) as mock_parse:
            mock_parse.return_value = mock_media_info

            result = extractor.extract(fake_video)

        assert result is not None
        assert result.duration_seconds == 7200  # 2 heures en secondes

    def test_duration_90_minutes(
        self,
        extractor: MediaInfoExtractor,
        mock_video_track_1080p: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test duree typique d'un film (90 minutes)."""
        fake_video = tmp_path / "video.mkv"
        fake_video.touch()

        mock_general_track = MagicMock()
        mock_general_track.track_type = "General"
        mock_general_track.duration = 5400000  # 90 minutes en millisecondes

        mock_media_info = MagicMock()
        mock_media_info.tracks = [mock_general_track, mock_video_track_1080p]

        with patch(
            "src.adapters.parsing.mediainfo_extractor.PyMediaInfo.parse"
        ) as mock_parse:
            mock_parse.return_value = mock_media_info

            result = extractor.extract(fake_video)

        assert result is not None
        assert result.duration_seconds == 5400  # 90 minutes en secondes


class TestMediaInfoExtractorLanguages:
    """Tests pour l'extraction des langues."""

    def test_extracts_french_language(
        self,
        extractor: MediaInfoExtractor,
        mock_video_track_1080p: MagicMock,
        mock_general_track_2h: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test extraction de la langue francaise."""
        fake_video = tmp_path / "video.mkv"
        fake_video.touch()

        mock_audio_track = MagicMock()
        mock_audio_track.track_type = "Audio"
        mock_audio_track.format = "AAC"
        mock_audio_track.channel_s = 2
        mock_audio_track.language = "fr"

        mock_media_info = MagicMock()
        mock_media_info.tracks = [
            mock_general_track_2h,
            mock_video_track_1080p,
            mock_audio_track,
        ]

        with patch(
            "src.adapters.parsing.mediainfo_extractor.PyMediaInfo.parse"
        ) as mock_parse:
            mock_parse.return_value = mock_media_info

            result = extractor.extract(fake_video)

        assert result is not None
        assert len(result.audio_languages) == 1
        assert result.audio_languages[0].code == "fr"
        assert result.audio_languages[0].name == "Francais"

    def test_extracts_multiple_languages(
        self,
        extractor: MediaInfoExtractor,
        mock_video_track_1080p: MagicMock,
        mock_general_track_2h: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test extraction de plusieurs langues."""
        fake_video = tmp_path / "video.mkv"
        fake_video.touch()

        mock_audio_fr = MagicMock()
        mock_audio_fr.track_type = "Audio"
        mock_audio_fr.format = "AAC"
        mock_audio_fr.channel_s = 2
        mock_audio_fr.language = "fr"

        mock_audio_en = MagicMock()
        mock_audio_en.track_type = "Audio"
        mock_audio_en.format = "AC-3"
        mock_audio_en.channel_s = 6
        mock_audio_en.language = "en"

        mock_media_info = MagicMock()
        mock_media_info.tracks = [
            mock_general_track_2h,
            mock_video_track_1080p,
            mock_audio_fr,
            mock_audio_en,
        ]

        with patch(
            "src.adapters.parsing.mediainfo_extractor.PyMediaInfo.parse"
        ) as mock_parse:
            mock_parse.return_value = mock_media_info

            result = extractor.extract(fake_video)

        assert result is not None
        assert len(result.audio_languages) == 2
        language_codes = [lang.code for lang in result.audio_languages]
        assert "fr" in language_codes
        assert "en" in language_codes


class TestMediaInfoExtractorErrorHandling:
    """Tests pour la gestion des erreurs."""

    def test_returns_none_for_nonexistent_file(
        self, extractor: MediaInfoExtractor, tmp_path: Path
    ) -> None:
        """Test retourne None pour un fichier inexistant."""
        nonexistent = tmp_path / "nonexistent.mkv"

        result = extractor.extract(nonexistent)

        assert result is None

    def test_returns_none_on_parse_exception(
        self, extractor: MediaInfoExtractor, tmp_path: Path
    ) -> None:
        """Test retourne None si pymediainfo leve une exception."""
        # Creer un fichier vide (pas un vrai video)
        fake_video = tmp_path / "fake.mkv"
        fake_video.write_text("not a video")

        with patch(
            "src.adapters.parsing.mediainfo_extractor.PyMediaInfo.parse"
        ) as mock_parse:
            mock_parse.side_effect = Exception("Parse error")

            result = extractor.extract(fake_video)

        assert result is None
