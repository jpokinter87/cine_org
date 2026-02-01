"""
Tests unitaires pour RenamerService.

Tests TDD pour la génération de noms de fichiers standardisés.
"""

import pytest

from src.core.entities.media import Movie, Series, Episode
from src.core.value_objects.media_info import (
    MediaInfo,
    Resolution,
    VideoCodec,
    AudioCodec,
    Language,
)
from src.services.renamer import (
    sanitize_for_filesystem,
    format_language_code,
    generate_movie_filename,
    generate_series_filename,
)


# ====================
# Fixtures
# ====================

@pytest.fixture
def movie_fixture() -> Movie:
    """Film Matrix avec métadonnées complètes."""
    return Movie(
        tmdb_id=603,
        title="Matrix",
        original_title="The Matrix",
        year=1999,
        genres=("Science-Fiction", "Action"),
        duration_seconds=8160,  # 136 minutes
    )


@pytest.fixture
def movie_without_year() -> Movie:
    """Film sans année."""
    return Movie(
        title="Inception",
        genres=("Science-Fiction",),
    )


@pytest.fixture
def series_fixture() -> Series:
    """Série Breaking Bad."""
    return Series(
        tvdb_id=81189,
        title="Breaking Bad",
        year=2008,
        genres=("Drame", "Crime"),
    )


@pytest.fixture
def episode_fixture() -> Episode:
    """Premier épisode de Breaking Bad."""
    return Episode(
        season_number=1,
        episode_number=1,
        title="Pilot",
    )


@pytest.fixture
def episode_no_title() -> Episode:
    """Episode sans titre."""
    return Episode(
        season_number=2,
        episode_number=5,
        title="",
    )


@pytest.fixture
def media_info_complete() -> MediaInfo:
    """MediaInfo complet avec toutes les métadonnées."""
    return MediaInfo(
        resolution=Resolution(width=1920, height=1080),
        video_codec=VideoCodec(name="HEVC", profile="Main 10"),
        audio_codecs=(AudioCodec(name="DTS-HD", channels="5.1"),),
        audio_languages=(Language(code="fr", name="Français"),),
        duration_seconds=8160,
    )


@pytest.fixture
def media_info_multi_language() -> MediaInfo:
    """MediaInfo avec plusieurs langues."""
    return MediaInfo(
        resolution=Resolution(width=3840, height=2160),
        video_codec=VideoCodec(name="AV1"),
        audio_codecs=(
            AudioCodec(name="TrueHD", channels="7.1"),
            AudioCodec(name="AC3", channels="5.1"),
        ),
        audio_languages=(
            Language(code="fr", name="Français"),
            Language(code="en", name="English"),
        ),
        duration_seconds=7200,
    )


@pytest.fixture
def media_info_minimal() -> MediaInfo:
    """MediaInfo minimal sans certains champs."""
    return MediaInfo(
        resolution=Resolution(width=1280, height=720),
        video_codec=VideoCodec(name="H.264"),
        audio_codecs=(),
        audio_languages=(),
    )


# ====================
# Tests sanitize_for_filesystem
# ====================

class TestSanitizeForFilesystem:
    """Tests pour la fonction de nettoyage des noms de fichiers."""

    def test_sanitize_replaces_colon_with_dash(self) -> None:
        """Le deux-points est remplacé par un tiret."""
        assert sanitize_for_filesystem("Test: Subtitle") == "Test- Subtitle"

    def test_sanitize_replaces_quotes_with_dash(self) -> None:
        """Les guillemets sont remplacés par des tirets."""
        assert sanitize_for_filesystem('Film "Quoted"') == "Film -Quoted-"

    def test_sanitize_replaces_slashes_with_dash(self) -> None:
        """Les slashs sont remplacés par des tirets."""
        assert sanitize_for_filesystem("Path/To\\File") == "Path-To-File"

    def test_sanitize_replaces_star_and_angle_brackets(self) -> None:
        """Les étoiles et chevrons sont remplacés par des tirets."""
        assert sanitize_for_filesystem("File*<>Test") == "File---Test"

    def test_sanitize_replaces_pipe_with_dash(self) -> None:
        """Le pipe est remplacé par un tiret."""
        assert sanitize_for_filesystem("Left|Right") == "Left-Right"

    def test_sanitize_replaces_question_mark_with_ellipsis(self) -> None:
        """Le point d'interrogation est remplacé par des points de suspension."""
        assert sanitize_for_filesystem("What?") == "What..."

    def test_sanitize_replaces_multiple_question_marks(self) -> None:
        """Plusieurs points d'interrogation sont tous remplacés."""
        assert sanitize_for_filesystem("Who? Why?") == "Who... Why..."

    def test_sanitize_normalizes_french_ligature_oe(self) -> None:
        """La ligature oe (U+0153) est normalisée en 'oe'."""
        # \u0153 = œ (ligature oe)
        assert sanitize_for_filesystem("C\u0153ur") == "Coeur"
        assert sanitize_for_filesystem("S\u0153ur") == "Soeur"

    def test_sanitize_normalizes_uppercase_ligature_oe(self) -> None:
        """La ligature OE majuscule (U+0152) est normalisée en 'Oe'."""
        # \u0152 = Œ (ligature OE majuscule)
        assert sanitize_for_filesystem("\u0152uvre") == "Oeuvre"

    def test_sanitize_normalizes_french_ligature_ae(self) -> None:
        """La ligature ae (U+00E6) est normalisée en 'ae'."""
        # \u00e6 = æ (ligature ae)
        assert sanitize_for_filesystem("C\u00e6sar") == "Caesar"

    def test_sanitize_normalizes_uppercase_ligature_ae(self) -> None:
        """La ligature AE majuscule (U+00C6) est normalisée en 'Ae'."""
        # \u00c6 = Æ (ligature AE majuscule)
        assert sanitize_for_filesystem("\u00c6on") == "Aeon"

    def test_sanitize_truncates_long_names(self) -> None:
        """Les noms trop longs sont tronqués à 200 caractères."""
        long_name = "A" * 250
        result = sanitize_for_filesystem(long_name)
        assert len(result) <= 200

    def test_sanitize_preserves_dots(self) -> None:
        """Les points sont préservés (pour l'extension notamment)."""
        assert sanitize_for_filesystem("file.name.test") == "file.name.test"

    def test_sanitize_preserves_parentheses(self) -> None:
        """Les parenthèses sont préservées (pour l'année)."""
        assert sanitize_for_filesystem("Film (2024)") == "Film (2024)"

    def test_sanitize_empty_string(self) -> None:
        """Une chaîne vide retourne une chaîne vide."""
        assert sanitize_for_filesystem("") == ""

    def test_sanitize_combined_special_chars(self) -> None:
        """Combinaison de plusieurs caractères spéciaux."""
        result = sanitize_for_filesystem('Test: "What?" <film>')
        assert ":" not in result
        assert '"' not in result
        assert "?" not in result
        assert "<" not in result
        assert ">" not in result


# ====================
# Tests format_language_code
# ====================

class TestFormatLanguageCode:
    """Tests pour le formatage des codes de langue."""

    def test_format_language_single_french(self) -> None:
        """Une seule langue française retourne FR."""
        assert format_language_code(("fr",)) == "FR"

    def test_format_language_single_english(self) -> None:
        """Une seule langue anglaise retourne EN."""
        assert format_language_code(("en",)) == "EN"

    def test_format_language_single_german(self) -> None:
        """Une seule langue allemande retourne DE."""
        assert format_language_code(("de",)) == "DE"

    def test_format_language_two_codes(self) -> None:
        """Deux langues retournent MULTi."""
        assert format_language_code(("fr", "en")) == "MULTi"

    def test_format_language_three_codes(self) -> None:
        """Trois langues ou plus retournent MULTi."""
        assert format_language_code(("fr", "en", "de")) == "MULTi"

    def test_format_language_empty(self) -> None:
        """Une liste vide retourne une chaîne vide."""
        assert format_language_code(()) == ""

    def test_format_language_preserves_case_of_input(self) -> None:
        """Le code est toujours retourné en majuscules."""
        assert format_language_code(("FR",)) == "FR"
        assert format_language_code(("Fr",)) == "FR"


# ====================
# Tests generate_movie_filename
# ====================

class TestGenerateMovieFilename:
    """Tests pour la génération de noms de fichiers films."""

    def test_generate_movie_filename_complete(
        self,
        movie_fixture: Movie,
        media_info_complete: MediaInfo,
    ) -> None:
        """Nom complet avec tous les éléments."""
        result = generate_movie_filename(movie_fixture, media_info_complete, ".mkv")
        # Format: Titre (Année) Langue Codec Résolution.ext
        assert result == "Matrix (1999) FR HEVC 1080p.mkv"

    def test_generate_movie_filename_multi_language(
        self,
        movie_fixture: Movie,
        media_info_multi_language: MediaInfo,
    ) -> None:
        """Film avec plusieurs langues affiche MULTi."""
        result = generate_movie_filename(movie_fixture, media_info_multi_language, ".mkv")
        assert result == "Matrix (1999) MULTi AV1 4K.mkv"

    def test_generate_movie_filename_without_year(
        self,
        movie_without_year: Movie,
        media_info_complete: MediaInfo,
    ) -> None:
        """Film sans année omet la parenthèse."""
        result = generate_movie_filename(movie_without_year, media_info_complete, ".mkv")
        assert result == "Inception FR HEVC 1080p.mkv"

    def test_generate_movie_filename_no_media_info(
        self,
        movie_fixture: Movie,
    ) -> None:
        """Film sans MediaInfo n'a que le titre et l'année."""
        result = generate_movie_filename(movie_fixture, None, ".mp4")
        assert result == "Matrix (1999).mp4"

    def test_generate_movie_filename_minimal_media_info(
        self,
        movie_fixture: Movie,
        media_info_minimal: MediaInfo,
    ) -> None:
        """Film avec MediaInfo minimal (pas de langue)."""
        result = generate_movie_filename(movie_fixture, media_info_minimal, ".avi")
        assert result == "Matrix (1999) H.264 720p.avi"

    def test_generate_movie_filename_special_chars_in_title(self) -> None:
        """Les caractères spéciaux du titre sont nettoyés."""
        movie = Movie(title='Star Wars: Episode IV "A New Hope"', year=1977)
        result = generate_movie_filename(movie, None, ".mkv")
        # Les : et " sont remplacés par des tirets
        assert ":" not in result
        assert '"' not in result
        assert "(1977)" in result

    def test_generate_movie_filename_with_ligatures(self) -> None:
        """Les ligatures dans le titre sont normalisées."""
        movie = Movie(title="L'\u0152uvre au Noir", year=1988)  # œ
        result = generate_movie_filename(movie, None, ".mkv")
        assert "Oeuvre" in result


# ====================
# Tests generate_series_filename
# ====================

class TestGenerateSeriesFilename:
    """Tests pour la génération de noms de fichiers séries."""

    def test_generate_series_filename_complete(
        self,
        series_fixture: Series,
        episode_fixture: Episode,
        media_info_complete: MediaInfo,
    ) -> None:
        """Nom complet avec tous les éléments."""
        result = generate_series_filename(
            series_fixture, episode_fixture, media_info_complete, ".mkv"
        )
        # Format: Titre (Année) - SxxExx - TitreEpisode - Langue Codec Résolution.ext
        assert result == "Breaking Bad (2008) - S01E01 - Pilot - FR HEVC 1080p.mkv"

    def test_generate_series_filename_no_episode_title(
        self,
        series_fixture: Series,
        episode_no_title: Episode,
        media_info_complete: MediaInfo,
    ) -> None:
        """Episode sans titre omet le tiret et le titre."""
        result = generate_series_filename(
            series_fixture, episode_no_title, media_info_complete, ".mkv"
        )
        # Sans titre d'épisode
        assert result == "Breaking Bad (2008) - S02E05 - FR HEVC 1080p.mkv"

    def test_generate_series_filename_double_digit_season(
        self,
        series_fixture: Series,
        media_info_complete: MediaInfo,
    ) -> None:
        """Les numéros de saison à deux chiffres sont formatés correctement."""
        episode = Episode(season_number=12, episode_number=3, title="Test")
        result = generate_series_filename(
            series_fixture, episode, media_info_complete, ".mkv"
        )
        assert "S12E03" in result

    def test_generate_series_filename_double_digit_episode(
        self,
        series_fixture: Series,
        media_info_complete: MediaInfo,
    ) -> None:
        """Les numéros d'épisode à deux chiffres sont formatés correctement."""
        episode = Episode(season_number=1, episode_number=15, title="Test")
        result = generate_series_filename(
            series_fixture, episode, media_info_complete, ".mkv"
        )
        assert "S01E15" in result

    def test_generate_series_filename_no_media_info(
        self,
        series_fixture: Series,
        episode_fixture: Episode,
    ) -> None:
        """Série sans MediaInfo n'a que les informations de base."""
        result = generate_series_filename(
            series_fixture, episode_fixture, None, ".mp4"
        )
        assert result == "Breaking Bad (2008) - S01E01 - Pilot.mp4"

    def test_generate_series_filename_without_year(
        self,
        episode_fixture: Episode,
        media_info_complete: MediaInfo,
    ) -> None:
        """Série sans année omet la parenthèse."""
        series = Series(title="Friends", year=None)
        result = generate_series_filename(
            series, episode_fixture, media_info_complete, ".mkv"
        )
        assert result == "Friends - S01E01 - Pilot - FR HEVC 1080p.mkv"

    def test_generate_series_filename_special_chars_in_episode_title(
        self,
        series_fixture: Series,
        media_info_complete: MediaInfo,
    ) -> None:
        """Les caractères spéciaux du titre d'épisode sont nettoyés."""
        episode = Episode(season_number=1, episode_number=2, title='Who Is "Heisenberg"?')
        result = generate_series_filename(
            series_fixture, episode, media_info_complete, ".mkv"
        )
        assert '"' not in result
        assert "..." in result  # ? -> ...

    def test_generate_series_filename_multi_language(
        self,
        series_fixture: Series,
        episode_fixture: Episode,
        media_info_multi_language: MediaInfo,
    ) -> None:
        """Série avec plusieurs langues affiche MULTi."""
        result = generate_series_filename(
            series_fixture, episode_fixture, media_info_multi_language, ".mkv"
        )
        assert "MULTi" in result
        assert "AV1" in result
        assert "4K" in result


# ====================
# Tests fallback langue (guessit)
# ====================

class TestLanguageFallback:
    """Tests pour le fallback de langue depuis guessit quand mediainfo ne détecte pas."""

    def test_movie_fallback_language_when_mediainfo_empty(
        self,
        movie_fixture: Movie,
        media_info_minimal: MediaInfo,
    ) -> None:
        """Utilise fallback_language si mediainfo n'a pas de langue."""
        # media_info_minimal n'a pas de langue
        result = generate_movie_filename(
            movie_fixture, media_info_minimal, ".mkv", fallback_language="FR"
        )
        assert result == "Matrix (1999) FR H.264 720p.mkv"

    def test_movie_fallback_language_not_used_when_mediainfo_has_language(
        self,
        movie_fixture: Movie,
        media_info_complete: MediaInfo,
    ) -> None:
        """N'utilise pas fallback si mediainfo a déjà une langue."""
        # media_info_complete a FR
        result = generate_movie_filename(
            movie_fixture, media_info_complete, ".mkv", fallback_language="EN"
        )
        # Doit utiliser FR de mediainfo, pas EN du fallback
        assert result == "Matrix (1999) FR HEVC 1080p.mkv"

    def test_movie_no_language_without_fallback(
        self,
        movie_fixture: Movie,
        media_info_minimal: MediaInfo,
    ) -> None:
        """Sans fallback et sans langue mediainfo, pas de langue dans le nom."""
        result = generate_movie_filename(movie_fixture, media_info_minimal, ".mkv")
        assert result == "Matrix (1999) H.264 720p.mkv"

    def test_series_fallback_language_when_mediainfo_empty(
        self,
        series_fixture: Series,
        episode_fixture: Episode,
        media_info_minimal: MediaInfo,
    ) -> None:
        """Série utilise fallback_language si mediainfo n'a pas de langue."""
        result = generate_series_filename(
            series_fixture, episode_fixture, media_info_minimal, ".mkv",
            fallback_language="EN"
        )
        assert result == "Breaking Bad (2008) - S01E01 - Pilot - EN H.264 720p.mkv"

    def test_series_fallback_language_not_used_when_mediainfo_has_language(
        self,
        series_fixture: Series,
        episode_fixture: Episode,
        media_info_complete: MediaInfo,
    ) -> None:
        """Série n'utilise pas fallback si mediainfo a déjà une langue."""
        result = generate_series_filename(
            series_fixture, episode_fixture, media_info_complete, ".mkv",
            fallback_language="DE"
        )
        # Doit utiliser FR de mediainfo, pas DE du fallback
        assert result == "Breaking Bad (2008) - S01E01 - Pilot - FR HEVC 1080p.mkv"

    def test_movie_fallback_with_no_media_info(
        self,
        movie_fixture: Movie,
    ) -> None:
        """Fallback fonctionne même sans MediaInfo."""
        result = generate_movie_filename(
            movie_fixture, None, ".mkv", fallback_language="FR"
        )
        assert result == "Matrix (1999) FR.mkv"

    def test_series_fallback_with_no_media_info(
        self,
        series_fixture: Series,
        episode_fixture: Episode,
    ) -> None:
        """Série: fallback fonctionne même sans MediaInfo."""
        result = generate_series_filename(
            series_fixture, episode_fixture, None, ".mkv",
            fallback_language="EN"
        )
        assert result == "Breaking Bad (2008) - S01E01 - Pilot - EN.mkv"

    def test_fallback_language_case_normalization(
        self,
        movie_fixture: Movie,
    ) -> None:
        """Le fallback de langue est normalisé en majuscules."""
        result = generate_movie_filename(
            movie_fixture, None, ".mkv", fallback_language="fr"
        )
        assert "FR" in result
        assert "fr" not in result
