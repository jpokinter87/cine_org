"""Tests du réalignement des fichiers d'une série sur sa fiche canonique.

Après une ré-association, la fiche porte le bon titre/année mais les fichiers
et symlinks gardent ceux de l'ancienne association (dossier « Found (2017) »,
titres d'épisodes du documentaire). Ce service les réaligne.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.core.value_objects.media_info import (
    AudioCodec,
    Language,
    MediaInfo,
    Resolution,
    VideoCodec,
)
from src.infrastructure.persistence.models import EpisodeModel, SeriesModel
from src.services.series_renamer import SeriesRenamer

OLD_FOLDER = "Found (2017)"
OLD_FILE = "Found (2017) - S01E01 - Weapons of Mass Deduction - MULTi x264 1080p.mkv"
NEW_FOLDER = "Found - Les Oubliés (2023)"
NEW_PREFIX = "Found - Les Oubliés (2023) - S01E01 - Disparition - une fugueuse"


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def extractor():
    ext = MagicMock()
    ext.extract.return_value = MediaInfo(
        resolution=Resolution(width=1920, height=1080),
        video_codec=VideoCodec(name="x264"),
        audio_codecs=(AudioCodec(name="AC3"),),
        audio_languages=(Language(code="fr", name="Francais"),),
        duration_seconds=2580,
    )
    return ext


@pytest.fixture
def tree(tmp_path):
    """Arborescence storage/video avec un épisode déjà transféré."""
    storage_season = tmp_path / "storage" / "Series" / OLD_FOLDER / "Saison 01"
    video_season = tmp_path / "video" / "Series" / OLD_FOLDER / "Saison 01"
    storage_season.mkdir(parents=True)
    video_season.mkdir(parents=True)

    storage_file = storage_season / OLD_FILE
    storage_file.write_bytes(b"video")
    symlink = video_season / OLD_FILE
    symlink.symlink_to(storage_file)

    return {"storage": storage_file, "symlink": symlink, "root": tmp_path}


def _seed(session: Session, tree, *, episode_title="Disparition : une fugueuse"):
    """Fiche corrigée (2023) pointant encore sur les fichiers « Found (2017) »."""
    series = SeriesModel(title="Found : Les Oubliés", year=2023, tvdb_id=423102)
    session.add(series)
    session.commit()
    session.refresh(series)
    episode = EpisodeModel(
        series_id=series.id,
        season_number=1,
        episode_number=1,
        title=episode_title,
        file_path=str(tree["storage"]),
        symlink_path=str(tree["symlink"]),
    )
    session.add(episode)
    session.commit()
    session.refresh(episode)
    return series, episode


def test_renomme_dossier_fichier_et_symlink(session, extractor, tree):
    """Le dossier série, le fichier storage et le symlink suivent la fiche."""
    series, episode = _seed(session, tree)

    outcomes = SeriesRenamer(session, extractor).rename_series(series.id, dry_run=False)

    assert [o.status for o in outcomes] == ["renamed"]

    new_storage = Path(episode.file_path)
    new_symlink = Path(episode.symlink_path)

    assert new_storage.parent.parent.name == NEW_FOLDER
    assert new_symlink.parent.parent.name == NEW_FOLDER
    assert new_storage.name.startswith(NEW_PREFIX)
    assert new_storage.suffix == ".mkv"
    assert new_storage.exists()
    assert new_symlink.is_symlink()
    assert new_symlink.resolve() == new_storage.resolve()
    assert not (tree["root"] / "storage" / "Series" / OLD_FOLDER).exists()
    assert not (tree["root"] / "video" / "Series" / OLD_FOLDER).exists()


def test_dry_run_annonce_sans_rien_modifier(session, extractor, tree):
    """Le dry-run décrit le renommage mais laisse disque et base intacts."""
    series, episode = _seed(session, tree)

    outcomes = SeriesRenamer(session, extractor).rename_series(series.id)

    assert outcomes[0].status == "renamed"
    assert outcomes[0].new_name.startswith(NEW_PREFIX)
    assert tree["storage"].exists()
    assert tree["symlink"].is_symlink()
    assert episode.file_path == str(tree["storage"])


def test_fichier_deja_canonique_est_ignore(session, extractor, tmp_path):
    """Rien à faire quand les noms correspondent déjà à la fiche."""
    season = tmp_path / "storage" / "Series" / NEW_FOLDER / "Saison 01"
    season.mkdir(parents=True)
    series = SeriesModel(title="Found : Les Oubliés", year=2023)
    session.add(series)
    session.commit()
    session.refresh(series)

    canonical = season / f"{NEW_PREFIX} - FR x264 1080p.mkv"
    canonical.write_bytes(b"video")
    session.add(
        EpisodeModel(
            series_id=series.id,
            season_number=1,
            episode_number=1,
            title="Disparition : une fugueuse",
            file_path=str(canonical),
        )
    )
    session.commit()

    outcomes = SeriesRenamer(session, extractor).rename_series(series.id, dry_run=False)

    assert [o.status for o in outcomes] == ["already_canonical"]
    assert canonical.exists()


def test_fichier_absent_est_signale(session, extractor, tree):
    """Un fichier disparu du storage est signalé, pas renommé."""
    series, episode = _seed(session, tree)
    tree["storage"].unlink()

    outcomes = SeriesRenamer(session, extractor).rename_series(series.id, dry_run=False)

    assert [o.status for o in outcomes] == ["file_missing"]


def test_dossier_cible_existant_renomme_les_fichiers_sur_place(
    session, extractor, tree
):
    """Si le dossier canonique existe déjà, on renomme sans déplacer le dossier."""
    series, episode = _seed(session, tree)
    (tree["root"] / "storage" / "Series" / NEW_FOLDER).mkdir(parents=True)

    outcomes = SeriesRenamer(session, extractor).rename_series(series.id, dry_run=False)

    assert [o.status for o in outcomes] == ["renamed"]
    new_storage = Path(episode.file_path)
    assert new_storage.parent.parent.name == OLD_FOLDER
    assert new_storage.name.startswith(NEW_PREFIX)
    assert new_storage.exists()


def test_une_panne_de_renommage_ne_casse_pas_la_reassociation(
    session, extractor, tree, monkeypatch
):
    """Le réalignement est best-effort : une erreur disque reste sans effet visible."""
    from src.web.routes.library import reassociate

    series, _ = _seed(session, tree)

    def _boom(*args, **kwargs):
        raise OSError("NAS injoignable")

    monkeypatch.setattr(SeriesRenamer, "rename_series", _boom)

    assert reassociate._rename_series_files(session, series, extractor) == 0


def test_serie_sans_fichier_ne_produit_aucun_resultat(session, extractor):
    """Une fiche sans épisode sur disque ne déclenche aucune opération."""
    series = SeriesModel(title="Found : Les Oubliés", year=2023)
    session.add(series)
    session.commit()
    session.refresh(series)
    session.add(
        EpisodeModel(series_id=series.id, season_number=1, episode_number=1, title="E1")
    )
    session.commit()

    assert SeriesRenamer(session, extractor).rename_series(series.id) == []


def test_saison_corrigee_deplace_le_fichier_dans_le_bon_dossier(
    session, extractor, tree
):
    """Un numéro de saison corrigé en base déplace fichier et symlink.

    Cas réel : les cours d'anime livrés en S01/S02/S03 par les teams sont
    réalignés sur la saison canonique du fournisseur (Bleach TYBW → saison 17).
    """
    series, episode = _seed(session, tree)
    episode.season_number = 17
    episode.episode_number = 3
    session.add(episode)
    session.commit()

    outcomes = SeriesRenamer(session, extractor).rename_series(series.id, dry_run=False)

    assert [o.status for o in outcomes] == ["renamed"]

    new_storage = Path(episode.file_path)
    new_symlink = Path(episode.symlink_path)

    assert new_storage.parent.name == "Saison 17"
    assert new_symlink.parent.name == "Saison 17"
    assert "S17E03" in new_storage.name
    assert new_storage.exists()
    assert new_symlink.is_symlink()
    assert new_symlink.resolve() == new_storage.resolve()
    assert not tree["storage"].exists()


def test_dossier_de_saison_vide_est_supprime(session, extractor, tmp_path):
    """Le dossier de saison quitté est retiré une fois vidé.

    Le dossier de série ne bouge pas ici : seul le numéro de saison change.
    """
    storage_season = tmp_path / "storage" / "Series" / NEW_FOLDER / "Saison 01"
    video_season = tmp_path / "video" / "Series" / NEW_FOLDER / "Saison 01"
    storage_season.mkdir(parents=True)
    video_season.mkdir(parents=True)
    storage_file = storage_season / "ancien.mkv"
    storage_file.write_bytes(b"video")
    symlink = video_season / "ancien.mkv"
    symlink.symlink_to(storage_file)

    series = SeriesModel(title="Found : Les Oubliés", year=2023)
    session.add(series)
    session.commit()
    session.refresh(series)
    episode = EpisodeModel(
        series_id=series.id,
        season_number=17,
        episode_number=1,
        title="Disparition : une fugueuse",
        file_path=str(storage_file),
        symlink_path=str(symlink),
    )
    session.add(episode)
    session.commit()
    session.refresh(episode)

    SeriesRenamer(session, extractor).rename_series(series.id, dry_run=False)

    assert Path(episode.file_path).parent.name == "Saison 17"
    assert not storage_season.exists()
    assert not video_season.exists()
