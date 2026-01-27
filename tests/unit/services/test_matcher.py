"""
Tests for MatcherService - scoring API results by relevance.

TDD tests covering:
- Title similarity (exact, case-insensitive, word order)
- Year matching with tolerance (+/-1 year)
- Duration matching with tolerance (+/-10%)
- Movie scoring formula (50% title + 25% year + 25% duration)
- Series scoring (100% title)
- Results sorting and determinism
"""

import pytest
from src.services.matcher import (
    MatcherService,
    calculate_movie_score,
    calculate_series_score,
)
from src.core.ports.api_clients import SearchResult


class TestTitleSimilarity:
    """Tests for title matching behavior."""

    def test_title_similarity_exact_match(self):
        """Exact same title should return 100% similarity."""
        score = calculate_movie_score(
            query_title="Avatar",
            query_year=2009,
            query_duration=9720,
            candidate_title="Avatar",
            candidate_year=2009,
            candidate_duration=9720,
        )
        assert score == 100.0

    def test_title_similarity_case_insensitive(self):
        """Title matching should be case insensitive."""
        score1 = calculate_movie_score(
            query_title="avatar",
            query_year=2009,
            query_duration=9720,
            candidate_title="Avatar",
            candidate_year=2009,
            candidate_duration=9720,
        )
        score2 = calculate_movie_score(
            query_title="AVATAR",
            query_year=2009,
            query_duration=9720,
            candidate_title="avatar",
            candidate_year=2009,
            candidate_duration=9720,
        )
        assert score1 == 100.0
        assert score2 == 100.0

    def test_title_similarity_word_order_independent(self):
        """Token sort ratio should handle word order differences."""
        score = calculate_movie_score(
            query_title="Bad Breaking",
            query_year=2008,
            query_duration=2700,
            candidate_title="Breaking Bad",
            candidate_year=2008,
            candidate_duration=2700,
        )
        # token_sort_ratio should handle word reordering
        assert score == 100.0


class TestYearScoring:
    """Tests for year matching with tolerance."""

    def test_year_exact_match(self):
        """Exact year match should contribute full 25%."""
        score = calculate_movie_score(
            query_title="Avatar",
            query_year=2009,
            query_duration=9720,
            candidate_title="Avatar",
            candidate_year=2009,
            candidate_duration=9720,
        )
        assert score == 100.0

    def test_year_tolerance_one_year(self):
        """Year within +/-1 should still be 100%."""
        score_plus = calculate_movie_score(
            query_title="Avatar",
            query_year=2009,
            query_duration=9720,
            candidate_title="Avatar",
            candidate_year=2010,
            candidate_duration=9720,
        )
        score_minus = calculate_movie_score(
            query_title="Avatar",
            query_year=2009,
            query_duration=9720,
            candidate_title="Avatar",
            candidate_year=2008,
            candidate_duration=9720,
        )
        assert score_plus == 100.0
        assert score_minus == 100.0

    def test_year_penalty_two_years(self):
        """2 years difference: 1 year outside tolerance = 75% year score.

        Year formula: exact or +/-1 = 100%, each additional year = -25%
        2 years diff = 1 year over tolerance = 75%
        Total score = 50% (title) + 25% * 0.75 (year) + 25% (duration)
        = 50 + 18.75 + 25 = 93.75
        """
        score = calculate_movie_score(
            query_title="Avatar",
            query_year=2009,
            query_duration=9720,
            candidate_title="Avatar",
            candidate_year=2011,
            candidate_duration=9720,
        )
        # Title: 100% * 0.5 = 50, Year: 75% * 0.25 = 18.75, Duration: 100% * 0.25 = 25
        assert score == 93.75

    def test_year_missing_is_zero(self):
        """Missing year (None) should contribute 0% to year component."""
        # Query has no year
        score_query_none = calculate_movie_score(
            query_title="Avatar",
            query_year=None,
            query_duration=9720,
            candidate_title="Avatar",
            candidate_year=2009,
            candidate_duration=9720,
        )
        # Candidate has no year
        score_candidate_none = calculate_movie_score(
            query_title="Avatar",
            query_year=2009,
            query_duration=9720,
            candidate_title="Avatar",
            candidate_year=None,
            candidate_duration=9720,
        )
        # Title: 50, Year: 0, Duration: 25 = 75
        assert score_query_none == 75.0
        assert score_candidate_none == 75.0


class TestDurationScoring:
    """Tests for duration matching with +/-10% tolerance."""

    def test_duration_within_10_percent(self):
        """Duration within +/-10% should be 100%."""
        base_duration = 9720
        # +10% = 10692, -10% = 8748
        score_high = calculate_movie_score(
            query_title="Avatar",
            query_year=2009,
            query_duration=base_duration,
            candidate_title="Avatar",
            candidate_year=2009,
            candidate_duration=10692,  # exactly +10%
        )
        score_low = calculate_movie_score(
            query_title="Avatar",
            query_year=2009,
            query_duration=base_duration,
            candidate_title="Avatar",
            candidate_year=2009,
            candidate_duration=8748,  # exactly -10%
        )
        assert score_high == 100.0
        assert score_low == 100.0

    def test_duration_outside_tolerance_penalty(self):
        """Duration outside 10% tolerance should be penalized.

        Each additional 10% deviation = -50% on duration score.
        20% difference = 10% over tolerance = 50% duration score
        Total = 50 (title) + 25 (year) + 25*0.5 = 50 + 25 + 12.5 = 87.5
        """
        base_duration = 10000
        # +20% = 12000
        score = calculate_movie_score(
            query_title="Avatar",
            query_year=2009,
            query_duration=base_duration,
            candidate_title="Avatar",
            candidate_year=2009,
            candidate_duration=12000,  # 20% higher
        )
        assert score == 87.5

    def test_duration_missing_is_zero(self):
        """Missing duration (None) should contribute 0% to duration component."""
        # Query has no duration
        score_query_none = calculate_movie_score(
            query_title="Avatar",
            query_year=2009,
            query_duration=None,
            candidate_title="Avatar",
            candidate_year=2009,
            candidate_duration=9720,
        )
        # Candidate has no duration
        score_candidate_none = calculate_movie_score(
            query_title="Avatar",
            query_year=2009,
            query_duration=9720,
            candidate_title="Avatar",
            candidate_year=None,
            candidate_duration=None,
        )
        # Query none: Title: 50, Year: 25, Duration: 0 = 75
        assert score_query_none == 75.0
        # Candidate none (year and duration): Title: 50, Year: 0, Duration: 0 = 50
        assert score_candidate_none == 50.0


class TestMovieScoreFormula:
    """Tests for the complete movie scoring formula."""

    def test_movie_score_formula_weights(self):
        """Verify 50% title + 25% year + 25% duration weights."""
        # Title only (year and duration missing)
        title_only = calculate_movie_score(
            query_title="Avatar",
            query_year=None,
            query_duration=None,
            candidate_title="Avatar",
            candidate_year=None,
            candidate_duration=None,
        )
        assert title_only == 50.0  # 100% title * 50% weight

        # Title + year (duration missing)
        title_year = calculate_movie_score(
            query_title="Avatar",
            query_year=2009,
            query_duration=None,
            candidate_title="Avatar",
            candidate_year=2009,
            candidate_duration=None,
        )
        assert title_year == 75.0  # 50 (title) + 25 (year)

        # Title + duration (year missing)
        title_duration = calculate_movie_score(
            query_title="Avatar",
            query_year=None,
            query_duration=9720,
            candidate_title="Avatar",
            candidate_year=None,
            candidate_duration=9720,
        )
        assert title_duration == 75.0  # 50 (title) + 25 (duration)


class TestSeriesScoring:
    """Tests for series-specific scoring (100% title)."""

    def test_series_score_title_only(self):
        """Series scoring should use 100% title similarity."""
        score = calculate_series_score(
            query_title="Breaking Bad",
            candidate_title="Breaking Bad",
        )
        assert score == 100.0

    def test_series_score_case_insensitive(self):
        """Series title matching should be case insensitive."""
        score = calculate_series_score(
            query_title="breaking bad",
            candidate_title="Breaking Bad",
        )
        assert score == 100.0

    def test_series_score_partial_match(self):
        """Series with episode info should still match well."""
        score = calculate_series_score(
            query_title="Breaking Bad S01E05",
            candidate_title="Breaking Bad",
        )
        # token_sort_ratio will give high score for subset
        assert score >= 70.0


class TestScoreResults:
    """Tests for score_results method."""

    def test_score_results_sorts_descending(self):
        """Results should be sorted by score descending."""
        matcher = MatcherService()
        results = [
            SearchResult(id="1", title="Avatar 2", year=2022, source="tmdb"),
            SearchResult(id="2", title="Avatar", year=2009, source="tmdb"),
            SearchResult(id="3", title="Avatars", year=2011, source="tmdb"),
        ]
        scored = matcher.score_results(
            results=results,
            query_title="Avatar",
            query_year=2009,
            query_duration=9720,
            is_series=False,
        )
        # Best match should be first
        assert scored[0].title == "Avatar"
        assert scored[0].year == 2009
        # Scores should be in descending order
        for i in range(len(scored) - 1):
            assert scored[i].score >= scored[i + 1].score

    def test_score_results_modifies_score_field(self):
        """score_results should populate the score field.

        Note: SearchResult from API does not have duration, so duration
        component is always 0% in score_results. Max movie score = 75%
        (50% title + 25% year + 0% duration).
        """
        matcher = MatcherService()
        results = [
            SearchResult(id="1", title="Avatar", year=2009, source="tmdb"),
        ]
        scored = matcher.score_results(
            results=results,
            query_title="Avatar",
            query_year=2009,
            query_duration=9720,  # Ignored - API results don't have duration
            is_series=False,
        )
        assert scored[0].score > 0
        # Title: 50%, Year: 25%, Duration: 0% (no candidate duration) = 75%
        assert scored[0].score == 75.0

    def test_score_results_series_mode(self):
        """is_series=True should use series scoring (title only)."""
        matcher = MatcherService()
        results = [
            SearchResult(id="1", title="Breaking Bad", year=2008, source="tvdb"),
        ]
        scored = matcher.score_results(
            results=results,
            query_title="Breaking Bad",
            query_year=2020,  # Different year should not affect series score
            query_duration=None,
            is_series=True,
        )
        # Series uses 100% title, so year mismatch should not matter
        assert scored[0].score == 100.0


class TestDeterminism:
    """Tests for scoring determinism."""

    def test_scoring_is_deterministic(self):
        """Same input should always produce same output."""
        matcher = MatcherService()
        results = [
            SearchResult(id="1", title="Avatar", year=2009, source="tmdb"),
            SearchResult(id="2", title="Avatar 2", year=2022, source="tmdb"),
        ]

        # Run 10 times and verify consistent results
        scores = []
        for _ in range(10):
            scored = matcher.score_results(
                results=results.copy(),
                query_title="Avatar",
                query_year=2009,
                query_duration=9720,
                is_series=False,
            )
            scores.append((scored[0].score, scored[1].score))

        # All iterations should produce identical scores
        first_run = scores[0]
        for run in scores[1:]:
            assert run == first_run


class TestMatchThreshold:
    """Tests for MATCH_THRESHOLD constant."""

    def test_match_threshold_value(self):
        """MATCH_THRESHOLD should be 85."""
        matcher = MatcherService()
        assert matcher.MATCH_THRESHOLD == 85

    def test_match_threshold_auto_validation(self):
        """Results >= 85% should be candidates for auto-validation.

        For series, 100% title match exceeds threshold.
        For movies via score_results, max is 75% without duration from API.
        Direct calculate_movie_score with duration can reach 100%.
        """
        matcher = MatcherService()
        # Use series mode to get 100% (title only)
        results = [
            SearchResult(id="1", title="Breaking Bad", year=2008, source="tvdb"),
        ]
        scored = matcher.score_results(
            results=results,
            query_title="Breaking Bad",
            query_year=2008,
            query_duration=None,
            is_series=True,
        )
        # Perfect series match should exceed threshold
        assert scored[0].score >= matcher.MATCH_THRESHOLD

        # Also test direct movie score with duration
        movie_score = calculate_movie_score(
            query_title="Avatar",
            query_year=2009,
            query_duration=9720,
            candidate_title="Avatar",
            candidate_year=2009,
            candidate_duration=9720,
        )
        assert movie_score >= matcher.MATCH_THRESHOLD


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_results_list(self):
        """Empty results list should return empty list."""
        matcher = MatcherService()
        scored = matcher.score_results(
            results=[],
            query_title="Avatar",
            query_year=2009,
            query_duration=9720,
            is_series=False,
        )
        assert scored == []

    def test_score_rounded_to_two_decimals(self):
        """Scores should be rounded to 2 decimal places."""
        # Use values that would produce floating point imprecision
        score = calculate_movie_score(
            query_title="Test Movie",
            query_year=2020,
            query_duration=7200,
            candidate_title="Test Movie",
            candidate_year=2018,  # 2 years diff = 75% year score
            candidate_duration=7200,
        )
        # Should be clean decimal, not something like 93.75000000001
        assert score == round(score, 2)
        assert str(score).count('.') <= 1  # No scientific notation

    def test_year_large_difference(self):
        """Very large year difference should bottom out at 0%."""
        score = calculate_movie_score(
            query_title="Avatar",
            query_year=2009,
            query_duration=9720,
            candidate_title="Avatar",
            candidate_year=2000,  # 9 years diff
            candidate_duration=9720,
        )
        # Title: 50, Year: max(0, 100 - 8*25) = 0, Duration: 25 = 75
        # 9 years diff = 8 years over tolerance
        assert score == 75.0

    def test_duration_very_different(self):
        """Very different duration should bottom out at 0%."""
        score = calculate_movie_score(
            query_title="Avatar",
            query_year=2009,
            query_duration=9720,
            candidate_title="Avatar",
            candidate_year=2009,
            candidate_duration=20000,  # ~106% different
        )
        # Duration should be 0%
        # Title: 50, Year: 25, Duration: 0 = 75
        assert score == 75.0
