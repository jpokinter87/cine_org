"""Annotation des parties de films dans _fix_duplicate_filenames."""

from pathlib import Path
from types import SimpleNamespace

from src.adapters.cli.batch_builder import _fix_duplicate_filenames
from src.services.renamer import RenamerService


def _movie_transfer(filename: str, movie_id: int) -> dict:
    video_file = SimpleNamespace(filename=filename, media_info=None)
    pending = SimpleNamespace(video_file=video_file)
    return {
        "pending": pending,
        "source": Path(f"/dl/{filename}"),
        # Meme destination pour les deux parties (collision) -> declenche le fix
        "destination": Path(
            "/storage/Nos meilleures annees (2003) MULTi x265 1080p.mkv"
        ),
        "new_filename": "Nos meilleures annees (2003) MULTi x265 1080p.mkv",
        "symlink_destination": Path(
            "/video/Nos meilleures annees (2003) MULTi x265 1080p.mkv"
        ),
        "is_series": False,
        "title": "Nos meilleures annees",
        "year": 2003,
        "movie_id": movie_id,
    }


def test_film_multipartie_annote_les_parties_non_primaires():
    renamer = RenamerService()
    transfers = [
        _movie_transfer("Nos.meilleures.annees.2003.Part.1.MULTi.x265.1080p.mkv", 42),
        _movie_transfer("Nos.meilleures.annees.2003.Part.2.MULTi.x265.1080p.mkv", 42),
    ]

    result = _fix_duplicate_filenames(transfers, renamer)

    by_part = {t["new_filename"]: t for t in result}
    p1 = next(t for t in result if "Partie 1" in t["new_filename"])
    p2 = next(t for t in result if "Partie 2" in t["new_filename"])

    assert "movie_part_number" not in p1
    assert p2["movie_part_number"] == 2
    assert len(by_part) == 2
