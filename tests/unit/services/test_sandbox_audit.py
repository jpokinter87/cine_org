"""
Tests pour SandboxAuditor — vérification qu'un fichier sandboxé a bien
un remplaçant légitime dans la vidéothèque avant toute suppression.
"""

import os

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    SeriesModel,
)
from src.services.sandbox_audit import (
    MISSING,
    REPLACED,
    UNKNOWN,
    SandboxAuditor,
)


@pytest.fixture
def session():
    """Session SQLModel en mémoire."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def arbo(tmp_path):
    """Arborescence sandbox + storage de test."""
    sandbox = tmp_path / ".sandbox"
    storage = tmp_path / "storage"
    sandbox.mkdir()
    storage.mkdir()
    return sandbox, storage


def _fichier(base, relatif: str, taille: int = 1024):
    """Crée un fichier de test et retourne son chemin."""
    p = base / relatif
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * taille)
    return p


def _serie(session, titre: str, annee: int | None = None) -> SeriesModel:
    s = SeriesModel(title=titre, year=annee)
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


class TestRemplacantSerie:
    """Résolution du remplaçant pour un épisode de série."""

    def test_remplacant_present_purge_sure(self, session, arbo):
        sandbox, storage = arbo
        remplacant = _fichier(storage, "Series/Utopia (2020)/S01E03 - v2.mkv")
        serie = _serie(session, "Utopia", 2020)
        session.add(
            EpisodeModel(
                series_id=serie.id,
                season_number=1,
                episode_number=3,
                title="Episode 3",
                file_path=str(remplacant),
            )
        )
        session.commit()

        vieux = _fichier(
            sandbox,
            "Series/TV/U-Z/Utopia (2020)/Saison 01/Utopia (2020) - S01E03 - x.mkv",
        )
        audit = SandboxAuditor(session, sandbox).audit(vieux)

        assert audit.status == REPLACED
        assert audit.replacement_path == remplacant
        assert audit.reclaimable_bytes == 1024

    def test_fiche_pointant_vers_un_fichier_disparu(self, session, arbo):
        """Cas Utopia : la fiche existe mais le fichier storage a disparu."""
        sandbox, storage = arbo
        serie = _serie(session, "Utopia", 2020)
        session.add(
            EpisodeModel(
                series_id=serie.id,
                season_number=1,
                episode_number=3,
                title="Episode 3",
                file_path=str(storage / "Series/disparu.mkv"),
            )
        )
        session.commit()

        vieux = _fichier(
            sandbox,
            "Series/TV/U-Z/Utopia (2020)/Saison 01/Utopia (2020) - S01E03 - x.mkv",
        )
        audit = SandboxAuditor(session, sandbox).audit(vieux)

        assert audit.status == MISSING
        assert audit.replacement_path is None

    def test_aucune_fiche_en_base(self, session, arbo):
        sandbox, _ = arbo
        vieux = _fichier(
            sandbox, "Series/TV/I-K/Inconnue (2020)/Saison 01/Inconnue - S01E01 - x.mkv"
        )
        assert SandboxAuditor(session, sandbox).audit(vieux).status == MISSING

    def test_serie_sans_annee_dans_le_dossier(self, session, arbo):
        """Le dossier « The Killing » doit matcher la fiche « The Killing »."""
        sandbox, storage = arbo
        remplacant = _fichier(storage, "Series/The Killing/S01E01.mkv")
        serie = _serie(session, "The Killing", 2007)
        session.add(
            EpisodeModel(
                series_id=serie.id,
                season_number=1,
                episode_number=1,
                title="Episode 1",
                file_path=str(remplacant),
            )
        )
        session.commit()

        vieux = _fichier(
            sandbox, "Series/TV/I-K/The Killing/Saison 1/The.Killing.S01E01.mkv"
        )
        assert SandboxAuditor(session, sandbox).audit(vieux).status == REPLACED

    def test_accents_normalises(self, session, arbo):
        sandbox, storage = arbo
        remplacant = _fichier(storage, "Series/Elite/S01E01.mkv")
        serie = _serie(session, "Élite", 2018)
        session.add(
            EpisodeModel(
                series_id=serie.id,
                season_number=1,
                episode_number=1,
                title="Episode 1",
                file_path=str(remplacant),
            )
        )
        session.commit()

        vieux = _fichier(
            sandbox, "Series/TV/E/Elite (2018)/Saison 01/Elite - S01E01 - x.mkv"
        )
        assert SandboxAuditor(session, sandbox).audit(vieux).status == REPLACED


class TestMultiEpisodes:
    """Un fichier couvrant plusieurs épisodes doit être résolu via episode_end."""

    def test_plage_couverte_par_episode_end(self, session, arbo):
        sandbox, storage = arbo
        remplacant = _fichier(storage, "Series/Kaamelott/S05E01-E06.mkv")
        serie = _serie(session, "Kaamelott", 2005)
        session.add(
            EpisodeModel(
                series_id=serie.id,
                season_number=5,
                episode_number=1,
                episode_end=6,
                title="Corvus",
                file_path=str(remplacant),
            )
        )
        session.commit()

        vieux = _fichier(
            sandbox,
            "Series/TV/I-K/Kaamelott/Saison 5/Kaamelott - s05e01-e06 - Corvus.mkv",
        )
        assert SandboxAuditor(session, sandbox).audit(vieux).status == REPLACED

    def test_plage_non_couverte(self, session, arbo):
        sandbox, storage = arbo
        remplacant = _fichier(storage, "Series/Kaamelott/S05E01.mkv")
        serie = _serie(session, "Kaamelott", 2005)
        session.add(
            EpisodeModel(
                series_id=serie.id,
                season_number=5,
                episode_number=1,
                title="Episode 1",
                file_path=str(remplacant),
            )
        )
        session.commit()

        vieux = _fichier(
            sandbox,
            "Series/TV/I-K/Kaamelott/Saison 5/Kaamelott - s05e01-e06 - Corvus.mkv",
        )
        assert SandboxAuditor(session, sandbox).audit(vieux).status == MISSING


class TestFilms:
    """Résolution du remplaçant pour un film."""

    def test_film_remplace(self, session, arbo):
        sandbox, storage = arbo
        remplacant = _fichier(storage, "Films/Avatar (2009).mkv")
        session.add(MovieModel(title="Avatar", year=2009, file_path=str(remplacant)))
        session.commit()

        vieux = _fichier(sandbox, "Films/SF/A/Avatar (2009) - FR x264 1080p.mkv")
        assert SandboxAuditor(session, sandbox).audit(vieux).status == REPLACED

    def test_film_sans_remplacant(self, session, arbo):
        sandbox, _ = arbo
        vieux = _fichier(sandbox, "Films/SF/A/Alien (1979) - FR x264 1080p.mkv")
        assert SandboxAuditor(session, sandbox).audit(vieux).status == MISSING


class TestCasNonEvaluables:
    """Ce qui ne peut pas être tranché doit être signalé, pas supposé sûr."""

    def test_fichier_non_video(self, session, arbo):
        sandbox, _ = arbo
        p = _fichier(sandbox, "dedup_manifest.json")
        assert SandboxAuditor(session, sandbox).audit(p).status == UNKNOWN

    def test_nommage_hors_schema(self, session, arbo):
        sandbox, _ = arbo
        p = _fichier(sandbox, "Series/divers/bonus-making-of.mkv")
        assert SandboxAuditor(session, sandbox).audit(p).status == UNKNOWN


class TestEspaceRecuperable:
    """Un fichier partageant son inode ne libère pas d'espace."""

    def test_hardlink_signale_et_sans_gain(self, session, arbo):
        sandbox, storage = arbo
        remplacant = _fichier(storage, "Series/Bodies (2004)/S01E01.mkv", taille=2048)
        serie = _serie(session, "Bodies", 2004)
        session.add(
            EpisodeModel(
                series_id=serie.id,
                season_number=1,
                episode_number=1,
                title="Episode 1",
                file_path=str(remplacant),
            )
        )
        session.commit()

        vieux = sandbox / "Series/TV/B/Bodies (2004)/Saison 01/Bodies - S01E01 - x.mkv"
        vieux.parent.mkdir(parents=True, exist_ok=True)
        os.link(remplacant, vieux)  # même inode que le fichier vivant

        audit = SandboxAuditor(session, sandbox).audit(vieux)
        assert audit.status == REPLACED
        assert audit.shares_inode is True
        assert audit.reclaimable_bytes == 0
