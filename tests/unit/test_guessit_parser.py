"""
Tests unitaires pour GuessitFilenameParser.

Tests TDD pour valider le parsing des noms de fichiers video
avec guessit, couvrant films, series, double episodes, et type hints.
"""

import pytest

from src.adapters.parsing.guessit_parser import GuessitFilenameParser
from src.core.value_objects.parsed_info import MediaType, ParsedFilename


class TestGuessitFilenameParserMovies:
    """Tests pour le parsing de noms de fichiers de films."""

    @pytest.fixture
    def parser(self) -> GuessitFilenameParser:
        """Instance du parser pour les tests."""
        return GuessitFilenameParser()

    def test_basic_movie_parsing(self, parser: GuessitFilenameParser) -> None:
        """Test parsing d'un film basique avec annee et qualite."""
        result = parser.parse("Inception.2010.1080p.BluRay.x264-SPARKS.mkv", None)

        assert result.title == "Inception"
        assert result.year == 2010
        assert result.media_type == MediaType.MOVIE
        assert result.resolution == "1080p"
        assert result.source == "Blu-ray"
        assert result.release_group == "SPARKS"

    def test_movie_with_french_language(self, parser: GuessitFilenameParser) -> None:
        """Test parsing d'un film avec indicateur de langue francaise."""
        result = parser.parse("The.Matrix.1999.FRENCH.720p.BluRay.mkv", MediaType.MOVIE)

        assert result.title == "The Matrix"
        assert result.year == 1999
        assert result.media_type == MediaType.MOVIE
        assert result.resolution == "720p"
        assert result.language == "FR"

    def test_movie_with_episode_like_title(self, parser: GuessitFilenameParser) -> None:
        """Test qu'un titre avec Episode n'est pas detecte comme serie."""
        result = parser.parse(
            "Star.Wars.Episode.IV.A.New.Hope.1977.mkv", MediaType.MOVIE
        )

        # Avec type_hint MOVIE, doit detecter comme film meme si le titre contient "Episode"
        assert "Star Wars" in result.title
        assert result.year == 1977
        assert result.media_type == MediaType.MOVIE
        # Pas de saison/episode car c'est un film
        assert result.season is None
        assert result.episode is None

    def test_movie_with_multi_word_title(self, parser: GuessitFilenameParser) -> None:
        """Test parsing d'un film avec titre multi-mots."""
        result = parser.parse(
            "The.Lord.of.the.Rings.The.Fellowship.of.the.Ring.2001.mkv", None
        )

        assert "Lord" in result.title or "Rings" in result.title
        assert result.year == 2001
        assert result.media_type == MediaType.MOVIE


class TestGuessitFilenameParserSeries:
    """Tests pour le parsing de noms de fichiers de series."""

    @pytest.fixture
    def parser(self) -> GuessitFilenameParser:
        """Instance du parser pour les tests."""
        return GuessitFilenameParser()

    def test_basic_series_parsing(self, parser: GuessitFilenameParser) -> None:
        """Test parsing d'un episode de serie basique."""
        result = parser.parse("Breaking.Bad.S01E01.720p.HDTV.x264-CTU.mkv", None)

        assert result.title == "Breaking Bad"
        assert result.media_type == MediaType.SERIES
        assert result.season == 1
        assert result.episode == 1
        assert result.resolution == "720p"
        assert result.source == "HDTV"
        assert result.release_group == "CTU"

    def test_double_episode_parsing(self, parser: GuessitFilenameParser) -> None:
        """Test parsing d'un double episode (S03E09E10)."""
        result = parser.parse("Game.of.Thrones.S03E09E10.1080p.mkv", MediaType.SERIES)

        assert result.title == "Game of Thrones"
        assert result.media_type == MediaType.SERIES
        assert result.season == 3
        assert result.episode == 9
        assert result.episode_end == 10

    def test_series_with_episode_title(self, parser: GuessitFilenameParser) -> None:
        """Test parsing d'un episode avec titre d'episode."""
        result = parser.parse("The.Office.US.S02E03.The.Dundies.mkv", None)

        assert "Office" in result.title
        assert result.media_type == MediaType.SERIES
        assert result.season == 2
        assert result.episode == 3
        assert result.episode_title == "The Dundies"

    def test_multi_season_returns_first(self, parser: GuessitFilenameParser) -> None:
        """Test que quand guessit retourne plusieurs saisons, on prend la premiere."""
        # Simuler le cas "Bref" où guessit retourne season=[1, 90]
        from unittest.mock import patch

        fake_result = {
            "title": "Bref",
            "season": [1, 90],
            "episode": 56,
            "type": "episode",
        }
        with patch("guessit.guessit", return_value=fake_result):
            result = parser.parse("Bref - S01E56.mkv", MediaType.SERIES)

        assert result.season == 1
        assert result.episode == 56


class TestGuessitFilenameParserTypeHint:
    """Tests pour le respect du type_hint fourni."""

    @pytest.fixture
    def parser(self) -> GuessitFilenameParser:
        """Instance du parser pour les tests."""
        return GuessitFilenameParser()

    def test_type_hint_movie_overrides_series_pattern(
        self, parser: GuessitFilenameParser
    ) -> None:
        """Test que le type_hint MOVIE est respecte meme si le nom ressemble a une serie."""
        # Ce nom ressemble a une serie mais le type_hint dit que c'est un film
        result = parser.parse("Movie.Name.S01E01.mkv", MediaType.MOVIE)

        # Le type_hint MOVIE doit etre respecte
        assert result.media_type == MediaType.MOVIE

    def test_type_hint_series_overrides_movie_pattern(
        self, parser: GuessitFilenameParser
    ) -> None:
        """Test que le type_hint SERIES est respecte."""
        result = parser.parse("Some.Video.2020.mkv", MediaType.SERIES)

        # Le type_hint SERIES doit etre respecte
        assert result.media_type == MediaType.SERIES

    def test_no_type_hint_detects_automatically(
        self, parser: GuessitFilenameParser
    ) -> None:
        """Test que sans type_hint, le type est detecte automatiquement."""
        # Film sans type_hint
        movie_result = parser.parse("Inception.2010.mkv", None)
        assert movie_result.media_type == MediaType.MOVIE

        # Serie sans type_hint
        series_result = parser.parse("Breaking.Bad.S01E01.mkv", None)
        assert series_result.media_type == MediaType.SERIES


class TestGuessitFilenameParserTechnicalInfo:
    """Tests pour l'extraction des informations techniques du nom de fichier."""

    @pytest.fixture
    def parser(self) -> GuessitFilenameParser:
        """Instance du parser pour les tests."""
        return GuessitFilenameParser()

    def test_video_codec_extraction(self, parser: GuessitFilenameParser) -> None:
        """Test extraction du codec video depuis le nom de fichier."""
        # Note: guessit reconnait H265/HEVC mais pas x265 dans certaines versions
        result = parser.parse("Movie.2020.H265.1080p.mkv", None)

        assert result.video_codec is not None
        assert "265" in result.video_codec or "HEVC" in result.video_codec

    def test_audio_codec_extraction(self, parser: GuessitFilenameParser) -> None:
        """Test extraction du codec audio depuis le nom de fichier."""
        result = parser.parse("Movie.2020.AAC.1080p.mkv", None)

        assert result.audio_codec == "AAC"

    def test_resolution_extraction(self, parser: GuessitFilenameParser) -> None:
        """Test extraction de la resolution depuis le nom de fichier."""
        result = parser.parse("Movie.2020.1080p.mkv", None)

        assert result.resolution == "1080p"

    def test_4k_resolution_extraction(self, parser: GuessitFilenameParser) -> None:
        """Test extraction de la resolution 4K."""
        result = parser.parse("Movie.2020.2160p.mkv", None)

        assert result.resolution == "2160p"

    def test_full_technical_info(self, parser: GuessitFilenameParser) -> None:
        """Test extraction de toutes les infos techniques."""
        # Note: guessit reconnait H265/HEVC mais pas x265 dans certaines versions
        result = parser.parse("Movie.2020.HEVC.AAC.1080p.BluRay.mkv", None)

        assert result.year == 2020
        assert result.resolution == "1080p"
        assert result.source == "Blu-ray"
        assert result.audio_codec == "AAC"
        assert result.video_codec is not None
        assert "265" in result.video_codec or "HEVC" in result.video_codec


class TestGuessitFilenameParserEdgeCases:
    """Tests pour les cas limites et edge cases."""

    @pytest.fixture
    def parser(self) -> GuessitFilenameParser:
        """Instance du parser pour les tests."""
        return GuessitFilenameParser()

    def test_simple_filename_without_info(
        self, parser: GuessitFilenameParser
    ) -> None:
        """Test parsing d'un nom de fichier simple sans metadonnees."""
        result = parser.parse("random_video.mkv", None)

        # Doit au moins avoir un titre
        assert result.title is not None
        assert len(result.title) > 0

    def test_filename_with_dots_in_title(
        self, parser: GuessitFilenameParser
    ) -> None:
        """Test parsing d'un fichier avec points dans le titre."""
        result = parser.parse("Dr.Strange.2016.mkv", None)

        assert result.title is not None
        assert result.year == 2016

    def test_unknown_type_when_ambiguous(
        self, parser: GuessitFilenameParser
    ) -> None:
        """Test que le type est UNKNOWN quand non determinable sans hint."""
        result = parser.parse("video_file.mkv", None)

        # Pour un nom tres generique, le type peut etre UNKNOWN
        # ou guessit peut deviner MOVIE par defaut
        assert result.media_type in [MediaType.UNKNOWN, MediaType.MOVIE]
