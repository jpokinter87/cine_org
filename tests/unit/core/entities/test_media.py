"""
Tests pour les entites media (Movie, Series, Episode).

Verifie les nouveaux champs de notes (vote_average, vote_count).
"""

import pytest

from src.core.entities.media import Episode, Movie, Series


class TestMovieEntity:
    """Tests pour l'entite Movie."""

    def test_movie_with_vote_fields(self):
        """Movie doit supporter les champs vote_average et vote_count."""
        movie = Movie(
            title="Avatar",
            year=2009,
            vote_average=7.6,
            vote_count=27000,
        )
        assert movie.vote_average == 7.6
        assert movie.vote_count == 27000

    def test_movie_vote_fields_default_none(self):
        """Les champs de vote doivent etre None par defaut."""
        movie = Movie(title="Test Movie")
        assert movie.vote_average is None
        assert movie.vote_count is None

    def test_movie_with_all_fields(self):
        """Movie doit supporter tous les champs incluant les votes."""
        movie = Movie(
            id="1",
            tmdb_id=19995,
            title="Avatar",
            original_title="Avatar",
            year=2009,
            genres=("Action", "Science-Fiction"),
            duration_seconds=9720,
            overview="Un marine paralyse...",
            poster_path="/path/to/poster.jpg",
            vote_average=7.6,
            vote_count=27000,
        )
        assert movie.id == "1"
        assert movie.tmdb_id == 19995
        assert movie.title == "Avatar"
        assert movie.vote_average == 7.6
        assert movie.vote_count == 27000


class TestSeriesEntity:
    """Tests pour l'entite Series."""

    def test_series_with_vote_fields(self):
        """Series doit supporter les champs vote_average et vote_count."""
        series = Series(
            title="Breaking Bad",
            year=2008,
            vote_average=9.5,
            vote_count=15000,
        )
        assert series.vote_average == 9.5
        assert series.vote_count == 15000

    def test_series_vote_fields_default_none(self):
        """Les champs de vote doivent etre None par defaut."""
        series = Series(title="Test Series")
        assert series.vote_average is None
        assert series.vote_count is None

    def test_series_with_all_fields(self):
        """Series doit supporter tous les champs incluant les votes."""
        series = Series(
            id="1",
            tvdb_id=81189,
            title="Breaking Bad",
            original_title="Breaking Bad",
            year=2008,
            genres=("Drame", "Crime"),
            overview="Un professeur de chimie...",
            poster_path="/path/to/poster.jpg",
            vote_average=9.5,
            vote_count=15000,
        )
        assert series.id == "1"
        assert series.tvdb_id == 81189
        assert series.title == "Breaking Bad"
        assert series.vote_average == 9.5
        assert series.vote_count == 15000


class TestMovieIMDbFields:
    """Tests pour les champs IMDb dans Movie."""

    def test_movie_with_imdb_fields(self):
        """Movie doit supporter les champs IMDb."""
        movie = Movie(
            title="Avatar",
            year=2009,
            imdb_id="tt0499549",
            imdb_rating=7.9,
            imdb_votes=1500000,
        )
        assert movie.imdb_id == "tt0499549"
        assert movie.imdb_rating == 7.9
        assert movie.imdb_votes == 1500000

    def test_movie_imdb_fields_default_none(self):
        """Les champs IMDb doivent etre None par defaut."""
        movie = Movie(title="Test Movie")
        assert movie.imdb_id is None
        assert movie.imdb_rating is None
        assert movie.imdb_votes is None


class TestSeriesIMDbFields:
    """Tests pour les champs IMDb dans Series."""

    def test_series_with_imdb_fields(self):
        """Series doit supporter les champs IMDb."""
        series = Series(
            title="Breaking Bad",
            year=2008,
            imdb_id="tt0903747",
            imdb_rating=9.5,
            imdb_votes=2000000,
        )
        assert series.imdb_id == "tt0903747"
        assert series.imdb_rating == 9.5
        assert series.imdb_votes == 2000000

    def test_series_imdb_fields_default_none(self):
        """Les champs IMDb doivent etre None par defaut."""
        series = Series(title="Test Series")
        assert series.imdb_id is None
        assert series.imdb_rating is None
        assert series.imdb_votes is None


class TestEpisodeEntity:
    """Tests pour l'entite Episode (verification qu'elle n'est pas affectee)."""

    def test_episode_fields_unchanged(self):
        """Episode ne doit pas avoir de champs de vote."""
        episode = Episode(
            series_id="1",
            season_number=1,
            episode_number=1,
            title="Pilot",
        )
        # Les episodes n'ont pas de champs vote
        assert not hasattr(episode, "vote_average") or episode.__dict__.get("vote_average") is None
