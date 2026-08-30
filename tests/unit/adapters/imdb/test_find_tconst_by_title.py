"""Tests pour IMDbDatasetImporter.find_tconst_by_title.

Repli quand TMDB ne fournit pas d'imdb_id : on retrouve le tconst via la table
locale imdb_akas (titres alternatifs IMDb), avec garde-fou anti-homonymes.
"""

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from src.adapters.imdb.dataset_importer import IMDbDatasetImporter


@pytest.fixture
def session_with_akas():
    """Session en mémoire avec une table imdb_akas peuplée (hors ORM)."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    s = Session(engine)
    s.exec(
        text(
            "CREATE TABLE imdb_akas (id INTEGER PRIMARY KEY, tconst VARCHAR, "
            "title VARCHAR, title_normalized VARCHAR, region VARCHAR, language VARCHAR)"
        )
    )
    rows = [
        (
            "tt14131062",
            "Félix, Maude et la fin du monde",
            "felix, maude et la fin du monde",
            "CA",
        ),
        (
            "tt14131062",
            "Felix, Maude and the End of the World",
            "felix, maude and the end of the world",
            "XWW",
        ),
        ("tt0067185", "Harold et Maude", "harold et maude", "FR"),
        # Homonyme volontaire : deux tconst distincts pour le meme titre
        ("tt1111111", "Doublon", "doublon", "US"),
        ("tt2222222", "Doublon", "doublon", "FR"),
    ]
    for i, (tconst, title, tn, region) in enumerate(rows, 1):
        s.exec(
            text(
                "INSERT INTO imdb_akas (id, tconst, title, title_normalized, region) "
                "VALUES (:i, :t, :ti, :tn, :r)"
            ),
            params={"i": i, "t": tconst, "ti": title, "tn": tn, "r": region},
        )
    s.commit()
    return s


@pytest.fixture
def importer(session_with_akas):
    return IMDbDatasetImporter(
        cache_dir=Path("/tmp/test_imdb"), session=session_with_akas
    )


def test_trouve_tconst_par_titre_exact(importer):
    """Titre exact -> tconst unique."""
    assert (
        importer.find_tconst_by_title("Félix, Maude et la fin du monde") == "tt14131062"
    )


def test_insensible_a_la_casse_et_aux_accents(importer):
    """Recherche insensible casse/accents via title_normalized."""
    assert (
        importer.find_tconst_by_title("felix, maude et la fin du monde") == "tt14131062"
    )
    assert (
        importer.find_tconst_by_title("FELIX, MAUDE ET LA FIN DU MONDE") == "tt14131062"
    )


def test_titre_original_anglais(importer):
    """Le titre original (autre aka du meme tconst) marche aussi."""
    assert (
        importer.find_tconst_by_title("Felix, Maude and the End of the World")
        == "tt14131062"
    )


def test_abstention_si_homonyme(importer):
    """Plusieurs tconst distincts pour le meme titre -> None (pas de devinette)."""
    assert importer.find_tconst_by_title("Doublon") is None


def test_none_si_introuvable(importer):
    """Titre absent -> None."""
    assert importer.find_tconst_by_title("Titre Inexistant 12345") is None


def test_none_si_table_absente():
    """Si imdb_akas n'existe pas (vieilles bases), renvoie None sans planter."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    imp = IMDbDatasetImporter(cache_dir=Path("/tmp/test_imdb"), session=Session(engine))
    assert imp.find_tconst_by_title("Quoi que ce soit") is None
