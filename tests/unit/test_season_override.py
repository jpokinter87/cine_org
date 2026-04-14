"""
Tests pour SeasonOverrideModel et la colonne is_extra d'EpisodeModel.

Phase 42-01 : overrides manuels du nombre d'episodes par saison, pour
gerer les decoupages alternatifs des distributeurs (ex: The Big C S04
= 4 episodes officiels TVDB mais 8 dans la version locale).
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from src.infrastructure.persistence.models import (
    EpisodeModel,
    SeasonOverrideModel,
    SeriesModel,
)


@pytest.fixture
def engine():
    """Engine SQLite in-memory avec toutes les tables."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    """Session fraiche sur l'engine en memoire."""
    with Session(engine) as session:
        yield session


class TestSeasonOverrideModel:
    """Tests du modele SeasonOverrideModel."""

    def test_insert_and_retrieve(self, session):
        """Un override s'insere et se relit par (tvdb_id, season_number)."""
        override = SeasonOverrideModel(
            tvdb_id=246063,
            season_number=4,
            episode_count=8,
        )
        session.add(override)
        session.commit()

        result = session.exec(
            select(SeasonOverrideModel).where(
                SeasonOverrideModel.tvdb_id == 246063,
                SeasonOverrideModel.season_number == 4,
            )
        ).first()

        assert result is not None
        assert result.episode_count == 8
        assert result.tvdb_id == 246063
        assert result.season_number == 4

    def test_unique_constraint_on_tvdb_season(self, session):
        """Un doublon (tvdb_id, season_number) leve IntegrityError."""
        first = SeasonOverrideModel(
            tvdb_id=246063,
            season_number=4,
            episode_count=8,
        )
        session.add(first)
        session.commit()

        duplicate = SeasonOverrideModel(
            tvdb_id=246063,
            season_number=4,
            episode_count=10,
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.commit()

    def test_same_series_different_seasons_allowed(self, session):
        """Une meme serie peut avoir des overrides sur differentes saisons."""
        s3 = SeasonOverrideModel(tvdb_id=246063, season_number=3, episode_count=11)
        s4 = SeasonOverrideModel(tvdb_id=246063, season_number=4, episode_count=8)
        session.add(s3)
        session.add(s4)
        session.commit()

        results = session.exec(
            select(SeasonOverrideModel).where(
                SeasonOverrideModel.tvdb_id == 246063
            )
        ).all()
        assert len(results) == 2


class TestEpisodeIsExtra:
    """Tests de la colonne is_extra sur EpisodeModel."""

    def test_is_extra_default_false(self, session):
        """is_extra vaut False par defaut."""
        series = SeriesModel(title="The Big C", tvdb_id=246063, year=2010)
        session.add(series)
        session.commit()
        assert series.id is not None

        episode = EpisodeModel(
            series_id=series.id,
            season_number=4,
            episode_number=1,
            title="Quelque chose",
        )
        session.add(episode)
        session.commit()

        assert episode.is_extra is False

    def test_is_extra_persisted_true(self, session):
        """is_extra=True est persiste et relu correctement."""
        series = SeriesModel(title="The Big C", tvdb_id=246063, year=2010)
        session.add(series)
        session.commit()

        extra = EpisodeModel(
            series_id=series.id,
            season_number=4,
            episode_number=7,
            title="Hors canon",
            is_extra=True,
        )
        session.add(extra)
        session.commit()

        refreshed = session.exec(
            select(EpisodeModel).where(
                EpisodeModel.series_id == series.id,
                EpisodeModel.episode_number == 7,
            )
        ).first()
        assert refreshed is not None
        assert refreshed.is_extra is True
