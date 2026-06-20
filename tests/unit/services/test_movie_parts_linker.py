"""Service de rattachement des parties orphelines (backfill)."""

from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine, select

from src.infrastructure.persistence.models import MovieModel, MoviePartModel
from src.services.movie_parts import MoviePartLinker


def _make_symlink(video_dir: Path, name: str, storage_dir: Path) -> Path:
    target = storage_dir / name
    target.write_bytes(b"x")
    link = video_dir / name
    link.symlink_to(target)
    return link


def test_linker_cree_les_parties_manquantes_et_est_idempotent(tmp_path):
    video_dir = tmp_path / "video"
    storage_dir = tmp_path / "storage"
    video_dir.mkdir()
    storage_dir.mkdir()

    p1 = _make_symlink(
        video_dir, "Nos meilleures années (2003) Partie 1 MULTi.mkv", storage_dir
    )
    _make_symlink(
        video_dir, "Nos meilleures années (2003) Partie 2 MULTi.mkv", storage_dir
    )

    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    session.add(
        MovieModel(
            title="Nos meilleures années",
            year=2003,
            tmdb_id=11659,
            file_path=str(p1.resolve()),
            symlink_path=str(p1),
        )
    )
    session.commit()

    linker = MoviePartLinker(session, video_dir)
    plan = linker.build_plan()
    assert len(plan) == 1
    assert plan[0].part_number == 2

    created = linker.apply(plan)
    assert created == 1

    parts = session.exec(select(MoviePartModel)).all()
    assert len(parts) == 1
    assert parts[0].part_number == 2
    assert parts[0].symlink_path.endswith("Partie 2 MULTi.mkv")

    assert linker.build_plan() == []
