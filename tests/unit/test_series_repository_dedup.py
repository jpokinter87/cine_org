"""Tests : déduplication des séries dans ``SQLModelSeriesRepository.save``.

Les séries matchées via la source ``tmdb_tv`` ont ``tvdb_id`` NULL. Sans
repli de déduplication par ``tmdb_id``, un nouveau transfert de la même
série créait une fiche en double (cas « Sous ses yeux »). On vérifie que
``save`` réutilise la fiche existante via ``tmdb_id`` quand ``tvdb_id``
est absent, tout en conservant la déduplication par ``tvdb_id``.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from src.core.entities.media import Series
from src.infrastructure.persistence.models import SeriesModel
from src.infrastructure.persistence.repositories.series_repository import (
    SQLModelSeriesRepository,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _count(session) -> int:
    return len(session.exec(select(SeriesModel)).all())


def test_dedup_par_tmdb_id_quand_tvdb_absent(session):
    """Deux save successifs (tvdb_id NULL, même tmdb_id) → une seule fiche."""
    repo = SQLModelSeriesRepository(session)

    repo.save(Series(tmdb_id=457481, tvdb_id=None, title="Sous ses yeux", year=2026))
    repo.save(
        Series(tmdb_id=457481, tvdb_id=None, title="Sous ses yeux (corrigé)", year=2026)
    )

    assert _count(session) == 1
    model = session.exec(select(SeriesModel)).first()
    assert model.title == "Sous ses yeux (corrigé)"


def test_dedup_par_tvdb_id_inchangee(session):
    """Régression : la déduplication par tvdb_id reste fonctionnelle."""
    repo = SQLModelSeriesRepository(session)

    repo.save(Series(tvdb_id=81189, title="Breaking Bad", year=2008))
    repo.save(Series(tvdb_id=81189, title="Breaking Bad MAJ", year=2008))

    assert _count(session) == 1


def test_series_distinctes_non_fusionnees(session):
    """Deux tmdb_id différents → deux fiches distinctes (pas de faux merge)."""
    repo = SQLModelSeriesRepository(session)

    repo.save(Series(tmdb_id=280511, tvdb_id=None, title="Sous ses yeux", year=2026))
    repo.save(Series(tmdb_id=999999, tvdb_id=None, title="Autre série", year=2026))

    assert _count(session) == 2
