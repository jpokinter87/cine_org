"""Test du rétro-remplissage des flags de granularité (Migration 14)."""

import json

from sqlmodel import Session, SQLModel, create_engine, select

from src.infrastructure.persistence.database import _backfill_completeness_flags
from src.infrastructure.persistence.models import SeriesModel


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    return engine


def test_backfill_sets_flags_from_missing_json():
    """Le backfill dérive les deux flags depuis completeness_missing_json."""
    engine = _make_engine()
    with Session(engine) as session:
        # Épisodes manquants seulement.
        session.add(
            SeriesModel(
                title="EpsOnly",
                completeness_status="incomplete",
                completeness_missing_json=json.dumps(
                    {"missing_seasons": [], "missing_episodes": [{"season": 1, "episode": 2}]}
                ),
            )
        )
        # Saisons manquantes seulement.
        session.add(
            SeriesModel(
                title="SeasonsOnly",
                completeness_status="incomplete",
                completeness_missing_json=json.dumps(
                    {"missing_seasons": [2], "missing_episodes": []}
                ),
            )
        )
        # Les deux.
        session.add(
            SeriesModel(
                title="Mixed",
                completeness_status="incomplete",
                completeness_missing_json=json.dumps(
                    {"missing_seasons": [3], "missing_episodes": [{"season": 1, "episode": 2}]}
                ),
            )
        )
        # Jamais vérifiée (JSON nul) → flags inchangés (False).
        session.add(SeriesModel(title="Untouched", completeness_missing_json=None))
        session.commit()

    with engine.begin() as conn:
        _backfill_completeness_flags(conn)

    with Session(engine) as session:
        rows = {
            s.title: (s.has_missing_episodes, s.has_missing_seasons)
            for s in session.exec(select(SeriesModel)).all()
        }
    assert rows["EpsOnly"] == (True, False)
    assert rows["SeasonsOnly"] == (False, True)
    assert rows["Mixed"] == (True, True)
    assert rows["Untouched"] == (False, False)
