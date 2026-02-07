"""
Tests unitaires pour SymlinkRepairService.

Tests TDD pour la detection et la reparation des symlinks brises :
- Modeles de donnees (RepairDecision, RepairCandidate, RepairResult)
- Normalisation et extraction de noms de fichiers
- Calcul de similarite entre fichiers
- Construction de l'index de fichiers video
- Recherche de candidats pour reparation
- Scan des symlinks brises
- Reparation effective des symlinks
"""

import os
from pathlib import Path

import pytest

from src.services.symlink_repair import (
    RepairCandidate,
    RepairDecision,
    RepairResult,
    SymlinkRepairService,
)


# ====================
# Fixtures
# ====================


@pytest.fixture
def storage_dir(tmp_path: Path) -> Path:
    """Repertoire de stockage avec des fichiers video de test."""
    d = tmp_path / "storage"
    d.mkdir()
    return d


@pytest.fixture
def video_dir(tmp_path: Path) -> Path:
    """Repertoire video (symlinks) de test."""
    d = tmp_path / "video"
    d.mkdir()
    return d


@pytest.fixture
def service(storage_dir: Path) -> SymlinkRepairService:
    """Service de reparation avec les parametres par defaut."""
    return SymlinkRepairService(storage_dir=storage_dir, min_score=60.0, dry_run=False)


@pytest.fixture
def service_dry_run(storage_dir: Path) -> SymlinkRepairService:
    """Service de reparation en mode dry-run."""
    return SymlinkRepairService(storage_dir=storage_dir, min_score=60.0, dry_run=True)


def _create_video_file(directory: Path, filename: str, size: int = 1024) -> Path:
    """Cree un fichier video factice dans le repertoire donne."""
    filepath = directory / filename
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_bytes(b"\x00" * size)
    return filepath


def _create_symlink(link_path: Path, target: Path) -> Path:
    """Cree un symlink vers la cible donnee."""
    link_path.parent.mkdir(parents=True, exist_ok=True)
    link_path.symlink_to(target)
    return link_path


def _create_broken_symlink(link_path: Path, fake_target: str = "/nonexistent/file.mkv") -> Path:
    """Cree un symlink brise pointant vers une cible inexistante."""
    link_path.parent.mkdir(parents=True, exist_ok=True)
    link_path.symlink_to(fake_target)
    return link_path


# ====================
# Tests RepairDecision
# ====================


class TestRepairDecision:
    """Tests pour l'enum RepairDecision."""

    def test_valeurs_enum(self):
        """Verifie que les valeurs de l'enum sont correctes."""
        assert RepairDecision.REPAIRED.value == "repaired"
        assert RepairDecision.NO_MATCH.value == "no_match"
        assert RepairDecision.SKIPPED.value == "skipped"
        assert RepairDecision.ERROR.value == "error"

    def test_comparaison_enum(self):
        """Verifie que les comparaisons d'enum fonctionnent."""
        assert RepairDecision.REPAIRED == RepairDecision.REPAIRED
        assert RepairDecision.REPAIRED != RepairDecision.ERROR


# ====================
# Tests RepairCandidate
# ====================


class TestRepairCandidate:
    """Tests pour le dataclass RepairCandidate."""

    def test_creation_candidate(self):
        """Verifie la creation d'un candidat avec tous les champs."""
        candidate = RepairCandidate(
            path=Path("/storage/film.mkv"),
            score=85.5,
            size_bytes=1_500_000_000,
            match_reason="nom cible similaire",
        )
        assert candidate.path == Path("/storage/film.mkv")
        assert candidate.score == 85.5
        assert candidate.size_bytes == 1_500_000_000
        assert candidate.match_reason == "nom cible similaire"


# ====================
# Tests RepairResult
# ====================


class TestRepairResult:
    """Tests pour le dataclass RepairResult."""

    def test_creation_avec_valeurs_par_defaut(self):
        """Verifie que candidates est initialise a une liste vide par __post_init__."""
        result = RepairResult(
            symlink_path=Path("/video/film.mkv"),
            original_target=Path("/storage/film.mkv"),
            decision=RepairDecision.NO_MATCH,
        )
        assert result.candidates == []
        assert result.new_target is None
        assert result.error_message is None

    def test_creation_avec_candidates_explicite(self):
        """Verifie que candidates peut etre fourni explicitement."""
        candidates = [
            RepairCandidate(
                path=Path("/storage/film_v2.mkv"),
                score=90.0,
                size_bytes=2_000_000,
                match_reason="nom cible similaire",
            )
        ]
        result = RepairResult(
            symlink_path=Path("/video/film.mkv"),
            original_target=Path("/storage/film.mkv"),
            decision=RepairDecision.NO_MATCH,
            candidates=candidates,
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].score == 90.0

    def test_post_init_ne_remplace_pas_liste_existante(self):
        """Verifie que __post_init__ ne remplace pas une liste deja fournie."""
        candidates = [
            RepairCandidate(
                path=Path("/storage/a.mkv"),
                score=75.0,
                size_bytes=100,
                match_reason="test",
            ),
            RepairCandidate(
                path=Path("/storage/b.mkv"),
                score=80.0,
                size_bytes=200,
                match_reason="test",
            ),
        ]
        result = RepairResult(
            symlink_path=Path("/video/film.mkv"),
            original_target=Path("/storage/film.mkv"),
            decision=RepairDecision.NO_MATCH,
            candidates=candidates,
        )
        assert len(result.candidates) == 2

    def test_creation_avec_erreur(self):
        """Verifie la creation d'un resultat d'erreur."""
        result = RepairResult(
            symlink_path=Path("/video/film.mkv"),
            original_target=Path(""),
            decision=RepairDecision.ERROR,
            error_message="Permission refusee",
        )
        assert result.decision == RepairDecision.ERROR
        assert result.error_message == "Permission refusee"
        assert result.candidates == []

    def test_creation_reparation_reussie(self):
        """Verifie la creation d'un resultat de reparation reussie."""
        result = RepairResult(
            symlink_path=Path("/video/film.mkv"),
            original_target=Path("/storage/old.mkv"),
            decision=RepairDecision.REPAIRED,
            new_target=Path("/storage/new.mkv"),
        )
        assert result.decision == RepairDecision.REPAIRED
        assert result.new_target == Path("/storage/new.mkv")


# ====================
# Tests _normalize_filename
# ====================


class TestNormalizeFilename:
    """Tests pour la normalisation des noms de fichiers."""

    def test_supprime_extension_mkv(self, service: SymlinkRepairService):
        """Verifie la suppression de l'extension .mkv."""
        assert service._normalize_filename("film.mkv") == "film"

    def test_supprime_extension_mp4(self, service: SymlinkRepairService):
        """Verifie la suppression de l'extension .mp4."""
        assert service._normalize_filename("film.mp4") == "film"

    def test_met_en_minuscules(self, service: SymlinkRepairService):
        """Verifie la mise en minuscules."""
        assert service._normalize_filename("Mon.Film.mkv") == "mon film"

    def test_remplace_points_par_espaces(self, service: SymlinkRepairService):
        """Verifie le remplacement des points par des espaces."""
        assert service._normalize_filename("mon.super.film.mkv") == "mon super film"

    def test_remplace_underscores_par_espaces(self, service: SymlinkRepairService):
        """Verifie le remplacement des underscores par des espaces."""
        assert service._normalize_filename("mon_super_film.mkv") == "mon super film"

    def test_remplace_tirets_par_espaces(self, service: SymlinkRepairService):
        """Verifie le remplacement des tirets par des espaces."""
        assert service._normalize_filename("mon-super-film.mkv") == "mon super film"

    def test_supprime_espaces_multiples(self, service: SymlinkRepairService):
        """Verifie la suppression des espaces multiples."""
        result = service._normalize_filename("mon..super...film.mkv")
        assert result == "mon super film"

    def test_supprime_espaces_debut_fin(self, service: SymlinkRepairService):
        """Verifie la suppression des espaces en debut et fin."""
        result = service._normalize_filename("-mon-film-.mkv")
        assert result == "mon film"

    def test_separateurs_mixtes(self, service: SymlinkRepairService):
        """Verifie le traitement de separateurs mixtes."""
        result = service._normalize_filename("Mon_Super.Film-2024.mkv")
        assert result == "mon super film 2024"

    def test_nom_sans_extension(self, service: SymlinkRepairService):
        """Verifie le traitement d'un nom sans extension reconnue."""
        result = service._normalize_filename("film")
        assert result == "film"

    def test_nom_vide_avec_extension(self, service: SymlinkRepairService):
        """Verifie le traitement d'un fichier commencant par un point (dotfile)."""
        # Path(".mkv").stem retourne ".mkv" (considere comme dotfile, pas extension)
        result = service._normalize_filename(".mkv")
        assert result == "mkv"


# ====================
# Tests _extract_title_parts
# ====================


class TestExtractTitleParts:
    """Tests pour l'extraction du titre et de l'annee."""

    def test_titre_avec_annee(self, service: SymlinkRepairService):
        """Verifie l'extraction du titre et de l'annee."""
        title, year = service._extract_title_parts("Matrix.1999.mkv")
        assert title == "matrix"
        assert year == 1999

    def test_titre_sans_annee(self, service: SymlinkRepairService):
        """Verifie l'extraction quand il n'y a pas d'annee."""
        title, year = service._extract_title_parts("Film.Inconnu.mkv")
        assert title == "film inconnu"
        assert year is None

    def test_supprime_pattern_french(self, service: SymlinkRepairService):
        """Verifie la suppression du pattern 'french'."""
        title, year = service._extract_title_parts("Matrix.1999.FRENCH.mkv")
        assert "french" not in title
        assert year == 1999

    def test_supprime_pattern_vostfr(self, service: SymlinkRepairService):
        """Verifie la suppression du pattern 'vostfr'."""
        title, year = service._extract_title_parts("Matrix.1999.VOSTFR.mkv")
        assert "vostfr" not in title

    def test_supprime_pattern_multi(self, service: SymlinkRepairService):
        """Verifie la suppression du pattern 'multi'."""
        title, year = service._extract_title_parts("Matrix.1999.MULTI.mkv")
        assert "multi" not in title

    def test_supprime_pattern_1080p(self, service: SymlinkRepairService):
        """Verifie la suppression de la resolution 1080p."""
        title, year = service._extract_title_parts("Matrix.1999.1080p.mkv")
        assert "1080p" not in title

    def test_supprime_pattern_720p(self, service: SymlinkRepairService):
        """Verifie la suppression de la resolution 720p."""
        title, year = service._extract_title_parts("Film.720p.mkv")
        assert "720p" not in title

    def test_supprime_pattern_2160p(self, service: SymlinkRepairService):
        """Verifie la suppression de la resolution 2160p (4K)."""
        title, year = service._extract_title_parts("Film.2160p.mkv")
        assert "2160p" not in title

    def test_supprime_pattern_x264(self, service: SymlinkRepairService):
        """Verifie la suppression du codec x264."""
        title, year = service._extract_title_parts("Matrix.1999.x264.mkv")
        assert "x264" not in title

    def test_supprime_pattern_x265(self, service: SymlinkRepairService):
        """Verifie la suppression du codec x265."""
        title, year = service._extract_title_parts("Film.x265.mkv")
        assert "x265" not in title

    def test_supprime_pattern_hevc(self, service: SymlinkRepairService):
        """Verifie la suppression du codec HEVC."""
        title, year = service._extract_title_parts("Film.HEVC.mkv")
        assert "hevc" not in title

    def test_supprime_pattern_bluray(self, service: SymlinkRepairService):
        """Verifie la suppression de la source BluRay."""
        title, year = service._extract_title_parts("Matrix.1999.BluRay.mkv")
        assert "bluray" not in title

    def test_supprime_pattern_webrip(self, service: SymlinkRepairService):
        """Verifie la suppression de la source WebRip."""
        title, year = service._extract_title_parts("Film.WEBRip.mkv")
        assert "webrip" not in title

    def test_supprime_pattern_dts(self, service: SymlinkRepairService):
        """Verifie la suppression du codec audio DTS."""
        title, year = service._extract_title_parts("Film.DTS.mkv")
        assert "dts" not in title

    def test_supprime_pattern_ac3(self, service: SymlinkRepairService):
        """Verifie la suppression du codec audio AC3."""
        title, year = service._extract_title_parts("Film.AC3.mkv")
        assert "ac3" not in title

    def test_supprime_multiples_patterns_techniques(self, service: SymlinkRepairService):
        """Verifie la suppression de plusieurs patterns techniques combines."""
        title, year = service._extract_title_parts(
            "Matrix.1999.FRENCH.1080p.BluRay.x264.DTS.mkv"
        )
        assert title == "matrix"
        assert year == 1999

    def test_titre_avant_annee_seulement(self, service: SymlinkRepairService):
        """Verifie que seul le texte avant l'annee est considere comme titre."""
        title, year = service._extract_title_parts("Mon.Super.Film.2020.FRENCH.mkv")
        assert title == "mon super film"
        assert year == 2020

    def test_annee_limite_basse_1900(self, service: SymlinkRepairService):
        """Verifie la detection d'une annee en 1900."""
        title, year = service._extract_title_parts("Ancien.Film.1900.mkv")
        assert year == 1900

    def test_annee_limite_haute_2099(self, service: SymlinkRepairService):
        """Verifie la detection d'une annee en 2099."""
        title, year = service._extract_title_parts("Futur.Film.2099.mkv")
        assert year == 2099

    def test_supprime_pattern_truefrench(self, service: SymlinkRepairService):
        """Verifie la suppression du pattern TrueFrench."""
        title, year = service._extract_title_parts("Film.TrueFrench.mkv")
        assert "truefrench" not in title

    def test_supprime_pattern_4k(self, service: SymlinkRepairService):
        """Verifie la suppression du pattern 4k."""
        title, year = service._extract_title_parts("Film.4k.mkv")
        assert "4k" not in title

    def test_supprime_pattern_uhd(self, service: SymlinkRepairService):
        """Verifie la suppression du pattern UHD."""
        title, year = service._extract_title_parts("Film.UHD.mkv")
        assert "uhd" not in title

    def test_supprime_pattern_hdtv(self, service: SymlinkRepairService):
        """Verifie la suppression du pattern HDTV."""
        title, year = service._extract_title_parts("Film.HDTV.mkv")
        assert "hdtv" not in title

    def test_supprime_pattern_dvdrip(self, service: SymlinkRepairService):
        """Verifie la suppression du pattern DVDRip."""
        title, year = service._extract_title_parts("Film.DVDRip.mkv")
        assert "dvdrip" not in title

    def test_supprime_pattern_dolby(self, service: SymlinkRepairService):
        """Verifie la suppression du pattern Dolby."""
        title, year = service._extract_title_parts("Film.Dolby.mkv")
        assert "dolby" not in title

    def test_supprime_pattern_atmos(self, service: SymlinkRepairService):
        """Verifie la suppression du pattern Atmos."""
        title, year = service._extract_title_parts("Film.Atmos.mkv")
        assert "atmos" not in title

    def test_nettoyage_espaces_multiples_apres_suppression(self, service: SymlinkRepairService):
        """Verifie que les espaces multiples sont nettoyes apres suppression des patterns."""
        title, year = service._extract_title_parts("Film.FRENCH.1080p.mkv")
        # Apres suppression de french et 1080p, il ne doit pas rester d'espaces multiples
        assert "  " not in title


# ====================
# Tests _calculate_similarity
# ====================


class TestCalculateSimilarity:
    """Tests pour le calcul de similarite entre noms de fichiers."""

    def test_meme_fichier_meme_annee(self, service: SymlinkRepairService):
        """Deux fichiers identiques avec la meme annee donnent un score eleve."""
        score = service._calculate_similarity(
            "Matrix.1999.mkv",
            "Matrix.1999.mkv",
        )
        # 100% similarite titre + 10% bonus annee = 110 -> clippe a 100
        assert score >= 95.0

    def test_meme_titre_annees_differentes(self, service: SymlinkRepairService):
        """Meme titre mais annees differentes donne un score reduit."""
        score = service._calculate_similarity(
            "Matrix.1999.mkv",
            "Matrix.2021.mkv",
        )
        # Titre tres similaire mais malus annee de -10%
        assert score >= 50.0
        assert score < 100.0

    def test_meme_titre_annees_proches(self, service: SymlinkRepairService):
        """Meme titre avec annees proches (diff=1) donne un petit bonus."""
        score = service._calculate_similarity(
            "Film.2020.mkv",
            "Film.2021.mkv",
        )
        # Bonus de +5% pour annee proche
        assert score >= 80.0

    def test_titres_tres_differents(self, service: SymlinkRepairService):
        """Deux titres completement differents donnent un score bas."""
        score = service._calculate_similarity(
            "Matrix.1999.mkv",
            "Titanic.1997.mkv",
        )
        assert score < 50.0

    def test_sans_annee_titre_similaire(self, service: SymlinkRepairService):
        """Titres similaires sans annee (pas de bonus/malus)."""
        score = service._calculate_similarity(
            "MonFilm.mkv",
            "MonFilm.mkv",
        )
        # Similarite parfaite sans bonus annee
        assert score >= 90.0

    def test_score_minimum_zero(self, service: SymlinkRepairService):
        """Le score ne peut pas etre negatif."""
        score = service._calculate_similarity(
            "AAAA.1999.mkv",
            "ZZZZ.2050.mkv",
        )
        assert score >= 0.0

    def test_score_maximum_cent(self, service: SymlinkRepairService):
        """Le score ne peut pas depasser 100."""
        score = service._calculate_similarity(
            "Film.2020.mkv",
            "Film.2020.mkv",
        )
        assert score <= 100.0

    def test_variations_separateurs(self, service: SymlinkRepairService):
        """Des fichiers avec differents separateurs restent tres similaires."""
        score = service._calculate_similarity(
            "Mon.Super.Film.2020.mkv",
            "Mon_Super_Film_2020.mkv",
        )
        assert score >= 90.0

    def test_patterns_techniques_differents(self, service: SymlinkRepairService):
        """Meme film avec des infos techniques differentes reste similaire."""
        score = service._calculate_similarity(
            "Matrix.1999.FRENCH.1080p.BluRay.mkv",
            "Matrix.1999.MULTI.720p.WEBRip.mkv",
        )
        assert score >= 80.0

    def test_un_nom_avec_annee_autre_sans(self, service: SymlinkRepairService):
        """Un fichier avec annee et un sans : pas de bonus/malus annee."""
        score = service._calculate_similarity(
            "Matrix.1999.mkv",
            "Matrix.mkv",
        )
        # Pas de bonus/malus car une seule annee presente
        assert score >= 60.0


# ====================
# Tests _build_file_index
# ====================


class TestBuildFileIndex:
    """Tests pour la construction de l'index des fichiers video."""

    def test_indexe_fichiers_video(self, storage_dir: Path, service: SymlinkRepairService):
        """Verifie que les fichiers video sont indexes."""
        _create_video_file(storage_dir, "Film1.mkv")
        _create_video_file(storage_dir, "Film2.mp4")

        service._build_file_index()

        assert len(service._file_index) == 2
        assert service._indexed is True

    def test_ignore_fichiers_non_video(self, storage_dir: Path, service: SymlinkRepairService):
        """Verifie que les fichiers non-video ne sont pas indexes."""
        _create_video_file(storage_dir, "Film.mkv")
        (storage_dir / "readme.txt").write_text("texte")
        (storage_dir / "image.jpg").write_bytes(b"\xff\xd8")
        (storage_dir / "document.pdf").write_bytes(b"%PDF")

        service._build_file_index()

        assert len(service._file_index) == 1

    def test_ignore_symlinks(self, storage_dir: Path, service: SymlinkRepairService):
        """Verifie que les symlinks video ne sont pas indexes."""
        real_file = _create_video_file(storage_dir, "Film.mkv")
        _create_symlink(storage_dir / "Film_link.mkv", real_file)

        service._build_file_index()

        # Seul le fichier reel doit etre indexe, pas le symlink
        total_paths = sum(len(paths) for paths in service._file_index.values())
        assert total_paths == 1

    def test_indexation_recursive(self, storage_dir: Path, service: SymlinkRepairService):
        """Verifie que l'indexation est recursive dans les sous-repertoires."""
        _create_video_file(storage_dir / "Action", "Film1.mkv")
        _create_video_file(storage_dir / "Comedie" / "A-C", "Film2.mp4")
        _create_video_file(storage_dir / "Drame" / "D-F" / "subdir", "Film3.avi")

        service._build_file_index()

        total_paths = sum(len(paths) for paths in service._file_index.values())
        assert total_paths == 3

    def test_idempotent_ne_reconstruit_pas(self, storage_dir: Path, service: SymlinkRepairService):
        """Verifie que l'index n'est construit qu'une seule fois."""
        _create_video_file(storage_dir, "Film1.mkv")

        service._build_file_index()
        assert len(service._file_index) == 1

        # Ajouter un fichier apres la premiere indexation
        _create_video_file(storage_dir, "Film2.mkv")

        # La deuxieme invocation ne doit pas reconstruire l'index
        service._build_file_index()
        total_paths = sum(len(paths) for paths in service._file_index.values())
        assert total_paths == 1  # Toujours 1, pas 2

    def test_fichiers_meme_nom_normalise(self, storage_dir: Path, service: SymlinkRepairService):
        """Verifie que plusieurs fichiers avec le meme nom normalise sont groupes."""
        _create_video_file(storage_dir / "v1", "Mon.Film.mkv", size=1000)
        _create_video_file(storage_dir / "v2", "Mon.Film.mkv", size=2000)

        service._build_file_index()

        normalized = service._normalize_filename("Mon.Film.mkv")
        assert normalized in service._file_index
        assert len(service._file_index[normalized]) == 2

    def test_repertoire_vide(self, storage_dir: Path, service: SymlinkRepairService):
        """Verifie le comportement avec un repertoire de stockage vide."""
        service._build_file_index()

        assert len(service._file_index) == 0
        assert service._indexed is True

    def test_extensions_variees(self, storage_dir: Path, service: SymlinkRepairService):
        """Verifie l'indexation avec differentes extensions video."""
        _create_video_file(storage_dir, "film1.mkv")
        _create_video_file(storage_dir, "film2.mp4")
        _create_video_file(storage_dir, "film3.avi")
        _create_video_file(storage_dir, "film4.mov")
        _create_video_file(storage_dir, "film5.m4v")

        service._build_file_index()

        total_paths = sum(len(paths) for paths in service._file_index.values())
        assert total_paths == 5

    def test_extension_majuscule(self, storage_dir: Path, service: SymlinkRepairService):
        """Verifie que les extensions en majuscules sont aussi indexees."""
        _create_video_file(storage_dir, "Film.MKV")

        service._build_file_index()

        total_paths = sum(len(paths) for paths in service._file_index.values())
        assert total_paths == 1


# ====================
# Tests find_candidates
# ====================


class TestFindCandidates:
    """Tests pour la recherche de candidats de reparation."""

    def test_trouve_fichier_similaire(self, storage_dir: Path, service: SymlinkRepairService):
        """Verifie qu'un fichier similaire est trouve comme candidat."""
        target_file = _create_video_file(storage_dir, "Matrix.1999.FRENCH.1080p.mkv")
        broken_target = Path("/old/storage/Matrix.1999.FRENCH.720p.mkv")

        candidates = service.find_candidates(broken_target, "Matrix (1999).mkv")

        assert len(candidates) >= 1
        assert any(c.path == target_file for c in candidates)

    def test_pas_de_candidat_sous_min_score(self, storage_dir: Path):
        """Verifie qu'aucun candidat n'est retourne si le score est trop bas."""
        _create_video_file(storage_dir, "Titanic.1997.mkv")
        service = SymlinkRepairService(storage_dir=storage_dir, min_score=90.0)
        broken_target = Path("/old/storage/Matrix.1999.mkv")

        candidates = service.find_candidates(broken_target, "Matrix (1999).mkv")

        assert len(candidates) == 0

    def test_candidats_tries_par_score_decroissant(self, storage_dir: Path, service: SymlinkRepairService):
        """Verifie que les candidats sont tries par score decroissant."""
        _create_video_file(storage_dir, "Matrix.1999.FRENCH.1080p.BluRay.mkv")
        _create_video_file(storage_dir, "Matrix.Reloaded.2003.FRENCH.mkv")
        _create_video_file(storage_dir, "Matrix.Revolutions.2003.FRENCH.mkv")
        broken_target = Path("/old/storage/Matrix.1999.FRENCH.720p.mkv")

        candidates = service.find_candidates(broken_target, "Matrix (1999).mkv")

        if len(candidates) >= 2:
            for i in range(len(candidates) - 1):
                assert candidates[i].score >= candidates[i + 1].score

    def test_limite_a_10_candidats(self, storage_dir: Path):
        """Verifie que le nombre de candidats est limite a 10."""
        # Creer 15 fichiers similaires
        for i in range(15):
            _create_video_file(
                storage_dir / f"v{i}",
                f"Film.Generique.2020.version{i}.mkv",
            )

        service = SymlinkRepairService(storage_dir=storage_dir, min_score=30.0)
        broken_target = Path("/old/storage/Film.Generique.2020.mkv")

        candidates = service.find_candidates(broken_target, "Film Generique (2020).mkv")

        assert len(candidates) <= 10

    def test_taille_fichier_dans_candidat(self, storage_dir: Path, service: SymlinkRepairService):
        """Verifie que la taille du fichier est correctement renseignee."""
        file_size = 5000
        _create_video_file(storage_dir, "Matrix.1999.mkv", size=file_size)
        broken_target = Path("/old/storage/Matrix.1999.mkv")

        candidates = service.find_candidates(broken_target, "Matrix (1999).mkv")

        assert len(candidates) >= 1
        assert candidates[0].size_bytes == file_size

    def test_raison_match_nom_cible(self, storage_dir: Path, service: SymlinkRepairService):
        """Verifie que la raison du match inclut 'nom cible similaire'."""
        _create_video_file(storage_dir, "Matrix.1999.FRENCH.mkv")
        broken_target = Path("/old/storage/Matrix.1999.MULTI.mkv")

        candidates = service.find_candidates(broken_target, "ZZZZ.mkv")

        if candidates:
            assert "nom cible similaire" in candidates[0].match_reason

    def test_raison_match_nom_symlink(self, storage_dir: Path, service: SymlinkRepairService):
        """Verifie que la raison du match inclut 'nom symlink similaire'."""
        _create_video_file(storage_dir, "Matrix.1999.FRENCH.mkv")
        broken_target = Path("/old/storage/ZZZZ.mkv")

        candidates = service.find_candidates(broken_target, "Matrix.1999.mkv")

        if candidates:
            assert "nom symlink similaire" in candidates[0].match_reason

    def test_meilleur_score_entre_cible_et_symlink(self, storage_dir: Path, service: SymlinkRepairService):
        """Verifie que le meilleur score entre cible et symlink est utilise."""
        _create_video_file(storage_dir, "Matrix.1999.FRENCH.mkv")

        # La cible est tres differente, mais le symlink est similaire
        broken_target = Path("/old/storage/Fichier.Inconnu.mkv")
        candidates = service.find_candidates(broken_target, "Matrix.1999.mkv")

        # Devrait trouver via la similarite avec le nom du symlink
        assert len(candidates) >= 1

    def test_aucun_fichier_dans_storage(self, storage_dir: Path, service: SymlinkRepairService):
        """Verifie le comportement quand le repertoire de stockage est vide."""
        broken_target = Path("/old/storage/Matrix.1999.mkv")

        candidates = service.find_candidates(broken_target, "Matrix (1999).mkv")

        assert len(candidates) == 0

    def test_construit_index_automatiquement(self, storage_dir: Path, service: SymlinkRepairService):
        """Verifie que find_candidates construit l'index automatiquement."""
        _create_video_file(storage_dir, "Film.mkv")
        broken_target = Path("/old/storage/Film.mkv")

        assert service._indexed is False

        service.find_candidates(broken_target, "Film.mkv")

        assert service._indexed is True


# ====================
# Tests scan_broken_symlinks
# ====================


class TestScanBrokenSymlinks:
    """Tests pour le scan des symlinks brises."""

    def test_detecte_symlink_brise_video(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie la detection d'un symlink brise vers un fichier video."""
        _create_broken_symlink(
            video_dir / "Film.mkv",
            "/nonexistent/Film.mkv",
        )

        results = list(service.scan_broken_symlinks(video_dir))

        assert len(results) == 1
        assert results[0].symlink_path == video_dir / "Film.mkv"
        assert results[0].decision == RepairDecision.NO_MATCH

    def test_ignore_symlink_valide(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie que les symlinks valides sont ignores."""
        real_file = _create_video_file(storage_dir, "Film.mkv")
        _create_symlink(video_dir / "Film.mkv", real_file)

        results = list(service.scan_broken_symlinks(video_dir))

        assert len(results) == 0

    def test_ignore_fichier_non_video(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie que les symlinks brises vers des fichiers non-video sont ignores."""
        _create_broken_symlink(
            video_dir / "readme.txt",
            "/nonexistent/readme.txt",
        )

        results = list(service.scan_broken_symlinks(video_dir))

        assert len(results) == 0

    def test_ignore_fichiers_reguliers(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie que les fichiers reguliers (non-symlinks) sont ignores."""
        _create_video_file(video_dir, "Film.mkv")

        results = list(service.scan_broken_symlinks(video_dir))

        assert len(results) == 0

    def test_ignore_repertoires(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie que les repertoires sont ignores."""
        (video_dir / "SousRepertoire").mkdir()

        results = list(service.scan_broken_symlinks(video_dir))

        assert len(results) == 0

    def test_scan_recursif_sous_repertoires(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie que le scan est recursif dans les sous-repertoires."""
        subdir = video_dir / "Action" / "A-C"
        subdir.mkdir(parents=True)
        _create_broken_symlink(
            subdir / "Film.mkv",
            "/nonexistent/Film.mkv",
        )

        results = list(service.scan_broken_symlinks(video_dir))

        assert len(results) == 1

    def test_plusieurs_symlinks_brises(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie la detection de plusieurs symlinks brises."""
        _create_broken_symlink(video_dir / "Film1.mkv", "/nonexistent/Film1.mkv")
        _create_broken_symlink(video_dir / "Film2.mp4", "/nonexistent/Film2.mp4")
        _create_broken_symlink(video_dir / "Film3.avi", "/nonexistent/Film3.avi")

        results = list(service.scan_broken_symlinks(video_dir))

        assert len(results) == 3

    def test_melange_symlinks_brises_et_valides(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie le scan avec un melange de symlinks brises et valides."""
        real_file = _create_video_file(storage_dir, "Valide.mkv")
        _create_symlink(video_dir / "Valide.mkv", real_file)
        _create_broken_symlink(video_dir / "Brise.mkv", "/nonexistent/Brise.mkv")

        results = list(service.scan_broken_symlinks(video_dir))

        assert len(results) == 1
        assert results[0].symlink_path == video_dir / "Brise.mkv"

    def test_symlink_brise_avec_candidats(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie qu'un symlink brise avec des candidats retourne les candidats."""
        _create_video_file(storage_dir, "Matrix.1999.FRENCH.1080p.mkv")
        _create_broken_symlink(
            video_dir / "Matrix.1999.mkv",
            "/nonexistent/Matrix.1999.FRENCH.720p.mkv",
        )

        results = list(service.scan_broken_symlinks(video_dir))

        assert len(results) == 1
        assert len(results[0].candidates) >= 1

    def test_symlink_brise_sans_candidats(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie qu'un symlink brise sans candidats retourne NO_MATCH."""
        _create_broken_symlink(
            video_dir / "Film.Introuvable.mkv",
            "/nonexistent/Film.Introuvable.mkv",
        )

        results = list(service.scan_broken_symlinks(video_dir))

        assert len(results) == 1
        assert results[0].decision == RepairDecision.NO_MATCH
        assert results[0].candidates == []

    def test_generateur_yield_resultats(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie que scan_broken_symlinks est un generateur (yield)."""
        _create_broken_symlink(video_dir / "Film.mkv", "/nonexistent/Film.mkv")

        # scan_broken_symlinks retourne un generateur, pas une liste
        gen = service.scan_broken_symlinks(video_dir)
        from types import GeneratorType
        assert isinstance(gen, GeneratorType)

    def test_extensions_video_variees(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie la detection de symlinks brises avec differentes extensions video."""
        for ext in [".mkv", ".mp4", ".avi", ".mov", ".m4v"]:
            _create_broken_symlink(
                video_dir / f"Film{ext}",
                f"/nonexistent/Film{ext}",
            )

        results = list(service.scan_broken_symlinks(video_dir))

        assert len(results) == 5

    def test_repertoire_vide(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie le comportement avec un repertoire video vide."""
        results = list(service.scan_broken_symlinks(video_dir))

        assert len(results) == 0


# ====================
# Tests repair_symlink
# ====================


class TestRepairSymlink:
    """Tests pour la reparation effective des symlinks."""

    def test_reparation_reussie(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie qu'un symlink est correctement repare."""
        new_target = _create_video_file(storage_dir, "Matrix.1999.FRENCH.1080p.mkv")
        broken_link = _create_broken_symlink(
            video_dir / "Matrix.mkv",
            "/nonexistent/Matrix.mkv",
        )

        result = service.repair_symlink(broken_link, new_target)

        assert result.decision == RepairDecision.REPAIRED
        assert result.new_target == new_target
        # Le symlink doit maintenant pointer vers la nouvelle cible
        assert broken_link.is_symlink()
        assert broken_link.resolve() == new_target.resolve()

    def test_symlink_pointe_vers_nouvelle_cible(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie que le symlink repare pointe bien vers le nouveau fichier."""
        new_target = _create_video_file(storage_dir, "Film.mkv", size=4096)
        broken_link = _create_broken_symlink(
            video_dir / "Film.mkv",
            "/nonexistent/Film.mkv",
        )

        service.repair_symlink(broken_link, new_target)

        # Le fichier doit etre lisible via le symlink
        assert broken_link.stat().st_size == 4096

    def test_dry_run_ne_modifie_pas(
        self, storage_dir: Path, video_dir: Path, service_dry_run: SymlinkRepairService
    ):
        """Verifie que le mode dry-run ne modifie pas le systeme de fichiers."""
        new_target = _create_video_file(storage_dir, "Film.mkv")
        broken_link = _create_broken_symlink(
            video_dir / "Film.mkv",
            "/nonexistent/Film.mkv",
        )

        result = service_dry_run.repair_symlink(broken_link, new_target)

        # Le resultat indique REPAIRED
        assert result.decision == RepairDecision.REPAIRED
        assert result.new_target == new_target
        # Mais le symlink original n'est PAS modifie
        assert broken_link.is_symlink()
        assert not os.path.exists(broken_link)  # Toujours brise

    def test_dry_run_conserve_cible_originale(
        self, storage_dir: Path, video_dir: Path, service_dry_run: SymlinkRepairService
    ):
        """Verifie que le mode dry-run conserve la cible originale dans le resultat."""
        new_target = _create_video_file(storage_dir, "Film.mkv")
        original_target_path = "/nonexistent/Film.Original.mkv"
        broken_link = _create_broken_symlink(
            video_dir / "Film.mkv",
            original_target_path,
        )

        result = service_dry_run.repair_symlink(broken_link, new_target)

        assert result.original_target is not None

    def test_erreur_symlink_inexistant(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie la gestion d'erreur quand le symlink n'existe pas."""
        nonexistent_link = video_dir / "inexistant.mkv"
        new_target = _create_video_file(storage_dir, "Film.mkv")

        result = service.repair_symlink(nonexistent_link, new_target)

        assert result.decision == RepairDecision.ERROR
        assert result.error_message is not None

    def test_resultat_contient_ancienne_cible(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie que le resultat contient l'ancienne cible du symlink."""
        new_target = _create_video_file(storage_dir, "Film.Nouveau.mkv")
        broken_link = _create_broken_symlink(
            video_dir / "Film.mkv",
            "/ancien/chemin/Film.mkv",
        )

        result = service.repair_symlink(broken_link, new_target)

        assert result.original_target is not None
        assert result.decision == RepairDecision.REPAIRED

    def test_reparation_successive(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie que plusieurs reparations successives fonctionnent."""
        target1 = _create_video_file(storage_dir, "Film1.mkv")
        target2 = _create_video_file(storage_dir, "Film2.mkv")

        link1 = _create_broken_symlink(video_dir / "Link1.mkv", "/nonexistent/1.mkv")
        link2 = _create_broken_symlink(video_dir / "Link2.mkv", "/nonexistent/2.mkv")

        result1 = service.repair_symlink(link1, target1)
        result2 = service.repair_symlink(link2, target2)

        assert result1.decision == RepairDecision.REPAIRED
        assert result2.decision == RepairDecision.REPAIRED
        assert link1.resolve() == target1.resolve()
        assert link2.resolve() == target2.resolve()


# ====================
# Tests d'integration service complet
# ====================


class TestIntegrationSymlinkRepair:
    """Tests d'integration combinant plusieurs methodes du service."""

    def test_scan_et_reparation_complete(
        self, storage_dir: Path, video_dir: Path, service: SymlinkRepairService
    ):
        """Verifie le flux complet : scan -> trouver candidats -> reparer."""
        # Creer un fichier reel dans storage
        real_file = _create_video_file(storage_dir, "Matrix.1999.FRENCH.1080p.BluRay.mkv")
        # Creer un symlink brise dans video
        _create_broken_symlink(
            video_dir / "Matrix (1999).mkv",
            "/old/storage/Matrix.1999.FRENCH.720p.mkv",
        )

        # Scanner
        results = list(service.scan_broken_symlinks(video_dir))
        assert len(results) == 1

        broken_result = results[0]
        assert broken_result.decision == RepairDecision.NO_MATCH
        assert len(broken_result.candidates) >= 1

        # Reparer avec le meilleur candidat
        best_candidate = broken_result.candidates[0]
        repair_result = service.repair_symlink(
            broken_result.symlink_path, best_candidate.path
        )

        assert repair_result.decision == RepairDecision.REPAIRED
        assert (video_dir / "Matrix (1999).mkv").resolve() == real_file.resolve()

    def test_min_score_personalise(self, storage_dir: Path, tmp_path: Path):
        """Verifie que le min_score personnalise filtre correctement."""
        _create_video_file(storage_dir, "Film.Generique.mkv")

        # Avec un score minimum tres eleve, aucun candidat ne doit etre trouve
        service_strict = SymlinkRepairService(
            storage_dir=storage_dir, min_score=99.0
        )
        broken_target = Path("/old/Film.Generique.Modifie.mkv")
        candidates = service_strict.find_candidates(broken_target, "Autre.Nom.mkv")

        assert len(candidates) == 0

    def test_service_avec_storage_vide(self, tmp_path: Path):
        """Verifie le comportement du service avec un storage completement vide."""
        empty_storage = tmp_path / "empty_storage"
        empty_storage.mkdir()
        video_d = tmp_path / "video"
        video_d.mkdir()

        service = SymlinkRepairService(storage_dir=empty_storage)
        _create_broken_symlink(video_d / "Film.mkv", "/nonexistent/Film.mkv")

        results = list(service.scan_broken_symlinks(video_d))

        assert len(results) == 1
        assert results[0].decision == RepairDecision.NO_MATCH
        assert results[0].candidates == []
