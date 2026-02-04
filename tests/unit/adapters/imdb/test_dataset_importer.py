"""
Tests pour IMDbDatasetImporter.

Verifie le telechargement, l'import et le lookup des datasets IMDb.
"""

import gzip
import pytest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch, AsyncMock

from src.adapters.imdb.dataset_importer import IMDbDatasetImporter, IMDbDatasetStats


class TestIMDbDatasetImporter:
    """Tests pour IMDbDatasetImporter."""

    @pytest.fixture
    def temp_dir(self):
        """Repertoire temporaire pour les fichiers de test."""
        with TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def sample_ratings_file(self, temp_dir):
        """Cree un fichier title.ratings.tsv.gz de test."""
        content = (
            "tconst\taverageRating\tnumVotes\n"
            "tt0499549\t7.6\t27000\n"
            "tt1375666\t8.8\t2400000\n"
        )
        file_path = temp_dir / "title.ratings.tsv.gz"
        with gzip.open(file_path, "wt", encoding="utf-8") as f:
            f.write(content)
        return file_path

    @pytest.fixture
    def mock_session(self):
        """Mock pour la session SQLModel."""
        session = MagicMock()
        return session

    @pytest.fixture
    def importer(self, temp_dir, mock_session):
        """Importer avec repertoire de cache temporaire."""
        return IMDbDatasetImporter(
            cache_dir=temp_dir,
            session=mock_session,
        )

    def test_needs_update_returns_true_for_missing_file(self, importer, temp_dir):
        """needs_update doit retourner True si le fichier n'existe pas."""
        missing_file = temp_dir / "missing.tsv.gz"
        assert importer.needs_update(missing_file) is True

    def test_needs_update_returns_true_for_old_file(
        self, importer, sample_ratings_file
    ):
        """needs_update doit retourner True si le fichier est trop vieux."""
        # Modifier la date de modification pour etre vieille
        import os
        old_time = (date.today() - timedelta(days=10)).timetuple()
        old_timestamp = os.path.getmtime(sample_ratings_file) - (10 * 24 * 3600)
        os.utime(sample_ratings_file, (old_timestamp, old_timestamp))

        assert importer.needs_update(sample_ratings_file, max_age_days=7) is True

    def test_needs_update_returns_false_for_recent_file(
        self, importer, sample_ratings_file
    ):
        """needs_update doit retourner False si le fichier est recent."""
        assert importer.needs_update(sample_ratings_file, max_age_days=7) is False

    def test_import_ratings_inserts_records(
        self, importer, sample_ratings_file, mock_session
    ):
        """import_ratings doit inserer les enregistrements en base."""
        stats = importer.import_ratings(sample_ratings_file)

        assert stats.total == 2
        assert stats.imported == 2
        # Verifie que la session a ete utilisee (merge pour upsert)
        assert mock_session.merge.called
        assert mock_session.commit.called

    def test_get_rating_returns_tuple(self, importer, mock_session):
        """get_rating doit retourner (average_rating, num_votes)."""
        # Mock le resultat de la requete
        mock_result = MagicMock()
        mock_result.first.return_value = (7.6, 27000)
        mock_session.exec.return_value = mock_result

        result = importer.get_rating("tt0499549")

        assert result == (7.6, 27000)

    def test_get_rating_returns_none_for_missing(self, importer, mock_session):
        """get_rating doit retourner None si l'ID n'existe pas."""
        # Mock le resultat vide
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_session.exec.return_value = mock_result

        result = importer.get_rating("tt9999999")

        assert result is None


class TestIMDbDatasetStats:
    """Tests pour la dataclass IMDbDatasetStats."""

    def test_stats_creation(self):
        """Devrait creer des stats avec les valeurs par defaut."""
        stats = IMDbDatasetStats()
        assert stats.total == 0
        assert stats.imported == 0
        assert stats.skipped == 0
        assert stats.errors == 0

    def test_stats_with_values(self):
        """Devrait creer des stats avec les valeurs fournies."""
        stats = IMDbDatasetStats(total=1000, imported=990, skipped=5, errors=5)
        assert stats.total == 1000
        assert stats.imported == 990


class TestDownloadDataset:
    """Tests pour le telechargement des datasets (mock HTTP)."""

    @pytest.fixture
    def temp_dir(self):
        """Repertoire temporaire pour les fichiers de test."""
        with TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def mock_session(self):
        """Mock pour la session SQLModel."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_download_dataset_creates_file(self, temp_dir, mock_session):
        """download_dataset doit creer le fichier telecharge."""
        importer = IMDbDatasetImporter(
            cache_dir=temp_dir,
            session=mock_session,
        )

        # Mock httpx pour simuler le telechargement
        sample_content = b"tconst\taverageRating\tnumVotes\ntt0000001\t5.7\t1941\n"
        compressed = gzip.compress(sample_content)

        with patch(
            "src.adapters.imdb.dataset_importer.httpx.AsyncClient"
        ) as mock_client_class:
            # Configurer le mock pour le context manager async
            mock_client = MagicMock()
            mock_client_class.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

            # Configurer le mock pour stream()
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()

            async def async_iter_bytes():
                yield compressed

            mock_response.aiter_bytes = async_iter_bytes

            mock_stream_context = MagicMock()
            mock_stream_context.__aenter__ = AsyncMock(return_value=mock_response)
            mock_stream_context.__aexit__ = AsyncMock(return_value=None)
            mock_client.stream.return_value = mock_stream_context

            file_path = await importer.download_dataset("title.ratings")

            assert file_path.exists()
            assert file_path.suffix == ".gz"
