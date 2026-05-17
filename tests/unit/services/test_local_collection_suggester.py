"""Tests P4-4 — LocalCollectionSuggester."""

from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from src.infrastructure.persistence.models import LocalCollectionModel, MovieModel
from src.services.local_collection_suggester import LocalCollectionSuggester


def _make_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _make_short(
    session: Session,
    title: str,
    *,
    collection_name: str | None = None,
    local_collection_id: int | None = None,
) -> MovieModel:
    model = MovieModel(
        title=title,
        duration_seconds=420,
        is_short=True,
        collection_name=collection_name,
        local_collection_id=local_collection_id,
    )
    session.add(model)
    session.commit()
    session.refresh(model)
    return model


class TestFindOrphanGroups:
    """Groupement des courts orphelins par préfixe de titre commun."""

    def test_two_shorts_with_common_2word_prefix_form_group(self) -> None:
        session = _make_session()
        _make_short(session, "Bugs Bunny in Hare-Way to the Stars")
        _make_short(session, "Bugs Bunny — Knighty Knight Bugs")

        groups = LocalCollectionSuggester(session).find_orphan_groups()
        assert len(groups) == 1
        assert groups[0].suggested_name == "Bugs Bunny"
        assert {m.title for m in groups[0].movies} == {
            "Bugs Bunny in Hare-Way to the Stars",
            "Bugs Bunny — Knighty Knight Bugs",
        }

    def test_isolated_short_is_not_grouped(self) -> None:
        session = _make_session()
        _make_short(session, "Bugs Bunny in Hare-Way")
        _make_short(session, "Wallace and Gromit — A Grand Day Out")

        # Aucun préfixe commun (deux films isolés, préfixes différents)
        groups = LocalCollectionSuggester(session).find_orphan_groups()
        assert groups == []

    def test_short_with_tmdb_collection_is_excluded(self) -> None:
        session = _make_session()
        _make_short(session, "Bugs Bunny A", collection_name="Looney Tunes")
        _make_short(session, "Bugs Bunny B")

        # Un seul orphelin restant → pas de groupe
        groups = LocalCollectionSuggester(session).find_orphan_groups()
        assert groups == []

    def test_short_with_local_collection_is_excluded(self) -> None:
        session = _make_session()
        coll = LocalCollectionModel(name="Existing")
        session.add(coll)
        session.commit()
        session.refresh(coll)

        _make_short(session, "Bugs Bunny A", local_collection_id=coll.id)
        _make_short(session, "Bugs Bunny B")

        groups = LocalCollectionSuggester(session).find_orphan_groups()
        assert groups == []

    def test_long_movies_are_excluded(self) -> None:
        session = _make_session()
        # Deux films longs (is_short=False) avec préfixe commun
        for title in ("Star Wars Episode IV", "Star Wars Episode V"):
            m = MovieModel(title=title, duration_seconds=7200, is_short=False)
            session.add(m)
        session.commit()

        groups = LocalCollectionSuggester(session).find_orphan_groups()
        assert groups == []

    def test_three_shorts_share_prefix_yields_single_group(self) -> None:
        session = _make_session()
        _make_short(session, "Tom and Jerry — Cat Concerto")
        _make_short(session, "Tom and Jerry — The Bowling Alley-Cat")
        _make_short(session, "Tom and Jerry — Dog Trouble")

        groups = LocalCollectionSuggester(session).find_orphan_groups()
        assert len(groups) == 1
        assert groups[0].suggested_name == "Tom and"
        assert len(groups[0].movies) == 3
