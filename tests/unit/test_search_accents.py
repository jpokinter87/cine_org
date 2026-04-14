"""
Tests de la recherche insensible aux accents (phase 43-01).

Couvre :
- UDF SQLite ``unaccent`` enregistrée par le listener dans database.py
- ``search_variants`` étendu avec la version accent-stripped
- ``_title_search_filter`` matche dans les deux sens accent/sans-accent
- Non-régression sur ligatures (œ/oe) et titres ASCII (Batman)
"""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

# Import database.py pour activer le listener @event.listens_for(Engine, "connect")
# ⚠️ Ne pas retirer : l'import déclenche l'enregistrement de l'UDF
from src.infrastructure.persistence import database as _db_module  # noqa: F401
from src.infrastructure.persistence.models import MovieModel, SeriesModel
from src.utils.helpers import normalize_accents, search_variants
from src.web.routes.library.helpers import _title_search_filter


@pytest.fixture
def engine():
    """Engine SQLite in-memory avec schéma + UDF auto-enregistrée."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


# ─── UDF unaccent ─────────────────────────────────────────────────────────


class TestUnaccentUdf:
    def test_udf_is_registered(self, session):
        """L'UDF unaccent est disponible sur la connexion."""
        result = session.exec(text("SELECT unaccent('Millénium')")).one()
        assert result[0] == "Millenium"

    def test_udf_on_multi_diacritics(self, session):
        """Couvre é è ê à â ç ô û ñ."""
        result = session.exec(
            text("SELECT unaccent('Héroïne à Châtelet Forêt Façon Nuñez')")
        ).one()
        assert result[0] == "Heroine a Chatelet Foret Facon Nunez"

    def test_udf_handles_null(self, session):
        result = session.exec(text("SELECT unaccent(NULL)")).one()
        assert result[0] is None

    def test_udf_ascii_unchanged(self, session):
        result = session.exec(text("SELECT unaccent('Batman')")).one()
        assert result[0] == "Batman"

    def test_udf_ligatures_preserved(self, session):
        """L'UDF ne touche PAS aux ligatures (géré par search_variants)."""
        result = session.exec(text("SELECT unaccent('Œuvre')")).one()
        assert result[0] == "Œuvre"


# ─── search_variants étendu ───────────────────────────────────────────────


class TestSearchVariants:
    def test_accented_query_includes_unaccented(self):
        variants = search_variants("Millénium")
        assert any(normalize_accents(v) == "Millenium" for v in variants)
        assert "millenium" in {v.lower() for v in variants}

    def test_unaccented_query_contains_unaccented(self):
        variants = search_variants("Millenium")
        # Identique sans accents (pas de regression)
        assert "Millenium" in variants or "millenium" in variants

    def test_ligatures_still_work(self):
        variants = search_variants("Œuvre")
        lowered = {v.lower() for v in variants}
        assert "oeuvre" in lowered or "œuvre" in lowered


# ─── _title_search_filter ─────────────────────────────────────────────────


def _add_movie(session, title, tmdb_id):
    m = MovieModel(title=title, year=2020, tmdb_id=tmdb_id)
    session.add(m)
    session.commit()


def _search_titles(session, query: str, model_class=MovieModel) -> list[str]:
    filt = _title_search_filter(model_class, query)
    rows = session.exec(select(model_class).where(filt)).all()
    return [r.title for r in rows]


class TestTitleSearchFilter:
    def test_unaccented_query_finds_accented_title(self, session):
        """Ta recherche: 'Millenium' doit trouver 'Millénium' en DB."""
        _add_movie(session, "Millénium", 15472)
        _add_movie(session, "Batman", 1)
        results = _search_titles(session, "Millenium")
        assert "Millénium" in results
        assert "Batman" not in results

    def test_accented_query_finds_accented_title(self, session):
        """Sanity : query accentuée trouve toujours le titre accentué."""
        _add_movie(session, "Millénium", 15472)
        results = _search_titles(session, "Millénium")
        assert "Millénium" in results

    def test_accented_query_finds_unaccented_title(self, session):
        """Sens inverse : query avec accent trouve titre sans accent."""
        # Cas théorique : titre DB sans accent mais query avec accent
        _add_movie(session, "Bokeh", 99)
        results = _search_titles(session, "Bokéh")
        assert "Bokeh" in results

    def test_all_millenium_variants_found_with_unaccented_query(self, session):
        """Scenario utilisateur : cherche 'Millenium', trouve toute la saga."""
        _add_movie(session, "Millénium", 1)
        _add_movie(session, "Millénium 2 : La Fille qui rêvait", 2)
        _add_movie(session, "Millénium 3 : La Reine", 3)
        _add_movie(session, "Millennium Actress", 4)  # autre film
        _add_movie(session, "Batman", 5)  # non lié

        results = _search_titles(session, "Millenium")

        # Tous les Millénium (avec accent) doivent être trouvés
        assert "Millénium" in results
        assert "Millénium 2 : La Fille qui rêvait" in results
        assert "Millénium 3 : La Reine" in results
        # Millennium Actress (2 N) : match aussi car 'millenium' ⊂ 'millennium'
        # via un des variants ? Non : 'millenium' n'est pas dans 'millennium'.
        # Vérifions juste qu'il n'y a pas Batman
        assert "Batman" not in results

    def test_ligatures_still_work_in_search(self, session):
        """Non-régression ligatures : Oeuvre trouve Œuvre."""
        _add_movie(session, "L'Œuvre", 42)
        results = _search_titles(session, "Oeuvre")
        assert "L'Œuvre" in results

    def test_ligatures_and_accents_combined(self, session):
        """Ligature + accent : cœur trouvé par 'coeur' et 'Coeur'."""
        _add_movie(session, "Plein Cœur", 10)
        r1 = _search_titles(session, "coeur")
        r2 = _search_titles(session, "Cœur")
        assert "Plein Cœur" in r1
        assert "Plein Cœur" in r2

    def test_ascii_titles_unchanged(self, session):
        """Sanity : recherche ASCII continue de fonctionner."""
        _add_movie(session, "Batman", 1)
        _add_movie(session, "Superman", 2)
        results = _search_titles(session, "Batman")
        assert "Batman" in results
        assert "Superman" not in results

    def test_case_insensitive_preserved(self, session):
        """LIKE SQLite est case-insensitive ASCII — garder ce comportement."""
        _add_movie(session, "Millénium", 15472)
        r_upper = _search_titles(session, "MILLENIUM")
        r_lower = _search_titles(session, "millenium")
        assert "Millénium" in r_upper
        assert "Millénium" in r_lower

    def test_series_also_work(self, session):
        """Le filtre fonctionne aussi sur SeriesModel."""
        s = SeriesModel(title="Séries à la mode", year=2020, tvdb_id=1)
        session.add(s)
        session.commit()
        filt = _title_search_filter(SeriesModel, "series")
        results = session.exec(select(SeriesModel).where(filt)).all()
        assert any(r.title == "Séries à la mode" for r in results)


# ─── Extended search (overview) ───────────────────────────────────────────


class TestExtendedSearch:
    def test_unaccented_query_matches_accented_overview(self, session):
        m = MovieModel(
            title="Le Film",
            year=2020,
            tmdb_id=1,
            overview="Un film à propos d'une héroïne.",
        )
        session.add(m)
        session.commit()
        filt = _title_search_filter(MovieModel, "heroine", extended=True)
        results = session.exec(select(MovieModel).where(filt)).all()
        assert len(results) == 1
