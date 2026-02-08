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

    def test_execute_creates_dirs_and_moves(self, tmp_path: Path) -> None:
        """Vérifier la création des répertoires et le déplacement des fichiers."""
        video_dir = tmp_path / "video"
        storage_dir = tmp_path / "storage"

        rel_dir = "Films/Drame/A-Ami"
        filenames = [
            "American Beauty (1999) MULTi HEVC 1080p.mkv",
            "American History X (1998) MULTi HEVC 1080p.mkv",
            "American Son (2019) MULTi x264 1080p.mkv",
        ]

        files = []
        for name in filenames:
            video_file, storage_file = self._create_symlink_and_storage(
                video_dir, storage_dir, f"{rel_dir}/{name}"
            )
            files.append(video_file)

        group = PrefixGroup(
            parent_dir=video_dir / rel_dir,
            prefix="American",
            files=files,
        )

        service = PrefixGrouperService()
        moved = service.execute([group], video_dir, storage_dir)

        assert moved == 3

        # Vérifier que les fichiers sont déplacés dans le sous-répertoire
        american_video = video_dir / rel_dir / "American"
        american_storage = storage_dir / rel_dir / "American"

        assert american_video.is_dir()
        assert american_storage.is_dir()

        for name in filenames:
            # Fichier storage dans le nouveau répertoire
            assert (american_storage / name).is_file()
            # Symlink dans le nouveau répertoire, pointant vers storage
            new_link = american_video / name
            assert new_link.is_symlink()
            assert new_link.resolve() == (american_storage / name).resolve()

            # Ancien emplacement supprimé
            assert not (video_dir / rel_dir / name).exists()
            assert not (storage_dir / rel_dir / name).exists()

    def test_execute_returns_zero_for_empty_groups(self, tmp_path: Path) -> None:
        """Pas de groupes → retourne 0."""
        service = PrefixGrouperService()
        moved = service.execute([], tmp_path / "video", tmp_path / "storage")
        assert moved == 0
