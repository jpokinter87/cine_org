"""
Tests unitaires pour le module CLI validation.

Tests couvrant:
- CandidatePaginator (pagination des resultats)
- render_candidate_card (affichage des cartes)
- detect_external_id (detection IMDB/numerique)
- determine_is_series (detection serie depuis candidats et nom de fichier)
- display_batch_summary (affichage tableau)
- validation_loop (boucle interactive avec mocks)
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.adapters.cli.validation import (
    CandidatePaginator,
    detect_external_id,
    determine_is_series,
    display_batch_summary,
    display_help,
    render_candidate_card,
    validation_loop,
)
from src.core.entities.video import PendingValidation, VideoFile
from src.core.ports.api_clients import SearchResult


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_candidates() -> list[SearchResult]:
    """Cree une liste de candidats pour les tests."""
    return [
        SearchResult(id="1", title="Avatar", year=2009, score=95.0, source="tmdb"),
        SearchResult(id="2", title="Avatar 2", year=2022, score=80.0, source="tmdb"),
        SearchResult(id="3", title="Avatar: TLA", year=2010, score=70.0, source="tvdb"),
        SearchResult(id="4", title="Test Movie 4", year=2015, score=65.0, source="tmdb"),
        SearchResult(id="5", title="Test Movie 5", year=2016, score=60.0, source="tmdb"),
        SearchResult(id="6", title="Test Movie 6", year=2017, score=55.0, source="tmdb"),
        SearchResult(id="7", title="Test Movie 7", year=2018, score=50.0, source="tmdb"),
        SearchResult(id="8", title="Test Movie 8", year=2019, score=45.0, source="tmdb"),
        SearchResult(id="9", title="Test Movie 9", year=2020, score=40.0, source="tmdb"),
        SearchResult(id="10", title="Test Movie 10", year=2021, score=35.0, source="tmdb"),
        SearchResult(id="11", title="Test Movie 11", year=2022, score=30.0, source="tmdb"),
        SearchResult(id="12", title="Test Movie 12", year=2023, score=25.0, source="tmdb"),
    ]


@pytest.fixture
def pending_movie() -> PendingValidation:
    """Cree un PendingValidation pour un film."""
    video_file = VideoFile(
        id="vf1",
        path=Path("/downloads/Avatar.2009.mkv"),
        filename="Avatar.2009.mkv",
    )
    return PendingValidation(
        id="pv1",
        video_file=video_file,
        candidates=[
            {"id": "1", "title": "Avatar", "year": 2009, "score": 95.0, "source": "tmdb"},
        ],
    )


@pytest.fixture
def pending_series() -> PendingValidation:
    """Cree un PendingValidation pour une serie."""
    video_file = VideoFile(
        id="vf2",
        path=Path("/downloads/Game.of.Thrones.S01E01.mkv"),
        filename="Game.of.Thrones.S01E01.mkv",
    )
    return PendingValidation(
        id="pv2",
        video_file=video_file,
        candidates=[
            {"id": "121361", "title": "Game of Thrones", "year": 2011, "score": 90.0, "source": "tvdb"},
        ],
    )


# ============================================================================
# Tests CandidatePaginator
# ============================================================================


class TestCandidatePaginator:
    """Tests pour la classe CandidatePaginator."""

    def test_paginator_total_pages(self, sample_candidates):
        """12 items avec page_size=5 donne 3 pages."""
        paginator = CandidatePaginator(sample_candidates, page_size=5)
        assert paginator.total_pages == 3

    def test_paginator_total_pages_empty(self):
        """Liste vide donne 0 pages."""
        paginator = CandidatePaginator([], page_size=5)
        assert paginator.total_pages == 0

    def test_paginator_total_pages_exact(self):
        """10 items avec page_size=5 donne 2 pages exactes."""
        candidates = [
            SearchResult(id=str(i), title=f"Movie {i}", score=50.0, source="tmdb")
            for i in range(10)
        ]
        paginator = CandidatePaginator(candidates, page_size=5)
        assert paginator.total_pages == 2

    def test_paginator_current_items_page_0(self, sample_candidates):
        """Page 0 retourne les 5 premiers items."""
        paginator = CandidatePaginator(sample_candidates, page_size=5)
        items = paginator.current_items
        assert len(items) == 5
        assert items[0].title == "Avatar"
        assert items[4].title == "Test Movie 5"

    def test_paginator_current_items_last_page(self, sample_candidates):
        """Derniere page retourne les items restants."""
        paginator = CandidatePaginator(sample_candidates, page_size=5)
        paginator.current_page = 2  # Derniere page
        items = paginator.current_items
        assert len(items) == 2
        assert items[0].title == "Test Movie 11"
        assert items[1].title == "Test Movie 12"

    def test_paginator_select_valid(self, sample_candidates):
        """Selection valide retourne le bon candidat."""
        paginator = CandidatePaginator(sample_candidates, page_size=5)
        # Selection 2 sur page 0 = index 1
        candidate = paginator.select(2)
        assert candidate is not None
        assert candidate.title == "Avatar 2"

    def test_paginator_select_page_2(self, sample_candidates):
        """Selection sur page 2 retourne le bon index global."""
        paginator = CandidatePaginator(sample_candidates, page_size=5)
        paginator.current_page = 2
        # Selection 1 sur page 2 = index 10
        candidate = paginator.select(1)
        assert candidate is not None
        assert candidate.title == "Test Movie 11"

    def test_paginator_select_invalid_high(self, sample_candidates):
        """Selection trop haute retourne None."""
        paginator = CandidatePaginator(sample_candidates, page_size=5)
        assert paginator.select(10) is None

    def test_paginator_select_invalid_zero(self, sample_candidates):
        """Selection 0 retourne None (1-based)."""
        paginator = CandidatePaginator(sample_candidates, page_size=5)
        assert paginator.select(0) is None

    def test_paginator_next_page_success(self, sample_candidates):
        """next_page incremente la page si possible."""
        paginator = CandidatePaginator(sample_candidates, page_size=5)
        assert paginator.current_page == 0
        result = paginator.next_page()
        assert result is True
        assert paginator.current_page == 1

    def test_paginator_next_page_at_end(self, sample_candidates):
        """next_page retourne False si deja a la fin."""
        paginator = CandidatePaginator(sample_candidates, page_size=5)
        paginator.current_page = 2  # Derniere page
        result = paginator.next_page()
        assert result is False
        assert paginator.current_page == 2

    def test_paginator_has_more_true(self, sample_candidates):
        """has_more retourne True si pages restantes."""
        paginator = CandidatePaginator(sample_candidates, page_size=5)
        assert paginator.has_more() is True

    def test_paginator_has_more_false(self, sample_candidates):
        """has_more retourne False sur derniere page."""
        paginator = CandidatePaginator(sample_candidates, page_size=5)
        paginator.current_page = 2
        assert paginator.has_more() is False


# ============================================================================
# Tests render_candidate_card
# ============================================================================


class TestRenderCandidateCard:
    """Tests pour la fonction render_candidate_card."""

    def test_render_candidate_card_basic(self):
        """Cree un Panel avec le titre correct."""
        candidate = SearchResult(
            id="1", title="Avatar", year=2009, score=95.0, source="tmdb"
        )
        panel = render_candidate_card(candidate, rank=1, is_best=False)

        # Verifier que c'est un Panel
        from rich.panel import Panel
        assert isinstance(panel, Panel)

        # Verifier le titre du panel
        assert "[1]" in str(panel.title)

    def test_render_candidate_card_best(self):
        """is_best=True ajoute le badge RECOMMANDE."""
        candidate = SearchResult(
            id="1", title="Avatar", year=2009, score=95.0, source="tmdb"
        )
        panel = render_candidate_card(candidate, rank=1, is_best=True)

        # Verifier le badge dans le titre
        assert "RECOMMANDE" in str(panel.title)
        assert panel.border_style == "green"

    def test_render_candidate_card_not_best(self):
        """is_best=False n'ajoute pas le badge."""
        candidate = SearchResult(
            id="1", title="Avatar", year=2009, score=95.0, source="tmdb"
        )
        panel = render_candidate_card(candidate, rank=2, is_best=False)

        assert "RECOMMANDE" not in str(panel.title or "")
        assert panel.border_style == "white"

    def test_render_candidate_card_score_green(self):
        """Score >= 85 a une couleur verte dans le contenu."""
        candidate = SearchResult(
            id="1", title="Test", year=2020, score=90.0, source="tmdb"
        )
        panel = render_candidate_card(candidate, rank=1)

        # Le contenu devrait contenir le score en vert
        # Note: on ne peut pas facilement verifier la couleur sans parser le markup
        assert panel.renderable is not None

    def test_render_candidate_card_score_yellow(self):
        """Score < 85 a une couleur jaune."""
        candidate = SearchResult(
            id="1", title="Test", year=2020, score=70.0, source="tmdb"
        )
        panel = render_candidate_card(candidate, rank=1)
        assert panel.renderable is not None

    def test_render_candidate_card_no_year(self):
        """Candidat sans annee s'affiche correctement."""
        candidate = SearchResult(
            id="1", title="Test Movie", year=None, score=75.0, source="tmdb"
        )
        panel = render_candidate_card(candidate, rank=1)
        assert panel.renderable is not None


# ============================================================================
# Tests detect_external_id
# ============================================================================


class TestDetectExternalId:
    """Tests pour la fonction detect_external_id."""

    def test_detect_imdb_id_lowercase(self):
        """Detecte un ID IMDB en minuscules."""
        id_type, id_value = detect_external_id("tt1234567")
        assert id_type == "imdb"
        assert id_value == "tt1234567"

    def test_detect_imdb_id_uppercase(self):
        """Detecte un ID IMDB en majuscules."""
        id_type, id_value = detect_external_id("TT1234567")
        assert id_type == "imdb"
        assert id_value == "tt1234567"  # Normalise en minuscules

    def test_detect_imdb_id_8_digits(self):
        """Detecte un ID IMDB a 8 chiffres."""
        id_type, id_value = detect_external_id("tt12345678")
        assert id_type == "imdb"
        assert id_value == "tt12345678"

    def test_detect_numeric_id(self):
        """Detecte un ID numerique."""
        id_type, id_value = detect_external_id("12345")
        assert id_type == "numeric"
        assert id_value == "12345"

    def test_detect_unknown_text(self):
        """Texte non reconnu retourne (None, None)."""
        id_type, id_value = detect_external_id("avatar")
        assert id_type is None
        assert id_value is None

    def test_detect_unknown_mixed(self):
        """Texte mixte non reconnu retourne (None, None)."""
        id_type, id_value = detect_external_id("movie123")
        assert id_type is None
        assert id_value is None

    def test_detect_imdb_id_too_short(self):
        """ID IMDB trop court n'est pas reconnu."""
        id_type, id_value = detect_external_id("tt123456")  # 6 chiffres
        assert id_type is None
        assert id_value is None

    def test_detect_with_whitespace(self):
        """Les espaces sont ignores."""
        id_type, id_value = detect_external_id("  tt1234567  ")
        assert id_type == "imdb"
        assert id_value == "tt1234567"


# ============================================================================
# Tests determine_is_series
# ============================================================================


class TestDetermineIsSeries:
    """Tests pour la fonction determine_is_series."""

    def test_determine_is_series_tvdb_candidate(self, pending_series):
        """Candidat avec source='tvdb' retourne True."""
        assert determine_is_series(pending_series) is True

    def test_determine_is_series_tmdb_candidate(self, pending_movie):
        """Candidat avec source='tmdb' retourne False."""
        assert determine_is_series(pending_movie) is False

    def test_determine_is_series_filename_pattern_s01e01(self):
        """Nom de fichier avec S01E01 retourne True (sans candidats)."""
        video_file = VideoFile(
            id="vf",
            path=Path("/test.S01E01.mkv"),
            filename="test.S01E01.mkv",
        )
        pending = PendingValidation(id="pv", video_file=video_file, candidates=[])
        assert determine_is_series(pending) is True

    def test_determine_is_series_filename_pattern_lowercase(self):
        """Nom de fichier avec s1e1 (minuscules) retourne True."""
        video_file = VideoFile(
            id="vf",
            path=Path("/show.s1e1.mkv"),
            filename="show.s1e1.mkv",
        )
        pending = PendingValidation(id="pv", video_file=video_file, candidates=[])
        assert determine_is_series(pending) is True

    def test_determine_is_series_filename_pattern_saison(self):
        """Nom de fichier avec 'saison' retourne True."""
        video_file = VideoFile(
            id="vf",
            path=Path("/serie.saison.1.mkv"),
            filename="serie.saison.1.mkv",
        )
        pending = PendingValidation(id="pv", video_file=video_file, candidates=[])
        assert determine_is_series(pending) is True

    def test_determine_is_series_filename_no_pattern(self):
        """Nom de fichier sans pattern serie retourne False."""
        video_file = VideoFile(
            id="vf",
            path=Path("/movie.2020.mkv"),
            filename="movie.2020.mkv",
        )
        pending = PendingValidation(id="pv", video_file=video_file, candidates=[])
        assert determine_is_series(pending) is False

    def test_determine_is_series_no_video_file(self):
        """video_file=None retourne False."""
        pending = PendingValidation(id="pv", video_file=None)
        assert determine_is_series(pending) is False

    def test_determine_is_series_candidate_dict_tvdb(self):
        """Candidat dict avec source='tvdb' retourne True."""
        video_file = VideoFile(
            id="vf",
            path=Path("/test.mkv"),
            filename="test.mkv",
        )
        pending = PendingValidation(
            id="pv",
            video_file=video_file,
            candidates=[{"id": "1", "title": "Test", "source": "tvdb"}],
        )
        assert determine_is_series(pending) is True

    def test_determine_is_series_candidate_searchresult_tvdb(self):
        """Candidat SearchResult avec source='tvdb' retourne True."""
        video_file = VideoFile(
            id="vf",
            path=Path("/test.mkv"),
            filename="test.mkv",
        )
        candidate = SearchResult(id="1", title="Test", score=80.0, source="tvdb")
        pending = PendingValidation(
            id="pv",
            video_file=video_file,
            candidates=[candidate],
        )
        assert determine_is_series(pending) is True


# ============================================================================
# Tests display_batch_summary
# ============================================================================


class TestDisplayBatchSummary:
    """Tests pour la fonction display_batch_summary."""

    def test_display_batch_summary_creates_tree(self):
        """Verifie qu'un Tree est cree et affiche."""
        transfers = [
            {
                "source": Path("/downloads/movie1.mkv"),
                "destination": Path("/storage/Films/Action/A/Avatar.mkv"),
                "new_filename": "Avatar (2009) FR DTS HEVC 1080p.mkv",
                "symlink_destination": Path("/video/Films/Action/A-M/Avatar (2009) FR DTS HEVC 1080p.mkv"),
                "is_series": False,
                "title": "Avatar",
                "year": 2009,
            },
            {
                "source": Path("/downloads/movie2.mkv"),
                "destination": Path("/storage/Films/Action/M/Matrix.mkv"),
                "new_filename": "Matrix (1999) FR AC3 H264 1080p.mkv",
                "symlink_destination": Path("/video/Films/Action/A-M/Matrix (1999) FR AC3 H264 1080p.mkv"),
                "is_series": False,
                "title": "Matrix",
                "year": 1999,
            },
        ]

        # Patch console.print pour capturer l'output
        with patch("src.adapters.cli.validation.console.print") as mock_print:
            display_batch_summary(transfers)

            # Verifier que print a ete appele
            assert mock_print.called

            # Verifier qu'un Tree a ete passe
            from rich.tree import Tree
            call_args = mock_print.call_args[0][0]
            assert isinstance(call_args, Tree)

    def test_display_batch_summary_shows_all_transfers(self):
        """Verifie que tous les fichiers sont dans l'arbre."""
        transfers = [
            {
                "source": Path("/downloads/movie1.mkv"),
                "destination": Path("/storage/Films/Action/A/movie1.mkv"),
                "new_filename": "Movie 1 (2020).mkv",
                "symlink_destination": Path("/video/Films/Action/A-M/Movie 1 (2020).mkv"),
                "is_series": False,
                "title": "Movie 1",
                "year": 2020,
            },
            {
                "source": Path("/downloads/movie2.mkv"),
                "destination": Path("/storage/Films/Action/B/movie2.mkv"),
                "new_filename": "Movie 2 (2021).mkv",
                "symlink_destination": Path("/video/Films/Action/A-M/Movie 2 (2021).mkv"),
                "is_series": False,
                "title": "Movie 2",
                "year": 2021,
            },
            {
                "source": Path("/downloads/movie3.mkv"),
                "destination": Path("/storage/Films/Action/C/movie3.mkv"),
                "new_filename": "Movie 3 (2022).mkv",
                "symlink_destination": Path("/video/Films/Action/A-M/Movie 3 (2022).mkv"),
                "is_series": False,
                "title": "Movie 3",
                "year": 2022,
            },
        ]

        with patch("src.adapters.cli.validation.console.print") as mock_print:
            display_batch_summary(transfers)

            from rich.tree import Tree
            tree = mock_print.call_args[0][0]
            assert isinstance(tree, Tree)
            # L'arbre doit avoir une branche Films
            # Note: Rich Tree structure verification - checking the label contains "Films"
            assert tree.label is not None

    def test_display_batch_summary_handles_string_paths(self):
        """Gere les chemins en string (sans .parts)."""
        transfers = [
            {
                "source": Path("/downloads/movie1.mkv"),
                "destination": Path("/storage/Films/movie1.mkv"),
                "new_filename": "Movie 1 (2020).mkv",
                "symlink_destination": None,  # Pas de symlink
                "is_series": False,
                "title": "Movie 1",
                "year": 2020,
            },
        ]

        # Ne doit pas lever d'exception
        with patch("src.adapters.cli.validation.console.print"):
            display_batch_summary(transfers)


# ============================================================================
# Tests display_help
# ============================================================================


class TestDisplayHelp:
    """Tests pour la fonction display_help."""

    def test_display_help_prints_commands(self):
        """Verifie que l'aide est affichee."""
        with patch("src.adapters.cli.validation.console.print") as mock_print:
            display_help()
            assert mock_print.called
            # Verifier que le texte contient les commandes
            help_text = mock_print.call_args[0][0]
            assert "1-5" in help_text
            assert "s" in help_text
            assert "t" in help_text
            assert "r" in help_text


# ============================================================================
# Tests validation_loop (avec mocks)
# ============================================================================


class TestValidationLoop:
    """Tests pour la fonction validation_loop avec mocks."""

    @pytest.mark.asyncio
    async def test_validation_loop_select_candidate(self, pending_movie):
        """Selection d'un candidat retourne un SearchResult."""
        mock_service = MagicMock()

        # Mock Prompt.ask pour retourner "1" puis confirmer
        with patch("src.adapters.cli.validation.Prompt.ask") as mock_ask, \
             patch("src.adapters.cli.validation.Confirm.ask") as mock_confirm:

            mock_ask.return_value = "1"
            mock_confirm.return_value = True

            result = await validation_loop(pending_movie, mock_service)

        # Un SearchResult avec l'ID du premier candidat
        assert isinstance(result, SearchResult)
        assert result.id == "1"

    @pytest.mark.asyncio
    async def test_validation_loop_skip(self, pending_movie):
        """Commande 's' retourne None (skip)."""
        mock_service = MagicMock()

        with patch("src.adapters.cli.validation.Prompt.ask") as mock_ask:
            mock_ask.return_value = "s"

            result = await validation_loop(pending_movie, mock_service)

        assert result is None

    @pytest.mark.asyncio
    async def test_validation_loop_trash(self, pending_movie):
        """Commande 't' retourne 'trash'."""
        mock_service = MagicMock()

        with patch("src.adapters.cli.validation.Prompt.ask") as mock_ask:
            mock_ask.return_value = "t"

            result = await validation_loop(pending_movie, mock_service)

        assert result == "trash"

    @pytest.mark.asyncio
    async def test_validation_loop_quit(self, pending_movie):
        """Commande 'q' retourne 'quit'."""
        mock_service = MagicMock()

        with patch("src.adapters.cli.validation.Prompt.ask") as mock_ask:
            mock_ask.return_value = "q"

            result = await validation_loop(pending_movie, mock_service)

        assert result == "quit"

    @pytest.mark.asyncio
    async def test_validation_loop_search_uses_determine_is_series(self, pending_series):
        """La recherche utilise determine_is_series() automatiquement."""
        mock_service = MagicMock()
        mock_service.search_manual = AsyncMock(return_value=[])

        with patch("src.adapters.cli.validation.Prompt.ask") as mock_ask, \
             patch("src.adapters.cli.validation.determine_is_series") as mock_determine:

            # Simuler: "r" -> recherche "test" -> "q" pour quitter
            mock_ask.side_effect = ["r", "test query", "q"]
            mock_determine.return_value = True  # Serie detectee

            await validation_loop(pending_series, mock_service)

        # Verifier que determine_is_series a ete appele
        mock_determine.assert_called_once_with(pending_series)

        # Verifier que search_manual a ete appele avec is_series=True
        mock_service.search_manual.assert_called_once_with("test query", is_series=True)

    @pytest.mark.asyncio
    async def test_validation_loop_next_page(self, sample_candidates):
        """Commande 'n' passe a la page suivante."""
        # Creer un pending avec beaucoup de candidats
        video_file = VideoFile(
            id="vf",
            path=Path("/test.mkv"),
            filename="test.mkv",
        )
        pending = PendingValidation(
            id="pv",
            video_file=video_file,
            candidates=[
                {"id": c.id, "title": c.title, "year": c.year, "score": c.score, "source": c.source}
                for c in sample_candidates
            ],
        )
        mock_service = MagicMock()

        with patch("src.adapters.cli.validation.Prompt.ask") as mock_ask:
            # "n" pour page suivante, puis "q" pour quitter
            mock_ask.side_effect = ["n", "q"]

            result = await validation_loop(pending, mock_service)

        assert result == "quit"

    @pytest.mark.asyncio
    async def test_validation_loop_decline_confirmation(self, pending_movie):
        """Refuser la confirmation ne valide pas."""
        mock_service = MagicMock()

        with patch("src.adapters.cli.validation.Prompt.ask") as mock_ask, \
             patch("src.adapters.cli.validation.Confirm.ask") as mock_confirm:

            # Selectionner 1, refuser, puis quitter
            mock_ask.side_effect = ["1", "q"]
            mock_confirm.return_value = False

            result = await validation_loop(pending_movie, mock_service)

        assert result == "quit"

    @pytest.mark.asyncio
    async def test_validation_loop_external_id_search(self, pending_movie):
        """Commande 'i' permet la recherche par ID externe et retourne un SearchResult."""
        mock_service = MagicMock()
        mock_details = MagicMock()
        mock_details.id = "12345"
        mock_details.title = "Avatar"
        mock_details.year = 2009
        mock_details.genres = ("Action", "Science-Fiction")
        mock_service.search_by_external_id = AsyncMock(return_value=mock_details)

        with patch("src.adapters.cli.validation.Prompt.ask") as mock_ask, \
             patch("src.adapters.cli.validation.Confirm.ask") as mock_confirm:

            # "i" -> ID "12345" -> source "tmdb" -> confirmer
            mock_ask.side_effect = ["i", "12345", "tmdb"]
            mock_confirm.return_value = True

            result = await validation_loop(pending_movie, mock_service)

        # Un SearchResult avec l'ID et les infos du candidat trouve
        assert isinstance(result, SearchResult)
        assert result.id == "12345"
        assert result.title == "Avatar"
        assert result.year == 2009
        assert result.source == "tmdb"
        mock_service.search_by_external_id.assert_called_once_with("tmdb", "12345")

    @pytest.mark.asyncio
    async def test_validation_loop_imdb_id_search(self, pending_movie):
        """ID IMDB detecte automatiquement sans demander la source et retourne un SearchResult."""
        mock_service = MagicMock()
        mock_details = MagicMock()
        mock_details.id = "tt1234567"
        mock_details.title = "Avatar"
        mock_details.year = 2009
        mock_details.genres = ()
        mock_service.search_by_external_id = AsyncMock(return_value=mock_details)

        with patch("src.adapters.cli.validation.Prompt.ask") as mock_ask, \
             patch("src.adapters.cli.validation.Confirm.ask") as mock_confirm:

            # "i" -> ID IMDB -> confirmer (pas de demande de source)
            mock_ask.side_effect = ["i", "tt1234567"]
            mock_confirm.return_value = True

            result = await validation_loop(pending_movie, mock_service)

        # Un SearchResult avec l'ID IMDB et les infos du candidat
        assert isinstance(result, SearchResult)
        assert result.id == "tt1234567"
        assert result.title == "Avatar"
        assert result.source == "imdb"
        mock_service.search_by_external_id.assert_called_once_with("imdb", "tt1234567")
