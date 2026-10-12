"""Résumé d'épisode dépliable sur la fiche série.

Les résumés étaient enregistrés en base mais aucune page ne les affichait.
Le titre d'un épisode qui a un résumé devient un bouton qui le déplie.
"""

from fastapi.testclient import TestClient

from src.infrastructure.persistence.database import get_session
from src.infrastructure.persistence.models import EpisodeModel, SeriesModel
from src.web.app import app
from tests.unit.test_browse_incomplete_filter import isolated_db  # noqa: F401


def _seed() -> int:
    session = next(get_session())
    try:
        series = SeriesModel(title="Mouche", year=2019)
        session.add(series)
        session.commit()
        session.refresh(series)
        session.add(
            EpisodeModel(
                series_id=series.id,
                season_number=1,
                episode_number=1,
                title="Épisode 1",
                overview="Mouche est une trentenaire parisienne & libre.",
            )
        )
        session.add(
            EpisodeModel(
                series_id=series.id,
                season_number=1,
                episode_number=2,
                title="Épisode 2",
            )
        )
        session.commit()
        return series.id
    finally:
        session.close()


def test_episode_with_overview_has_toggle_and_text(isolated_db):  # noqa: F811
    series_id = _seed()
    with TestClient(app) as client:
        html = client.get(f"/library/series/{series_id}").text

    assert html.count('class="lib-episode-title lib-episode-title-toggle"') == 1
    assert 'aria-expanded="false"' in html
    # Texte échappé (pas d'injection HTML depuis les données TVDB)
    assert "Mouche est une trentenaire parisienne &amp; libre." in html
    assert html.count('class="lib-episode-overview"') == 1


def test_episode_without_overview_keeps_plain_title(isolated_db):  # noqa: F811
    series_id = _seed()
    with TestClient(app) as client:
        html = client.get(f"/library/series/{series_id}").text

    assert '<span class="lib-episode-title">Épisode 2</span>' in html
