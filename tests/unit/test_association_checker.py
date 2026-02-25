"""Tests unitaires pour le service AssociationChecker."""

from unittest.mock import MagicMock, patch

import pytest

from src.services.association_checker import AssociationChecker, SuspiciousAssociation


@pytest.fixture
def checker():
    """Crée un AssociationChecker avec session mockée."""
    session = MagicMock()
    return AssociationChecker(session)


class TestSuspiciousAssociation:
    """Tests du dataclass SuspiciousAssociation."""

    def test_creation(self):
        sa = SuspiciousAssociation(
            entity_type="movie",
            entity_id=1,
            title_tmdb="Inception",
            title_parsed="Inception",
            year_tmdb=2010,
            year_parsed=2010,
            confidence_score=100,
            reasons=[],
            poster_path="/poster.jpg",
        )
        assert sa.entity_type == "movie"
        assert sa.confidence_score == 100


class TestMovieHeuristics:
    """Tests des heuristiques de détection pour les films."""

    def test_film_titre_tres_different_est_suspect(self, checker):
        """Un film dont le titre parsé est très différent du titre TMDB est suspect."""
        movie = MagicMock()
        movie.id = 1
        movie.title = "Inception"
        movie.original_title = None
        movie.year = 2010
        movie.duration_seconds = 8880
        movie.file_path = "/storage/Films/Action/I/Inception (2010)/Totally Different Movie (2015) FR AAC x264 1080p.mkv"
        movie.poster_path = "/poster.jpg"
        movie.tmdb_id = 27205

        with patch.object(checker, "_parse_filename") as mock_parse:
            mock_parse.return_value = ("Totally Different Movie", 2015)
            with patch.object(checker, "_get_file_duration") as mock_dur:
                mock_dur.return_value = None
                result = checker._check_movie(movie)

        assert result is not None
        assert result.confidence_score < 60
        assert any("titre" in r.lower() for r in result.reasons)

    def test_film_annee_ecart_grand_est_suspect(self, checker):
        """Un film avec un écart d'année >= 3 est suspect."""
        movie = MagicMock()
        movie.id = 2
        movie.title = "Matrix"
        movie.original_title = None
        movie.year = 1999
        movie.duration_seconds = 8160
        movie.file_path = "/storage/Films/Action/M/Matrix (1999)/Matrix (2005) FR DTS x264 1080p.mkv"
        movie.poster_path = None
        movie.tmdb_id = 603

        with patch.object(checker, "_parse_filename") as mock_parse:
            mock_parse.return_value = ("Matrix", 2005)
            with patch.object(checker, "_get_file_duration") as mock_dur:
                mock_dur.return_value = None
                result = checker._check_movie(movie)

        assert result is not None
        assert result.confidence_score < 100
        assert any("année" in r.lower() for r in result.reasons)

    def test_film_duree_ecart_grand_est_suspect(self, checker):
        """Un film avec un écart de durée >= 30% est suspect."""
        movie = MagicMock()
        movie.id = 3
        movie.title = "Amélie"
        movie.original_title = None
        movie.year = 2001
        movie.duration_seconds = 7200  # 2h TMDB
        movie.file_path = "/storage/Films/Comédie/A/Amelie (2001)/Amelie (2001) FR AAC x264 1080p.mkv"
        movie.poster_path = None
        movie.tmdb_id = 194

        with patch.object(checker, "_parse_filename") as mock_parse:
            mock_parse.return_value = ("Amelie", 2001)
            with patch.object(checker, "_get_file_duration") as mock_dur:
                mock_dur.return_value = 3600  # 1h fichier — écart 60min
                result = checker._check_movie(movie)

        assert result is not None
        assert result.confidence_score < 60
        assert any("durée" in r.lower() for r in result.reasons)

    def test_film_duree_ecart_moyen_penalite_legere(self, checker):
        """Un film avec un écart de durée 15-30% reçoit une pénalité légère."""
        movie = MagicMock()
        movie.id = 4
        movie.title = "Amélie"
        movie.original_title = None
        movie.year = 2001
        movie.duration_seconds = 7200  # 120min TMDB
        movie.file_path = "/storage/Films/Comédie/A/Amelie (2001)/Amelie (2001) FR AAC x264 1080p.mkv"
        movie.poster_path = None
        movie.tmdb_id = 194

        with patch.object(checker, "_parse_filename") as mock_parse:
            mock_parse.return_value = ("Amelie", 2001)
            with patch.object(checker, "_get_file_duration") as mock_dur:
                mock_dur.return_value = 5760  # 96min — écart ~20% de 120min
                result = checker._check_movie(movie)

        # Pénalité légère mais pas suspect (score >= 60)
        if result is not None:
            assert result.confidence_score >= 60

    def test_film_correct_non_suspect(self, checker):
        """Un film avec bon titre et bonne année n'est pas suspect."""
        movie = MagicMock()
        movie.id = 5
        movie.title = "Inception"
        movie.original_title = None
        movie.year = 2010
        movie.duration_seconds = 8880
        movie.file_path = "/storage/Films/Action/I/Inception (2010)/Inception (2010) FR DTS x265 1080p.mkv"
        movie.poster_path = "/poster.jpg"
        movie.tmdb_id = 27205

        with patch.object(checker, "_parse_filename") as mock_parse:
            mock_parse.return_value = ("Inception", 2010)
            with patch.object(checker, "_get_file_duration") as mock_dur:
                mock_dur.return_value = None
                result = checker._check_movie(movie)

        # Pas suspect (None ou score >= 60)
        assert result is None or result.confidence_score >= 60

    def test_film_sans_file_path_ignore(self, checker):
        """Un film sans file_path est ignoré."""
        movie = MagicMock()
        movie.id = 6
        movie.title = "Test"
        movie.original_title = None
        movie.file_path = None
        movie.tmdb_id = 999

        result = checker._check_movie(movie)
        assert result is None


class TestSeriesHeuristics:
    """Tests des heuristiques de détection pour les séries."""

    def test_serie_titre_tres_different_est_suspect(self, checker):
        """Une série dont le titre parsé est très différent est suspecte."""
        series = MagicMock()
        series.id = 1
        series.title = "Breaking Bad"
        series.original_title = None
        series.year = 2008
        series.poster_path = None
        series.tmdb_id = 1396

        episode = MagicMock()
        episode.file_path = "/storage/Séries/B/Wrong Show/Saison 1/Something Completely Different S01E01.mkv"

        with patch.object(checker, "_get_first_episode") as mock_ep:
            mock_ep.return_value = episode
            with patch.object(checker, "_parse_filename") as mock_parse:
                mock_parse.return_value = ("Something Completely Different", None)
                result = checker._check_series(series)

        assert result is not None
        assert result.confidence_score < 60
        assert any("titre" in r.lower() for r in result.reasons)

    def test_serie_correcte_non_suspecte(self, checker):
        """Une série avec un bon titre n'est pas suspecte."""
        series = MagicMock()
        series.id = 2
        series.title = "Breaking Bad"
        series.original_title = None
        series.year = 2008
        series.poster_path = None
        series.tmdb_id = 1396

        episode = MagicMock()
        episode.file_path = "/storage/Séries/B/Breaking Bad/Breaking Bad (2008) - S01E01 - Pilot - EN AAC x264 720p.mkv"

        with patch.object(checker, "_get_first_episode") as mock_ep:
            mock_ep.return_value = episode
            with patch.object(checker, "_parse_filename") as mock_parse:
                mock_parse.return_value = ("Breaking Bad", 2008)
                result = checker._check_series(series)

        assert result is None or result.confidence_score >= 60
