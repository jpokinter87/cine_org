"""
Tests pour l'import et la recherche des akas IMDb.

Verifie le flux complet : parse_akas → import_akas (avec filtres) →
search_akas (lookup normalisé). Utilise une vraie DB SQLite in-memory
pour valider l'intégration parser + ORM.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.adapters.imdb.dataset_importer import (
    IMDbDatasetImporter,
)
from src.adapters.imdb.tsv_parser import TSVParser
from src.infrastructure.persistence.models import IMDbAkaModel


_AKAS_HEADER = (
    "titleId\tordering\ttitle\tregion\tlanguage\ttypes\tattributes\tisOriginalTitle"
)


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def sample_akas_file(tmp_path) -> Path:
    """Echantillon d'akas couvrant : titre fr avec accents, langue, region,
    ligne \\N partout, ligne hors filtre, ligne en anglais."""
    p = tmp_path / "title.akas.tsv"
    lines = [
        _AKAS_HEADER,
        # tt0082416 : The French Lieutenant's Woman — original anglais
        "tt0082416\t1\tThe French Lieutenant's Woman\t\\N\t\\N\toriginal\t\\N\t1",
        # variante fr avec accents
        "tt0082416\t2\tLa Maîtresse du lieutenant français\tFR\tfr\timdbDisplay\t\\N\t0",
        # variante US sans language
        "tt0082416\t3\tThe French Lieutenant's Woman\tUS\t\\N\timdbDisplay\t\\N\t0",
        # variante japonaise (filtrée gardée car ja in DEFAULT)
        "tt0082416\t4\tフランス軍中尉の女\tJP\tja\t\\N\t\\N\t0",
        # variante en latin (langue exotique non listée + region non listée)
        "tt0082416\t5\tFeminae Lugentis\tVA\tla\t\\N\t\\N\t0",
        # Autre film, variante fr
        "tt9999999\t1\tLe Truc\tFR\tfr\t\\N\t\\N\t0",
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# ---- TSVParser.parse_akas -------------------------------------------------


def test_parse_akas_yields_expected_fields(sample_akas_file):
    parser = TSVParser()
    rows = list(parser.parse_akas(sample_akas_file))
    assert len(rows) == 6
    first = rows[0]
    assert first["tconst"] == "tt0082416"
    assert first["title"] == "The French Lieutenant's Woman"
    assert first["region"] is None  # \\N
    assert first["language"] is None  # \\N


def test_parse_akas_decodes_unicode_titles(sample_akas_file):
    parser = TSVParser()
    rows = list(parser.parse_akas(sample_akas_file))
    fr = next(r for r in rows if r["language"] == "fr")
    assert fr["title"] == "La Maîtresse du lieutenant français"


# ---- IMDbDatasetImporter.import_akas + search_akas -----------------------


def test_import_akas_filters_by_language_and_region(session, tmp_path, sample_akas_file):
    importer = IMDbDatasetImporter(cache_dir=tmp_path / "cache", session=session)
    stats = importer.import_akas(sample_akas_file)

    # 6 lignes totales ; les 5 utiles + la latine skippée.
    assert stats.total == 6
    # Imported : original (region=\\N + lang=\\N) → skip
    #            fr (FR/fr) → keep
    #            US (region=US, lang=\\N) → keep via region
    #            ja (JP/ja) → keep
    #            latin (VA/la) → skip
    #            Le Truc (FR/fr) → keep
    assert stats.imported == 4
    assert stats.skipped == 2


def test_import_akas_purges_existing_records(session, tmp_path, sample_akas_file):
    """Un 2e import full-refresh : la table est vidée avant insertion."""
    importer = IMDbDatasetImporter(cache_dir=tmp_path / "cache", session=session)
    importer.import_akas(sample_akas_file)
    first_count = importer.get_akas_stats()["count"]
    # Re-import même fichier → même count (pas de doublons accumulés)
    importer.import_akas(sample_akas_file)
    assert importer.get_akas_stats()["count"] == first_count


def test_search_akas_finds_tconst_from_french_title_with_accents(
    session, tmp_path, sample_akas_file
):
    """Le scénario qui motive cette feature."""
    importer = IMDbDatasetImporter(cache_dir=tmp_path / "cache", session=session)
    importer.import_akas(sample_akas_file)

    # Query sans accents et lowercase — doit matcher quand même.
    tconsts = importer.search_akas("la maitresse du lieutenant francais")
    assert tconsts == ["tt0082416"]


def test_search_akas_finds_tconst_from_japanese_title(
    session, tmp_path, sample_akas_file
):
    importer = IMDbDatasetImporter(cache_dir=tmp_path / "cache", session=session)
    importer.import_akas(sample_akas_file)

    tconsts = importer.search_akas("フランス軍中尉の女")
    assert tconsts == ["tt0082416"]


def test_search_akas_returns_empty_for_unknown_title(
    session, tmp_path, sample_akas_file
):
    importer = IMDbDatasetImporter(cache_dir=tmp_path / "cache", session=session)
    importer.import_akas(sample_akas_file)
    assert importer.search_akas("Film Imaginaire 2099") == []


def test_search_akas_returns_empty_for_blank_query(session, tmp_path):
    importer = IMDbDatasetImporter(cache_dir=tmp_path / "cache", session=session)
    assert importer.search_akas("") == []
    assert importer.search_akas("   ") == []


def test_search_akas_ranks_tconst_by_aka_frequency(session, tmp_path):
    """Plus un tconst a de variantes matchant la query, plus il est haut."""
    importer = IMDbDatasetImporter(cache_dir=tmp_path / "cache", session=session)
    # 2 tconst partagent un même titre normalisé ; le 2e a 3 entrées vs 1.
    for tconst, n in [("tt111", 1), ("tt222", 3)]:
        for i in range(n):
            session.add(
                IMDbAkaModel(
                    tconst=tconst,
                    title="Title",
                    title_normalized="title",
                    region="FR",
                    language="fr",
                )
            )
    session.commit()

    tconsts = importer.search_akas("title")
    assert tconsts == ["tt222", "tt111"]


def test_import_akas_keeps_session_identity_map_empty(
    session, tmp_path, sample_akas_file
):
    """Anti-régression OOM : l'import ne doit JAMAIS accumuler des objets
    ORM dans la session (Identity Map). Avec 5-8M lignes, ça suffit à
    OOM la machine. Le fix : utiliser session.execute(insert(table), batch)
    direct au lieu de session.add(Model(...))."""
    importer = IMDbDatasetImporter(cache_dir=tmp_path / "cache", session=session)
    importer.import_akas(sample_akas_file)

    # `session.new` = objets ORM en attente d'INSERT.
    # `session.identity_map` = objets ORM connus de la session.
    assert len(session.new) == 0
    # L'Identity Map doit être quasi-vide (juste les éventuels objets
    # tirés par les requêtes de test précédentes, mais aucun IMDbAkaModel
    # créé par l'import).
    from src.infrastructure.persistence.models import IMDbAkaModel
    aka_in_map = sum(
        1 for obj in session.identity_map.values()
        if isinstance(obj, IMDbAkaModel)
    )
    assert aka_in_map == 0


def test_import_akas_calls_on_progress_per_batch(
    session, tmp_path, sample_akas_file
):
    """Le callback on_progress est invoqué après chaque batch (essentiel
    pour le feedback CLI sur un import de plusieurs millions de lignes)."""
    importer = IMDbDatasetImporter(cache_dir=tmp_path / "cache", session=session)

    ticks: list[int] = []

    def _on_progress(stats):
        ticks.append(stats.imported)

    # batch_size=1 force un callback par ligne pour pouvoir compter.
    importer.import_akas(
        sample_akas_file, batch_size=1, on_progress=_on_progress
    )
    # 4 lignes importées → 4 ticks (le batch final n'est pas dupliqué
    # quand il vient de se vider exactement).
    assert len(ticks) == 4
    assert ticks == [1, 2, 3, 4]


def test_get_akas_stats_returns_counts(session, tmp_path, sample_akas_file):
    importer = IMDbDatasetImporter(cache_dir=tmp_path / "cache", session=session)
    importer.import_akas(sample_akas_file)
    stats = importer.get_akas_stats()
    assert stats["count"] == 4
    # tt0082416 (3 akas gardées) + tt9999999 (1) = 2 tconst uniques
    assert stats["unique_tconsts"] == 2
