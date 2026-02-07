"""
Tests unitaires pour ConsolidationService - consolidation de la videotheque.

Tests couvrant:
- Dataclasses (ExternalSymlink, ConsolidationResult) et valeurs par defaut
- Detection de cibles externes (_is_external_target)
- Extraction de volume racine (_get_volume_root)
- Scan des symlinks externes (scan_external_symlinks)
- Consolidation de fichiers (consolidate)
- Resume par volume (get_summary)
"""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.services.consolidation import (
    ConsolidationResult,
    ConsolidationService,
    ConsolidationStatus,
    ExternalSymlink,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def storage_dir(tmp_path):
    """Repertoire de stockage principal."""
    d = tmp_path / "storage"
    d.mkdir()
    return d


@pytest.fixture
def external_dir(tmp_path):
    """Repertoire externe simulant un volume monte."""
    d = tmp_path / "external_volume"
    d.mkdir()
    return d


@pytest.fixture
def service(storage_dir):
    """Service de consolidation en mode normal."""
    return ConsolidationService(storage_dir=storage_dir, dry_run=False)


@pytest.fixture
def service_dry_run(storage_dir):
    """Service de consolidation en mode dry-run."""
    return ConsolidationService(storage_dir=storage_dir, dry_run=True)


# ============================================================================
# Tests ConsolidationStatus
# ============================================================================


class TestConsolidationStatus:
    """Tests de l'enum ConsolidationStatus."""

    def test_valeurs_enum(self):
        """Verifie que toutes les valeurs de l'enum sont presentes."""
        assert ConsolidationStatus.ACCESSIBLE.value == "accessible"
        assert ConsolidationStatus.INACCESSIBLE.value == "inaccessible"
        assert ConsolidationStatus.CONSOLIDATED.value == "consolidated"
        assert ConsolidationStatus.ERROR.value == "error"
        assert ConsolidationStatus.SKIPPED.value == "skipped"

    def test_nombre_de_membres(self):
        """Verifie qu'il y a exactement 5 statuts."""
        assert len(ConsolidationStatus) == 5


# ============================================================================
# Tests ExternalSymlink
# ============================================================================


class TestExternalSymlink:
    """Tests de la dataclass ExternalSymlink."""

    def test_creation_avec_valeurs_requises(self):
        """Verifie la creation avec uniquement les champs requis."""
        symlink = ExternalSymlink(
            symlink_path=Path("/storage/Films/film.mkv"),
            target_path=Path("/media/NAS/volume5/film.mkv"),
            target_volume="/media/NAS/volume5",
            status=ConsolidationStatus.ACCESSIBLE,
        )
        assert symlink.symlink_path == Path("/storage/Films/film.mkv")
        assert symlink.target_path == Path("/media/NAS/volume5/film.mkv")
        assert symlink.target_volume == "/media/NAS/volume5"
        assert symlink.status == ConsolidationStatus.ACCESSIBLE

    def test_valeurs_par_defaut(self):
        """Verifie que size_bytes et error_message sont None par defaut."""
        symlink = ExternalSymlink(
            symlink_path=Path("/storage/film.mkv"),
            target_path=Path("/external/film.mkv"),
            target_volume="/external",
            status=ConsolidationStatus.INACCESSIBLE,
        )
        assert symlink.size_bytes is None
        assert symlink.error_message is None

    def test_creation_avec_toutes_les_valeurs(self):
        """Verifie la creation avec tous les champs remplis."""
        symlink = ExternalSymlink(
            symlink_path=Path("/storage/film.mkv"),
            target_path=Path("/media/NAS/volume5/film.mkv"),
            target_volume="/media/NAS/volume5",
            status=ConsolidationStatus.ACCESSIBLE,
            size_bytes=1_500_000_000,
            error_message=None,
        )
        assert symlink.size_bytes == 1_500_000_000

    def test_creation_avec_erreur(self):
        """Verifie la creation avec un message d'erreur."""
        symlink = ExternalSymlink(
            symlink_path=Path("/storage/film.mkv"),
            target_path=Path("/media/NAS/volume5/film.mkv"),
            target_volume="/media/NAS/volume5",
            status=ConsolidationStatus.INACCESSIBLE,
            error_message="Cible introuvable",
        )
        assert symlink.error_message == "Cible introuvable"
        assert symlink.size_bytes is None


# ============================================================================
# Tests ConsolidationResult
# ============================================================================


class TestConsolidationResult:
    """Tests de la dataclass ConsolidationResult."""

    def test_valeurs_par_defaut(self):
        """Verifie les valeurs par defaut: new_path=None, status=SKIPPED, error=None."""
        ext_symlink = ExternalSymlink(
            symlink_path=Path("/storage/film.mkv"),
            target_path=Path("/external/film.mkv"),
            target_volume="/external",
            status=ConsolidationStatus.ACCESSIBLE,
        )
        result = ConsolidationResult(symlink=ext_symlink)
        assert result.new_path is None
        assert result.status == ConsolidationStatus.SKIPPED
        assert result.error_message is None

    def test_creation_complete(self):
        """Verifie la creation avec toutes les valeurs."""
        ext_symlink = ExternalSymlink(
            symlink_path=Path("/storage/film.mkv"),
            target_path=Path("/external/film.mkv"),
            target_volume="/external",
            status=ConsolidationStatus.ACCESSIBLE,
            size_bytes=100,
        )
        result = ConsolidationResult(
            symlink=ext_symlink,
            new_path=Path("/storage/film.mkv"),
            status=ConsolidationStatus.CONSOLIDATED,
        )
        assert result.new_path == Path("/storage/film.mkv")
        assert result.status == ConsolidationStatus.CONSOLIDATED

    def test_creation_avec_erreur(self):
        """Verifie la creation avec un statut d'erreur."""
        ext_symlink = ExternalSymlink(
            symlink_path=Path("/storage/film.mkv"),
            target_path=Path("/external/film.mkv"),
            target_volume="/external",
            status=ConsolidationStatus.ACCESSIBLE,
        )
        result = ConsolidationResult(
            symlink=ext_symlink,
            status=ConsolidationStatus.ERROR,
            error_message="Taille du fichier copie incorrecte",
        )
        assert result.status == ConsolidationStatus.ERROR
        assert result.error_message == "Taille du fichier copie incorrecte"


# ============================================================================
# Tests _is_external_target
# ============================================================================


class TestIsExternalTarget:
    """Tests de la methode _is_external_target."""

    def test_cible_interne_retourne_false(self, service, storage_dir):
        """Un symlink pointant dans storage_dir est interne -> False."""
        symlink = storage_dir / "Films" / "link.mkv"
        target = storage_dir / "Films" / "real_file.mkv"
        assert service._is_external_target(symlink, target) is False

    def test_cible_interne_sous_repertoire_retourne_false(self, service, storage_dir):
        """Un symlink pointant dans un sous-rep de storage_dir est interne -> False."""
        symlink = storage_dir / "Films" / "link.mkv"
        target = storage_dir / "Films" / "Action" / "A-D" / "film.mkv"
        assert service._is_external_target(symlink, target) is False

    def test_cible_externe_retourne_true(self, service, storage_dir, tmp_path):
        """Un symlink pointant hors de storage_dir est externe -> True."""
        symlink = storage_dir / "Films" / "link.mkv"
        target = tmp_path / "other_volume" / "film.mkv"
        assert service._is_external_target(symlink, target) is True

    def test_cible_racine_retourne_true(self, service, storage_dir):
        """Un symlink pointant vers la racine est externe -> True."""
        symlink = storage_dir / "Films" / "link.mkv"
        target = Path("/tmp/film.mkv")
        assert service._is_external_target(symlink, target) is True

    def test_cible_volume_media_retourne_true(self, service, storage_dir):
        """Un symlink pointant vers /media/... est externe -> True."""
        symlink = storage_dir / "link.mkv"
        target = Path("/media/NAS/volume5/Films/film.mkv")
        assert service._is_external_target(symlink, target) is True

    def test_storage_dir_lui_meme_est_interne(self, service, storage_dir):
        """Un chemin egal a storage_dir est considere comme interne."""
        symlink = storage_dir / "link.mkv"
        target = storage_dir
        assert service._is_external_target(symlink, target) is False


# ============================================================================
# Tests _get_volume_root
# ============================================================================


class TestGetVolumeRoot:
    """Tests de la methode _get_volume_root."""

    def test_chemin_media_nas_volume(self, service):
        """Extrait le volume pour /media/NAS/volume5/dossier/fichier.

        Note: parts = ('/', 'media', 'NAS', 'volume5', ...) et join donne '//media/NAS/volume5'.
        """
        path = Path("/media/NAS/volume5/Films/Action/film.mkv")
        result = service._get_volume_root(path)
        # parts[:4] = ('/', 'media', 'NAS', 'volume5'), join => '//media/NAS/volume5'
        assert result == "//media/NAS/volume5"

    def test_chemin_media_usb(self, service):
        """Extrait le volume pour /media/user/USB_DRIVE/fichier."""
        path = Path("/media/user/USB_DRIVE/video.mp4")
        result = service._get_volume_root(path)
        assert result == "//media/user/USB_DRIVE"

    def test_chemin_media_court(self, service):
        """Un chemin /media/x avec seulement 3 parts retourne le parent."""
        path = Path("/media/fichier.mkv")
        # len(parts) = 3: ('/', 'media', 'fichier.mkv') -> < 4, donc parent
        assert service._get_volume_root(path) == "/media"

    def test_chemin_non_media(self, service):
        """Un chemin non-/media retourne le parent."""
        path = Path("/home/user/Videos/film.mkv")
        assert service._get_volume_root(path) == "/home/user/Videos"

    def test_chemin_tmp(self, service):
        """Un chemin dans /tmp retourne le parent."""
        path = Path("/tmp/external/film.mkv")
        assert service._get_volume_root(path) == "/tmp/external"

    def test_chemin_media_profond(self, service):
        """Meme pour un chemin tres profond, on extrait les 4 premieres parts."""
        path = Path("/media/NAS/volume1/a/b/c/d/e/film.mkv")
        assert service._get_volume_root(path) == "//media/NAS/volume1"


# ============================================================================
# Tests scan_external_symlinks
# ============================================================================


class TestScanExternalSymlinks:
    """Tests de la methode scan_external_symlinks."""

    def test_repertoire_vide(self, service):
        """Un repertoire vide ne produit aucun symlink."""
        result = list(service.scan_external_symlinks())
        assert result == []

    def test_fichiers_normaux_ignores(self, service, storage_dir):
        """Les fichiers reguliers (non-symlinks) sont ignores."""
        # Creer un fichier video normal
        film = storage_dir / "film.mkv"
        film.write_bytes(b"\x00" * 100)

        result = list(service.scan_external_symlinks())
        assert result == []

    def test_symlink_interne_ignore(self, service, storage_dir):
        """Un symlink pointant dans storage_dir est ignore (interne)."""
        # Creer un fichier cible interne
        target = storage_dir / "real_film.mkv"
        target.write_bytes(b"\x00" * 100)

        # Creer un symlink interne
        link = storage_dir / "Films" / "link_film.mkv"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)

        result = list(service.scan_external_symlinks())
        assert result == []

    def test_symlink_externe_accessible(self, service, storage_dir, external_dir):
        """Un symlink vers un fichier externe accessible est detecte."""
        # Creer le fichier cible externe
        target = external_dir / "film.mkv"
        target.write_bytes(b"\x00" * 500)

        # Creer le symlink dans storage
        link = storage_dir / "Films" / "film.mkv"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)

        result = list(service.scan_external_symlinks())
        assert len(result) == 1
        assert result[0].status == ConsolidationStatus.ACCESSIBLE
        assert result[0].size_bytes == 500
        assert result[0].symlink_path == link
        assert result[0].target_path == target.resolve()

    def test_symlink_externe_inaccessible(self, service, storage_dir, tmp_path):
        """Un symlink vers un fichier inexistant est marque inaccessible."""
        # Creer un symlink vers un fichier qui n'existe pas
        link = storage_dir / "film.mkv"
        fake_target = tmp_path / "disparu" / "film.mkv"
        link.symlink_to(fake_target)

        result = list(service.scan_external_symlinks())
        assert len(result) == 1
        assert result[0].status == ConsolidationStatus.INACCESSIBLE
        assert result[0].error_message == "Cible introuvable"
        assert result[0].size_bytes is None

    def test_fichier_non_video_ignore(self, service, storage_dir, external_dir):
        """Les fichiers non-video (.txt, .nfo, etc.) sont ignores."""
        # Creer un fichier non-video externe
        target = external_dir / "info.nfo"
        target.write_text("metadata")

        # Symlink vers ce fichier non-video
        link = storage_dir / "info.nfo"
        link.symlink_to(target)

        result = list(service.scan_external_symlinks())
        assert result == []

    def test_plusieurs_extensions_video(self, service, storage_dir, external_dir):
        """Differentes extensions video sont toutes detectees."""
        extensions = [".mkv", ".mp4", ".avi"]
        for ext in extensions:
            target = external_dir / f"film{ext}"
            target.write_bytes(b"\x00" * 100)
            link = storage_dir / f"film{ext}"
            link.symlink_to(target)

        result = list(service.scan_external_symlinks())
        assert len(result) == 3
        for r in result:
            assert r.status == ConsolidationStatus.ACCESSIBLE

    def test_symlinks_dans_sous_repertoires(self, service, storage_dir, external_dir):
        """Les symlinks dans des sous-repertoires de storage sont trouves."""
        # Creer une arborescence profonde
        target = external_dir / "film.mkv"
        target.write_bytes(b"\x00" * 200)

        subdir = storage_dir / "Films" / "Action" / "A-D"
        subdir.mkdir(parents=True)
        link = subdir / "film.mkv"
        link.symlink_to(target)

        result = list(service.scan_external_symlinks())
        assert len(result) == 1
        assert result[0].symlink_path == link

    def test_melange_internes_et_externes(self, service, storage_dir, external_dir):
        """Seuls les symlinks externes sont retournes, pas les internes."""
        # Fichier interne
        internal_target = storage_dir / "real_internal.mkv"
        internal_target.write_bytes(b"\x00" * 100)
        internal_link = storage_dir / "link_internal.mkv"
        internal_link.symlink_to(internal_target)

        # Fichier externe
        external_target = external_dir / "real_external.mkv"
        external_target.write_bytes(b"\x00" * 200)
        external_link = storage_dir / "link_external.mkv"
        external_link.symlink_to(external_target)

        result = list(service.scan_external_symlinks())
        assert len(result) == 1
        assert result[0].symlink_path == external_link

    def test_permission_error_retourne_inaccessible(
        self, service, storage_dir, external_dir
    ):
        """Un PermissionError sur la cible retourne un statut inaccessible."""
        target = external_dir / "film.mkv"
        target.write_bytes(b"\x00" * 100)

        link = storage_dir / "film.mkv"
        link.symlink_to(target)

        # Simuler un PermissionError lors de l'appel a target.exists()
        with patch.object(Path, "exists", side_effect=PermissionError("interdit")):
            result = list(service.scan_external_symlinks())

        assert len(result) == 1
        assert result[0].status == ConsolidationStatus.INACCESSIBLE
        assert result[0].error_message == "Permission refusee"

    def test_os_error_retourne_inaccessible(
        self, service, storage_dir, external_dir
    ):
        """Un OSError generique sur la cible retourne inaccessible avec message."""
        target = external_dir / "film.mkv"
        target.write_bytes(b"\x00" * 100)

        link = storage_dir / "film.mkv"
        link.symlink_to(target)

        with patch.object(
            Path, "exists", side_effect=OSError("erreur disque")
        ):
            result = list(service.scan_external_symlinks())

        assert len(result) == 1
        assert result[0].status == ConsolidationStatus.INACCESSIBLE
        assert "erreur disque" in result[0].error_message

    def test_extension_majuscule(self, service, storage_dir, external_dir):
        """Les extensions en majuscules (.MKV) sont aussi detectees."""
        target = external_dir / "film.MKV"
        target.write_bytes(b"\x00" * 100)

        link = storage_dir / "film.MKV"
        link.symlink_to(target)

        result = list(service.scan_external_symlinks())
        assert len(result) == 1
        assert result[0].status == ConsolidationStatus.ACCESSIBLE

    def test_resolve_os_error_utilise_readlink(
        self, service, storage_dir, tmp_path
    ):
        """Si resolve() leve OSError, readlink() est utilise comme fallback."""
        # Creer un symlink vers un chemin externe
        fake_target = tmp_path / "elsewhere" / "film.mkv"
        link = storage_dir / "film.mkv"
        link.symlink_to(fake_target)

        # Patcher resolve() pour lever OSError, simulant un symlink problematique
        original_resolve = Path.resolve

        def mock_resolve(self_path, *args, **kwargs):
            if self_path == link:
                raise OSError("Boucle de symlinks")
            return original_resolve(self_path, *args, **kwargs)

        with patch.object(Path, "resolve", mock_resolve):
            result = list(service.scan_external_symlinks())

        # Le symlink doit quand meme etre detecte (via readlink fallback)
        # La cible n'existe pas, donc inaccessible
        assert len(result) == 1
        assert result[0].status == ConsolidationStatus.INACCESSIBLE


# ============================================================================
# Tests consolidate
# ============================================================================


class TestConsolidate:
    """Tests de la methode consolidate."""

    def test_symlink_accessible_copie_et_remplace(
        self, service, storage_dir, external_dir
    ):
        """Un symlink accessible est copie puis remplace par le fichier reel."""
        # Preparer le fichier cible externe
        content = b"video_content_here_1234567890"
        target = external_dir / "film.mkv"
        target.write_bytes(content)

        # Creer le symlink
        link = storage_dir / "Films" / "film.mkv"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)

        ext_symlink = ExternalSymlink(
            symlink_path=link,
            target_path=target,
            target_volume=str(external_dir),
            status=ConsolidationStatus.ACCESSIBLE,
            size_bytes=len(content),
        )

        result = service.consolidate(ext_symlink)

        assert result.status == ConsolidationStatus.CONSOLIDATED
        assert result.new_path == link
        assert result.error_message is None
        # Le lien n'est plus un symlink
        assert not link.is_symlink()
        # C'est maintenant un fichier reel avec le bon contenu
        assert link.is_file()
        assert link.read_bytes() == content

    def test_symlink_inaccessible_est_ignore(self, service):
        """Un symlink inaccessible retourne SKIPPED."""
        ext_symlink = ExternalSymlink(
            symlink_path=Path("/storage/film.mkv"),
            target_path=Path("/external/film.mkv"),
            target_volume="/external",
            status=ConsolidationStatus.INACCESSIBLE,
            error_message="Cible introuvable",
        )

        result = service.consolidate(ext_symlink)

        assert result.status == ConsolidationStatus.SKIPPED
        assert result.error_message == "Cible non accessible"
        assert result.new_path is None

    def test_symlink_avec_statut_error_est_ignore(self, service):
        """Un symlink avec statut ERROR retourne aussi SKIPPED."""
        ext_symlink = ExternalSymlink(
            symlink_path=Path("/storage/film.mkv"),
            target_path=Path("/external/film.mkv"),
            target_volume="/external",
            status=ConsolidationStatus.ERROR,
        )

        result = service.consolidate(ext_symlink)

        assert result.status == ConsolidationStatus.SKIPPED
        assert result.error_message == "Cible non accessible"

    def test_dry_run_ne_modifie_rien(
        self, service_dry_run, storage_dir, external_dir
    ):
        """En mode dry-run, aucune modification n'est effectuee."""
        # Preparer le fichier
        content = b"video_data"
        target = external_dir / "film.mkv"
        target.write_bytes(content)

        link = storage_dir / "film.mkv"
        link.symlink_to(target)

        ext_symlink = ExternalSymlink(
            symlink_path=link,
            target_path=target,
            target_volume=str(external_dir),
            status=ConsolidationStatus.ACCESSIBLE,
            size_bytes=len(content),
        )

        result = service_dry_run.consolidate(ext_symlink)

        assert result.status == ConsolidationStatus.CONSOLIDATED
        assert result.new_path == link
        # En dry-run, le symlink doit toujours etre la
        assert link.is_symlink()
        assert link.resolve() == target.resolve()

    def test_erreur_taille_incorrecte(self, service, storage_dir, external_dir):
        """Si la taille copiee ne correspond pas, retourne ERROR et nettoie."""
        content = b"video_content_real"
        target = external_dir / "film.mkv"
        target.write_bytes(content)

        link = storage_dir / "film.mkv"
        link.symlink_to(target)

        # Declarer une taille differente de la taille reelle
        ext_symlink = ExternalSymlink(
            symlink_path=link,
            target_path=target,
            target_volume=str(external_dir),
            status=ConsolidationStatus.ACCESSIBLE,
            size_bytes=len(content) + 999,  # Taille incorrecte
        )

        result = service.consolidate(ext_symlink)

        assert result.status == ConsolidationStatus.ERROR
        assert "Taille du fichier copie incorrecte" in result.error_message
        # Le fichier temporaire doit avoir ete supprime
        temp_path = link.with_suffix(link.suffix + ".tmp")
        assert not temp_path.exists()
        # Le symlink original doit toujours etre la
        assert link.is_symlink()

    def test_permission_error_retourne_erreur(
        self, service, storage_dir, external_dir
    ):
        """Un PermissionError pendant la copie retourne ERROR."""
        content = b"video"
        target = external_dir / "film.mkv"
        target.write_bytes(content)

        link = storage_dir / "film.mkv"
        link.symlink_to(target)

        ext_symlink = ExternalSymlink(
            symlink_path=link,
            target_path=target,
            target_volume=str(external_dir),
            status=ConsolidationStatus.ACCESSIBLE,
            size_bytes=len(content),
        )

        with patch("src.services.consolidation.shutil.copy2") as mock_copy:
            mock_copy.side_effect = PermissionError("acces refuse")
            result = service.consolidate(ext_symlink)

        assert result.status == ConsolidationStatus.ERROR
        assert "Permission refusee" in result.error_message

    def test_os_error_retourne_erreur(self, service, storage_dir, external_dir):
        """Un OSError pendant la copie retourne ERROR."""
        content = b"video_data"
        target = external_dir / "film.mkv"
        target.write_bytes(content)

        link = storage_dir / "film.mkv"
        link.symlink_to(target)

        ext_symlink = ExternalSymlink(
            symlink_path=link,
            target_path=target,
            target_volume=str(external_dir),
            status=ConsolidationStatus.ACCESSIBLE,
            size_bytes=len(content),
        )

        with patch("src.services.consolidation.shutil.copy2") as mock_copy:
            mock_copy.side_effect = OSError("erreur disque plein")
            result = service.consolidate(ext_symlink)

        assert result.status == ConsolidationStatus.ERROR
        assert "erreur disque plein" in result.error_message

    def test_exception_inattendue_retourne_erreur(
        self, service, storage_dir, external_dir
    ):
        """Une exception inattendue pendant la copie retourne ERROR."""
        content = b"video"
        target = external_dir / "film.mkv"
        target.write_bytes(content)

        link = storage_dir / "film.mkv"
        link.symlink_to(target)

        ext_symlink = ExternalSymlink(
            symlink_path=link,
            target_path=target,
            target_volume=str(external_dir),
            status=ConsolidationStatus.ACCESSIBLE,
            size_bytes=len(content),
        )

        with patch("src.services.consolidation.shutil.copy2") as mock_copy:
            mock_copy.side_effect = RuntimeError("erreur bizarre")
            result = service.consolidate(ext_symlink)

        assert result.status == ConsolidationStatus.ERROR
        assert "Erreur inattendue" in result.error_message
        assert "erreur bizarre" in result.error_message

    def test_consolidation_preserve_le_contenu(
        self, service, storage_dir, external_dir
    ):
        """Apres consolidation, le contenu du fichier est identique a l'original."""
        # Creer un contenu significatif
        content = bytes(range(256)) * 100
        target = external_dir / "gros_film.mkv"
        target.write_bytes(content)

        link = storage_dir / "gros_film.mkv"
        link.symlink_to(target)

        ext_symlink = ExternalSymlink(
            symlink_path=link,
            target_path=target,
            target_volume=str(external_dir),
            status=ConsolidationStatus.ACCESSIBLE,
            size_bytes=len(content),
        )

        result = service.consolidate(ext_symlink)

        assert result.status == ConsolidationStatus.CONSOLIDATED
        assert link.read_bytes() == content
        assert link.stat().st_size == len(content)

    def test_fichier_temporaire_nettoye_apres_succes(
        self, service, storage_dir, external_dir
    ):
        """Le fichier .tmp est supprime apres une consolidation reussie."""
        content = b"video_data_ok"
        target = external_dir / "film.mkv"
        target.write_bytes(content)

        link = storage_dir / "film.mkv"
        link.symlink_to(target)

        ext_symlink = ExternalSymlink(
            symlink_path=link,
            target_path=target,
            target_volume=str(external_dir),
            status=ConsolidationStatus.ACCESSIBLE,
            size_bytes=len(content),
        )

        service.consolidate(ext_symlink)

        temp_path = link.with_suffix(".mkv.tmp")
        assert not temp_path.exists()


# ============================================================================
# Tests get_summary
# ============================================================================


class TestGetSummary:
    """Tests de la methode get_summary."""

    def test_liste_vide(self, service):
        """Une liste vide retourne un dictionnaire vide."""
        result = service.get_summary([])
        assert result == {}

    def test_un_seul_volume_accessible(self, service):
        """Un seul symlink accessible sur un volume."""
        symlinks = [
            ExternalSymlink(
                symlink_path=Path("/storage/film.mkv"),
                target_path=Path("/media/NAS/volume5/film.mkv"),
                target_volume="/media/NAS/volume5",
                status=ConsolidationStatus.ACCESSIBLE,
                size_bytes=1_000_000,
            ),
        ]
        result = service.get_summary(symlinks)

        assert "/media/NAS/volume5" in result
        vol = result["/media/NAS/volume5"]
        assert vol["count"] == 1
        assert vol["accessible"] == 1
        assert vol["inaccessible"] == 0
        assert vol["total_size"] == 1_000_000

    def test_un_seul_volume_inaccessible(self, service):
        """Un seul symlink inaccessible sur un volume."""
        symlinks = [
            ExternalSymlink(
                symlink_path=Path("/storage/film.mkv"),
                target_path=Path("/media/NAS/volume5/film.mkv"),
                target_volume="/media/NAS/volume5",
                status=ConsolidationStatus.INACCESSIBLE,
                error_message="Cible introuvable",
            ),
        ]
        result = service.get_summary(symlinks)

        vol = result["/media/NAS/volume5"]
        assert vol["count"] == 1
        assert vol["accessible"] == 0
        assert vol["inaccessible"] == 1
        assert vol["total_size"] == 0

    def test_plusieurs_volumes(self, service):
        """Aggregation correcte sur plusieurs volumes differents."""
        symlinks = [
            ExternalSymlink(
                symlink_path=Path("/storage/film1.mkv"),
                target_path=Path("/media/NAS/volume5/film1.mkv"),
                target_volume="/media/NAS/volume5",
                status=ConsolidationStatus.ACCESSIBLE,
                size_bytes=1_000_000,
            ),
            ExternalSymlink(
                symlink_path=Path("/storage/film2.mkv"),
                target_path=Path("/media/NAS/volume5/film2.mkv"),
                target_volume="/media/NAS/volume5",
                status=ConsolidationStatus.ACCESSIBLE,
                size_bytes=2_000_000,
            ),
            ExternalSymlink(
                symlink_path=Path("/storage/film3.mkv"),
                target_path=Path("/media/USB/disk1/film3.mkv"),
                target_volume="/media/USB/disk1",
                status=ConsolidationStatus.INACCESSIBLE,
            ),
        ]
        result = service.get_summary(symlinks)

        assert len(result) == 2

        vol5 = result["/media/NAS/volume5"]
        assert vol5["count"] == 2
        assert vol5["accessible"] == 2
        assert vol5["inaccessible"] == 0
        assert vol5["total_size"] == 3_000_000

        usb = result["/media/USB/disk1"]
        assert usb["count"] == 1
        assert usb["accessible"] == 0
        assert usb["inaccessible"] == 1
        assert usb["total_size"] == 0

    def test_melange_accessible_et_inaccessible_meme_volume(self, service):
        """Un volume avec des symlinks accessibles et inaccessibles."""
        symlinks = [
            ExternalSymlink(
                symlink_path=Path("/storage/film1.mkv"),
                target_path=Path("/media/NAS/vol/film1.mkv"),
                target_volume="/media/NAS/vol",
                status=ConsolidationStatus.ACCESSIBLE,
                size_bytes=500_000,
            ),
            ExternalSymlink(
                symlink_path=Path("/storage/film2.mkv"),
                target_path=Path("/media/NAS/vol/film2.mkv"),
                target_volume="/media/NAS/vol",
                status=ConsolidationStatus.INACCESSIBLE,
            ),
            ExternalSymlink(
                symlink_path=Path("/storage/film3.mkv"),
                target_path=Path("/media/NAS/vol/film3.mkv"),
                target_volume="/media/NAS/vol",
                status=ConsolidationStatus.ACCESSIBLE,
                size_bytes=300_000,
            ),
        ]
        result = service.get_summary(symlinks)

        vol = result["/media/NAS/vol"]
        assert vol["count"] == 3
        assert vol["accessible"] == 2
        assert vol["inaccessible"] == 1
        assert vol["total_size"] == 800_000

    def test_accessible_sans_taille_ne_plante_pas(self, service):
        """Un symlink accessible avec size_bytes=None n'ajoute pas a total_size."""
        symlinks = [
            ExternalSymlink(
                symlink_path=Path("/storage/film.mkv"),
                target_path=Path("/media/NAS/vol/film.mkv"),
                target_volume="/media/NAS/vol",
                status=ConsolidationStatus.ACCESSIBLE,
                size_bytes=None,  # Pas de taille connue
            ),
        ]
        result = service.get_summary(symlinks)

        vol = result["/media/NAS/vol"]
        assert vol["count"] == 1
        assert vol["accessible"] == 1
        assert vol["total_size"] == 0

    def test_accessible_taille_zero(self, service):
        """Un symlink accessible avec size_bytes=0 n'ajoute rien (falsy)."""
        symlinks = [
            ExternalSymlink(
                symlink_path=Path("/storage/film.mkv"),
                target_path=Path("/media/NAS/vol/film.mkv"),
                target_volume="/media/NAS/vol",
                status=ConsolidationStatus.ACCESSIBLE,
                size_bytes=0,
            ),
        ]
        result = service.get_summary(symlinks)

        vol = result["/media/NAS/vol"]
        assert vol["total_size"] == 0


# ============================================================================
# Tests d'initialisation du service
# ============================================================================


class TestConsolidationServiceInit:
    """Tests du constructeur de ConsolidationService."""

    def test_init_par_defaut(self, storage_dir):
        """Verifie les valeurs par defaut du constructeur."""
        svc = ConsolidationService(storage_dir=storage_dir)
        assert svc._storage_dir == storage_dir
        assert svc._dry_run is False

    def test_init_dry_run_true(self, storage_dir):
        """Verifie l'initialisation en mode dry-run."""
        svc = ConsolidationService(storage_dir=storage_dir, dry_run=True)
        assert svc._dry_run is True

    def test_init_dry_run_false(self, storage_dir):
        """Verifie l'initialisation en mode normal."""
        svc = ConsolidationService(storage_dir=storage_dir, dry_run=False)
        assert svc._dry_run is False
