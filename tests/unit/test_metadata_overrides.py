"""
Tests pour le service metadata_overrides (phase 42-02, tache 1).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from sqlmodel import Session, SQLModel, create_engine, select

from src.infrastructure.persistence.models import MovieModel, SeriesModel
from src.services.metadata_overrides import (
    ALLOWED_POSTER_EXTENSIONS,
    delete_poster,
    find_poster,
    get_metadata_dir,
    poster_filename,
    save_poster_from_url,
    save_poster_upload,
)


@pytest.fixture
def storage_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


class TestPosterFilename:
    def test_poster_filename_movie(self):
        assert poster_filename("movie", 42, ".jpg") == "movie-42.jpg"

    def test_poster_filename_series(self):
        assert poster_filename("series", 17, ".png") == "series-17.png"

    def test_poster_filename_normalizes_extension(self):
        assert poster_filename("movie", 1, "JPG") == "movie-1.jpg"


class TestGetMetadataDir:
    def test_creates_directory(self, storage_dir: Path):
        result = get_metadata_dir(storage_dir)
        assert result.exists()
        assert result == storage_dir / ".metadata" / "posters"

    def test_idempotent(self, storage_dir: Path):
        get_metadata_dir(storage_dir)
        result = get_metadata_dir(storage_dir)
        assert result.exists()


class TestSavePosterUpload:
    def test_save_jpg_writes_file(self, storage_dir: Path):
        path = save_poster_upload(
            storage_dir, "movie", 42, "original.jpg", b"\xff\xd8\xff\xe0"
        )
        assert path.exists()
        assert path.name == "movie-42.jpg"
        assert path.read_bytes() == b"\xff\xd8\xff\xe0"

    def test_save_png_writes_file(self, storage_dir: Path):
        path = save_poster_upload(
            storage_dir, "series", 17, "cover.png", b"\x89PNG\r\n"
        )
        assert path.name == "series-17.png"

    def test_save_webp_accepted(self, storage_dir: Path):
        path = save_poster_upload(
            storage_dir, "movie", 1, "p.webp", b"RIFF...WEBP"
        )
        assert path.name == "movie-1.webp"

    def test_rejects_bad_extension(self, storage_dir: Path):
        with pytest.raises(ValueError, match="non autorisee"):
            save_poster_upload(storage_dir, "movie", 42, "notes.txt", b"data")

    def test_rejects_no_extension(self, storage_dir: Path):
        with pytest.raises(ValueError):
            save_poster_upload(storage_dir, "movie", 42, "poster", b"data")

    def test_replaces_existing_same_extension(self, storage_dir: Path):
        save_poster_upload(storage_dir, "movie", 42, "old.jpg", b"old")
        path = save_poster_upload(
            storage_dir, "movie", 42, "new.jpg", b"new-content"
        )
        assert path.read_bytes() == b"new-content"

    def test_replaces_existing_different_extension(self, storage_dir: Path):
        """Upload d'un .png remplace un .jpg existant pour la meme entite."""
        old = save_poster_upload(storage_dir, "movie", 42, "old.jpg", b"old")
        assert old.exists()
        new = save_poster_upload(
            storage_dir, "movie", 42, "new.png", b"new-content"
        )
        assert new.name == "movie-42.png"
        assert not old.exists()  # ancien supprime

    def test_independent_entities(self, storage_dir: Path):
        """Plusieurs entites coexistent."""
        a = save_poster_upload(storage_dir, "movie", 1, "a.jpg", b"a")
        b = save_poster_upload(storage_dir, "movie", 2, "b.jpg", b"b")
        c = save_poster_upload(storage_dir, "series", 1, "c.jpg", b"c")
        assert a.exists() and b.exists() and c.exists()


class TestSavePosterFromUrl:
    @respx.mock
    def test_downloads_and_saves(self, storage_dir: Path):
        respx.get("https://example.com/poster.jpg").mock(
            return_value=httpx.Response(
                200, content=b"IMAGEDATA", headers={"content-type": "image/jpeg"}
            )
        )
        path = save_poster_from_url(
            storage_dir, "movie", 42, "https://example.com/poster.jpg"
        )
        assert path.exists()
        assert path.name == "movie-42.jpg"
        assert path.read_bytes() == b"IMAGEDATA"

    @respx.mock
    def test_rejects_404(self, storage_dir: Path):
        respx.get("https://example.com/missing.jpg").mock(
            return_value=httpx.Response(404)
        )
        with pytest.raises(ValueError, match="status 404"):
            save_poster_from_url(
                storage_dir, "movie", 1, "https://example.com/missing.jpg"
            )

    @respx.mock
    def test_rejects_non_image_content_type(self, storage_dir: Path):
        respx.get("https://example.com/page.html").mock(
            return_value=httpx.Response(
                200, content=b"<html/>", headers={"content-type": "text/html"}
            )
        )
        with pytest.raises(ValueError, match="Content-Type invalide"):
            save_poster_from_url(
                storage_dir, "movie", 1, "https://example.com/page.html"
            )

    def test_rejects_bad_url_scheme(self, storage_dir: Path):
        with pytest.raises(ValueError, match="URL invalide"):
            save_poster_from_url(
                storage_dir, "movie", 1, "ftp://example.com/p.jpg"
            )

    @respx.mock
    def test_uses_content_type_for_extension(self, storage_dir: Path):
        """URL sans extension + Content-Type image/png → fichier .png."""
        respx.get("https://cdn.example.com/img?id=42").mock(
            return_value=httpx.Response(
                200, content=b"PNGDATA", headers={"content-type": "image/png"}
            )
        )
        path = save_poster_from_url(
            storage_dir, "series", 10, "https://cdn.example.com/img?id=42"
        )
        assert path.name == "series-10.png"


class TestDeletePoster:
    def test_delete_existing(self, storage_dir: Path):
        save_poster_upload(storage_dir, "movie", 42, "p.jpg", b"x")
        assert delete_poster(storage_dir, "movie", 42) is True
        assert find_poster(storage_dir, "movie", 42) is None

    def test_delete_absent_returns_false(self, storage_dir: Path):
        get_metadata_dir(storage_dir)  # cree le dossier vide
        assert delete_poster(storage_dir, "movie", 999) is False


class TestOverrideColumnsPersistence:
    """Verifie que les nouvelles colonnes MovieModel/SeriesModel persistent."""

    def test_movie_overrides_round_trip(self, session):
        m = MovieModel(
            title="Test",
            poster_override="/x/.metadata/posters/movie-1.jpg",
            overview_override="Override synopsis",
            cast_override_json='[{"name":"Actor","role":"Hero"}]',
            preserve_overrides=True,
        )
        session.add(m)
        session.commit()
        session.refresh(m)

        assert m.poster_override == "/x/.metadata/posters/movie-1.jpg"
        assert m.overview_override == "Override synopsis"
        assert m.preserve_overrides is True
        assert m.cast_override == [{"name": "Actor", "role": "Hero"}]

    def test_series_overrides_round_trip(self, session):
        s = SeriesModel(
            title="Show",
            poster_override=None,
            overview_override="S override",
            preserve_overrides=False,
        )
        s.cast_override = [
            {"name": "A", "role": "X"},
            {"name": "B", "role": "Y"},
        ]
        session.add(s)
        session.commit()
        session.refresh(s)

        assert s.preserve_overrides is False
        assert s.overview_override == "S override"
        assert s.cast_override == [
            {"name": "A", "role": "X"},
            {"name": "B", "role": "Y"},
        ]

    def test_defaults_when_unset(self, session):
        m = MovieModel(title="Plain")
        session.add(m)
        session.commit()
        session.refresh(m)

        assert m.poster_override is None
        assert m.overview_override is None
        assert m.cast_override_json is None
        assert m.cast_override == []
        assert m.preserve_overrides is False


class TestAllowedExtensions:
    def test_has_common_formats(self):
        assert ".jpg" in ALLOWED_POSTER_EXTENSIONS
        assert ".jpeg" in ALLOWED_POSTER_EXTENSIONS
        assert ".png" in ALLOWED_POSTER_EXTENSIONS
        assert ".webp" in ALLOWED_POSTER_EXTENSIONS
