"""
Tests du filtrage des racines gérées par CineOrg.

storage_dir et video_dir hébergent bien plus que la vidéothèque (musique,
contenus éducatifs, documents…). Les balayages doivent se limiter aux
sous-répertoires gérés, sans quoi ils perdent du temps et remontent des
anomalies sur des contenus qui ne concernent pas l'application.
"""


import pytest

from src.utils.constants import MANAGED_SUBDIRS
from src.utils.helpers import managed_roots


@pytest.fixture
def racine(tmp_path):
    """Racine mêlant vidéothèque gérée et contenus étrangers."""
    for d in ("Films", "Series", "Musique", "Éducatif", "Assmat", ".sandbox", "temp"):
        (tmp_path / d).mkdir()
    return tmp_path


def test_ne_retient_que_les_dossiers_geres(racine):
    assert managed_roots(racine) == [racine / "Films", racine / "Series"]


def test_ordre_stable(racine):
    """L'ordre suit MANAGED_SUBDIRS, pas l'ordre du système de fichiers."""
    assert [p.name for p in managed_roots(racine)] == list(MANAGED_SUBDIRS)


def test_ignore_un_dossier_gere_absent(tmp_path):
    (tmp_path / "Films").mkdir()
    assert managed_roots(tmp_path) == [tmp_path / "Films"]


def test_repli_sur_la_racine_si_aucun_dossier_gere(tmp_path):
    """Une installation organisée autrement ne doit pas se retrouver aveugle."""
    (tmp_path / "Autre").mkdir()
    assert managed_roots(tmp_path) == [tmp_path]


def test_repli_si_racine_vide(tmp_path):
    assert managed_roots(tmp_path) == [tmp_path]


def test_un_fichier_homonyme_n_est_pas_une_racine(tmp_path):
    """« Films » en fichier ne doit pas être pris pour un répertoire géré."""
    (tmp_path / "Films").write_text("x")
    (tmp_path / "Series").mkdir()
    assert managed_roots(tmp_path) == [tmp_path / "Series"]


def test_liste_personnalisee(racine):
    assert managed_roots(racine, ("Musique",)) == [racine / "Musique"]


def test_racine_inexistante(tmp_path):
    absente = tmp_path / "nulle-part"
    assert managed_roots(absente) == [absente]


class TestSymlinksCassesLimitesAuxDossiersGeres:
    """find_broken_symlinks ne doit pas rapporter d'anomalies hors périmètre."""

    def _service(self, video_dir):
        from unittest.mock import MagicMock

        from src.adapters.file_system import FileSystemAdapter
        from src.services.repair.repair_service import RepairService

        return RepairService(
            file_system=FileSystemAdapter(),
            video_file_repo=MagicMock(),
            storage_dir=video_dir,
            video_dir=video_dir,
        )

    def test_ignore_les_branches_non_gerees(self, tmp_path):
        """Un lien cassé sous Musique/ ne concerne pas CineOrg."""
        for d in ("Films", "Musique"):
            (tmp_path / d).mkdir()
        (tmp_path / "Films/film.mkv").symlink_to(tmp_path / "absent.mkv")
        (tmp_path / "Musique/album.flac").symlink_to(tmp_path / "absent.flac")

        casses = self._service(tmp_path).find_broken_symlinks()

        assert [p.name for p in casses] == ["film.mkv"]

    def test_couvre_toutes_les_racines_gerees(self, tmp_path):
        for d in ("Films", "Series"):
            (tmp_path / d).mkdir()
        (tmp_path / "Films/film.mkv").symlink_to(tmp_path / "absent.mkv")
        (tmp_path / "Series/ep.mkv").symlink_to(tmp_path / "absent2.mkv")

        casses = self._service(tmp_path).find_broken_symlinks()

        assert sorted(p.name for p in casses) == ["ep.mkv", "film.mkv"]


class TestIntegriteLimiteeAuPerimetre:
    """L'analyse d'intégrité ne doit pas signaler des orphelins hors périmètre."""

    def _checker(self, storage):
        from unittest.mock import MagicMock

        from src.services.integrity import IntegrityChecker

        repo = MagicMock()
        repo.get_by_path.return_value = None  # tout est « orphelin »
        return IntegrityChecker(
            file_system=MagicMock(),
            video_file_repo=repo,
            storage_dir=storage,
            video_dir=storage,
        )

    def test_ignore_les_branches_non_gerees(self, tmp_path):
        from src.services.integrity import IntegrityReport

        for d in ("Films", "Musique"):
            (tmp_path / d).mkdir()
        (tmp_path / "Films/film.mkv").write_bytes(b"x")
        (tmp_path / "Musique/clip.mkv").write_bytes(b"x")

        report = IntegrityReport()
        self._checker(tmp_path)._check_orphan_files(report)

        assert [i.path.name for i in report.issues] == ["film.mkv"]


class TestConsolidationLimiteeAuPerimetre:
    """Le scan des volumes externes reste dans le périmètre géré."""

    def test_ignore_les_branches_non_gerees(self, tmp_path):

        from src.services.consolidation import ConsolidationService

        externe = tmp_path / "externe"
        externe.mkdir()
        cible = externe / "cible.mkv"
        cible.write_bytes(b"x")

        for d in ("Films", "Musique"):
            (tmp_path / "storage" / d).mkdir(parents=True)
        (tmp_path / "storage/Films/film.mkv").symlink_to(cible)
        (tmp_path / "storage/Musique/clip.mkv").symlink_to(cible)

        svc = ConsolidationService(storage_dir=tmp_path / "storage")
        trouves = [s.symlink_path.name for s in svc.scan_external_symlinks()]

        assert trouves == ["film.mkv"]


class TestImporterLimiteAuPerimetre:
    """L'import d'une vidéothèque existante ignore les contenus étrangers."""

    def _importer(self):
        from unittest.mock import MagicMock

        from src.services.importer import ImporterService

        svc = ImporterService(
            file_system=MagicMock(),
            filename_parser=MagicMock(),
            media_info_extractor=MagicMock(),
            video_file_repo=MagicMock(),
            pending_repo=MagicMock(),
            compute_hash_fn=lambda p: "hash",
        )
        svc._process_file = lambda p: p
        svc._process_symlink = lambda p: p
        return svc

    def test_scan_library_ignore_les_branches_non_gerees(self, tmp_path):
        for d in ("Films", "Musique"):
            (tmp_path / d).mkdir()
        (tmp_path / "Films/film.mkv").write_bytes(b"x")
        (tmp_path / "Musique/clip.mkv").write_bytes(b"x")

        trouves = [p.name for p in self._importer().scan_library(tmp_path)]

        assert trouves == ["film.mkv"]

    def test_scan_from_symlinks_ignore_les_branches_non_gerees(self, tmp_path):
        cible = tmp_path / "cible.mkv"
        cible.write_bytes(b"x")
        for d in ("Series", "Éducatif"):
            (tmp_path / "video" / d).mkdir(parents=True)
        (tmp_path / "video/Series/ep.mkv").symlink_to(cible)
        (tmp_path / "video/Éducatif/cours.mkv").symlink_to(cible)

        trouves = [
            p.name for p in self._importer().scan_from_symlinks(tmp_path / "video")
        ]

        assert trouves == ["ep.mkv"]
