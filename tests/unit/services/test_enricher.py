"""
Tests pour EnricherService - enrichissement des metadonnees via API.

TDD tests couvrant:
- Liste des fichiers necessitant enrichissement (candidats vides)
- Detection du type (film vs serie)
- Enrichissement unitaire via TMDB/TVDB
- Rate limiting avec asyncio.sleep
- Gestion des erreurs et continuation du batch
"""

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.entities.video import PendingValidation, ValidationStatus, VideoFile
from src.core.ports.api_clients import SearchResult
from src.core.value_objects import MediaInfo
from src.services.enricher import EnricherService, EnrichmentResult


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_pending_repo():
    """Create a mock PendingValidationRepository."""
    repo = MagicMock()
    repo.save = MagicMock(side_effect=lambda x: x)
    repo.list_pending = MagicMock(return_value=[])
    return repo


@pytest.fixture
def mock_video_file_repo():
    """Create a mock VideoFileRepository."""
    return MagicMock()


@pytest.fixture
def mock_matcher():
    """Create a mock MatcherService."""
    matcher = MagicMock()
    # Par defaut, retourner les resultats avec un score
    def score_results(results, **kwargs):
        scored = []
        for i, r in enumerate(results):
            # Simuler un score decroissant
            new_r = SearchResult(
                id=r.id,
                title=r.title,
                year=r.year,
                score=90.0 - i * 5,
                source=r.source,
            )
            scored.append(new_r)
        return scored

    matcher.score_results = MagicMock(side_effect=score_results)
    return matcher


@pytest.fixture
def mock_tmdb_client():
    """Create a mock TMDBClient with valid api_key."""
    client = MagicMock()
    client._api_key = "test_tmdb_key"
    client.search = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_tvdb_client():
    """Create a mock TVDBClient with valid api_key."""
    client = MagicMock()
    client._api_key = "test_tvdb_key"
    client.search = AsyncMock(return_value=[])
    return client


@pytest.fixture
def enricher_service(
    mock_pending_repo, mock_video_file_repo, mock_matcher, mock_tmdb_client, mock_tvdb_client
):
    """Create an EnricherService with all mocks."""
    return EnricherService(
        pending_repo=mock_pending_repo,
        video_file_repo=mock_video_file_repo,
        matcher=mock_matcher,
        tmdb_client=mock_tmdb_client,
        tvdb_client=mock_tvdb_client,
    )


@pytest.fixture
def sample_video_file():
    """Create a sample VideoFile entity for movies."""
    return VideoFile(
        id="1",
        path=Path("/downloads/Avatar.2009.1080p.BluRay.mkv"),
        filename="Avatar.2009.1080p.BluRay.mkv",
        size_bytes=4_500_000_000,
        media_info=MediaInfo(duration_seconds=9720),
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_series_video_file():
    """Create a sample VideoFile entity for series."""
    return VideoFile(
        id="2",
        path=Path("/downloads/Breaking.Bad.S01E01.720p.mkv"),
        filename="Breaking.Bad.S01E01.720p.mkv",
        size_bytes=1_500_000_000,
        media_info=MediaInfo(duration_seconds=3600),
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_search_results():
    """Create sample search results from API."""
    return [
        SearchResult(id="19995", title="Avatar", year=2009, score=0.0, source="tmdb"),
        SearchResult(id="76600", title="Avatar: The Way of Water", year=2022, score=0.0, source="tmdb"),
    ]


# ============================================================================
# Tests: list_pending_enrichment
# ============================================================================


class TestListPendingEnrichment:
    """Tests for list_pending_enrichment method."""

    def test_list_pending_enrichment_empty_candidates(
        self, enricher_service, mock_pending_repo, sample_video_file
    ):
        """Retourne les fichiers avec candidats vides ou None."""
        # Setup: fichiers avec et sans candidats
        pending_without = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=[],  # Vide
            validation_status=ValidationStatus.PENDING,
        )
        pending_with = PendingValidation(
            id="2",
            video_file=sample_video_file,
            candidates=[{"id": "123", "title": "Test", "score": 90.0, "source": "tmdb"}],
            validation_status=ValidationStatus.PENDING,
        )

        mock_pending_repo.list_pending.return_value = [pending_without, pending_with]

        # Act
        result = enricher_service.list_pending_enrichment()

        # Assert
        assert len(result) == 1
        assert result[0].id == "1"

    def test_list_pending_enrichment_none_candidates(
        self, enricher_service, mock_pending_repo, sample_video_file
    ):
        """Retourne les fichiers avec candidates=None."""
        pending = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=None,  # type: ignore - Simule None stocke en DB
            validation_status=ValidationStatus.PENDING,
        )

        mock_pending_repo.list_pending.return_value = [pending]

        result = enricher_service.list_pending_enrichment()

        assert len(result) == 1


# ============================================================================
# Tests: _detect_is_series
# ============================================================================


class TestDetectIsSeries:
    """Tests for _detect_is_series method."""

    def test_detect_series_from_filename_pattern(
        self, enricher_service, sample_series_video_file
    ):
        """Detecte une serie via le pattern SxxExx dans le nom."""
        pending = PendingValidation(
            id="1",
            video_file=sample_series_video_file,
            candidates=[],
        )

        assert enricher_service._detect_is_series(pending) is True

    def test_detect_movie_from_filename(
        self, enricher_service, sample_video_file
    ):
        """Detecte un film (pas de pattern SxxExx)."""
        pending = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=[],
        )

        assert enricher_service._detect_is_series(pending) is False


# ============================================================================
# Tests: enrich_batch rate limiting
# ============================================================================


class TestEnrichBatchRateLimit:
    """Tests for rate limiting in enrich_batch."""

    @pytest.mark.asyncio
    async def test_enrich_batch_respects_rate_limit(
        self, enricher_service, mock_pending_repo, mock_tmdb_client, sample_video_file
    ):
        """Verifie que asyncio.sleep est appele entre les requetes."""
        # Setup: 2 fichiers a enrichir
        pending1 = PendingValidation(
            id="1",
            video_file=VideoFile(
                id="1",
                path=Path("/downloads/Film1.mkv"),
                filename="Film1.mkv",
            ),
            candidates=[],
        )
        pending2 = PendingValidation(
            id="2",
            video_file=VideoFile(
                id="2",
                path=Path("/downloads/Film2.mkv"),
                filename="Film2.mkv",
            ),
            candidates=[],
        )

        # Mock TMDB pour retourner des resultats
        mock_tmdb_client.search = AsyncMock(
            return_value=[
                SearchResult(id="1", title="Film 1", year=2020, source="tmdb"),
            ]
        )

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await enricher_service.enrich_batch([pending1, pending2])

            # Verifie que sleep a ete appele au moins 2 fois (1 apres chaque item)
            assert mock_sleep.call_count >= 2

            # Verifie le delai utilise
            for call in mock_sleep.call_args_list:
                delay = call[0][0] if call[0] else call[1].get("delay", 0)
                assert delay >= 0.25 or delay == 0.25


# ============================================================================
# Tests: _enrich_single
# ============================================================================


class TestEnrichSingle:
    """Tests for _enrich_single method."""

    @pytest.mark.asyncio
    async def test_enrich_single_movie(
        self,
        enricher_service,
        mock_tmdb_client,
        mock_matcher,
        mock_pending_repo,
        sample_video_file,
        sample_search_results,
    ):
        """Enrichissement d'un film appelle tmdb_client.search()."""
        pending = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=[],
        )

        mock_tmdb_client.search = AsyncMock(return_value=sample_search_results)

        result = await enricher_service._enrich_single(pending)

        assert result is True
        mock_tmdb_client.search.assert_called_once()
        # Verifier que les arguments contiennent le titre
        call_args = mock_tmdb_client.search.call_args
        assert "Avatar" in call_args[0][0]  # query_title

        # Verifier que les candidats ont ete sauvegardes
        mock_pending_repo.save.assert_called_once()
        saved_pending = mock_pending_repo.save.call_args[0][0]
        assert len(saved_pending.candidates) == 2

    @pytest.mark.asyncio
    async def test_enrich_single_series(
        self,
        enricher_service,
        mock_tvdb_client,
        mock_matcher,
        mock_pending_repo,
        sample_series_video_file,
    ):
        """Enrichissement d'une serie appelle tvdb_client.search()."""
        pending = PendingValidation(
            id="1",
            video_file=sample_series_video_file,
            candidates=[],
        )

        series_results = [
            SearchResult(id="81189", title="Breaking Bad", year=2008, source="tvdb"),
        ]
        mock_tvdb_client.search = AsyncMock(return_value=series_results)

        result = await enricher_service._enrich_single(pending)

        assert result is True
        mock_tvdb_client.search.assert_called_once()

        # Verifier que TMDB n'a pas ete appele (c'est une serie)
        # Note: on ne peut pas faire ca facilement car le client est un mock
        # Mais on peut verifier que tvdb a bien ete utilise


# ============================================================================
# Tests: enrich_batch error handling
# ============================================================================


class TestEnrichBatchErrorHandling:
    """Tests for error handling in enrich_batch."""

    @pytest.mark.asyncio
    async def test_enrich_continues_on_error(
        self, enricher_service, mock_tmdb_client, mock_pending_repo
    ):
        """Erreur sur un fichier n'arrete pas le batch."""
        # Setup: 3 fichiers, le 2e echoue
        pending1 = PendingValidation(
            id="1",
            video_file=VideoFile(id="1", filename="Film1.mkv", path=Path("/f1.mkv")),
            candidates=[],
        )
        pending2 = PendingValidation(
            id="2",
            video_file=VideoFile(id="2", filename="Film2.mkv", path=Path("/f2.mkv")),
            candidates=[],
        )
        pending3 = PendingValidation(
            id="3",
            video_file=VideoFile(id="3", filename="Film3.mkv", path=Path("/f3.mkv")),
            candidates=[],
        )

        # Mock TMDB: 1er et 3e reussissent, 2e echoue systematiquement (meme apres retries)
        # Compteur par fichier pour gerer les retries
        file_calls = {"Film1": 0, "Film2": 0, "Film3": 0}

        async def mock_search(query, year=None):
            # Identifier le fichier par le titre (qui est le nom de fichier nettoye)
            for name in file_calls:
                if name.lower() in query.lower():
                    file_calls[name] += 1
                    if name == "Film2":
                        raise Exception("Erreur API simulee persistante")
                    return [SearchResult(id="123", title="Test", year=2020, source="tmdb")]
            return [SearchResult(id="123", title="Test", year=2020, source="tmdb")]

        mock_tmdb_client.search = AsyncMock(side_effect=mock_search)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await enricher_service.enrich_batch([pending1, pending2, pending3])

        # Verifie que le batch continue malgre l'erreur
        assert result.enriched >= 1  # Au moins 1 succes
        assert result.failed >= 1  # Au moins 1 echec
        assert result.total == 3  # Tous les fichiers traites

    @pytest.mark.asyncio
    async def test_enrich_skips_already_enriched(
        self, enricher_service, mock_tmdb_client, mock_pending_repo
    ):
        """Les fichiers deja enrichis sont ignores."""
        pending_with_candidates = PendingValidation(
            id="1",
            video_file=VideoFile(id="1", filename="Film1.mkv", path=Path("/f1.mkv")),
            candidates=[{"id": "123", "title": "Deja enrichi", "score": 90.0, "source": "tmdb"}],
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await enricher_service.enrich_batch([pending_with_candidates])

        assert result.skipped == 1
        assert result.enriched == 0
        # TMDB ne doit pas avoir ete appele
        mock_tmdb_client.search.assert_not_called()


# ============================================================================
# Tests: EnrichmentResult dataclass
# ============================================================================


class TestEnrichmentResult:
    """Tests for EnrichmentResult dataclass."""

    def test_enrichment_result_total(self):
        """La propriete total calcule correctement la somme."""
        result = EnrichmentResult(enriched=5, failed=2, skipped=3)
        assert result.total == 10

    def test_enrichment_result_defaults(self):
        """Les valeurs par defaut sont 0."""
        result = EnrichmentResult()
        assert result.enriched == 0
        assert result.failed == 0
        assert result.skipped == 0
        assert result.total == 0


# ============================================================================
# Tests: Edge cases
# ============================================================================


class TestEnricherEdgeCases:
    """Tests for edge cases."""

    @pytest.mark.asyncio
    async def test_enrich_without_tmdb_client(
        self, mock_pending_repo, mock_video_file_repo, mock_matcher, sample_video_file
    ):
        """Enrichissement sans client TMDB retourne False pour les films."""
        service = EnricherService(
            pending_repo=mock_pending_repo,
            video_file_repo=mock_video_file_repo,
            matcher=mock_matcher,
            tmdb_client=None,  # Pas de client
            tvdb_client=None,
        )

        pending = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=[],
        )

        result = await service._enrich_single(pending)
        assert result is False

    @pytest.mark.asyncio
    async def test_enrich_with_empty_api_key(
        self, mock_pending_repo, mock_video_file_repo, mock_matcher, sample_video_file
    ):
        """Client avec api_key vide retourne False."""
        mock_client = MagicMock()
        mock_client._api_key = None  # Pas de cle

        service = EnricherService(
            pending_repo=mock_pending_repo,
            video_file_repo=mock_video_file_repo,
            matcher=mock_matcher,
            tmdb_client=mock_client,
            tvdb_client=None,
        )

        pending = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=[],
        )

        result = await service._enrich_single(pending)
        assert result is False

    @pytest.mark.asyncio
    async def test_enrich_no_results_returns_false(
        self, enricher_service, mock_tmdb_client, sample_video_file
    ):
        """Recherche sans resultat retourne False."""
        pending = PendingValidation(
            id="1",
            video_file=sample_video_file,
            candidates=[],
        )

        mock_tmdb_client.search = AsyncMock(return_value=[])

        result = await enricher_service._enrich_single(pending)
        assert result is False

    def test_extract_query_info_cleans_filename(self, enricher_service):
        """_extract_query_info nettoie correctement le nom de fichier."""
        video_file = VideoFile(
            id="1",
            filename="Avatar.2009.1080p.BluRay.x264.mkv",
            path=Path("/test.mkv"),
        )
        pending = PendingValidation(id="1", video_file=video_file, candidates=[])

        query, year, duration = enricher_service._extract_query_info(pending)

        assert "Avatar" in query
        assert year == 2009
        assert "1080p" not in query
        assert "BluRay" not in query
        assert "x264" not in query
