"""
Tests pour les modeles SQLModel de persistance.

Verifie les nouveaux champs de notes (vote_average, vote_count) dans MovieModel et SeriesModel.
"""

import pytest

from src.infrastructure.persistence.models import MovieModel, SeriesModel


class TestMovieModel:
    """Tests pour MovieModel avec champs de vote."""

    def test_movie_model_with_vote_fields(self):
        """MovieModel doit supporter vote_average et vote_count."""
        model = MovieModel(
            title="Avatar",
            year=2009,
            tmdb_id=19995,
            vote_average=7.6,
            vote_count=27000,
        )
        assert model.vote_average == 7.6
        assert model.vote_count == 27000

    def test_movie_model_vote_fields_nullable(self):
        """Les champs de vote doivent etre nullable."""
        model = MovieModel(title="Test Movie")
        assert model.vote_average is None
        assert model.vote_count is None

    def test_movie_model_all_fields(self):
        """MovieModel doit supporter tous les champs existants + votes."""
        model = MovieModel(
            tmdb_id=19995,
            imdb_id="tt0499549",
            title="Avatar",
            original_title="Avatar",
            year=2009,
            genres_json='["Action", "Science-Fiction"]',
            duration_seconds=9720,
            overview="Un marine...",
            poster_path="/path/to/poster.jpg",
            vote_average=7.6,
            vote_count=27000,
        )
        assert model.tmdb_id == 19995
        assert model.vote_average == 7.6
        assert model.vote_count == 27000


class TestSeriesModel:
    """Tests pour SeriesModel avec champs de vote."""

    def test_series_model_with_vote_fields(self):
        """SeriesModel doit supporter vote_average et vote_count."""
        model = SeriesModel(
            title="Breaking Bad",
            year=2008,
            tvdb_id=81189,
            vote_average=9.5,
            vote_count=15000,
        )
        assert model.vote_average == 9.5
        assert model.vote_count == 15000

    def test_series_model_vote_fields_nullable(self):
        """Les champs de vote doivent etre nullable."""
        model = SeriesModel(title="Test Series")
        assert model.vote_average is None
        assert model.vote_count is None

    def test_series_model_all_fields(self):
        """SeriesModel doit supporter tous les champs existants + votes."""
        model = SeriesModel(
            tvdb_id=81189,
            imdb_id="tt0903747",
            title="Breaking Bad",
            original_title="Breaking Bad",
            year=2008,
            genres_json='["Drame", "Crime"]',
            overview="Un professeur...",
            poster_path="/path/to/poster.jpg",
            vote_average=9.5,
            vote_count=15000,
        )
        assert model.tvdb_id == 81189
        assert model.vote_average == 9.5
        assert model.vote_count == 15000
