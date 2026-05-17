"""Tests P6 — MissingFileResolver : retrouve un fichier déplacé par basename."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from src.infrastructure.persistence.models import MovieModel
from src.services.missing_file_resolver import MissingFileResolver
from src.services.missing_files_scanner import MissingRecord


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _record(
    stale_path: Path, *, entity_type: str = "movie", entity_id: int = 1
) -> MissingRecord:
    return MissingRecord(
        entity_type=entity_type,
        entity_id=entity_id,
        title=stale_path.stem,
        file_path=str(stale_path),
    )


class TestResolverFindCandidates:
    """Recherche par basename exact dans les répertoires fournis."""

    def test_finds_file_moved_to_other_directory(self, tmp_path: Path) -> None:
        # Fichier réel à un autre endroit que celui en DB
        real = tmp_path / "Films" / "Drame" / "Et la fête continue ! (2024).mkv"
        real.parent.mkdir(parents=True)
        real.touch()

        stale = tmp_path / "Films" / "Comédie" / "Et la fête continue ! (2024).mkv"
        rec = _record(stale)

        resolver = MissingFileResolver(search_dirs=[tmp_path])
        candidates = resolver.find_candidates(rec)
        assert candidates == [real]

    def test_no_match_returns_empty(self, tmp_path: Path) -> None:
        # Seul un fichier sans rapport existe
        (tmp_path / "Films").mkdir()
        (tmp_path / "Films" / "Autre.mkv").touch()

        stale = tmp_path / "Films" / "Inexistant.mkv"
        resolver = MissingFileResolver(search_dirs=[tmp_path])
        assert resolver.find_candidates(_record(stale)) == []

    def test_multiple_matches_all_returned(self, tmp_path: Path) -> None:
        """Le même basename présent dans 2 sous-arbo (ex. storage + video symlink)."""
        a = tmp_path / "storage" / "Plein la vue (1997).mkv"
        b = tmp_path / "video" / "Plein la vue (1997).mkv"
        a.parent.mkdir()
        b.parent.mkdir()
        a.touch()
        b.touch()

        stale = tmp_path / "ailleurs" / "Plein la vue (1997).mkv"
        resolver = MissingFileResolver(search_dirs=[tmp_path])
        candidates = resolver.find_candidates(_record(stale))
        assert set(candidates) == {a, b}

    def test_excludes_stale_path_itself(self, tmp_path: Path) -> None:
        """Si par accident le file_path stale existe (course condition),
        il ne doit pas être retourné comme candidat."""
        stale = tmp_path / "Films" / "Respire (2014).mkv"
        stale.parent.mkdir()
        stale.touch()

        resolver = MissingFileResolver(search_dirs=[tmp_path])
        assert resolver.find_candidates(_record(stale)) == []


class TestApplyRepair:
    """Mise à jour de file_path en DB."""

    def test_apply_updates_movie_file_path(self, session, tmp_path: Path) -> None:
        new_path = tmp_path / "Films" / "Drame" / "Respire (2014).mkv"
        new_path.parent.mkdir(parents=True)
        new_path.touch()

        movie = MovieModel(
            title="Respire",
            year=2014,
            file_path=str(tmp_path / "Films" / "Comédie" / "Respire (2014).mkv"),
        )
        session.add(movie)
        session.commit()
        session.refresh(movie)

        rec = MissingRecord(
            entity_type="movie",
            entity_id=movie.id,
            title="Respire",
            file_path=movie.file_path,
        )
        resolver = MissingFileResolver(search_dirs=[tmp_path])
        ok = resolver.apply_repair(session, rec, new_path)

        assert ok is True
        session.refresh(movie)
        assert movie.file_path == str(new_path)

    def test_apply_unknown_entity_type_returns_false(
        self, session, tmp_path: Path
    ) -> None:
        rec = MissingRecord(
            entity_type="invalid",
            entity_id=1,
            title="?",
            file_path="/whatever",
        )
        ok = MissingFileResolver(search_dirs=[tmp_path]).apply_repair(
            session, rec, tmp_path / "x.mkv"
        )
        assert ok is False
