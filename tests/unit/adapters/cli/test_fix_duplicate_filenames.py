"""
Tests unitaires pour _fix_duplicate_filenames (filet de securite multi-parties).

Verifie que le filet detecte les noms de destination en doublon
et les corrige automatiquement avec un suffixe "Partie N".
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.adapters.cli.batch_builder import _fix_duplicate_filenames


def _make_transfer(
    filename: str,
    original_filename: str,
    dest_dir: str = "/storage/Films/Drame/N",
    title: str = "Nos meilleures annees",
    year: int = 2003,
    is_series: bool = False,
) -> dict:
    """Helper pour creer un dict transfert minimal."""
    pending = MagicMock()
    pending.video_file.filename = original_filename
    pending.video_file.media_info = None

    dest = Path(dest_dir) / filename
    symlink_dest = Path("/video/Films/Drame/N") / filename

    return {
        "pending": pending,
        "source": Path("/downloads") / original_filename,
        "destination": dest,
        "new_filename": filename,
        "action": "move+symlink",
        "symlink_destination": symlink_dest,
        "is_series": is_series,
        "title": title,
        "year": year,
    }


class TestFixDuplicateFilenames:
    """Tests pour le filet de securite des doublons."""

    @pytest.fixture
    def renamer(self):
        """RenamerService reel."""
        from src.services.renamer import RenamerService

        return RenamerService()

    def test_no_duplicates_unchanged(self, renamer):
        """Sans doublons, la liste reste inchangee."""
        transfers = [
            _make_transfer(
                "Inception (2010) Multi.mkv",
                "Inception.2010.MULTi.1080p.mkv",
                title="Inception",
                year=2010,
            ),
            _make_transfer(
                "Nos meilleures annees (2003) Multi.mkv",
                "La.meglio.gioventu.2003.MULTi.1080p.mkv",
            ),
        ]
        result = _fix_duplicate_filenames(transfers, renamer)
        assert result[0]["new_filename"] == "Inception (2010) Multi.mkv"
        assert result[1]["new_filename"] == "Nos meilleures annees (2003) Multi.mkv"

    def test_duplicates_with_part_in_original(self, renamer):
        """Doublons avec part1/part2 dans le nom original → Partie 1/Partie 2."""
        same_name = "Nos meilleures annees (2003) Multi.mkv"
        transfers = [
            _make_transfer(
                same_name,
                "La.meglio.gioventu.Part.1.2003.MULTi.1080p.mkv",
            ),
            _make_transfer(
                same_name,
                "La.meglio.gioventu.Part.2.2003.MULTi.1080p.mkv",
            ),
        ]
        result = _fix_duplicate_filenames(transfers, renamer)

        assert "Partie 1" in result[0]["new_filename"]
        assert "Partie 2" in result[1]["new_filename"]
        # Les destinations doivent etre differentes
        assert result[0]["destination"] != result[1]["destination"]
        # Les symlinks aussi
        assert result[0]["symlink_destination"] != result[1]["symlink_destination"]

    def test_duplicates_without_part_gets_sequential(self, renamer):
        """Doublons sans indication de part → numerotation sequentielle."""
        same_name = "Nos meilleures annees (2003) Multi.mkv"
        transfers = [
            _make_transfer(
                same_name,
                "La.meglio.gioventu.2003.MULTi.1080p.CD1.mkv",
            ),
            _make_transfer(
                same_name,
                "La.meglio.gioventu.2003.MULTi.1080p.CD2.mkv",
            ),
        ]
        result = _fix_duplicate_filenames(transfers, renamer)

        assert "Partie 1" in result[0]["new_filename"]
        assert "Partie 2" in result[1]["new_filename"]
        assert result[0]["destination"] != result[1]["destination"]

    def test_three_parts(self, renamer):
        """Film decoupe en 3 parties."""
        same_name = "Carlos (2010) Multi.mkv"
        transfers = [
            _make_transfer(
                same_name,
                "Carlos.Partie.1.2010.MULTi.1080p.mkv",
                title="Carlos",
                year=2010,
            ),
            _make_transfer(
                same_name,
                "Carlos.Partie.2.2010.MULTi.1080p.mkv",
                title="Carlos",
                year=2010,
            ),
            _make_transfer(
                same_name,
                "Carlos.Partie.3.2010.MULTi.1080p.mkv",
                title="Carlos",
                year=2010,
            ),
        ]
        result = _fix_duplicate_filenames(transfers, renamer)

        assert "Partie 1" in result[0]["new_filename"]
        assert "Partie 2" in result[1]["new_filename"]
        assert "Partie 3" in result[2]["new_filename"]
        # Toutes les destinations uniques
        dests = {str(r["destination"]) for r in result}
        assert len(dests) == 3

    def test_mixed_batch_only_fixes_duplicates(self, renamer):
        """Un batch mixte : seuls les doublons sont corriges."""
        transfers = [
            _make_transfer(
                "Inception (2010) Multi.mkv",
                "Inception.2010.MULTi.1080p.mkv",
                title="Inception",
                year=2010,
            ),
            _make_transfer(
                "Nos meilleures annees (2003) Multi.mkv",
                "La.meglio.gioventu.Part.1.2003.MULTi.mkv",
            ),
            _make_transfer(
                "Nos meilleures annees (2003) Multi.mkv",
                "La.meglio.gioventu.Part.2.2003.MULTi.mkv",
            ),
        ]
        result = _fix_duplicate_filenames(transfers, renamer)

        # Inception inchange
        assert result[0]["new_filename"] == "Inception (2010) Multi.mkv"
        # Les deux doublons corriges
        assert "Partie 1" in result[1]["new_filename"]
        assert "Partie 2" in result[2]["new_filename"]
