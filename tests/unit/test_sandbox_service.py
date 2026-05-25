"""Tests unitaires pour SandboxService."""

from datetime import datetime
from pathlib import Path

import pytest

from src.services.sandbox_service import (
    CATEGORY_ORPHAN,
    CATEGORY_OTHER,
    CATEGORY_REJECTED,
    CATEGORY_REPLACED,
    REJECTED_SUBDIR,
    REPLACED_SUBDIR,
    SandboxService,
    SandboxedFile,
)


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

        count = service.delete_files([f])

        assert count == 1
        assert not f.exists()
        assert not (orphans_dir / "Films" / "Action").exists()

    def test_refuse_outside_sandbox(self, service, dirs):
        """Refuse de supprimer un fichier hors du sandbox."""
        outside = _create_file(dirs["storage"] / "important.mkv")

        count = service.delete_files([outside])

        assert count == 0
        assert outside.exists()

    def test_skip_already_deleted(self, service, dirs):
        """Les fichiers déjà absents sont ignorés."""
        missing = dirs["sandbox"] / "orphans" / "gone.mkv"

        count = service.delete_files([missing])

        assert count == 0


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


class TestListSandboxedCategories:
    """list_sandboxed scanne toutes les catégories."""

    def test_categories_and_original_base(self, service, dirs):
        sb = dirs["sandbox"]
        _create_file(sb / "orphans" / "Films" / "Action" / "o.mkv")
        _create_file(sb / REPLACED_SUBDIR / "Films" / "SF" / "r.mkv")
        _create_file(
            sb / REJECTED_SUBDIR / "Series" / "T (2021)" / "Saison 01" / "x.mkv"
        )
        _create_file(sb / "vieux_a_la_racine.mkv")  # legacy

        result = {f.name: f for f in service.list_sandboxed()}

        assert result["o.mkv"].category == CATEGORY_ORPHAN
        assert (
            result["o.mkv"].original_path
            == dirs["storage"] / "Films" / "Action" / "o.mkv"
        )
        assert result["r.mkv"].category == CATEGORY_REPLACED
        assert (
            result["r.mkv"].original_path == dirs["storage"] / "Films" / "SF" / "r.mkv"
        )
        assert result["x.mkv"].category == CATEGORY_REJECTED
        # rejet : base = downloads
        assert (
            result["x.mkv"].original_path
            == dirs["downloads"] / "Series" / "T (2021)" / "Saison 01" / "x.mkv"
        )
        assert result["vieux_a_la_racine.mkv"].category == CATEGORY_OTHER

    def test_file_at_category_root(self, service, dirs):
        """Fichier directement sous orphans/ (sans Films/Series intermédiaire)."""
        _create_file(dirs["sandbox"] / "orphans" / "seul.mkv")
        result = {f.name: f for f in service.list_sandboxed()}
        assert result["seul.mkv"].category == CATEGORY_ORPHAN
        assert result["seul.mkv"].original_path == dirs["storage"] / "seul.mkv"


class TestSandboxRejected:
    """sandbox_rejected déplace un doublon rejeté de downloads → rejets_doublons/."""

    def test_preserve_arborescence_from_downloads(self, service, dirs):
        src = _create_file(
            dirs["downloads"] / "Series" / "Octobre (2021)" / "ep01.mkv", "x265"
        )

        count = service.sandbox_rejected([src])

        assert count == 1
        dest = (
            dirs["sandbox"] / REJECTED_SUBDIR / "Series" / "Octobre (2021)" / "ep01.mkv"
        )
        assert dest.exists()
        assert dest.read_text() == "x265"
        assert not src.exists()

    def test_fallback_name_when_outside_downloads(self, service, dirs):
        src = _create_file(dirs["storage"] / "ailleurs.mkv", "data")

        count = service.sandbox_rejected([src])

        assert count == 1
        assert (dirs["sandbox"] / REJECTED_SUBDIR / "ailleurs.mkv").exists()

    def test_skip_missing(self, service, dirs):
        count = service.sandbox_rejected([dirs["downloads"] / "nope.mkv"])
        assert count == 0

    def test_cleanup_empty_dirs_in_downloads(self, service, dirs):
        """Les dossiers vides laissés dans downloads/ sont nettoyés."""
        src = _create_file(
            dirs["downloads"] / "Series" / "Octobre (2021)" / "ep01.mkv", "x265"
        )
        service.sandbox_rejected([src])
        assert not (dirs["downloads"] / "Series" / "Octobre (2021)").exists()

    def test_fallback_outside_downloads_does_not_clean_other_trees(self, service, dirs):
        """Un fichier hors downloads ne déclenche pas de nettoyage de storage/."""
        other = _create_file(dirs["storage"] / "Films" / "x.mkv", "data")
        service.sandbox_rejected([other])
        # storage/Films ne doit PAS avoir été supprimé par le nettoyage
        assert (dirs["storage"] / "Films").exists()


class TestAnnotateKeptVersions:
    """annotate_kept_versions marque vert/rouge selon présence dans video/."""

    def test_movie_present_and_absent(self, service, dirs, tmp_path):
        video = tmp_path / "video"
        # Film présent dans la vidéothèque
        _create_file(
            video / "Films" / "Action" / "A-B" / "Heat (1995)" / "Heat (1995) VF.mkv"
        )
        sb = dirs["sandbox"]
        _create_file(
            sb / REJECTED_SUBDIR / "Films" / "Heat (1995)" / "Heat (1995) VF x265.mkv"
        )
        _create_file(
            sb / REJECTED_SUBDIR / "Films" / "Inconnu (2099)" / "Inconnu (2099).mkv"
        )

        files = service.list_sandboxed()
        service.annotate_kept_versions(files, video)
        by_name = {f.name: f for f in files}

        assert by_name["Heat (1995) VF x265.mkv"].kept_version is not None
        assert by_name["Inconnu (2099).mkv"].kept_version is None

    def test_series_episode_presence(self, service, dirs, tmp_path):
        video = tmp_path / "video"
        _create_file(
            video
            / "Series"
            / "O"
            / "Octobre (2021)"
            / "Saison 01"
            / "Octobre (2021) - S01E01 - VF.mkv"
        )
        sb = dirs["sandbox"]
        _create_file(
            sb
            / REJECTED_SUBDIR
            / "Series"
            / "Octobre (2021)"
            / "Saison 01"
            / "Octobre (2021) - S01E01 - x265.mkv"
        )
        _create_file(
            sb
            / REJECTED_SUBDIR
            / "Series"
            / "Octobre (2021)"
            / "Saison 01"
            / "Octobre (2021) - S01E09 - x265.mkv"
        )

        files = service.list_sandboxed()
        service.annotate_kept_versions(files, video)
        by_name = {f.name: f for f in files}

        assert by_name["Octobre (2021) - S01E01 - x265.mkv"].kept_version is not None
        assert by_name["Octobre (2021) - S01E09 - x265.mkv"].kept_version is None

    def test_video_dir_missing_is_safe(self, service, dirs, tmp_path):
        sb = dirs["sandbox"]
        _create_file(sb / REJECTED_SUBDIR / "Films" / "X (2000)" / "X (2000).mkv")
        files = service.list_sandboxed()
        service.annotate_kept_versions(files, tmp_path / "inexistant")
        assert all(f.kept_version is None for f in files)

    def test_raw_filename_no_year_is_none(self, service, dirs, tmp_path):
        """Nom de fichier brut sans « (Année) » → kept_version None (pas d'erreur)."""
        _create_file(dirs["sandbox"] / REJECTED_SUBDIR / "Films" / "batman.mkv")
        files = service.list_sandboxed()
        service.annotate_kept_versions(files, tmp_path / "video")
        assert files[0].kept_version is None

    def test_rejected_series_flat_name_matches_kept(self, service, dirs, tmp_path):
        """Rejet série à plat (nom formaté, sans dossier Titre) → version trouvée."""
        video = tmp_path / "video"
        _create_file(
            video / "Series" / "O" / "Octobre (2021)" / "Saison 01"
            / "Octobre (2021) - S01E01 - VF.mkv"
        )
        # Rejet tel que déposé par sandbox_rejected : à plat sous Series/, nom formaté
        _create_file(
            dirs["sandbox"] / REJECTED_SUBDIR / "Series"
            / "Octobre (2021) - S01E01 - MULTI x265.mkv"
        )
        files = service.list_sandboxed()
        service.annotate_kept_versions(files, video)
        assert files[0].kept_version is not None


class TestReinjectAllCategories:
    """reinject_files fonctionne pour les catégories hors orphans/."""

    def test_reinject_rejected_series(self, service, dirs):
        f = _create_file(
            dirs["sandbox"] / REJECTED_SUBDIR / "Series" / "T (2021)" / "ep.mkv", "d"
        )
        count = service.reinject_files([f])
        assert count == 1
        assert (dirs["downloads"] / "Series" / "ep.mkv").exists()
        assert not f.exists()

    def test_delete_rejected_cleans_dirs(self, service, dirs):
        f = _create_file(
            dirs["sandbox"] / REJECTED_SUBDIR / "Films" / "X (2000)" / "x.mkv"
        )
        count = service.delete_files([f])
        assert count == 1
        assert not (dirs["sandbox"] / REJECTED_SUBDIR / "Films" / "X (2000)").exists()
        # la racine du sandbox subsiste
        assert dirs["sandbox"].exists()
