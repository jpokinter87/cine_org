"""
Tests pour le parser TSV des datasets IMDb.

Verifie le parsing des fichiers title.ratings.tsv.gz.
"""

import gzip
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.adapters.imdb.tsv_parser import TSVParser


class TestTSVParser:
    """Tests pour TSVParser."""

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
            "tt0000001\t5.7\t1941\n"
            "tt0000002\t5.8\t260\n"
            "tt0499549\t7.6\t27000\n"  # Avatar
            "tt1375666\t8.8\t2400000\n"  # Inception
        )
        file_path = temp_dir / "title.ratings.tsv.gz"
        with gzip.open(file_path, "wt", encoding="utf-8") as f:
            f.write(content)
        return file_path

    def test_parse_ratings_returns_generator(self, sample_ratings_file):
        """parse_ratings doit retourner un generateur."""
        parser = TSVParser()
        result = parser.parse_ratings(sample_ratings_file)
        # Verifier que c'est un generateur
        assert hasattr(result, "__iter__")
        assert hasattr(result, "__next__")

    def test_parse_ratings_extracts_all_records(self, sample_ratings_file):
        """parse_ratings doit extraire tous les enregistrements."""
        parser = TSVParser()
        records = list(parser.parse_ratings(sample_ratings_file))
        assert len(records) == 4

    def test_parse_ratings_extracts_correct_fields(self, sample_ratings_file):
        """parse_ratings doit extraire les champs corrects."""
        parser = TSVParser()
        records = list(parser.parse_ratings(sample_ratings_file))

        # Verifier le premier enregistrement
        assert records[0]["tconst"] == "tt0000001"
        assert records[0]["average_rating"] == 5.7
        assert records[0]["num_votes"] == 1941

        # Verifier Avatar
        avatar = next(r for r in records if r["tconst"] == "tt0499549")
        assert avatar["average_rating"] == 7.6
        assert avatar["num_votes"] == 27000

        # Verifier Inception
        inception = next(r for r in records if r["tconst"] == "tt1375666")
        assert inception["average_rating"] == 8.8
        assert inception["num_votes"] == 2400000

    def test_parse_ratings_handles_missing_file(self, temp_dir):
        """parse_ratings doit lever une erreur pour fichier inexistant."""
        parser = TSVParser()
        with pytest.raises(FileNotFoundError):
            list(parser.parse_ratings(temp_dir / "nonexistent.tsv.gz"))

    def test_parse_ratings_handles_uncompressed_file(self, temp_dir):
        """parse_ratings doit gerer les fichiers non compresses."""
        content = (
            "tconst\taverageRating\tnumVotes\n"
            "tt0000001\t5.7\t1941\n"
        )
        file_path = temp_dir / "title.ratings.tsv"
        file_path.write_text(content)

        parser = TSVParser()
        records = list(parser.parse_ratings(file_path))
        assert len(records) == 1
        assert records[0]["tconst"] == "tt0000001"


class TestTSVParserTitleBasics:
    """Tests pour le parsing de title.basics.tsv.gz (optionnel)."""

    @pytest.fixture
    def temp_dir(self):
        """Repertoire temporaire pour les fichiers de test."""
        with TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def sample_basics_file(self, temp_dir):
        """Cree un fichier title.basics.tsv.gz de test."""
        content = (
            "tconst\ttitleType\tprimaryTitle\toriginalTitle\tisAdult\tstartYear\tendYear\truntimeMinutes\tgenres\n"
            "tt0499549\tmovie\tAvatar\tAvatar\t0\t2009\t\\N\t162\tAction,Adventure,Fantasy\n"
            "tt1375666\tmovie\tInception\tInception\t0\t2010\t\\N\t148\tAction,Adventure,Sci-Fi\n"
        )
        file_path = temp_dir / "title.basics.tsv.gz"
        with gzip.open(file_path, "wt", encoding="utf-8") as f:
            f.write(content)
        return file_path

    def test_parse_basics_extracts_records(self, sample_basics_file):
        """parse_basics doit extraire les enregistrements."""
        parser = TSVParser()
        records = list(parser.parse_basics(sample_basics_file))
        assert len(records) == 2

    def test_parse_basics_extracts_correct_fields(self, sample_basics_file):
        """parse_basics doit extraire les champs corrects."""
        parser = TSVParser()
        records = list(parser.parse_basics(sample_basics_file))

        avatar = records[0]
        assert avatar["tconst"] == "tt0499549"
        assert avatar["title_type"] == "movie"
        assert avatar["primary_title"] == "Avatar"
        assert avatar["start_year"] == 2009
        assert avatar["runtime_minutes"] == 162
        assert avatar["genres"] == ["Action", "Adventure", "Fantasy"]

    def test_parse_basics_handles_null_values(self, sample_basics_file):
        """parse_basics doit gerer les valeurs \\N (null)."""
        parser = TSVParser()
        records = list(parser.parse_basics(sample_basics_file))

        # endYear est \\N pour les films (pas de date de fin)
        for record in records:
            assert record["end_year"] is None
