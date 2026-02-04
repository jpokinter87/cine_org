"""
Tests pour les dataclasses ports API (SearchResult, MediaDetails, EpisodeDetails).

Verifie les nouveaux champs de notes (vote_average, vote_count) dans MediaDetails.
"""

import pytest

from src.core.ports.api_clients import EpisodeDetails, MediaDetails, SearchResult


class TestSearchResult:
    """Tests pour SearchResult (verification qu'il n'est pas affecte)."""

    def test_search_result_unchanged(self):
        """SearchResult ne doit pas avoir de champs de vote."""
        result = SearchResult(
            id="19995",
            title="Avatar",
            year=2009,
            source="tmdb",
        )
        assert result.id == "19995"
        assert result.title == "Avatar"
        assert not hasattr(result, "vote_average")


class TestMediaDetails:
    """Tests pour MediaDetails avec champs de vote."""

    def test_media_details_with_vote_fields(self):
        """MediaDetails doit supporter vote_average et vote_count."""
        details = MediaDetails(
            id="19995",
            title="Avatar",
            year=2009,
            genres=("Action", "Science-Fiction"),
            duration_seconds=9720,
            vote_average=7.6,
            vote_count=27000,
        )
        assert details.vote_average == 7.6
        assert details.vote_count == 27000

    def test_media_details_vote_fields_default_none(self):
        """Les champs de vote doivent etre None par defaut."""
        details = MediaDetails(id="1", title="Test")
        assert details.vote_average is None
        assert details.vote_count is None

    def test_media_details_all_fields(self):
        """MediaDetails doit supporter tous les champs existants + votes."""
        details = MediaDetails(
            id="19995",
            title="Avatar",
            original_title="Avatar",
            year=2009,
            genres=("Action", "Aventure", "Science-Fiction"),
            duration_seconds=9720,
            overview="Un marine paralyse...",
            poster_url="https://image.tmdb.org/t/p/w500/path.jpg",
            director="James Cameron",
            cast=("Sam Worthington", "Zoe Saldana"),
            vote_average=7.6,
            vote_count=27000,
        )
        assert details.id == "19995"
        assert details.title == "Avatar"
        assert details.director == "James Cameron"
        assert details.vote_average == 7.6
        assert details.vote_count == 27000


class TestEpisodeDetails:
    """Tests pour EpisodeDetails (verification qu'il n'est pas affecte)."""

    def test_episode_details_unchanged(self):
        """EpisodeDetails ne doit pas avoir de champs de vote."""
        details = EpisodeDetails(
            id="1",
            title="Pilot",
            season_number=1,
            episode_number=1,
        )
        assert details.id == "1"
        assert details.title == "Pilot"
        assert not hasattr(details, "vote_average")
