"""Tests des colonnes de complétude sur SeriesModel et de leur persistance."""

from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine, select

from src.infrastructure.persistence.models import SeriesModel


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    return engine


def test_series_model_has_completeness_columns():
    """Les trois colonnes de complétude existent et sont persistées."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="Test", tvdb_id=123)
        series.completeness_status = "incomplete"
        series.completeness_checked_at = datetime(2026, 6, 23, 12, 0, 0)
        series.completeness_missing_json = '{"missing_seasons": [2]}'
        session.add(series)
        session.commit()
        session.refresh(series)

    with Session(engine) as session:
        loaded = session.exec(
            select(SeriesModel).where(SeriesModel.title == "Test")
        ).first()
        assert loaded.completeness_status == "incomplete"
        assert loaded.completeness_checked_at == datetime(2026, 6, 23, 12, 0, 0)
        assert loaded.completeness_missing_json == '{"missing_seasons": [2]}'


def test_completeness_status_defaults_to_none():
    """Une série jamais vérifiée a completeness_status = None."""
    engine = _make_engine()
    with Session(engine) as session:
        series = SeriesModel(title="Neuve")
        session.add(series)
        session.commit()
        session.refresh(series)
        assert series.completeness_status is None
        assert series.completeness_checked_at is None
        assert series.completeness_missing_json is None
