"""
Tests unitaires pour PrefixGrouperService.

Tests TDD pour la détection de préfixes récurrents et le regroupement
de fichiers dans des sous-répertoires de préfixe.
"""

from pathlib import Path

import pytest

from src.services.prefix_grouper import (
    PrefixGroup,
    PrefixGrouperService,
    extract_title_from_filename,
    extract_first_word,
    save_regroup_cache,
    load_regroup_cache,
)


# ====================
# Tests extract_title_from_filename
# ====================

class TestExtractTitleFromFilename:
    """Tests pour l'extraction du titre depuis un nom de fichier."""

    def test_standard_movie_filename(self) -> None:
        """Format standard avec année entre parenthèses."""
        assert extract_title_from_filename(
            "American Beauty (1999) MULTi HEVC 1080p.mkv"
        ) == "American Beauty"

    def test_filename_without_year(self) -> None:
        """Nom sans année retourne tout sauf l'extension."""
        assert extract_title_from_filename(
            "SomeMovie.mkv"
        ) == "SomeMovie"

    def test_filename_with_article(self) -> None:
        """Article L' strippé par extract_title."""
        assert extract_title_from_filename(
            "L'Amant (1992) FR HEVC 1080p.mkv"
        ) == "L'Amant"

    def test_filename_with_multiple_parentheses(self) -> None:
        """Prend tout avant la première année entre parenthèses."""
        assert extract_title_from_filename(
            "Batman (The Dark Knight) (2008) MULTi HEVC 1080p.mkv"
        ) == "Batman (The Dark Knight)"

    def test_empty_filename(self) -> None:
        """Nom vide retourne vide."""
        assert extract_title_from_filename("") == ""

    def test_filename_year_at_start(self) -> None:
        """Année au début (pas entre parenthèses) ne confond pas."""
        assert extract_title_from_filename(
            "2001 A Space Odyssey (1968) MULTi HEVC 1080p.mkv"
        ) == "2001 A Space Odyssey"


# ====================
# Tests extract_first_word
# ====================

class TestExtractFirstWord:
    """Tests pour l'extraction du premier mot significatif."""

    def test_simple_title(self) -> None:
        """Premier mot simple."""
        assert extract_first_word("American Beauty") == "American"

    def test_with_article_le(self) -> None:
        """Article 'Le' strippé, retourne le premier mot après."""
        assert extract_first_word("Le Monde") == "Monde"

    def test_with_article_l_apostrophe(self) -> None:
        """Article L' strippé, retourne le premier mot après."""
        assert extract_first_word("L'Amant") == "Amant"

    def test_with_article_les(self) -> None:
        """Article 'Les' strippé."""
        assert extract_first_word("Les Amants") == "Amants"

    def test_compound_word(self) -> None:
        """Mot composé avec tiret est un seul token."""
        assert extract_first_word("Au-delà des Murs") == "Au-delà"

    def test_single_word(self) -> None:
        """Un seul mot."""
        assert extract_first_word("Batman") == "Batman"

    def test_empty_string(self) -> None:
        """Chaîne vide retourne vide."""
        assert extract_first_word("") == ""

    def test_with_article_the(self) -> None:
        """Article anglais 'The' strippé."""
        assert extract_first_word("The Matrix") == "Matrix"


# ====================
# Tests PrefixGrouperService.analyze
# ====================

class TestPrefixGrouperAnalyze:
    """Tests pour la détection de groupes de préfixes."""

    def _create_movie_file(self, directory: Path, name: str) -> Path:
        """Helper : crée un fichier film dans le répertoire."""
        filepath = directory / name
        filepath.touch()
        return filepath

    def test_find_prefix_groups_basic(self, tmp_path: Path) -> None:
        """4 fichiers 'American *' → 1 groupe 'American'."""
        parent = tmp_path / "A-Ami"
        parent.mkdir()
        self._create_movie_file(parent, "American Beauty (1999) MULTi HEVC 1080p.mkv")
        self._create_movie_file(parent, "American History X (1998) MULTi HEVC 1080p.mkv")
        self._create_movie_file(parent, "American Son (2019) MULTi x264 1080p.mkv")
        self._create_movie_file(parent, "American Translation (2011) FR HEVC 1080p.mkv")
        # Fichier sans le préfixe
        self._create_movie_file(parent, "Amadeus (1984) MULTi HEVC 1080p.mkv")

        service = PrefixGrouperService()
        groups = service.analyze(tmp_path, min_count=3)

        assert len(groups) == 1
        assert groups[0].prefix == "American"
        assert len(groups[0].files) == 4

    def test_find_prefix_groups_with_article(self, tmp_path: Path) -> None:
        """'L'Amant', 'Les Amants', 'L'Amante' → groupe 'Amant'."""
        parent = tmp_path / "A-Ami"
        parent.mkdir()
        self._create_movie_file(parent, "L'Amant (1992) FR HEVC 1080p.mkv")
        self._create_movie_file(parent, "Les Amants (1958) FR HEVC 1080p.mkv")
        self._create_movie_file(parent, "L'Amante (2020) FR HEVC 1080p.mkv")

        service = PrefixGrouperService()
        groups = service.analyze(tmp_path, min_count=3)

        assert len(groups) == 1
        assert groups[0].prefix == "Amant"
        assert len(groups[0].files) == 3

    def test_find_prefix_groups_below_threshold(self, tmp_path: Path) -> None:
        """1 seul fichier 'American' → pas de groupe (seuil 3)."""
        parent = tmp_path / "A-Ami"
        parent.mkdir()
        self._create_movie_file(parent, "American Beauty (1999) MULTi HEVC 1080p.mkv")

        service = PrefixGrouperService()
        groups = service.analyze(tmp_path, min_count=3)

        assert len(groups) == 0

    def test_find_prefix_groups_compound_word(self, tmp_path: Path) -> None:
        """'Au-delà *' → groupe 'Au-delà' (mot composé)."""
        parent = tmp_path / "A-Ami"
        parent.mkdir()
        # Note : 'Au' est un article strippé → "delà" -> premier mot "Au-delà"
        # Mais en réalité "Au-delà" traité sans article → le premier mot est "Au-delà"
        # car strip_article retire "Au " (espace), mais "Au-delà" n'a pas d'espace après "Au"
        self._create_movie_file(parent, "Au-delà des Murs (2012) FR HEVC 1080p.mkv")
        self._create_movie_file(parent, "Au-delà du Réel (1999) FR HEVC 1080p.mkv")
        self._create_movie_file(parent, "Au-delà des Limites (2018) FR HEVC 1080p.mkv")

        service = PrefixGrouperService()
        groups = service.analyze(tmp_path, min_count=3)

        assert len(groups) == 1
        assert groups[0].prefix == "Au-delà"
        assert len(groups[0].files) == 3

    def test_merge_prefix_groups(self, tmp_path: Path) -> None:
        """Fusion 'Amant' + 'Amants' + 'Amante' → 'Amant' (plus court)."""
        parent = tmp_path / "A-Ami"
        parent.mkdir()
        self._create_movie_file(parent, "Amant de Lady Chatterley (1955) FR HEVC 1080p.mkv")
        self._create_movie_file(parent, "Amants du Pont-Neuf (1991) FR HEVC 1080p.mkv")
        self._create_movie_file(parent, "Amante (2020) FR HEVC 1080p.mkv")

        service = PrefixGrouperService()
        groups = service.analyze(tmp_path, min_count=3)

        assert len(groups) == 1
        assert groups[0].prefix == "Amant"
        assert len(groups[0].files) == 3

    def test_analyze_full_directory(self, tmp_path: Path) -> None:
        """Analyse complète : structure avec 2 groupes potentiels."""
        # Créer une structure réaliste
        a_ami = tmp_path / "A-Ami"
        a_ami.mkdir()
        # Groupe "American" (4 fichiers)
        self._create_movie_file(a_ami, "American Beauty (1999) MULTi HEVC 1080p.mkv")
        self._create_movie_file(a_ami, "American History X (1998) MULTi HEVC 1080p.mkv")
        self._create_movie_file(a_ami, "American Son (2019) MULTi x264 1080p.mkv")
        self._create_movie_file(a_ami, "American Translation (2011) FR HEVC 1080p.mkv")
        # Groupe insuffisant (2 fichiers "Amadeus")
        self._create_movie_file(a_ami, "Amadeus (1984) MULTi HEVC 1080p.mkv")
        self._create_movie_file(a_ami, "Amadeus Director Cut (1984) FR HEVC 1080p.mkv")
        # Fichier isolé
        self._create_movie_file(a_ami, "Alien (1979) MULTi HEVC 1080p.mkv")

        service = PrefixGrouperService()
        groups = service.analyze(tmp_path, min_count=3)

        assert len(groups) == 1
        assert groups[0].prefix == "American"

    def test_analyze_excludes_existing_prefix_dirs(self, tmp_path: Path) -> None:
        """Les fichiers déjà dans un sous-répertoire préfixe ne sont pas re-groupés."""
        a_ami = tmp_path / "A-Ami"
        # Répertoire préfixe existant avec fichiers
        american_dir = a_ami / "American"
        american_dir.mkdir(parents=True)
        self._create_movie_file(american_dir, "American Beauty (1999) MULTi HEVC 1080p.mkv")
        self._create_movie_file(american_dir, "American History X (1998) MULTi HEVC 1080p.mkv")
        self._create_movie_file(american_dir, "American Son (2019) MULTi x264 1080p.mkv")

        service = PrefixGrouperService()
        groups = service.analyze(tmp_path, min_count=3)

        # Pas de groupe car les fichiers sont déjà regroupés
        assert len(groups) == 0

    def test_analyze_skips_title_directory(self, tmp_path: Path) -> None:
        """Pas de regroupement dans un répertoire-titre (Resident Evil/, Le Seigneur des Anneaux/)."""
        # Cas 1 : répertoire-titre simple
        resident = tmp_path / "Pe-R" / "Resident Evil"
        resident.mkdir(parents=True)
        self._create_movie_file(resident, "Resident Evil  -  Damnation (2012) MULTi x264 1080p.mkv")
        self._create_movie_file(resident, "Resident Evil  -  Degeneration (2008) MULTi x264 1080p.mkv")
        self._create_movie_file(resident, "Resident Evil  -  Vendetta (2017) MULTi x264 1080p.mkv")

        service = PrefixGrouperService()
        groups = service.analyze(tmp_path, min_count=3)

        assert len(groups) == 0

    def test_analyze_skips_title_directory_with_article(self, tmp_path: Path) -> None:
        """Pas de regroupement dans 'Le Seigneur des Anneaux/' (article strippé → Seigneur)."""
        sda = tmp_path / "H-Z" / "S" / "Le Seigneur des Anneaux" / "1080p"
        sda.mkdir(parents=True)
        self._create_movie_file(sda, "Le Seigneur des anneaux  -  La Communauté de l'Anneau (2001) MULTi HEVC 1080p.mkv")
        self._create_movie_file(sda, "Le Seigneur des anneaux  -  Le Retour du roi (2003) MULTi HEVC 1080p.mkv")
        self._create_movie_file(sda, "Le Seigneur des anneaux  -  Les Deux Tours (2002) MULTi HEVC 1080p.mkv")

        service = PrefixGrouperService()
        groups = service.analyze(tmp_path, min_count=3)

        assert len(groups) == 0

    def test_analyze_recurses_into_subdirs(self, tmp_path: Path) -> None:
        """L'analyse scan les sous-répertoires (plages) récursivement."""
        # Structure : genre/A-Ami/ contient des fichiers
        genre = tmp_path / "Films" / "Drame"
        a_ami = genre / "A-Ami"
        a_ami.mkdir(parents=True)
        self._create_movie_file(a_ami, "American Beauty (1999) MULTi HEVC 1080p.mkv")
        self._create_movie_file(a_ami, "American History X (1998) MULTi HEVC 1080p.mkv")
        self._create_movie_file(a_ami, "American Son (2019) MULTi x264 1080p.mkv")

        service = PrefixGrouperService()
        groups = service.analyze(tmp_path, min_count=3)

        assert len(groups) == 1
        assert groups[0].parent_dir == a_ami


# ====================
# Tests PrefixGrouperService.execute
# ====================

class TestPrefixGrouperExecute:
    """Tests pour l'exécution du regroupement."""

    def _create_symlink_and_storage(
        self, video_dir: Path, storage_dir: Path, rel_path: str
    ) -> tuple[Path, Path]:
        """Helper : crée un symlink et le fichier storage correspondant."""
        video_file = video_dir / rel_path
        storage_file = storage_dir / rel_path
        storage_file.parent.mkdir(parents=True, exist_ok=True)
        storage_file.touch()
        video_file.parent.mkdir(parents=True, exist_ok=True)
        video_file.symlink_to(storage_file)
        return video_file, storage_file

    def test_execute_creates_dirs_and_moves_symlinks(self, tmp_path: Path) -> None:
        """Vérifier la création du répertoire préfixe et le déplacement des symlinks."""
        video_dir = tmp_path / "video"
        storage_dir = tmp_path / "storage"

        rel_dir = "Films/Drame/A-Ami"
        filenames = [
            "American Beauty (1999) MULTi HEVC 1080p.mkv",
            "American History X (1998) MULTi HEVC 1080p.mkv",
            "American Son (2019) MULTi x264 1080p.mkv",
        ]

        files = []
        original_targets = {}
        for name in filenames:
            video_file, storage_file = self._create_symlink_and_storage(
                video_dir, storage_dir, f"{rel_dir}/{name}"
            )
            files.append(video_file)
            original_targets[name] = storage_file

        group = PrefixGroup(
            parent_dir=video_dir / rel_dir,
            prefix="American",
            files=files,
        )

        service = PrefixGrouperService()
        moved = service.execute([group], video_dir, storage_dir)

        assert moved == 3

        american_video = video_dir / rel_dir / "American"
        assert american_video.is_dir()

        for name in filenames:
            # Le fichier storage n'est PAS déplacé — il reste à son emplacement original
            assert original_targets[name].is_file()

            # Le symlink est dans le nouveau répertoire préfixe
            new_link = american_video / name
            assert new_link.is_symlink()
            # Il pointe vers la même cible storage qu'avant
            assert new_link.resolve() == original_targets[name].resolve()

            # L'ancien symlink est supprimé
            assert not (video_dir / rel_dir / name).exists()

    def test_execute_returns_zero_for_empty_groups(self, tmp_path: Path) -> None:
        """Pas de groupes → retourne 0."""
        service = PrefixGrouperService()
        moved = service.execute([], tmp_path / "video", tmp_path / "storage")
        assert moved == 0

    def test_execute_symlink_storage_never_touched(self, tmp_path: Path) -> None:
        """Le storage (NAS) n'est jamais modifié — seuls les symlinks bougent."""
        video_dir = tmp_path / "video"
        storage_dir = tmp_path / "storage"
        # Stockage réel dans un chemin DIFFÉRENT de storage_dir
        actual_nas = tmp_path / "actual_nas"

        rel_dir = "Documentaire/Arts"
        filenames = [
            "Art moderne (2020) FR x264 1080p.mkv",
            "Art nouveau (2019) FR x264 1080p.mkv",
            "Art déco (2018) FR x264 1080p.mkv",
        ]

        files = []
        original_targets = {}
        for name in filenames:
            # Fichier physique sur le NAS
            real_file = actual_nas / rel_dir / name
            real_file.parent.mkdir(parents=True, exist_ok=True)
            real_file.write_text("contenu")

            # Symlink dans video_dir pointant vers le NAS
            video_file = video_dir / rel_dir / name
            video_file.parent.mkdir(parents=True, exist_ok=True)
            video_file.symlink_to(real_file)
            files.append(video_file)
            original_targets[name] = real_file

        group = PrefixGroup(
            parent_dir=video_dir / rel_dir,
            prefix="Art",
            files=files,
        )

        service = PrefixGrouperService()
        moved = service.execute([group], video_dir, storage_dir)

        assert moved == 3

        # Les fichiers NAS n'ont PAS bougé
        for name in filenames:
            assert original_targets[name].exists(), f"Fichier NAS déplacé par erreur: {name}"

        # Les symlinks sont dans le répertoire préfixe et pointent vers les MÊMES cibles
        for name in filenames:
            new_link = video_dir / rel_dir / "Art" / name
            assert new_link.is_symlink(), f"Symlink manquant: {new_link}"
            assert new_link.resolve() == original_targets[name].resolve()

    def test_execute_regular_files_moved_directly(self, tmp_path: Path) -> None:
        """Fichiers réguliers (pas symlinks) déplacés directement dans le répertoire préfixe."""
        video_dir = tmp_path / "video"
        storage_dir = tmp_path / "storage"

        rel_dir = "Documentaire/Histoire"
        filenames = [
            "Rome antique (2020) FR 1080p.mkv",
            "Rome impériale (2019) FR 1080p.mkv",
            "Rome, ville ouverte (1945) FR 1080p.mkv",
        ]

        files = []
        for name in filenames:
            video_file = video_dir / rel_dir / name
            video_file.parent.mkdir(parents=True, exist_ok=True)
            video_file.write_text("contenu")
            files.append(video_file)

        group = PrefixGroup(
            parent_dir=video_dir / rel_dir,
            prefix="Rome",
            files=files,
        )

        service = PrefixGrouperService()
        moved = service.execute([group], video_dir, storage_dir)

        assert moved == 3

        for name in filenames:
            moved_file = video_dir / rel_dir / "Rome" / name
            assert moved_file.exists(), f"Fichier manquant: {moved_file}"
            assert not moved_file.is_symlink()
            # Ancien emplacement supprimé
            assert not (video_dir / rel_dir / name).exists()

    def test_execute_progress_callback(self, tmp_path: Path) -> None:
        """Le callback de progression est appelé pour chaque groupe."""
        video_dir = tmp_path / "video"
        storage_dir = tmp_path / "storage"

        rel_dir = "Films/Drame/A"
        filenames = [
            "Alpha (2018) FR 1080p.mkv",
            "Alpha Dog (2006) FR 1080p.mkv",
            "Alpha et Omega (2010) FR 1080p.mkv",
        ]

        files = []
        for name in filenames:
            f = video_dir / rel_dir / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("contenu")
            files.append(f)

        group = PrefixGroup(
            parent_dir=video_dir / rel_dir,
            prefix="Alpha",
            files=files,
        )

        callbacks = []
        service = PrefixGrouperService()
        service.execute(
            [group], video_dir, storage_dir,
            progress_callback=lambda p, c: callbacks.append((p, c)),
        )

        assert callbacks == [("Alpha", 3)]


# ====================
# Tests cache regroup
# ====================

class TestRegroupCache:
    """Tests pour la sauvegarde/chargement du cache regroup."""

    def test_save_and_load_cache(self, tmp_path: Path) -> None:
        """Le cache sauvegardé est rechargé avec les mêmes données."""
        video_dir = Path("/media/Serveur/test/Films")
        storage_dir = Path("/media/Serveur/storage/Films")
        groups = [
            PrefixGroup(
                parent_dir=Path("/media/Serveur/test/Films/Drame/A-Ami"),
                prefix="American",
                files=[
                    Path("/media/Serveur/test/Films/Drame/A-Ami/American Beauty (1999).mkv"),
                    Path("/media/Serveur/test/Films/Drame/A-Ami/American History X (1998).mkv"),
                ],
            ),
        ]

        save_regroup_cache(video_dir, storage_dir, groups, cache_dir=tmp_path)
        result = load_regroup_cache(cache_dir=tmp_path)

        assert result is not None
        loaded_video, loaded_storage, loaded_groups = result
        assert loaded_video == video_dir
        assert loaded_storage == storage_dir
        assert len(loaded_groups) == 1
        assert loaded_groups[0].prefix == "American"
        assert len(loaded_groups[0].files) == 2

    def test_load_cache_expired(self, tmp_path: Path) -> None:
        """Un cache expiré retourne None."""
        save_regroup_cache(Path("/v"), Path("/s"), [], cache_dir=tmp_path)

        # Charger avec max_age_minutes=0 → expiré immédiatement
        result = load_regroup_cache(max_age_minutes=0, cache_dir=tmp_path)
        assert result is None

    def test_load_cache_missing(self, tmp_path: Path) -> None:
        """Pas de fichier cache → retourne None."""
        result = load_regroup_cache(cache_dir=tmp_path)
        assert result is None
