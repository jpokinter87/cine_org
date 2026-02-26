"""
Tests for ValidationService - validation workflow orchestration.

TDD tests covering:
- Auto-validation logic (single candidate with score >= 85%)
- Manual candidate selection and validation
- Search manual by title (TMDB/TVDB)
- Search by external ID (TMDB, TVDB, IMDB)
- Rejection flow
- List pending and validated items
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.entities.video import (
    PendingValidation,
    ValidationStatus,
    VideoFile,
)
from src.core.ports.api_clients import MediaDetails, SearchResult
from src.services.validation import THRESHOLD, ValidationService


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_pending_repo():
    """Create a mock PendingValidationRepository."""
    repo = MagicMock()
    repo.save = MagicMock(side_effect=lambda x: x)  # Return the entity as-is
    repo.list_pending = MagicMock(return_value=[])
    return repo


@pytest.fixture
def mock_matcher():
    """Create a mock MatcherService."""
    return MagicMock()


@pytest.fixture
def mock_tmdb_client():
    """Create a mock TMDBClient with valid api_key."""
    client = MagicMock()
    client._api_key = "test_tmdb_key"
    client.search = AsyncMock(return_value=[])
    client.get_details = AsyncMock(return_value=None)
    return client


@pytest.fixture
def mock_tvdb_client():
    """Create a mock TVDBClient with valid api_key."""
    client = MagicMock()
    client._api_key = "test_tvdb_key"
    client.search = AsyncMock(return_value=[])
    client.get_details = AsyncMock(return_value=None)
    return client


@pytest.fixture
def validation_service(mock_pending_repo, mock_matcher, mock_tmdb_client, mock_tvdb_client):
    """Create a ValidationService with all mocks."""
    return ValidationService(
        pending_repo=mock_pending_repo,
        matcher=mock_matcher,
        tmdb_client=mock_tmdb_client,
        tvdb_client=mock_tvdb_client,
    )


@pytest.fixture
def sample_video_file():
    """Create a sample VideoFile entity."""
    return VideoFile(
        id="1",
        path=Path("/downloads/Avatar.2009.mkv"),
        filename="Avatar.2009.mkv",
        size_bytes=4_500_000_000,
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_search_result():
    """Create a sample SearchResult."""
    return SearchResult(
        id="19995",
        title="Avatar",
        year=2009,
        score=90.0,
        source="tmdb",
    )


@pytest.fixture
def sample_media_details():
    """Create sample MediaDetails."""
    return MediaDetails(
        id="19995",
        title="Avatar",
        original_title="Avatar",
        year=2009,
        genres=("Science-Fiction", "Action", "Aventure"),
        duration_seconds=9720,
        overview="Un marine paralyse...",
        poster_url="https://image.tmdb.org/t/p/w500/avatar.jpg",
    )


# ============================================================================
# Tests: should_auto_validate
# ============================================================================


class TestShouldAutoValidate:
    """Tests for should_auto_validate method."""

    def test_should_auto_validate_single_high_score(self, validation_service):
        """Single candidate with score >= 85% should auto-validate."""
        candidates = [
            SearchResult(id="1", title="Avatar", year=2009, score=90.0, source="tmdb")
        ]
        assert validation_service.should_auto_validate(candidates) is True

    def test_should_auto_validate_single_at_threshold(self, validation_service):
        """Single candidate with score exactly at 85% should auto-validate."""
        candidates = [
            SearchResult(id="1", title="Avatar", year=2009, score=85.0, source="tmdb")
        ]
        assert validation_service.should_auto_validate(candidates) is True

    def test_should_auto_validate_single_below_threshold(self, validation_service):
        """Single candidate with score < 85% should NOT auto-validate."""
        candidates = [
            SearchResult(id="1", title="Avatar", year=2009, score=84.0, source="tmdb")
        ]
        assert validation_service.should_auto_validate(candidates) is False

    def test_should_auto_validate_multiple_high_confidence(self, validation_service):
        """Multiple candidates with best score >= 95% SHOULD auto-validate (high confidence)."""
        candidates = [
            SearchResult(id="1", title="Avatar", year=2009, score=95.0, source="tmdb"),
            SearchResult(id="2", title="Avatar 2", year=2022, score=90.0, source="tmdb"),
        ]
        # HIGH_CONFIDENCE_THRESHOLD (95%) allows auto-validation even with multiple candidates
        assert validation_service.should_auto_validate(candidates) is True

    def test_should_auto_validate_multiple_below_high_confidence(self, validation_service):
        """Multiple candidates with best score < 95% should NOT auto-validate."""
        candidates = [
            SearchResult(id="1", title="Avatar", year=2009, score=90.0, source="tmdb"),
            SearchResult(id="2", title="Avatar 2", year=2022, score=85.0, source="tmdb"),
        ]
        assert validation_service.should_auto_validate(candidates) is False

    def test_should_auto_validate_empty_candidates(self, validation_service):
        """Empty candidates list should NOT auto-validate."""
        assert validation_service.should_auto_validate([]) is False


# ============================================================================
# Tests: process_auto_validation
# ============================================================================


class TestProcessAutoValidation:
    """Tests for process_auto_validation method."""

    @pytest.mark.asyncio
    async def test_process_auto_validation_success(
        self, validation_service, mock_pending_repo, sample_video_file
    ):
        """Candidat unique 90% -> auto_validated=True, status=VALIDATED."""
        pending = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=[
                {"id": "19995", "title": "Avatar", "year": 2009, "score": 90.0, "source": "tmdb"}
            ],
            auto_validated=False,
            validation_status=ValidationStatus.PENDING,
        )

        result = await validation_service.process_auto_validation(pending)

        assert result.auto_validated is True
        assert result.validation_status == ValidationStatus.VALIDATED
        assert result.selected_candidate_id == "19995"
        mock_pending_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_auto_validation_below_threshold(
        self, validation_service, mock_pending_repo, sample_video_file
    ):
        """Candidat unique 70% -> entite inchangee."""
        pending = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=[
                {"id": "19995", "title": "Avatar", "year": 2009, "score": 70.0, "source": "tmdb"}
            ],
            auto_validated=False,
            validation_status=ValidationStatus.PENDING,
        )

        result = await validation_service.process_auto_validation(pending)

        assert result.auto_validated is False
        assert result.validation_status == ValidationStatus.PENDING
        assert result.selected_candidate_id is None
        mock_pending_repo.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_auto_validation_multiple_candidates_high_confidence(
        self, validation_service, mock_pending_repo, sample_video_file
    ):
        """2 candidats avec best >= 95% -> auto-validation (haute confiance)."""
        pending = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=[
                {"id": "19995", "title": "Avatar", "year": 2009, "score": 95.0, "source": "tmdb"},
                {"id": "76600", "title": "Avatar 2", "year": 2022, "score": 90.0, "source": "tmdb"},
            ],
            auto_validated=False,
            validation_status=ValidationStatus.PENDING,
        )

        result = await validation_service.process_auto_validation(pending)

        # HIGH_CONFIDENCE_THRESHOLD (95%) permet l'auto-validation
        assert result.auto_validated is True
        assert result.validation_status == ValidationStatus.VALIDATED
        assert result.selected_candidate_id == "19995"
        mock_pending_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_auto_validation_multiple_candidates_low_confidence(
        self, validation_service, mock_pending_repo, sample_video_file
    ):
        """2 candidats avec best < 95% -> entite inchangee."""
        pending = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=[
                {"id": "19995", "title": "Avatar", "year": 2009, "score": 90.0, "source": "tmdb"},
                {"id": "76600", "title": "Avatar 2", "year": 2022, "score": 85.0, "source": "tmdb"},
            ],
            auto_validated=False,
            validation_status=ValidationStatus.PENDING,
        )

        result = await validation_service.process_auto_validation(pending)

        assert result.auto_validated is False
        assert result.validation_status == ValidationStatus.PENDING
        mock_pending_repo.save.assert_not_called()


# ============================================================================
# Tests: validate_candidate
# ============================================================================


class TestValidateCandidate:
    """Tests for validate_candidate method."""

    @pytest.mark.asyncio
    async def test_validate_candidate_tmdb(
        self, validation_service, mock_pending_repo, mock_tmdb_client,
        sample_video_file, sample_search_result, sample_media_details
    ):
        """Source=tmdb -> appelle tmdb_client.get_details."""
        mock_tmdb_client.get_details = AsyncMock(return_value=sample_media_details)

        pending = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=[],
            validation_status=ValidationStatus.PENDING,
        )

        result = await validation_service.validate_candidate(pending, sample_search_result)

        mock_tmdb_client.get_details.assert_called_once_with("19995")
        assert result == sample_media_details

    @pytest.mark.asyncio
    async def test_validate_candidate_tvdb(
        self, validation_service, mock_pending_repo, mock_tvdb_client,
        sample_video_file, sample_media_details
    ):
        """Source=tvdb -> appelle tvdb_client.get_details."""
        mock_tvdb_client.get_details = AsyncMock(return_value=sample_media_details)

        candidate = SearchResult(
            id="81189",
            title="Breaking Bad",
            year=2008,
            score=100.0,
            source="tvdb",
        )
        pending = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=[],
            validation_status=ValidationStatus.PENDING,
        )

        result = await validation_service.validate_candidate(pending, candidate)

        mock_tvdb_client.get_details.assert_called_once_with("81189")
        assert result == sample_media_details

    @pytest.mark.asyncio
    async def test_validate_candidate_updates_status(
        self, validation_service, mock_pending_repo, mock_tmdb_client,
        sample_video_file, sample_search_result, sample_media_details
    ):
        """Verifie status=VALIDATED et selected_candidate_id mis a jour."""
        mock_tmdb_client.get_details = AsyncMock(return_value=sample_media_details)

        pending = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=[],
            validation_status=ValidationStatus.PENDING,
        )

        await validation_service.validate_candidate(pending, sample_search_result)

        assert pending.validation_status == ValidationStatus.VALIDATED
        assert pending.selected_candidate_id == "19995"
        mock_pending_repo.save.assert_called_once_with(pending)


# ============================================================================
# Tests: reject_pending
# ============================================================================


class TestRejectPending:
    """Tests for reject_pending method."""

    def test_reject_pending_updates_status(
        self, validation_service, mock_pending_repo, sample_video_file
    ):
        """Verifie status=REJECTED apres rejet."""
        pending = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=[],
            validation_status=ValidationStatus.PENDING,
        )

        result = validation_service.reject_pending(pending)

        assert result.validation_status == ValidationStatus.REJECTED
        mock_pending_repo.save.assert_called_once_with(pending)


# ============================================================================
# Tests: reset_to_pending
# ============================================================================


class TestResetToPending:
    """Tests for reset_to_pending method."""

    def test_reset_validated_to_pending(
        self, validation_service, mock_pending_repo, sample_video_file
    ):
        """Remet un fichier auto-validé en statut pending."""
        pending = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=[],
            validation_status=ValidationStatus.VALIDATED,
            selected_candidate_id="tmdb:12345",
            auto_validated=True,
        )

        result = validation_service.reset_to_pending(pending)

        assert result.validation_status == ValidationStatus.PENDING
        assert result.selected_candidate_id is None
        assert result.auto_validated is False
        mock_pending_repo.save.assert_called_once_with(pending)

    def test_reset_manually_validated_to_pending(
        self, validation_service, mock_pending_repo, sample_video_file
    ):
        """Remet un fichier validé manuellement en statut pending."""
        pending = PendingValidation(
            id="2",
            video_file=sample_video_file,
            candidates=[],
            validation_status=ValidationStatus.VALIDATED,
            selected_candidate_id="tvdb:67890",
            auto_validated=False,
        )

        result = validation_service.reset_to_pending(pending)

        assert result.validation_status == ValidationStatus.PENDING
        assert result.selected_candidate_id is None
        assert result.auto_validated is False


# ============================================================================
# Tests: search_manual
# ============================================================================


class TestSearchManual:
    """Tests for search_manual method."""

    @pytest.mark.asyncio
    async def test_search_manual_movie(self, validation_service, mock_tmdb_client):
        """is_series=False -> utilise tmdb_client."""
        expected_results = [
            SearchResult(id="19995", title="Avatar", year=2009, source="tmdb")
        ]
        mock_tmdb_client.search = AsyncMock(return_value=expected_results)

        results = await validation_service.search_manual("Avatar", is_series=False, year=2009)

        mock_tmdb_client.search.assert_called_once_with("Avatar", year=2009)
        assert results == expected_results

    @pytest.mark.asyncio
    async def test_search_manual_series(self, validation_service, mock_tvdb_client):
        """is_series=True -> utilise tvdb_client."""
        expected_results = [
            SearchResult(id="81189", title="Breaking Bad", year=2008, source="tvdb")
        ]
        mock_tvdb_client.search = AsyncMock(return_value=expected_results)

        results = await validation_service.search_manual("Breaking Bad", is_series=True)

        mock_tvdb_client.search.assert_called_once_with("Breaking Bad", year=None)
        assert results == expected_results

    @pytest.mark.asyncio
    async def test_search_manual_no_client(self, mock_pending_repo, mock_matcher):
        """Client None -> retourne liste vide."""
        service = ValidationService(
            pending_repo=mock_pending_repo,
            matcher=mock_matcher,
            tmdb_client=None,
            tvdb_client=None,
        )

        results = await service.search_manual("Avatar", is_series=False)
        assert results == []

        results = await service.search_manual("Breaking Bad", is_series=True)
        assert results == []

    @pytest.mark.asyncio
    async def test_search_manual_client_no_api_key(self, mock_pending_repo, mock_matcher):
        """Client avec api_key vide -> retourne liste vide."""
        tmdb_client = MagicMock()
        tmdb_client._api_key = None  # No API key

        service = ValidationService(
            pending_repo=mock_pending_repo,
            matcher=mock_matcher,
            tmdb_client=tmdb_client,
            tvdb_client=None,
        )

        results = await service.search_manual("Avatar", is_series=False)
        assert results == []


# ============================================================================
# Tests: search_by_external_id
# ============================================================================


class TestSearchByExternalId:
    """Tests for search_by_external_id method."""

    @pytest.mark.asyncio
    async def test_search_by_tmdb_id(
        self, validation_service, mock_tmdb_client, sample_media_details
    ):
        """id_type=tmdb -> get_details avec l'ID TMDB."""
        mock_tmdb_client.get_details = AsyncMock(return_value=sample_media_details)

        result = await validation_service.search_by_external_id("tmdb", "19995")

        mock_tmdb_client.get_details.assert_called_once_with("19995")
        assert result == sample_media_details

    @pytest.mark.asyncio
    async def test_search_by_tvdb_id(
        self, validation_service, mock_tvdb_client, sample_media_details
    ):
        """id_type=tvdb -> get_details avec l'ID TVDB."""
        mock_tvdb_client.get_details = AsyncMock(return_value=sample_media_details)

        result = await validation_service.search_by_external_id("tvdb", "81189")

        mock_tvdb_client.get_details.assert_called_once_with("81189")
        assert result == sample_media_details

    @pytest.mark.asyncio
    async def test_search_by_unknown_type(self, validation_service):
        """id_type inconnu -> retourne None."""
        result = await validation_service.search_by_external_id("unknown", "12345")
        assert result is None

    @pytest.mark.asyncio
    async def test_search_by_imdb_id(
        self, validation_service, mock_tmdb_client, sample_media_details
    ):
        """id_type=imdb -> find_by_imdb_id via TMDB client."""
        mock_tmdb_client.find_by_imdb_id = AsyncMock(return_value=sample_media_details)

        result = await validation_service.search_by_external_id("imdb", "tt0499549")

        mock_tmdb_client.find_by_imdb_id.assert_called_once_with("tt0499549")
        assert result == sample_media_details

    @pytest.mark.asyncio
    async def test_search_by_external_id_no_client(self, mock_pending_repo, mock_matcher):
        """Client None -> retourne None."""
        service = ValidationService(
            pending_repo=mock_pending_repo,
            matcher=mock_matcher,
            tmdb_client=None,
            tvdb_client=None,
        )

        result = await service.search_by_external_id("tmdb", "19995")
        assert result is None


# ============================================================================
# Tests: list_validated
# ============================================================================


class TestListValidated:
    """Tests for list_validated method."""

    def test_list_validated_returns_validated_only(
        self, mock_pending_repo, mock_matcher, mock_tmdb_client, mock_tvdb_client
    ):
        """Verifie filtrage par status VALIDATED."""
        # Create mock session that simulates DB query
        mock_session = MagicMock()
        mock_pending_repo._session = mock_session

        # Setup mock to return validated items when queried
        from src.infrastructure.persistence.models import PendingValidationModel

        validated_model = MagicMock()
        validated_model.id = 1
        validated_model.video_file_id = 1
        validated_model.candidates_json = "[]"
        validated_model.auto_validated = True
        validated_model.validation_status = "validated"
        validated_model.selected_candidate_id = "19995"
        validated_model.created_at = datetime.now()

        mock_session.exec.return_value.all.return_value = [validated_model]

        # Mock _to_entity to return a proper PendingValidation
        expected_result = PendingValidation(
            id="1",
            video_file=None,
            candidates=[],
            auto_validated=True,
            validation_status=ValidationStatus.VALIDATED,
            selected_candidate_id="19995",
        )
        mock_pending_repo._to_entity = MagicMock(return_value=expected_result)

        service = ValidationService(
            pending_repo=mock_pending_repo,
            matcher=mock_matcher,
            tmdb_client=mock_tmdb_client,
            tvdb_client=mock_tvdb_client,
        )

        results = service.list_validated()

        assert len(results) == 1
        assert results[0].validation_status == ValidationStatus.VALIDATED


# ============================================================================
# Tests: THRESHOLD constant
# ============================================================================


class TestThresholdConstant:
    """Tests for THRESHOLD constant value."""

    def test_threshold_value(self):
        """THRESHOLD should be 85."""
        assert THRESHOLD == 85


# ============================================================================
# Tests: Edge cases
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_validate_candidate_details_not_found(
        self, validation_service, mock_tmdb_client, sample_video_file
    ):
        """get_details returns None -> raises ValueError."""
        mock_tmdb_client.get_details = AsyncMock(return_value=None)

        candidate = SearchResult(id="99999", title="Unknown", source="tmdb")
        pending = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=[],
            validation_status=ValidationStatus.PENDING,
        )

        with pytest.raises(ValueError, match="Impossible de recuperer les details"):
            await validation_service.validate_candidate(pending, candidate)

    @pytest.mark.asyncio
    async def test_process_auto_validation_with_searchresult_objects(
        self, validation_service, mock_pending_repo, sample_video_file
    ):
        """Candidats sous forme de SearchResult (pas dict) doivent fonctionner."""
        candidate = SearchResult(
            id="19995", title="Avatar", year=2009, score=90.0, source="tmdb"
        )
        pending = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=[candidate],  # SearchResult object, not dict
            auto_validated=False,
            validation_status=ValidationStatus.PENDING,
        )

        result = await validation_service.process_auto_validation(pending)

        assert result.auto_validated is True
        assert result.selected_candidate_id == "19995"

    def test_list_pending_proxy(self, validation_service, mock_pending_repo):
        """list_pending should proxy to pending_repo.list_pending."""
        expected = [MagicMock()]
        mock_pending_repo.list_pending.return_value = expected

        results = validation_service.list_pending()

        mock_pending_repo.list_pending.assert_called_once()
        assert results == expected

    @pytest.mark.asyncio
    async def test_validate_candidate_unknown_source(
        self, validation_service, sample_video_file
    ):
        """Source inconnue -> raises ValueError car details is None."""
        candidate = SearchResult(id="123", title="Unknown", source="unknown_api")
        pending = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=[],
            validation_status=ValidationStatus.PENDING,
        )

        with pytest.raises(ValueError, match="Impossible de recuperer les details"):
            await validation_service.validate_candidate(pending, candidate)
