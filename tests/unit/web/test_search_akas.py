"""
Tests de la recherche par titre alternatif (akas IMDb).

Contexte : certaines fiches stockent un `title` dans la langue originale
(ex. « The Man in the High Castle ») alors que l'utilisateur cherche par titre
localisé (ex. « Le Maître du Haut-Château »). Le titre localisé n'existe pas dans
la table `series`/`movies`, mais il figure dans la table `imdb_akas` (titres
alternatifs IMDb, toutes régions) rattaché au même `imdb_id`.

Couvre :
- `_title_search_filter(..., include_akas=True)` matche via imdb_akas (toutes régions)
- include_akas désactivé : pas de match sur le titre alternatif
- `_akas_table_exists` : détection de la présence de la table (bases anciennes)
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

# Import database.py pour activer l'UDF unaccent (listener connect)
from src.infrastructure.persistence import database as _db_module  # noqa: F401
from src.infrastructure.persistence.models import MovieModel, SeriesModel
from src.web.routes.library.helpers import (
    _akas_table_exists,
    _matched_french_aliases,
    _title_search_filter,
)


def _create_akas_table(session: Session) -> None:
    """Crée la table imdb_akas hors ORM (pas de modèle SQLModel)."""
    session.exec(
        text(
            "CREATE TABLE imdb_akas (id INTEGER PRIMARY KEY, tconst VARCHAR, "
            "title VARCHAR, title_normalized VARCHAR, region VARCHAR, language VARCHAR)"
        )
    )
    session.commit()


def _add_aka(
    session: Session,
    _id: int,
    tconst: str,
    title: str,
    region: str,
    language: str = "",
) -> None:
    """Insère une ligne aka (title_normalized = accents retirés + minuscules)."""
    from src.utils.helpers import normalize_accents

    normalized = normalize_accents(title).lower().strip()
    session.exec(
        text(
            "INSERT INTO imdb_akas (id, tconst, title, title_normalized, region, language) "
            "VALUES (:i, :t, :ti, :tn, :r, :l)"
        ),
        params={
            "i": _id,
            "t": tconst,
            "ti": title,
            "tn": normalized,
            "r": region,
            "l": language,
        },
    )
    session.commit()


@pytest.fixture
def engine():
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


@pytest.fixture
def session_with_akas(session):
    """Session avec table imdb_akas + une série anglophone et ses akas."""
    _create_akas_table(session)
    # Série stockée avec le titre original anglais uniquement
    series = SeriesModel(
        title="The Man in the High Castle",
        original_title="The Man in the High Castle",
        year=2015,
        imdb_id="tt1740299",
        tmdb_id=62017,
    )
    session.add(series)
    session.commit()
    # Titres alternatifs IMDb, plusieurs régions
    _add_aka(session, 1, "tt1740299", "Le Maître du Haut Château", "FR")
    _add_aka(session, 2, "tt1740299", "El hombre en el castillo", "ES")
    _add_aka(session, 3, "tt1740299", "The Man in the High Castle", "US")
    # Aka d'une autre œuvre (ne doit pas polluer)
    _add_aka(session, 4, "tt0000001", "Autre Titre", "FR")
    return session


def _search(session, query, model_class=SeriesModel, include_akas=True):
    filt = _title_search_filter(model_class, query, include_akas=include_akas)
    return [r.title for r in session.exec(select(model_class).where(filt)).all()]


class TestSearchViaAkas:
    def test_french_title_finds_series(self, session_with_akas):
        """Cœur du bug : le titre français localisé trouve la série anglophone."""
        results = _search(session_with_akas, "Le Maître du Haut-Château")
        assert "The Man in the High Castle" in results

    def test_french_title_partial_match(self, session_with_akas):
        """Recherche partielle (substring) sur le titre français."""
        results = _search(session_with_akas, "haut château")
        assert "The Man in the High Castle" in results

    def test_spanish_title_finds_series(self, session_with_akas):
        """Toutes régions : un titre espagnol trouve aussi la série."""
        results = _search(session_with_akas, "el hombre en el castillo")
        assert "The Man in the High Castle" in results

    def test_unaccented_query_finds_accented_aka(self, session_with_akas):
        """Query sans accent matche l'aka accentué (insensible aux accents)."""
        results = _search(session_with_akas, "maitre du haut chateau")
        assert "The Man in the High Castle" in results

    def test_disabled_akas_does_not_match_localized_title(self, session_with_akas):
        """include_akas=False : le titre français reste introuvable."""
        results = _search(
            session_with_akas, "Le Maître du Haut-Château", include_akas=False
        )
        assert results == []

    def test_original_title_still_found_without_akas(self, session_with_akas):
        """Non-régression : le titre stocké reste trouvable sans les akas."""
        results = _search(session_with_akas, "high castle", include_akas=False)
        assert "The Man in the High Castle" in results

    def test_unrelated_aka_does_not_match(self, session_with_akas):
        """L'aka d'une autre œuvre (autre tconst) ne ramène pas la série."""
        results = _search(session_with_akas, "Autre Titre")
        assert results == []


class TestMatchedFrenchAliases:
    def test_returns_french_alias_matching_query(self, session_with_akas):
        """Retourne l'alias français qui a déclenché le match."""
        aliases = _matched_french_aliases(
            session_with_akas, ["tt1740299"], "haut château"
        )
        assert aliases == {"tt1740299": "Le Maître du Haut Château"}

    def test_prefers_region_fr_over_other_french(self, session):
        """Préférence : region='FR' devant un language='fr' (ex. CA-fr)."""
        _create_akas_table(session)
        _add_aka(session, 1, "tt1", "Le maître canadien", "CA", "fr")
        _add_aka(session, 2, "tt1", "Le maître de France", "FR", "")
        aliases = _matched_french_aliases(session, ["tt1"], "maitre")
        assert aliases["tt1"] == "Le maître de France"

    def test_falls_back_to_any_match_when_no_french(self, session):
        """Sans alias français, on explique quand même via l'alias matchant."""
        _create_akas_table(session)
        _add_aka(session, 1, "tt1", "El maestro español", "ES", "es")
        aliases = _matched_french_aliases(session, ["tt1"], "maestro")
        assert aliases["tt1"] == "El maestro español"

    def test_non_matching_tconst_absent(self, session_with_akas):
        """Un tconst dont aucun alias ne matche n'apparaît pas."""
        aliases = _matched_french_aliases(
            session_with_akas, ["tt1740299"], "introuvable xyz"
        )
        assert "tt1740299" not in aliases

    def test_empty_inputs_return_empty(self, session_with_akas):
        assert _matched_french_aliases(session_with_akas, [], "maitre") == {}
        assert _matched_french_aliases(session_with_akas, ["tt1740299"], "") == {}

    def test_missing_table_returns_empty(self, session):
        """Base ancienne sans imdb_akas : pas d'erreur, dict vide."""
        assert _matched_french_aliases(session, ["tt1"], "maitre") == {}


class TestAkasTableExists:
    def test_returns_true_when_table_present(self, session_with_akas):
        assert _akas_table_exists(session_with_akas) is True

    def test_returns_false_when_table_absent(self, session):
        """Base ancienne sans imdb_akas : détection négative, pas d'erreur."""
        assert _akas_table_exists(session) is False

    def test_filter_with_akas_works_on_movies(self, session):
        """Le filtre akas s'applique aussi aux films (MovieModel.imdb_id)."""
        _create_akas_table(session)
        movie = MovieModel(title="Original English Movie", year=2000, imdb_id="tt9999")
        session.add(movie)
        session.commit()
        _add_aka(session, 1, "tt9999", "Titre Français du Film", "FR")
        results = _search(session, "Titre Français", model_class=MovieModel)
        assert "Original English Movie" in results
