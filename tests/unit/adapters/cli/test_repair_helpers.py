"""
Tests unitaires pour les helpers de repair-links.

TDD tests couvrant:
- Extraction du nom de serie
- Auto-reparation des episodes apres confirmation du premier episode
- Enregistrement et consultation des series confirmees
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.adapters.cli.repair import InteractiveRepair, extract_series_name


# ============================================================================
# Tests extract_series_name
# ============================================================================


class TestExtractSeriesName:
    """Tests pour l'extraction du nom de serie depuis un chemin."""

    def test_standard_series_path(self):
        path = Path("/media/Serveur/test/Séries/Séries TV/A-M/Breaking Bad/Saison 01/ep.mkv")
        assert extract_series_name(path) == "Breaking Bad"

    def test_animation_series_path(self):
        path = Path(
            "/media/Serveur/test/Séries/Animation (Courts ou à épisodes)/T/"
            "The Amazing World of Gumball (2011)/Saison 5/ep.mkv"
        )
        assert extract_series_name(path) == "The Amazing World of Gumball (2011)"

    def test_documentary_series_path(self):
        """Les sous-categories documentaires sont bien ignorees."""
        path = Path(
            "/media/Serveur/test/Séries/Séries documentaires/Science/"
            "Strip The City/Dessous/ep.mkv"
        )
        assert extract_series_name(path) == "Strip The City"

    def test_documentary_with_geography(self):
        """Documentaire avec sous-genre Geographie."""
        path = Path(
            "/media/Serveur/test/Séries/Séries documentaires/Science/Géographie/"
            "Planet Earth II - VOSTFR/Planète/ep.mkv"
        )
        assert extract_series_name(path) == "Planet Earth II - VOSTFR"

    def test_no_series_in_path(self):
        path = Path("/media/Serveur/test/Films/Action/A-L/film.mkv")
        assert extract_series_name(path) is None


# ============================================================================
# Tests auto-reparation series
# ============================================================================


class TestSeriesAutoRepair:
    """Tests pour l'auto-reparation des episodes de series apres confirmation."""

    def setup_method(self):
        self.ir = InteractiveRepair()

    # ---- _get_nas_series_dir ----

    def test_get_nas_series_dir_with_saison(self):
        """Extrait le repertoire serie NAS depuis un chemin avec Saison."""
        target = Path(
            "/media/NAS64/Séries/Animation/M/"
            "Le monde incroyable de Gumball/Saison 5/"
            "Le Monde Incroyable de Gumball - S05E31.mkv"
        )
        result = self.ir._get_nas_series_dir(target)
        assert result == Path(
            "/media/NAS64/Séries/Animation/M/"
            "Le monde incroyable de Gumball"
        )

    def test_get_nas_series_dir_without_saison_fallback_parent(self):
        """Retourne target.parent si pas de composant 'Saison' (fichiers directs)."""
        target = Path(
            "/media/NAS64/Séries/Séries documentaires/Science/Géographie/"
            "Planet Earth II - VOSTFR/"
            "Planet.Earth.II.S01E05.720p.BluRay.x264-ROVERS.mkv"
        )
        result = self.ir._get_nas_series_dir(target)
        assert result == Path(
            "/media/NAS64/Séries/Séries documentaires/Science/Géographie/"
            "Planet Earth II - VOSTFR"
        )

    def test_get_nas_series_dir_saison_at_different_depth(self):
        """Fonctionne meme si Saison est a une profondeur differente."""
        target = Path(
            "/media/NAS64/Séries/Mangas/N/"
            "Naruto/Saison 01/Naruto - S01E01.mkv"
        )
        result = self.ir._get_nas_series_dir(target)
        assert result == Path("/media/NAS64/Séries/Mangas/N/Naruto")

    # ---- _register_confirmed_series ----

    def test_register_confirmed_series_with_saison(self):
        """Enregistre avec link.parent comme cle et NAS series dir comme valeur."""
        link = Path(
            "/media/Serveur/test/Séries/Animation (Courts ou à épisodes)/T/"
            "The Amazing World of Gumball (2011)/Saison 5/"
            "The Amazing World of Gumball (2011) - S05E31.mkv"
        )
        target = Path(
            "/media/NAS64/Séries/Animation/M/"
            "Le monde incroyable de Gumball/Saison 5/"
            "Le Monde Incroyable de Gumball - S05E31.mkv"
        )
        self.ir._register_confirmed_series(link, target)

        key = str(link.parent)
        assert key in self.ir.confirmed_series
        assert self.ir.confirmed_series[key] == Path(
            "/media/NAS64/Séries/Animation/M/Le monde incroyable de Gumball"
        )

    def test_register_confirmed_series_without_saison(self):
        """Enregistre meme sans composant Saison (fallback sur target.parent)."""
        link = Path(
            "/media/Serveur/test/Séries/Séries documentaires/Science/Géographie/"
            "Planet Earth II - VOSTFR/Planète/"
            "Planète Terre II - S01E05 - Les Prairies.mkv"
        )
        target = Path(
            "/media/NAS64/Séries/Séries documentaires/Science/Géographie/"
            "Planet Earth II - VOSTFR/"
            "Planet.Earth.II.S01E05.720p.BluRay.x264-ROVERS.mkv"
        )
        self.ir._register_confirmed_series(link, target)

        key = str(link.parent)
        assert key in self.ir.confirmed_series
        assert self.ir.confirmed_series[key] == Path(
            "/media/NAS64/Séries/Séries documentaires/Science/Géographie/"
            "Planet Earth II - VOSTFR"
        )

    # ---- _check_series_auto_repair ----

    def test_auto_repair_when_series_confirmed(self):
        """Auto-repare si le repertoire parent est confirme et le candidat correspond."""
        link = Path(
            "/media/Serveur/test/Séries/Animation/T/"
            "The Amazing World of Gumball (2011)/Saison 5/"
            "The Amazing World of Gumball (2011) - S05E33.mkv"
        )
        # Simuler la confirmation d'un episode precedent (meme parent)
        self.ir.confirmed_series[str(link.parent)] = Path(
            "/media/NAS64/Séries/Animation/M/Le monde incroyable de Gumball"
        )

        candidate = Path(
            "/media/NAS64/Séries/Animation/M/"
            "Le monde incroyable de Gumball/Saison 5/"
            "Le Monde Incroyable de Gumball - S05E33.mkv"
        )
        targets = [(candidate, 82.0)]

        result = self.ir._check_series_auto_repair(
            "The Amazing World of Gumball (2011)", link, targets
        )
        assert result == candidate

    def test_no_auto_repair_when_not_confirmed(self):
        """Pas d'auto-reparation si le repertoire parent n'est pas confirme."""
        link = Path(
            "/media/Serveur/test/Séries/Animation/T/"
            "The Amazing World of Gumball (2011)/Saison 5/ep.mkv"
        )
        candidate = Path(
            "/media/NAS64/Séries/Animation/M/"
            "Le monde incroyable de Gumball/Saison 5/ep.mkv"
        )
        targets = [(candidate, 82.0)]

        result = self.ir._check_series_auto_repair(
            "The Amazing World of Gumball (2011)", link, targets
        )
        assert result is None

    def test_no_auto_repair_when_candidate_from_different_dir(self):
        """Pas d'auto-reparation si le candidat est dans un autre repertoire NAS."""
        link = Path(
            "/media/Serveur/test/Séries/Animation/T/"
            "The Amazing World of Gumball (2011)/Saison 5/ep.mkv"
        )
        self.ir.confirmed_series[str(link.parent)] = Path(
            "/media/NAS64/Séries/Animation/M/Le monde incroyable de Gumball"
        )

        candidate = Path(
            "/media/NAS64/Séries/Séries TV/A-M/"
            "Autre Serie/Saison 1/ep.mkv"
        )
        targets = [(candidate, 60.0)]

        result = self.ir._check_series_auto_repair(
            "The Amazing World of Gumball (2011)", link, targets
        )
        assert result is None

    def test_no_auto_repair_when_no_candidates(self):
        """Pas d'auto-reparation si pas de candidats."""
        link = Path(
            "/media/Serveur/test/Séries/Animation/T/"
            "The Amazing World of Gumball (2011)/Saison 5/ep.mkv"
        )
        self.ir.confirmed_series[str(link.parent)] = Path(
            "/media/NAS64/Séries/Animation/M/Le monde incroyable de Gumball"
        )

        result = self.ir._check_series_auto_repair(
            "The Amazing World of Gumball (2011)", link, []
        )
        assert result is None

    def test_no_auto_repair_for_none_series_name(self):
        """Pas d'auto-reparation si series_name est None (film)."""
        link = Path("/media/Serveur/test/Films/Action/A-L/film.mkv")
        candidate = Path("/media/NAS64/Films/Action/A-L/film.mkv")
        targets = [(candidate, 90.0)]

        result = self.ir._check_series_auto_repair(None, link, targets)
        assert result is None

    def test_auto_repair_multi_season(self):
        """Auto-repare meme si l'episode est dans une saison differente."""
        link = Path(
            "/media/Serveur/test/Séries/Animation/T/"
            "The Amazing World of Gumball (2011)/Saison 5/ep.mkv"
        )
        # Note: les episodes de saisons differentes partagent le meme parent
        # si le symlink est dans Saison 5 - mais ici on teste qu'un candidat
        # dans Saison 4 sur le NAS est aussi accepte
        self.ir.confirmed_series[str(link.parent)] = Path(
            "/media/NAS64/Séries/Animation/M/Le monde incroyable de Gumball"
        )

        candidate = Path(
            "/media/NAS64/Séries/Animation/M/"
            "Le monde incroyable de Gumball/Saison 4/"
            "Le Monde Incroyable de Gumball - S04E01.mkv"
        )
        targets = [(candidate, 78.0)]

        result = self.ir._check_series_auto_repair(
            "The Amazing World of Gumball (2011)", link, targets
        )
        assert result == candidate

    def test_auto_repair_picks_best_candidate_in_confirmed_dir(self):
        """Si plusieurs candidats, prend le meilleur score dans le repertoire confirme."""
        link = Path(
            "/media/Serveur/test/Séries/Animation/T/"
            "The Amazing World of Gumball (2011)/Saison 5/ep.mkv"
        )
        self.ir.confirmed_series[str(link.parent)] = Path(
            "/media/NAS64/Séries/Animation/M/Le monde incroyable de Gumball"
        )

        candidate_wrong = Path("/media/NAS64/Séries/Autre/ep.mkv")
        candidate_good = Path(
            "/media/NAS64/Séries/Animation/M/"
            "Le monde incroyable de Gumball/Saison 5/ep_good.mkv"
        )
        # Le meilleur score est hors du repertoire confirme
        targets = [(candidate_wrong, 90.0), (candidate_good, 75.0)]

        result = self.ir._check_series_auto_repair(
            "The Amazing World of Gumball (2011)", link, targets
        )
        assert result == candidate_good

    def test_auto_repair_documentary_without_saison(self):
        """Auto-repare les documentaires sans structure Saison sur le NAS."""
        # Premier episode confirme
        link1 = Path(
            "/media/Serveur/test/Séries/Séries documentaires/Science/Géographie/"
            "Planet Earth II - VOSTFR/Planète/"
            "Planète Terre II - S01E05 - Les Prairies.mkv"
        )
        target1 = Path(
            "/media/NAS64/Séries/Séries documentaires/Science/Géographie/"
            "Planet Earth II - VOSTFR/"
            "Planet.Earth.II.S01E05.720p.BluRay.x264-ROVERS.mkv"
        )
        self.ir._register_confirmed_series(link1, target1)

        # Deuxieme episode - meme parent
        link2 = Path(
            "/media/Serveur/test/Séries/Séries documentaires/Science/Géographie/"
            "Planet Earth II - VOSTFR/Planète/"
            "Planète Terre II - S01E04 - Les Déserts.mkv"
        )
        candidate = Path(
            "/media/NAS64/Séries/Séries documentaires/Science/Géographie/"
            "Planet Earth II - VOSTFR/"
            "Planet.Earth.II.S01E04.720p.BluRay.x264-ROVERS.mkv"
        )
        targets = [(candidate, 66.0)]

        # series_name importe peu ici, c'est link.parent qui sert de cle
        result = self.ir._check_series_auto_repair("whatever", link2, targets)
        assert result == candidate

    # ---- _find_episode_in_nas_dir (fallback direct) ----

    def test_find_episode_in_nas_dir_flat_structure(self, tmp_path):
        """Trouve un episode par SxxExx dans un repertoire NAS sans sous-dossiers Saison."""
        nas_dir = tmp_path / "HPI, Haut Potentiel Intellectuel (2021)"
        nas_dir.mkdir()
        ep1 = nas_dir / "HPI, Haut Potentiel Intellectuel (2021) - S03E01 - FR HEVC 1080p.mkv"
        ep7 = nas_dir / "HPI, Haut Potentiel Intellectuel (2021) - S03E07 - FR HEVC 1080p.mkv"
        ep1.touch()
        ep7.touch()

        link = Path("/media/Serveur/test/Séries/Séries TV/G-H/He-Hz/"
                     "HPI, Haut Potentiel Intellectuel (2021)/Saison 03/HPI/"
                     "HPI - S03E07 - Tonnerre ! - FR HEVC 1080p.mkv")

        result = self.ir._find_episode_in_nas_dir(link, nas_dir)
        assert result == ep7

    def test_find_episode_in_nas_dir_with_saison_subdirs(self, tmp_path):
        """Trouve un episode dans un repertoire NAS avec sous-dossiers Saison."""
        nas_dir = tmp_path / "Breaking Bad"
        (nas_dir / "Saison 3").mkdir(parents=True)
        ep = nas_dir / "Saison 3" / "Breaking.Bad.S03E05.720p.mkv"
        ep.touch()

        link = Path("/media/Serveur/test/Séries/Séries TV/A-M/"
                     "Breaking Bad/Saison 03/ep/Breaking Bad - S03E05 - Mas.mkv")

        result = self.ir._find_episode_in_nas_dir(link, nas_dir)
        assert result == ep

    def test_find_episode_in_nas_dir_no_match(self, tmp_path):
        """Retourne None si aucun fichier ne correspond au numero d'episode."""
        nas_dir = tmp_path / "Serie"
        nas_dir.mkdir()
        (nas_dir / "Serie - S01E01.mkv").touch()

        link = Path("/fake/Serie/Saison 02/Serie - S02E05.mkv")

        result = self.ir._find_episode_in_nas_dir(link, nas_dir)
        assert result is None

    def test_find_episode_in_nas_dir_no_episode_in_name(self):
        """Retourne None si le nom du lien n'a pas de pattern SxxExx."""
        link = Path("/fake/Films/Un film sans episode.mkv")
        result = self.ir._find_episode_in_nas_dir(link, Path("/fake/nas"))
        assert result is None

    def test_find_episode_in_nas_dir_nonexistent(self):
        """Retourne None si le repertoire NAS n'existe pas."""
        link = Path("/fake/Serie/S01E01.mkv")
        result = self.ir._find_episode_in_nas_dir(link, Path("/nonexistent/path"))
        assert result is None

    # ---- auto-repair avec fallback direct ----

    def test_auto_repair_fallback_to_nas_dir_search(self, tmp_path):
        """Si aucun candidat ne correspond au repertoire confirme, cherche directement dedans."""
        # Setup: repertoire NAS avec le bon fichier
        nas_dir = tmp_path / "HPI"
        nas_dir.mkdir()
        expected = nas_dir / "HPI - S03E07 - FR HEVC 1080p.mkv"
        expected.touch()

        link = Path("/media/Serveur/test/Séries/Séries TV/G-H/"
                     "HPI (2021)/Saison 03/HPI/"
                     "HPI - S03E07 - Tonnerre.mkv")
        self.ir.confirmed_series[str(link.parent)] = nas_dir

        # Candidats de la recherche standard : aucun dans le bon repertoire
        wrong_candidates = [
            (Path("/media/NAS64/Séries/El Chapo - S03E07.mkv"), 66.0),
            (Path("/media/NAS64/Séries/The Wire - S03E07.mkv"), 66.0),
        ]

        result = self.ir._check_series_auto_repair("HPI", link, wrong_candidates)
        assert result == expected

    def test_auto_repair_fallback_works_with_empty_candidates(self, tmp_path):
        """Le fallback fonctionne meme si la liste de candidats est vide."""
        nas_dir = tmp_path / "Serie"
        nas_dir.mkdir()
        expected = nas_dir / "Serie - S01E03.mkv"
        expected.touch()

        link = Path("/media/Serveur/test/Séries/Serie/Saison 01/ep/"
                     "Serie - S01E03 - Titre.mkv")
        self.ir.confirmed_series[str(link.parent)] = nas_dir

        result = self.ir._check_series_auto_repair("Serie", link, [])
        assert result == expected

    def test_different_series_same_category_not_confused(self):
        """Deux series dans la meme categorie ne se confondent pas."""
        # Confirmer Planet Earth II
        link_pe = Path(
            "/media/Serveur/test/Séries/Séries documentaires/Science/Géographie/"
            "Planet Earth II - VOSTFR/Planète/ep.mkv"
        )
        target_pe = Path(
            "/media/NAS64/Séries/Séries documentaires/Science/Géographie/"
            "Planet Earth II - VOSTFR/ep_nas.mkv"
        )
        self.ir._register_confirmed_series(link_pe, target_pe)

        # Blue Planet - parent DIFFERENT
        link_bp = Path(
            "/media/Serveur/test/Séries/Séries documentaires/Science/Géographie/"
            "Blue Planet/Planète/ep.mkv"
        )
        candidate = Path(
            "/media/NAS64/Séries/Séries documentaires/Science/Géographie/"
            "Blue Planet/ep_nas.mkv"
        )
        targets = [(candidate, 70.0)]

        # Blue Planet n'est PAS confirme (parent different)
        result = self.ir._check_series_auto_repair("whatever", link_bp, targets)
        assert result is None
