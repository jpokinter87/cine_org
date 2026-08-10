"""Tests unitaires pour SandboxService."""

from datetime import datetime
from pathlib import Path

import pytest

from src.services.sandbox_service import SandboxService, SandboxedFile


@pytest.fixture
def dirs(tmp_path: Path):
    """Crée la structure de répertoires pour les tests."""
    storage = tmp_path / "storage"
    sandbox = tmp_path / ".sandbox"
    downloads = tmp_path / "downloads"

    storage.mkdir()
    downloads.mkdir()
    # sandbox créé à la demande par le service

    return {"storage": storage, "sandbox": sandbox, "downloads": downloads}


@pytest.fixture
def service(dirs):
    """Instance de SandboxService pour les tests."""
    return SandboxService(
        sandbox_dir=dirs["sandbox"],
        storage_dir=dirs["storage"],
        downloads_dir=dirs["downloads"],
    )


def _create_file(path: Path, content: str = "dummy", size: int | None = None) -> Path:
    """Crée un fichier de test avec contenu optionnel."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


class TestSandboxOrphans:
    """Tests pour sandbox_orphans()."""

    def test_preserve_arborescence(self, service, dirs):
        """Le déplacement préserve l'arborescence relative à storage."""
        f1 = _create_file(dirs["storage"] / "Films" / "Action" / "film.mkv")
        f2 = _create_file(dirs["storage"] / "Series" / "serie" / "ep01.mkv")

        count = service.sandbox_orphans([f1, f2])

        assert count == 2
        assert (dirs["sandbox"] / "orphans" / "Films" / "Action" / "film.mkv").exists()
        assert (dirs["sandbox"] / "orphans" / "Series" / "serie" / "ep01.mkv").exists()
        assert not f1.exists()
        assert not f2.exists()

    def test_skip_missing_files(self, service, dirs):
        """Les fichiers introuvables sont ignorés."""
        missing = dirs["storage"] / "inexistant.mkv"

        count = service.sandbox_orphans([missing])

        assert count == 0

    def test_cleanup_empty_dirs(self, service, dirs):
        """Les répertoires vides sont nettoyés après déplacement."""
        f = _create_file(dirs["storage"] / "Films" / "Genre" / "Sub" / "film.mkv")

        service.sandbox_orphans([f])

        assert not (dirs["storage"] / "Films" / "Genre" / "Sub").exists()
        # Films/ et Genre/ aussi nettoyés s'ils sont vides
        assert not (dirs["storage"] / "Films" / "Genre").exists()


class TestListSandboxed:
    """Tests pour list_sandboxed()."""

    def test_list_files_with_metadata(self, service, dirs):
        """La liste retourne les bons fichiers avec métadonnées."""
        orphans_dir = dirs["sandbox"] / "orphans"
        _create_file(orphans_dir / "Films" / "Action" / "film.mkv", "content123")

        result = service.list_sandboxed()

        assert len(result) == 1
        assert isinstance(result[0], SandboxedFile)
        assert result[0].name == "film.mkv"
        assert result[0].size == len("content123")
        assert isinstance(result[0].modified, datetime)
        assert (
            result[0].original_path == dirs["storage"] / "Films" / "Action" / "film.mkv"
        )

    def test_empty_sandbox(self, service):
        """Un sandbox vide retourne une liste vide."""
        result = service.list_sandboxed()
        assert result == []

    def test_ignores_directories(self, service, dirs):
        """Les répertoires ne sont pas listés."""
        orphans_dir = dirs["sandbox"] / "orphans" / "Films"
        orphans_dir.mkdir(parents=True)

        result = service.list_sandboxed()
        assert result == []


class TestDeleteFiles:
    """Tests pour delete_files()."""

    def test_delete_and_cleanup_empty_dirs(self, service, dirs):
        """Supprime les fichiers et nettoie les répertoires vides."""
        orphans_dir = dirs["sandbox"] / "orphans"
        f = _create_file(orphans_dir / "Films" / "Action" / "film.mkv")

        report = service.delete_files([f])

        assert report.deleted == 1
        assert not f.exists()
        assert not (orphans_dir / "Films" / "Action").exists()

    def test_refuse_outside_sandbox(self, service, dirs):
        """Refuse de supprimer un fichier hors du sandbox."""
        outside = _create_file(dirs["storage"] / "important.mkv")

        report = service.delete_files([outside])

        assert report.deleted == 0
        assert outside.exists()

    def test_skip_already_deleted(self, service, dirs):
        """Les fichiers déjà absents sont ignorés."""
        missing = dirs["sandbox"] / "orphans" / "gone.mkv"

        report = service.delete_files([missing])

        assert report.deleted == 0


class TestReinjectFiles:
    """Tests pour reinject_files()."""

    def test_move_to_downloads_preserves_type(self, service, dirs):
        """Déplace les fichiers vers downloads/Films ou downloads/Series."""
        orphans_dir = dirs["sandbox"] / "orphans"
        f = _create_file(orphans_dir / "Films" / "Action" / "film.mkv", "video_data")

        count = service.reinject_files([f])

        assert count == 1
        assert not f.exists()
        assert (dirs["downloads"] / "Films" / "film.mkv").exists()
        assert (dirs["downloads"] / "Films" / "film.mkv").read_text() == "video_data"

    def test_move_series_to_downloads_series(self, service, dirs):
        """Les séries vont dans downloads/Series."""
        orphans_dir = dirs["sandbox"] / "orphans"
        f = _create_file(orphans_dir / "Series" / "TV" / "ep01.mkv", "episode")

        count = service.reinject_files([f])

        assert count == 1
        assert (dirs["downloads"] / "Series" / "ep01.mkv").exists()

    def test_avoid_overwrite(self, service, dirs):
        """Évite l'écrasement en ajoutant un compteur."""
        orphans_dir = dirs["sandbox"] / "orphans"
        _create_file(dirs["downloads"] / "Films" / "film.mkv", "existing")
        f = _create_file(orphans_dir / "Films" / "film.mkv", "new_version")

        count = service.reinject_files([f])

        assert count == 1
        assert (dirs["downloads"] / "Films" / "film.mkv").read_text() == "existing"
        assert (dirs["downloads"] / "Films" / "film (1).mkv").exists()
        assert (
            dirs["downloads"] / "Films" / "film (1).mkv"
        ).read_text() == "new_version"

    def test_refuse_outside_sandbox(self, service, dirs):
        """Refuse de réinjecter un fichier hors du sandbox."""
        outside = _create_file(dirs["storage"] / "trap.mkv")

        count = service.reinject_files([outside])

        assert count == 0
        assert outside.exists()

    def test_cleanup_empty_dirs(self, service, dirs):
        """Les répertoires vides du sandbox sont nettoyés après réinjection."""
        orphans_dir = dirs["sandbox"] / "orphans"
        f = _create_file(orphans_dir / "Films" / "Genre" / "film.mkv")

        service.reinject_files([f])

        assert not (orphans_dir / "Films" / "Genre").exists()


class TestListeCompleteEtStatuts:
    """Le sandbox doit être visible en entier, avec le statut de chaque fichier."""

    def test_liste_au_dela_du_dossier_orphans(self, service, dirs):
        """Les anciennes versions déposées par le transfert doivent être visibles."""
        _create_file(dirs["sandbox"] / "orphans" / "Films" / "orphelin.mkv")
        _create_file(dirs["sandbox"] / "Series" / "TV" / "I-K" / "remplace.mkv")

        result = {f.name: f for f in service.list_sandboxed()}

        assert set(result) == {"orphelin.mkv", "remplace.mkv"}
        assert result["orphelin.mkv"].origin == "orphan"
        assert result["remplace.mkv"].origin == "replaced_version"

    def test_original_path_selon_origine(self, service, dirs):
        """L'emplacement d'origine se déduit de l'arborescence conservée."""
        _create_file(dirs["sandbox"] / "Series" / "TV" / "X" / "ep.mkv")

        item = service.list_sandboxed()[0]

        assert item.original_path == dirs["storage"] / "Series" / "TV" / "X" / "ep.mkv"


class _AuditeurFactice:
    """Auditeur de test : statut fixé par nom de fichier."""

    def __init__(self, statuts: dict[str, str]):
        self._statuts = statuts

    def audit(self, path: Path):
        from src.services.sandbox_audit import UNKNOWN, SandboxAudit

        statut = self._statuts.get(path.name, UNKNOWN)
        taille = path.stat().st_size if path.exists() else 0
        return SandboxAudit(statut, None, False, taille)


class TestSuppressionVerifiee:
    """La suppression ne doit jamais emporter la seule copie d'un média."""

    def _service(self, dirs, statuts):
        return SandboxService(
            sandbox_dir=dirs["sandbox"],
            storage_dir=dirs["storage"],
            downloads_dir=dirs["downloads"],
            auditor=_AuditeurFactice(statuts),
        )

    def test_refuse_un_fichier_sans_remplacant(self, dirs):
        from src.services.sandbox_audit import MISSING

        f = _create_file(dirs["sandbox"] / "Series" / "seule-copie.mkv")
        svc = self._service(dirs, {"seule-copie.mkv": MISSING})

        report = svc.delete_files([f])

        assert report.deleted == 0
        assert f.exists()
        assert report.refused and report.refused[0][0] == f

    def test_supprime_un_fichier_remplace(self, dirs):
        from src.services.sandbox_audit import REPLACED

        f = _create_file(dirs["sandbox"] / "Series" / "double.mkv", "abcd")
        svc = self._service(dirs, {"double.mkv": REPLACED})

        report = svc.delete_files([f])

        assert report.deleted == 1
        assert not f.exists()
        assert report.reclaimed_bytes == 4
        assert report.refused == []

    def test_indetermine_refuse_par_defaut(self, dirs):
        from src.services.sandbox_audit import UNKNOWN

        f = _create_file(dirs["sandbox"] / "Series" / "bizarre.mkv")
        svc = self._service(dirs, {"bizarre.mkv": UNKNOWN})

        assert svc.delete_files([f]).deleted == 0
        assert f.exists()

    def test_indetermine_supprime_si_force(self, dirs):
        from src.services.sandbox_audit import UNKNOWN

        f = _create_file(dirs["sandbox"] / "Series" / "bizarre.mkv")
        svc = self._service(dirs, {"bizarre.mkv": UNKNOWN})

        assert svc.delete_files([f], allow_unknown=True).deleted == 1
        assert not f.exists()

    def test_forcer_ne_deverrouille_pas_les_sans_remplacant(self, dirs):
        """allow_unknown ne doit jamais couvrir un fichier en statut MISSING."""
        from src.services.sandbox_audit import MISSING

        f = _create_file(dirs["sandbox"] / "Series" / "seule-copie.mkv")
        svc = self._service(dirs, {"seule-copie.mkv": MISSING})

        assert svc.delete_files([f], allow_unknown=True).deleted == 0
        assert f.exists()
