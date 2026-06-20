"""Le transfert web crée une MoviePart pour les parties non primaires.

Régression : `_update_db_paths` (chemin web) doit gérer `movie_part_number`
comme `transfer_step._update_file_paths` (chemin CLI), sinon la Partie 2 est
transférée mais jamais enregistrée comme partie (fiche sans bloc « Parties »).
"""

from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select

from src.infrastructure.persistence import database
from src.infrastructure.persistence.models import MovieModel, MoviePartModel


def _engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/t.db")
    SQLModel.metadata.create_all(engine)
    database._engine = engine
    return engine


def test_update_db_paths_partie_primaire_ecrit_la_fiche(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as s:
        movie = MovieModel(title="Film", year=2003, tmdb_id=1)
        s.add(movie)
        s.commit()
        s.refresh(movie)
        mid = movie.id

    from src.web.routes.transfer import _update_db_paths

    _update_db_paths(
        None,
        {"movie_id": mid},
        Path("/storage/Film Partie 1.mkv"),
        Path("/video/Film Partie 1.mkv"),
    )

    with Session(engine) as s:
        movie = s.get(MovieModel, mid)
        assert movie.file_path.endswith("Partie 1.mkv")
        assert s.exec(select(MoviePartModel)).all() == []


def test_update_db_paths_partie_non_primaire_cree_movie_part(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as s:
        movie = MovieModel(
            title="Film",
            year=2003,
            tmdb_id=1,
            file_path="/storage/Film Partie 1.mkv",
            symlink_path="/video/Film Partie 1.mkv",
        )
        s.add(movie)
        s.commit()
        s.refresh(movie)
        mid = movie.id

    from src.web.routes.transfer import _update_db_paths

    _update_db_paths(
        None,
        {"movie_id": mid, "movie_part_number": 2},
        Path("/storage/Film Partie 2.mkv"),
        Path("/video/Film Partie 2.mkv"),
    )

    with Session(engine) as s:
        # La fiche garde la Partie 1 (non écrasée)
        movie = s.get(MovieModel, mid)
        assert movie.file_path.endswith("Partie 1.mkv")
        # Une MoviePart créée pour la Partie 2
        parts = s.exec(
            select(MoviePartModel).where(MoviePartModel.movie_id == mid)
        ).all()
        assert len(parts) == 1
        assert parts[0].part_number == 2
        assert parts[0].file_path.endswith("Partie 2.mkv")
        assert parts[0].symlink_path.endswith("Partie 2.mkv")
