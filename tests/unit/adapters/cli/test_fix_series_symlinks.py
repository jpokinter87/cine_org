"""Tests unitaires pour la commande fix-series-symlinks."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.adapters.cli.commands.fix_series_symlinks_command import (
    _build_media_info_from_guessit,
    _check_episode_title,
    _check_saison_dir,
    _check_tech_specs,
    _compute_expected_dir,
    _extract_tech_from_storage,
    _normalize_for_compare,
)
from src.adapters.parsing.guessit_parser import GuessitFilenameParser
from src.core.entities.media import Series
from src.core.value_objects.media_info import MediaInfo, Resolution, VideoCodec
from src.core.value_objects.parsed_info import ParsedFilename


class TestBuildMediaInfoFromGuessit:
    """Tests pour _build_media_info_from_guessit."""

    def test_full_info(self):
        """Extrait codec et resolution depuis guessit."""
        parsed = ParsedFilename(
            title="Test",
            video_codec="H.264",
            resolution="1080p",
        )
        mi = _build_media_info_from_guessit(parsed)
        assert mi is not None
        assert mi.video_codec.name == "x264"
        assert mi.resolution.width == 1920
        assert mi.resolution.height == 1080

    def test_hevc_to_x265(self):
        """Convertit HEVC en x265."""
        parsed = ParsedFilename(
            title="Test",
            video_codec="H.265",
            resolution="720p",
        )
        mi = _build_media_info_from_guessit(parsed)
        assert mi is not None
        assert mi.video_codec.name == "x265"
        assert mi.resolution.label == "720p"

    def test_x264_unchanged(self):
        """Garde x264 tel quel."""
        parsed = ParsedFilename(title="Test", video_codec="x264", resolution="1080p")
        mi = _build_media_info_from_guessit(parsed)
        assert mi.video_codec.name == "x264"

    def test_4k_resolution(self):
        """Detecte la resolution 4K."""
        parsed = ParsedFilename(title="Test", video_codec="H.265", resolution="2160p")
        mi = _build_media_info_from_guessit(parsed)
        assert mi.resolution.label == "4K"

    def test_no_tech_info(self):
        """Retourne None si pas d'infos techniques."""
        parsed = ParsedFilename(title="Test")
        mi = _build_media_info_from_guessit(parsed)
        assert mi is None

    def test_codec_only(self):
        """Retourne MediaInfo avec codec seul."""
        parsed = ParsedFilename(title="Test", video_codec="H.264")
        mi = _build_media_info_from_guessit(parsed)
        assert mi is not None
        assert mi.video_codec.name == "x264"
        assert mi.resolution is None


class TestExtractTechFromStorage:
    """Tests pour _extract_tech_from_storage (mediainfo primaire, guessit fallback)."""

    def test_mediainfo_primary(self, tmp_path):
        """mediainfo est toujours appele en premier (pipeline standard)."""
        from src.core.value_objects.media_info import AudioCodec, Language

        storage = tmp_path / "Breaking.Bad.S01E01.720p.BluRay.x264-DEMAND.mkv"
        storage.write_text("data")

        parser = GuessitFilenameParser()
        mock_extractor = MagicMock()
        mock_extractor.extract.return_value = MediaInfo(
            resolution=Resolution(width=1280, height=720),
            video_codec=VideoCodec(name="x264"),
            audio_languages=(Language(code="fr", name="Francais"),),
        )

        mi, lang, sub_lang = _extract_tech_from_storage(
            storage, parser, mock_extractor
        )

        # mediainfo a ete appele sur le fichier
        mock_extractor.extract.assert_called_once_with(storage)
        # Les resultats viennent de mediainfo
        assert mi.video_codec.name == "x264"
        assert mi.resolution.label == "720p"
        assert len(mi.audio_languages) == 1

    def test_guessit_provides_fallback_language(self, tmp_path):
        """guessit fournit la langue fallback (depuis le nom de fichier)."""
        storage = tmp_path / "Naruto.S01E01.MULTi.1080p.BluRay.x265-GROUP.mkv"
        storage.write_text("data")

        parser = GuessitFilenameParser()
        mock_extractor = MagicMock()
        mock_extractor.extract.return_value = MediaInfo(
            resolution=Resolution(width=1920, height=1080),
            video_codec=VideoCodec(name="x265"),
        )

        mi, lang, sub_lang = _extract_tech_from_storage(
            storage, parser, mock_extractor
        )

        # MediaInfo vient de mediainfo, langue vient de guessit
        assert mi.video_codec.name == "x265"

    def test_guessit_detects_vostfr(self, tmp_path):
        """guessit detecte VOSTFR comme subtitle_language."""
        storage = tmp_path / "Monster.S01E01.VOSTFR.720p.BluRay.x264.mkv"
        storage.write_text("data")

        parser = GuessitFilenameParser()
        mock_extractor = MagicMock()
        mock_extractor.extract.return_value = MediaInfo(
            resolution=Resolution(width=1280, height=720),
            video_codec=VideoCodec(name="x264"),
        )

        mi, lang, sub_lang = _extract_tech_from_storage(
            storage, parser, mock_extractor
        )

        assert sub_lang == "FR"

    def test_guessit_fallback_when_mediainfo_fails(self, tmp_path):
        """Si mediainfo echoue, guessit fournit les specs techniques."""
        storage = tmp_path / "Show.S01E01.1080p.x264.mkv"
        storage.write_text("data")

        parser = GuessitFilenameParser()
        mock_extractor = MagicMock()
        mock_extractor.extract.return_value = None  # mediainfo echoue

        mi, lang, sub_lang = _extract_tech_from_storage(
            storage, parser, mock_extractor
        )

        # Fallback guessit : codec et resolution extraits du nom
        assert mi is not None
        assert mi.video_codec.name == "x264"
        assert mi.resolution.label == "1080p"

    def test_no_info_at_all(self, tmp_path):
        """Aucune info si mediainfo echoue et guessit n'extrait rien."""
        storage = tmp_path / "Show.S01E01.mkv"
        storage.write_text("data")

        parser = GuessitFilenameParser()
        mock_extractor = MagicMock()
        mock_extractor.extract.return_value = None

        mi, lang, sub_lang = _extract_tech_from_storage(
            storage, parser, mock_extractor
        )

        # Ni mediainfo ni guessit n'ont pu extraire
        assert mi is None


class TestCheckSaisonDir:
    """Tests pour _check_saison_dir."""

    def test_valid_saison(self, tmp_path):
        """Detecte un repertoire Saison correctement formate."""
        saison_dir = tmp_path / "Saison 01"
        saison_dir.mkdir()
        symlink = saison_dir / "ep.mkv"
        assert _check_saison_dir(symlink) is True

    def test_invalid_saison(self, tmp_path):
        """Rejette un repertoire Saison mal formate."""
        saison_dir = tmp_path / "Saison 1"
        saison_dir.mkdir()
        symlink = saison_dir / "ep.mkv"
        assert _check_saison_dir(symlink) is False

    def test_no_saison(self, tmp_path):
        """Rejette si pas de repertoire Saison."""
        series_dir = tmp_path / "Breaking Bad (2008)"
        series_dir.mkdir()
        symlink = series_dir / "ep.mkv"
        assert _check_saison_dir(symlink) is False


class TestCheckTechSpecs:
    """Tests pour _check_tech_specs."""

    def test_all_specs_present(self):
        """Detecte toutes les specs techniques."""
        name = "Show (2020) - S01E01 - Pilot - MULTi x264 1080p.mkv"
        result = _check_tech_specs(name)
        assert result == {"resolution": True, "codec": True, "language": True}

    def test_x265_detected(self):
        """Detecte x265 comme codec."""
        name = "Show (2020) - S01E01 - x265 1080p.mkv"
        result = _check_tech_specs(name)
        assert result["codec"] is True

    def test_sd_resolution(self):
        """Detecte SD comme resolution valide."""
        name = "Show (2020) - S01E01 - Pilot - FR x264 SD.avi"
        result = _check_tech_specs(name)
        assert result == {"resolution": True, "codec": True, "language": True}

    def test_mpeg4_codec(self):
        """Detecte MPEG-4 comme codec valide."""
        name = "Show (2020) - S01E01 - MPEG-4 SD.avi"
        result = _check_tech_specs(name)
        assert result["codec"] is True

    def test_no_specs(self):
        """Aucune spec detectee."""
        name = "Show (2020) - S01E01 - Pilot.mkv"
        result = _check_tech_specs(name)
        assert result == {"resolution": False, "codec": False, "language": False}


class TestNormalizeForCompare:
    """Tests pour _normalize_for_compare."""

    def test_strips_punctuation(self):
        """Retire la ponctuation pour comparaison."""
        assert _normalize_for_compare('"Fonda"') == "fonda"
        assert _normalize_for_compare("C'est la faute") == "c est la faute"

    def test_normalizes_dashes(self):
        """Normalise les tirets."""
        assert _normalize_for_compare("-Fonda-") == "fonda"

    def test_ligatures(self):
        """Decompose les ligatures Œ/Æ."""
        assert _normalize_for_compare("L'Œil de verre") == "l oeil de verre"
        assert _normalize_for_compare("L'Oeil de verre") == "l oeil de verre"
        assert _normalize_for_compare("Æon Flux") == "aeon flux"

    def test_slash_vs_dash(self):
        """Unifie slash et tiret pour comparaison."""
        assert _normalize_for_compare("partie 1/3") == "partie 1 3"
        assert _normalize_for_compare("partie 1-3") == "partie 1 3"


class TestComputeExpectedDir:
    """Tests pour _compute_expected_dir."""

    def test_finds_saison_dir(self, tmp_path):
        """Trouve un repertoire Saison existant."""
        saison_dir = tmp_path / "Series" / "TV" / "B" / "Breaking Bad" / "Saison 01"
        saison_dir.mkdir(parents=True)
        symlink = saison_dir / "ep.mkv"

        series = Series(id="1", title="Breaking Bad", year=2008)
        result = _compute_expected_dir(symlink, series, 1, tmp_path)
        assert result == saison_dir

    def test_corrects_bad_saison_format(self, tmp_path):
        """Corrige Saison 1 → Saison 01."""
        bad_dir = tmp_path / "Series" / "TV" / "U" / "Undone" / "Saison 1"
        bad_dir.mkdir(parents=True)
        symlink = bad_dir / "ep.mkv"

        series = Series(id="1", title="Undone", year=2019)
        result = _compute_expected_dir(symlink, series, 1, tmp_path)
        assert result.name == "Saison 01"

    def test_finds_series_dir_and_adds_saison(self, tmp_path):
        """Ajoute Saison au repertoire serie si manquant."""
        series_dir = tmp_path / "Series" / "TV" / "M" / "Monster (2017)"
        series_dir.mkdir(parents=True)
        symlink = series_dir / "ep.mkv"

        series = Series(id="1", title="Monster", year=2017)
        result = _compute_expected_dir(symlink, series, 1, tmp_path)
        assert result == series_dir / "Saison 01"
