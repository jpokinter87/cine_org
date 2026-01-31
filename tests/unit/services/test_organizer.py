"""
Tests unitaires pour OrganizerService.

Tests TDD pour le calcul des chemins de destination et le tri alphabétique.
"""

from pathlib import Path

import pytest

from src.core.entities.media import Movie, Series
from src.services.organizer import (
    get_sort_letter,
    get_priority_genre,
    get_movie_destination,
    get_series_destination,
    SubdivisionRange,
)


# ====================
# Fixtures
# ====================

@pytest.fixture
def storage_dir() -> Path:
    """Répertoire de stockage de test."""
    return Path("/storage")


@pytest.fixture
def video_dir() -> Path:
    """Répertoire video (symlinks) de test."""
    return Path("/video")


@pytest.fixture
def movie_scifi() -> Movie:
    """Film de science-fiction."""
    return Movie(
        title="Matrix",
        year=1999,
        genres=("Science-Fiction", "Action"),
    )


@pytest.fixture
def movie_with_french_article() -> Movie:
    """Film avec article français."""
    return Movie(
        title="Le Parrain",
        year=1972,
        genres=("Drame", "Crime"),  # Drame prioritaire sur Crime
    )


@pytest.fixture
def movie_with_english_article() -> Movie:
    """Film avec article anglais."""
    return Movie(
        title="The Matrix",
        year=1999,
        genres=("Science-Fiction", "Action"),
    )


@pytest.fixture
def movie_numeric() -> Movie:
    """Film avec titre numérique."""
    return Movie(
        title="2001 A Space Odyssey",
        year=1968,
        genres=("Science-Fiction",),
    )


@pytest.fixture
def movie_animation() -> Movie:
    """Film d'animation (priorité maximale)."""
    return Movie(
        title="Le Roi Lion",
        year=1994,
        genres=("Animation", "Drame", "Famille"),
    )


@pytest.fixture
def series_fixture() -> Series:
    """Série Breaking Bad."""
    return Series(
        title="Breaking Bad",
        year=2008,
        genres=("Drame", "Crime"),
    )


@pytest.fixture
def series_with_article() -> Series:
    """Série avec article anglais."""
    return Series(
        title="The Wire",
        year=2002,
        genres=("Crime", "Drame"),
    )


# ====================
# Tests get_sort_letter
# ====================

class TestGetSortLetter:
    """Tests pour l'extraction de la lettre de tri."""

    # --- Articles français ---
    def test_sort_letter_ignores_le(self) -> None:
        """L'article 'Le' est ignoré."""
        assert get_sort_letter("Le Parrain") == "P"

    def test_sort_letter_ignores_la(self) -> None:
        """L'article 'La' est ignoré."""
        assert get_sort_letter("La Guerre des Etoiles") == "G"

    def test_sort_letter_ignores_les(self) -> None:
        """L'article 'Les' est ignoré."""
        assert get_sort_letter("Les Miserables") == "M"

    def test_sort_letter_ignores_l_apostrophe(self) -> None:
        """L'article 'L'' (avec apostrophe) est ignoré."""
        assert get_sort_letter("L'Odyssee") == "O"

    def test_sort_letter_ignores_un(self) -> None:
        """L'article 'Un' est ignoré."""
        assert get_sort_letter("Un Homme et une Femme") == "H"

    def test_sort_letter_ignores_une(self) -> None:
        """L'article 'Une' est ignoré."""
        assert get_sort_letter("Une Vie") == "V"

    # --- Articles anglais ---
    def test_sort_letter_ignores_the(self) -> None:
        """L'article 'The' est ignoré."""
        assert get_sort_letter("The Matrix") == "M"

    def test_sort_letter_ignores_a(self) -> None:
        """L'article 'A' est ignoré."""
        assert get_sort_letter("A Beautiful Mind") == "B"

    def test_sort_letter_ignores_an(self) -> None:
        """L'article 'An' est ignoré."""
        assert get_sort_letter("An Officer and a Gentleman") == "O"

    # --- Articles allemands ---
    def test_sort_letter_ignores_der(self) -> None:
        """L'article allemand 'Der' est ignoré."""
        assert get_sort_letter("Der Untergang") == "U"

    def test_sort_letter_ignores_die(self) -> None:
        """L'article allemand 'Die' est ignoré."""
        assert get_sort_letter("Die Hard") == "H"

    def test_sort_letter_ignores_das(self) -> None:
        """L'article allemand 'Das' est ignoré."""
        assert get_sort_letter("Das Boot") == "B"

    def test_sort_letter_ignores_ein(self) -> None:
        """L'article allemand 'Ein' est ignoré."""
        assert get_sort_letter("Ein Freund") == "F"

    # --- Articles espagnols ---
    def test_sort_letter_ignores_el(self) -> None:
        """L'article espagnol 'El' est ignoré."""
        assert get_sort_letter("El Mariachi") == "M"

    def test_sort_letter_ignores_los(self) -> None:
        """L'article espagnol 'Los' est ignoré."""
        assert get_sort_letter("Los Olvidados") == "O"

    # --- Titres numériques ---
    def test_sort_letter_numeric_start(self) -> None:
        """Les titres commençant par un chiffre vont sous #."""
        assert get_sort_letter("2001 A Space Odyssey") == "#"

    def test_sort_letter_numeric_only(self) -> None:
        """Les titres numériques purs vont sous #."""
        assert get_sort_letter("300") == "#"

    def test_sort_letter_12_angry_men(self) -> None:
        """Titre '12 Angry Men' classé sous #."""
        assert get_sort_letter("12 Angry Men") == "#"

    # --- Cas spéciaux ---
    def test_sort_letter_special_start(self) -> None:
        """Les titres commençant par caractères spéciaux vont sous #."""
        assert get_sort_letter("...And Justice for All") == "#"

    def test_sort_letter_normal_title(self) -> None:
        """Un titre normal sans article."""
        assert get_sort_letter("Matrix") == "M"

    def test_sort_letter_lowercase(self) -> None:
        """La lettre est retournée en majuscule."""
        assert get_sort_letter("matrix") == "M"

    def test_sort_letter_case_insensitive_article(self) -> None:
        """Les articles sont détectés indépendamment de la casse."""
        assert get_sort_letter("THE Matrix") == "M"
        assert get_sort_letter("the matrix") == "M"

    def test_sort_letter_single_word_matching_article(self) -> None:
        """Un titre d'un seul mot identique à un article garde ce mot."""
        # "The" seul n'est pas traité comme article
        assert get_sort_letter("The") == "T"

    def test_sort_letter_empty_after_article_stripping(self) -> None:
        """Si le titre ne contient qu'un article, on le garde."""
        assert get_sort_letter("Le") == "L"


# ====================
# Tests get_priority_genre
# ====================

class TestGetPriorityGenre:
    """Tests pour la sélection du genre prioritaire."""

    def test_priority_genre_animation_first(self) -> None:
        """Animation est prioritaire sur tout."""
        assert get_priority_genre(("Action", "Animation", "Drame")) == "Animation"

    def test_priority_genre_scifi_over_action(self) -> None:
        """Science-Fiction est prioritaire sur Action."""
        assert get_priority_genre(("Action", "Science-Fiction")) == "Science-Fiction"

    def test_priority_genre_action_over_drame(self) -> None:
        """Action est prioritaire sur Drame."""
        assert get_priority_genre(("Drame", "Action")) == "Action"

    def test_priority_genre_horror_over_thriller(self) -> None:
        """Horreur est prioritaire sur Thriller."""
        assert get_priority_genre(("Thriller", "Horreur")) == "Horreur"

    def test_priority_genre_single(self) -> None:
        """Un seul genre retourne ce genre."""
        assert get_priority_genre(("Drame",)) == "Drame"

    def test_priority_genre_empty_returns_divers(self) -> None:
        """Genres vides retourne 'Divers'."""
        assert get_priority_genre(()) == "Divers"

    def test_priority_genre_unknown_single(self) -> None:
        """Un genre inconnu seul est retourné."""
        assert get_priority_genre(("Unknown",)) == "Unknown"

    def test_priority_genre_unknown_with_known(self) -> None:
        """Un genre inconnu avec un connu retourne le connu."""
        assert get_priority_genre(("Unknown", "Action")) == "Action"

    def test_priority_genre_all_unknown(self) -> None:
        """Tous genres inconnus retourne le premier."""
        assert get_priority_genre(("Genre1", "Genre2")) == "Genre1"


# ====================
# Tests get_movie_destination
# ====================

class TestGetMovieDestination:
    """Tests pour le calcul du chemin de destination des films (storage).

    Note: Le storage utilise la même structure que video (symlinks).
    Structure: Films/Genre/Lettre/
    """

    def test_movie_destination_basic(
        self, movie_scifi: Movie, storage_dir: Path, video_dir: Path
    ) -> None:
        """Structure storage: Films/Genre/Lettre."""
        path = get_movie_destination(movie_scifi, storage_dir, video_dir)
        # Science-Fiction -> SF (via GENRE_FOLDER_MAPPING)
        assert path == Path("/storage/Films/SF/M")

    def test_movie_destination_with_article(
        self, movie_with_french_article: Movie, storage_dir: Path, video_dir: Path
    ) -> None:
        """L'article est ignoré pour la lettre."""
        path = get_movie_destination(movie_with_french_article, storage_dir, video_dir)
        # Le Parrain -> Drame -> Lettre P
        assert path == Path("/storage/Films/Drame/P")

    def test_movie_destination_animation_priority(
        self, movie_animation: Movie, storage_dir: Path, video_dir: Path
    ) -> None:
        """Le Roi Lion -> Animation (prioritaire) -> Lettre R."""
        path = get_movie_destination(movie_animation, storage_dir, video_dir)
        assert path == Path("/storage/Films/Animation/R")

    def test_movie_destination_numeric(
        self, movie_numeric: Movie, storage_dir: Path, video_dir: Path
    ) -> None:
        """Titre numérique va sous #."""
        path = get_movie_destination(movie_numeric, storage_dir, video_dir)
        # Science-Fiction -> SF
        assert path == Path("/storage/Films/SF/#")

    def test_movie_destination_no_genres(self, storage_dir: Path, video_dir: Path) -> None:
        """Film sans genre utilise Drame (fallback Divers -> Drame)."""
        movie = Movie(title="Mystery Film", year=2020, genres=())
        path = get_movie_destination(movie, storage_dir, video_dir)
        assert path == Path("/storage/Films/Drame/M")

    def test_movie_destination_english_article(
        self, movie_with_english_article: Movie, storage_dir: Path, video_dir: Path
    ) -> None:
        """The est ignoré pour la lettre."""
        path = get_movie_destination(movie_with_english_article, storage_dir, video_dir)
        # The Matrix -> SF -> Lettre M
        assert path == Path("/storage/Films/SF/M")


# ====================
# Tests get_series_destination
# ====================

class TestGetSeriesDestination:
    """Tests pour le calcul du chemin de destination des séries.

    Note: Le storage utilise la même structure que video (symlinks).
    Structure: Séries/{Type}/{Lettre}/{Titre}/Saison XX/
    """

    def test_series_destination_basic(
        self, series_fixture: Series, storage_dir: Path, video_dir: Path
    ) -> None:
        """Structure de base: stockage/Séries/Type/Lettre/Titre (Annee)/Saison XX."""
        path = get_series_destination(series_fixture, season_number=1, storage_dir=storage_dir, video_dir=video_dir)
        # Drame -> Séries TV
        assert path == Path("/storage/Séries/Séries TV/B/Breaking Bad (2008)/Saison 01")

    def test_series_destination_season_double_digit(
        self, series_fixture: Series, storage_dir: Path, video_dir: Path
    ) -> None:
        """Numéro de saison à deux chiffres."""
        path = get_series_destination(series_fixture, season_number=12, storage_dir=storage_dir, video_dir=video_dir)
        assert path == Path("/storage/Séries/Séries TV/B/Breaking Bad (2008)/Saison 12")

    def test_series_destination_with_article(
        self, series_with_article: Series, storage_dir: Path, video_dir: Path
    ) -> None:
        """The est ignoré pour la lettre."""
        path = get_series_destination(series_with_article, season_number=3, storage_dir=storage_dir, video_dir=video_dir)
        assert path == Path("/storage/Séries/Séries TV/W/The Wire (2002)/Saison 03")

    def test_series_destination_no_year(self, storage_dir: Path, video_dir: Path) -> None:
        """Série sans année n'a pas de parenthèses."""
        series = Series(title="Friends", year=None)
        path = get_series_destination(series, season_number=5, storage_dir=storage_dir, video_dir=video_dir)
        assert path == Path("/storage/Séries/Séries TV/F/Friends/Saison 05")

    def test_series_destination_numeric_title(self, storage_dir: Path, video_dir: Path) -> None:
        """Titre numérique va sous #."""
        series = Series(title="24", year=2001)
        path = get_series_destination(series, season_number=1, storage_dir=storage_dir, video_dir=video_dir)
        assert path == Path("/storage/Séries/Séries TV/#/24 (2001)/Saison 01")


# ====================
# Tests SubdivisionRange
# ====================

class TestSubdivisionRange:
    """Tests pour la dataclass SubdivisionRange."""

    def test_subdivision_range_label(self) -> None:
        """Le label combine start et end."""
        subdivision = SubdivisionRange(start="A", end="C")
        assert subdivision.label == "A-C"

    def test_subdivision_range_single_letter(self) -> None:
        """Label pour une seule lettre."""
        subdivision = SubdivisionRange(start="M", end="M")
        assert subdivision.label == "M-M"

    def test_subdivision_range_immutable(self) -> None:
        """SubdivisionRange est immutable (frozen)."""
        subdivision = SubdivisionRange(start="A", end="C")
        with pytest.raises(AttributeError):
            subdivision.start = "B"  # type: ignore[misc]
