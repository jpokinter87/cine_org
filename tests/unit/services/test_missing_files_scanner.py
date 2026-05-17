"""Tests du service MissingFilesScanner (DB ↔ filesystem)."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from src.infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    SeriesModel,
)
from src.services.missing_files_scanner import (
    MissingFilesScanner,
    MissingRecord,
)


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


class TestFindMissing:
    """Détection des fiches dont le file_path n'existe plus."""

    def test_movie_with_existing_file_is_not_missing(
        self, session, tmp_path: Path
    ) -> None:
        f = tmp_path / "movie.mkv"
        f.touch()
        session.add(MovieModel(title="Existe", file_path=str(f)))
        session.commit()

        assert MissingFilesScanner(session).find_missing() == []

    def test_movie_with_missing_file_is_detected(self, session, tmp_path: Path) -> None:
        missing_path = tmp_path / "nope.mkv"
        session.add(MovieModel(title="Manquant", file_path=str(missing_path)))
        session.commit()

        results = MissingFilesScanner(session).find_missing()
        assert len(results) == 1
        assert results[0].entity_type == "movie"
        assert results[0].title == "Manquant"
        assert results[0].file_path == str(missing_path)

    def test_movie_without_file_path_is_skipped(self, session) -> None:
        """Une fiche incomplète (sans file_path) n'est pas marquée 'manquante'."""
        session.add(MovieModel(title="Sans file_path", file_path=None))
        session.commit()
        assert MissingFilesScanner(session).find_missing() == []

    def test_episode_with_missing_file_is_detected(
        self, session, tmp_path: Path
    ) -> None:
        # Crée d'abord une série pour la FK
        series = SeriesModel(title="Show")
        session.add(series)
        session.commit()
        session.refresh(series)

        missing_path = tmp_path / "ep.mkv"
        session.add(
            EpisodeModel(
                series_id=series.id,
                season_number=1,
                episode_number=1,
                title="E01",
                file_path=str(missing_path),
            )
        )
        session.commit()

        results = MissingFilesScanner(session).find_missing()
        assert len(results) == 1
        assert results[0].entity_type == "episode"
        assert results[0].title == "Show — S01E01 — E01"

    def test_mixed_results_sorted_by_type_then_title(
        self, session, tmp_path: Path
    ) -> None:
        series = SeriesModel(title="Z Show")
        session.add(series)
        session.commit()
        session.refresh(series)

        session.add(MovieModel(title="B film", file_path=str(tmp_path / "b.mkv")))
        session.add(MovieModel(title="A film", file_path=str(tmp_path / "a.mkv")))
        session.add(
            EpisodeModel(
                series_id=series.id,
                season_number=1,
                episode_number=1,
                title="Pilot",
                file_path=str(tmp_path / "pilot.mkv"),
            )
        )
        session.commit()

        results = MissingFilesScanner(session).find_missing()
        types = [r.entity_type for r in results]
        # Films d'abord (tri par type), puis episodes
        assert types == ["movie", "movie", "episode"]
        # Au sein de chaque type, tri par titre
        assert [r.title for r in results[:2]] == ["A film", "B film"]


class TestProgressCallback:
    """find_missing relaie sa progression via le callback fourni."""

    def test_callback_called_once_per_scanned_file(
        self, session, tmp_path: Path
    ) -> None:
        series = SeriesModel(title="Show")
        session.add(series)
        session.commit()
        session.refresh(series)

        f1 = tmp_path / "a.mkv"
        f1.touch()
        session.add(MovieModel(title="Existe", file_path=str(f1)))
        session.add(MovieModel(title="Manquant", file_path=str(tmp_path / "nope.mkv")))
        session.add(
            EpisodeModel(
                series_id=series.id,
                season_number=1,
                episode_number=1,
                title="Pilot",
                file_path=str(tmp_path / "pilot.mkv"),
            )
        )
        session.commit()

        calls: list[tuple[int, int, str]] = []
        MissingFilesScanner(session).find_missing(
            on_progress=lambda c, t, label: calls.append((c, t, label))
        )

        # 3 fichiers scannés → 3 callbacks, currents 1..3, total constant à 3
        assert len(calls) == 3
        assert [c[0] for c in calls] == [1, 2, 3]
        assert {c[1] for c in calls} == {3}

    def test_count_to_scan_matches_callback_total(
        self, session, tmp_path: Path
    ) -> None:
        for i in range(5):
            session.add(MovieModel(title=f"M{i}", file_path=str(tmp_path / f"{i}.mkv")))
        session.add(MovieModel(title="Sans path", file_path=None))
        session.commit()

        scanner = MissingFilesScanner(session)
        assert scanner.count_to_scan() == 5


class TestPrune:
    """Le pruning envoie chaque fiche manquante en corbeille."""

    def test_prune_moves_movie_to_trash(self, session, tmp_path: Path) -> None:
        from src.infrastructure.persistence.models import TrashModel

        missing_path = tmp_path / "nope.mkv"
        session.add(MovieModel(title="Manquant", file_path=str(missing_path)))
        session.commit()

        scanner = MissingFilesScanner(session)
        records = scanner.find_missing()
        pruned = scanner.prune(records)

        assert pruned == 1
        # Plus de Movie en DB
        from sqlmodel import select

        assert session.exec(select(MovieModel)).all() == []
        # Une entrée corbeille
        trash_entries = session.exec(select(TrashModel)).all()
        assert len(trash_entries) == 1
        assert trash_entries[0].entity_type == "movie"

    def test_prune_does_not_touch_filesystem(self, session, tmp_path: Path) -> None:
        """Si le fichier existe ailleurs (faux positif), prune ne le supprime pas.
        En pratique find_missing ne le retournerait pas, mais on vérifie que
        prune ne fait que des opérations DB."""
        existing = tmp_path / "real.mkv"
        existing.touch()

        rec = MissingRecord(
            entity_type="movie",
            entity_id=999,
            title="Fake",
            file_path=str(existing),
        )
        # Skipped : pas en DB → 0 prune
        assert MissingFilesScanner(session).prune([rec]) == 0
        # Fichier intact
        assert existing.exists()
