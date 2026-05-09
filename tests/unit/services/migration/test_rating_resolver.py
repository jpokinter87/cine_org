"""
Tests pour MigrationRatingResolver.

Le resolveur consulte la base CineOrg (MovieModel / SeriesModel + imdb_ratings)
pour produire une RatingDecision. La note retenue est max(imdb, tmdb,
personal*weight) avec weight=2 par défaut (échelle 1-5 → 0-10).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.adapters.parsing.guessit_parser import GuessitFilenameParser
from src.infrastructure.persistence.models import (
    IMDbRatingModel,
    MovieModel,
    SeriesModel,
)
from src.services.migration.dataclasses import MigrationCandidate
from src.services.migration.rating_resolver import MigrationRatingResolver


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


@pytest.fixture
def parser():
    return GuessitFilenameParser()


@pytest.fixture
def importer():
    imp = MagicMock()
    imp.get_rating.return_value = None
    return imp


def _candidate(name: str, media_root: str = "Films") -> MigrationCandidate:
    return MigrationCandidate(
        symlink_path=Path(f"/source/{media_root}/G/{name}"),
        target_path=Path(f"/target/{name}"),
        media_root=media_root,
        relative_category="G",
    )


def test_movie_resolves_with_combined_rating_personal_wins(session, parser, importer):
    """personal=4 → 8.0, > imdb=7.5 et tmdb=7.0 → personal gagne."""
    m = MovieModel(
        tmdb_id=10, title="Avatar", year=2009,
        imdb_rating=7.5, vote_average=7.0, personal_rating=4,
        imdb_id="tt0499549",
    )
    session.add(m)
    session.commit()

    resolver = MigrationRatingResolver(session, parser, importer)
    decision = resolver.resolve(_candidate("Avatar (2009) FR x265 1080p.mkv"))

    assert decision.value == pytest.approx(8.0)
    assert decision.source == "personal"
    assert decision.imdb == pytest.approx(7.5)
    assert decision.tmdb == pytest.approx(7.0)
    assert decision.personal == 4
    assert decision.movie_id_in_db == m.id
    assert decision.title_match == "Avatar"


def test_movie_imdb_wins_when_higher(session, parser, importer):
    m = MovieModel(
        tmdb_id=11, title="Inception", year=2010,
        imdb_rating=8.8, vote_average=8.4, personal_rating=3,
    )
    session.add(m)
    session.commit()
    resolver = MigrationRatingResolver(session, parser, importer)
    decision = resolver.resolve(_candidate("Inception (2010) FR x265 1080p.mkv"))
    assert decision.value == pytest.approx(8.8)
    assert decision.source == "imdb"


def test_movie_falls_back_to_imdb_dataset_when_db_imdb_missing(session, parser, importer):
    m = MovieModel(
        tmdb_id=12, title="Bambi", year=1942,
        vote_average=7.3, imdb_id="tt0034492",
    )
    session.add(m)
    session.commit()
    importer.get_rating.return_value = (7.4, 12345)

    resolver = MigrationRatingResolver(session, parser, importer)
    decision = resolver.resolve(_candidate("Bambi (1942) FR x265 1080p.mkv"))

    assert decision.imdb == pytest.approx(7.4)
    importer.get_rating.assert_called_once_with("tt0034492")


def test_movie_returns_none_value_when_no_rating_anywhere(session, parser, importer):
    m = MovieModel(tmdb_id=13, title="Obscur", year=2020)
    session.add(m)
    session.commit()
    resolver = MigrationRatingResolver(session, parser, importer)
    decision = resolver.resolve(_candidate("Obscur (2020) FR x265 1080p.mkv"))
    assert decision.value is None
    assert decision.source is None
    assert decision.movie_id_in_db == m.id  # film trouvé mais pas de note


def test_movie_unknown_in_db_returns_empty_decision(session, parser, importer):
    resolver = MigrationRatingResolver(session, parser, importer)
    decision = resolver.resolve(_candidate("ZZZ Inconnu (2050) FR x265 1080p.mkv"))
    assert decision.value is None
    assert decision.movie_id_in_db is None
    assert decision.title_match is None


def test_series_episode_resolved_via_series_title(session, parser, importer):
    s = SeriesModel(
        tvdb_id=42, title="Sopranos", year=1999,
        imdb_rating=9.2, vote_average=8.7, personal_rating=5,
    )
    session.add(s)
    session.commit()
    resolver = MigrationRatingResolver(session, parser, importer)
    cand = _candidate(
        "Sopranos (1999) - S01E01 - The Sopranos - FR x265 1080p.mkv",
        media_root="Séries",
    )
    decision = resolver.resolve(cand)

    # personal=5 → 10.0 > imdb=9.2 → personal gagne
    assert decision.value == pytest.approx(10.0)
    assert decision.source == "personal"
    assert decision.series_id_in_db == s.id
    assert decision.title_match == "Sopranos"


def test_series_falls_back_to_imdb_dataset(session, parser, importer):
    s = SeriesModel(
        tvdb_id=43, title="Lost", year=2004,
        vote_average=8.4, imdb_id="tt0411008",
    )
    session.add(s)
    session.commit()
    importer.get_rating.return_value = (8.3, 600000)
    resolver = MigrationRatingResolver(session, parser, importer)
    cand = _candidate(
        "Lost (2004) - S01E01 - Pilot - FR x265 1080p.mkv",
        media_root="Séries",
    )
    decision = resolver.resolve(cand)
    assert decision.imdb == pytest.approx(8.3)


def test_personal_weight_configurable(session, parser, importer):
    """Avec un poids personnel de 1 (au lieu de 2), personal=5 → 5.0 et imdb=7.9 gagne."""
    m = MovieModel(tmdb_id=14, title="Wall-E", year=2008,
                   imdb_rating=7.9, personal_rating=5)
    session.add(m); session.commit()
    resolver = MigrationRatingResolver(session, parser, importer, personal_weight=1)
    decision = resolver.resolve(_candidate("Wall-E (2008) FR x265 1080p.mkv"))
    assert decision.source == "imdb"
    assert decision.value == pytest.approx(7.9)


def test_search_partial_title(session, parser, importer):
    """Si l'exact échoue, on retombe sur LIKE %parsed_title% (DB englobe le titre parsé)."""
    m = MovieModel(tmdb_id=15, title="Le Seigneur des anneaux", year=2001, imdb_rating=8.8)
    session.add(m); session.commit()
    resolver = MigrationRatingResolver(session, parser, importer)
    # parsed.title sera "Seigneur Des Anneaux" → LIKE matche "Le Seigneur des anneaux"
    decision = resolver.resolve(_candidate("Seigneur des anneaux (2001) FR x265 1080p.mkv"))
    assert decision.movie_id_in_db == m.id
