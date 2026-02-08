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
    get_movie_video_destination,
    get_series_destination,
    SubdivisionRange,
    _title_matches_prefix_dir,
    _find_matching_subdir,
    _is_range_dir,
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

    # --- Articles français (de, du) ---
    def test_sort_letter_ignores_de(self) -> None:
        """L'article 'de' est ignoré : 'De parfaites demoiselles' -> P."""
        assert get_sort_letter("De parfaites demoiselles") == "P"

    def test_sort_letter_ignores_du(self) -> None:
        """L'article 'du' est ignoré : 'Du plomb dans la tete' -> P."""
        assert get_sort_letter("Du plomb dans la tete") == "P"

    def test_sort_letter_de_in_middle_not_stripped(self) -> None:
        """'de' au milieu du titre n'est pas strip : 'Valse de printemps' -> V."""
        assert get_sort_letter("Valse de printemps") == "V"

    def test_sort_letter_ignores_au(self) -> None:
        """L'article 'au' est ignoré : 'Au service de la France' -> S."""
        assert get_sort_letter("Au service de la France") == "S"

    def test_sort_letter_ignores_aux(self) -> None:
        """L'article 'aux' est ignoré : 'Aux yeux de tous' -> Y."""
        assert get_sort_letter("Aux yeux de tous") == "Y"

    def test_sort_letter_au_not_prefix(self) -> None:
        """'Au' dans 'Austin Powers' n'est pas strip : reste sous A."""
        assert get_sort_letter("Austin Powers") == "A"

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

    # --- Caractères invisibles Unicode ---
    def test_sort_letter_ignores_invisible_chars(self) -> None:
        """Les caractères invisibles Unicode sont ignorés."""
        # U+200E Left-to-Right Mark - caractère invisible courant dans les APIs
        assert get_sort_letter("\u200eZoe") == "Z"
        # U+200F Right-to-Left Mark
        assert get_sort_letter("\u200fMatrix") == "M"
        # U+FEFF BOM (Byte Order Mark)
        assert get_sort_letter("\ufeffAvatar") == "A"
        # U+00AD Soft Hyphen
        assert get_sort_letter("\u00adTest") == "T"
        # Zero-Width Space
        assert get_sort_letter("\u200bFilm") == "F"

    def test_sort_letter_invisible_with_article(self) -> None:
        """Caractères invisibles combinés avec articles."""
        # LRM + article français
        assert get_sort_letter("\u200eLe Parrain") == "P"
        # Article anglais avec caractère invisible au milieu
        assert get_sort_letter("The\u200e Matrix") == "M"


class TestTitleMatchesRange:
    """Tests pour _title_matches_range avec caractères invisibles."""

    def test_title_matches_range_invisible_not_hash(self) -> None:
        """Un titre avec caractère invisible ne doit pas matcher #."""
        from src.services.organizer import _title_matches_range
        # U+200E Left-to-Right Mark devant "Zoe"
        assert _title_matches_range("\u200eZoe, mon amie morte", "#") is False
        assert _title_matches_range("\u200eZoe, mon amie morte", "R-Z") is True
        assert _title_matches_range("\u200eZoe, mon amie morte", "Z") is True


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


# ====================
# Tests navigation subdivisions multi-niveaux
# ====================

class TestSeriesSubdivisionNavigation:
    """Tests pour la navigation récursive dans les subdivisions de séries."""

    def test_series_navigates_to_leaf_subdivision(self, tmp_path: Path) -> None:
        """Une série navigue jusqu'à la subdivision feuille (Di-Dz et non D)."""
        from src.services.organizer import get_series_video_destination

        # Créer la structure : Séries TV/D/Di-Dz/
        series_type_dir = tmp_path / "Séries" / "Séries TV"
        d_dir = series_type_dir / "D"
        di_dz_dir = d_dir / "Di-Dz"
        di_dz_dir.mkdir(parents=True)

        # Série "Downtown Cemetery" -> lettre D -> doit aller dans Di-Dz
        series = Series(title="Downtown Cemetery", year=2025, genres=("Drame",))

        path = get_series_video_destination(series, season_number=1, video_dir=tmp_path)

        # Vérifier que le chemin utilise Di-Dz (feuille) et non D (parent)
        assert path == tmp_path / "Séries" / "Séries TV" / "D" / "Di-Dz" / "Downtown Cemetery (2025)" / "Saison 01"

    def test_series_navigues_pa_to_po_leaf(self, tmp_path: Path) -> None:
        """Une série P-Q navigue jusqu'à Pa-Po et non P-Q."""
        from src.services.organizer import get_series_video_destination

        # Créer la structure : Séries TV/P-Q/Pa-Po/
        series_type_dir = tmp_path / "Séries" / "Séries TV"
        pq_dir = series_type_dir / "P-Q"
        pa_po_dir = pq_dir / "Pa-Po"
        pa_po_dir.mkdir(parents=True)

        # Série "Polar Park" -> lettre P -> doit aller dans Pa-Po
        series = Series(title="Polar Park", year=2025, genres=("Drame",))

        path = get_series_video_destination(series, season_number=1, video_dir=tmp_path)

        # Vérifier que le chemin utilise Pa-Po (feuille)
        assert path == tmp_path / "Séries" / "Séries TV" / "P-Q" / "Pa-Po" / "Polar Park (2025)" / "Saison 01"

    def test_series_navigues_sa_to_so_leaf(self, tmp_path: Path) -> None:
        """Une série S avec préfixe Sa-So navigue jusqu'à Sa-So et non S."""
        from src.services.organizer import get_series_video_destination

        # Créer la structure : Séries TV/S/Sa-So/
        series_type_dir = tmp_path / "Séries" / "Séries TV"
        s_dir = series_type_dir / "S"
        sa_so_dir = s_dir / "Sa-So"
        sa_so_dir.mkdir(parents=True)

        # Série "Sanctuary" -> préfixe Sa -> doit aller dans Sa-So
        series = Series(title="Sanctuary", year=2025, genres=("Drame",))

        path = get_series_video_destination(series, season_number=1, video_dir=tmp_path)

        # Vérifier que le chemin utilise Sa-So (feuille)
        assert path == tmp_path / "Séries" / "Séries TV" / "S" / "Sa-So" / "Sanctuary (2025)" / "Saison 01"

    def test_series_navigues_sp_to_sz_leaf(self, tmp_path: Path) -> None:
        """Une série S avec préfixe St navigue jusqu'à Sp-Sz."""
        from src.services.organizer import get_series_video_destination

        # Créer la structure : Séries TV/S/Sp-Sz/
        series_type_dir = tmp_path / "Séries" / "Séries TV"
        s_dir = series_type_dir / "S"
        sp_sz_dir = s_dir / "Sp-Sz"
        sp_sz_dir.mkdir(parents=True)

        # Série "Station Eleven" -> préfixe St -> doit aller dans Sp-Sz
        series = Series(title="Station Eleven", year=2025, genres=("Drame",))

        path = get_series_video_destination(series, season_number=1, video_dir=tmp_path)

        # Vérifier que le chemin utilise Sp-Sz (feuille)
        assert path == tmp_path / "Séries" / "Séries TV" / "S" / "Sp-Sz" / "Station Eleven (2025)" / "Saison 01"

    def test_series_three_level_subdivision_navigation(self, tmp_path: Path) -> None:
        """Navigation à travers 3 niveaux de subdivisions."""
        from src.services.organizer import get_series_video_destination

        # Créer une structure profonde : D/Da-Di/Di-Dz/
        series_type_dir = tmp_path / "Séries" / "Séries TV"
        d_dir = series_type_dir / "D"
        da_di_dir = d_dir / "Da-Di"
        di_dz_dir = da_di_dir / "Di-Dz"
        di_dz_dir.mkdir(parents=True)

        # Série "Downtown Abbey" -> lettre D -> Da-Di -> Di-Dz
        series = Series(title="Downtown Abbey", year=2025, genres=("Drame",))

        path = get_series_video_destination(series, season_number=1, video_dir=tmp_path)

        # Vérifier qu'on descend jusqu'au niveau le plus profond (Di-Dz)
        assert path == tmp_path / "Séries" / "Séries TV" / "D" / "Da-Di" / "Di-Dz" / "Downtown Abbey (2025)" / "Saison 01"

    def test_series_fallback_to_letter_when_no_subdivision(self, tmp_path: Path) -> None:
        """Sans subdivisions existantes, place directement dans le type_dir."""
        from src.services.organizer import get_series_video_destination

        # Créer seulement le répertoire type sans subdivisions
        series_type_dir = tmp_path / "Séries" / "Séries TV"
        series_type_dir.mkdir(parents=True)

        # Série "Alpha" -> lettre A
        series = Series(title="Alpha", year=2025, genres=("Drame",))

        path = get_series_video_destination(series, season_number=1, video_dir=tmp_path)

        # Fallback : place directement dans le répertoire type (pas de lettre)
        assert path == tmp_path / "Séries" / "Séries TV" / "Alpha (2025)" / "Saison 01"

    def test_series_type_manga(self, tmp_path: Path) -> None:
        """Les mangas utilisent le type Mangas."""
        from src.services.organizer import get_series_video_destination

        # Créer la structure : Mangas/D/Di-Dz/
        manga_dir = tmp_path / "Séries" / "Mangas" / "D" / "Di-Dz"
        manga_dir.mkdir(parents=True)

        # Série "Death Note" -> Anime -> Mangas
        series = Series(title="Death Note", year=2005, genres=("Anime", "Action"))

        path = get_series_video_destination(series, season_number=1, video_dir=tmp_path)

        # Vérifier l'utilisation du type Mangas
        assert path == tmp_path / "Séries" / "Mangas" / "D" / "Di-Dz" / "Death Note (2005)" / "Saison 01"

    def test_series_type_animation(self, tmp_path: Path) -> None:
        """Les séries d'animation utilisent le type Animation."""
        from src.services.organizer import get_series_video_destination

        # Créer la structure : Animation/S/Sa-Sm/
        animation_dir = tmp_path / "Séries" / "Animation" / "S" / "Sa-Sm"
        animation_dir.mkdir(parents=True)

        # Série "Spider-Man" -> Animation (pas Anime)
        series = Series(title="Spider-Man", year=2025, genres=("Animation", "Action"))

        path = get_series_video_destination(series, season_number=1, video_dir=tmp_path)

        # Vérifier l'utilisation du type Animation
        assert path == tmp_path / "Séries" / "Animation" / "S" / "Sa-Sm" / "Spider-Man (2025)" / "Saison 01"

    def test_series_chooses_correct_subdivision_when_multiple_exist(self, tmp_path: Path) -> None:
        """Quand plusieurs subdivisions existent, choisit la bonne (Sp-Sz et non Sa-So)."""
        from src.services.organizer import get_series_video_destination

        # Créer la structure avec les deux subdivisions : S/Sa-So/ et S/Sp-Sz/
        series_type_dir = tmp_path / "Séries" / "Séries TV" / "S"
        sa_so_dir = series_type_dir / "Sa-So"
        sp_sz_dir = series_type_dir / "Sp-Sz"
        sp_sz_dir.mkdir(parents=True)
        sa_so_dir.mkdir(parents=True)

        # Série "Station Eleven" -> préfixe St -> doit choisir Sp-Sz (pas Sa-So)
        series = Series(title="Station Eleven", year=2025, genres=("Drame",))

        path = get_series_video_destination(series, season_number=1, video_dir=tmp_path)

        # Vérifier que le chemin utilise Sp-Sz (le bon choix)
        assert path == tmp_path / "Séries" / "Séries TV" / "S" / "Sp-Sz" / "Station Eleven (2025)" / "Saison 01"


# ====================
# Tests _is_range_dir
# ====================

class TestIsRangeDir:
    """Tests pour la détection des répertoires de plage alphabétique."""

    def test_simple_range(self) -> None:
        """A-G est une plage."""
        assert _is_range_dir("A-G") is True

    def test_two_letter_range(self) -> None:
        """Ba-Bi est une plage."""
        assert _is_range_dir("Ba-Bi") is True

    def test_three_letter_range(self) -> None:
        """Mab-Man est une plage."""
        assert _is_range_dir("Mab-Man") is True

    def test_single_letter_not_range(self) -> None:
        """A n'est pas une plage."""
        assert _is_range_dir("A") is False

    def test_no_dash(self) -> None:
        """American n'est pas une plage."""
        assert _is_range_dir("American") is False

    def test_compound_word_not_range(self) -> None:
        """Au-delà n'est pas une plage (non alphabétique pur)."""
        assert _is_range_dir("Au-delà") is False

    def test_long_word_with_dash(self) -> None:
        """Sous-titre n'est pas une plage (parties trop longues)."""
        assert _is_range_dir("Sous-titre") is False

    def test_numeric_range_not_range(self) -> None:
        """1-9 n'est pas une plage alphabétique."""
        assert _is_range_dir("1-9") is False

    def test_hash_not_range(self) -> None:
        """# n'est pas une plage."""
        assert _is_range_dir("#") is False


# ====================
# Tests _title_matches_prefix_dir
# ====================

class TestTitleMatchesPrefixDir:
    """Tests pour le matching titre -> répertoire préfixe."""

    def test_basic_match(self) -> None:
        """'American Beauty' matche 'American'."""
        assert _title_matches_prefix_dir("American Beauty", "American") is True

    def test_with_article_l_apostrophe(self) -> None:
        """'L'Amant' matche 'Amant' (article L' strippé)."""
        assert _title_matches_prefix_dir("L'Amant", "Amant") is True

    def test_with_article_les_prefix(self) -> None:
        """'Les Amants' matche 'Amant' (prefix, 'Amants' commence par 'Amant')."""
        assert _title_matches_prefix_dir("Les Amants", "Amant") is True

    def test_no_match(self) -> None:
        """'Batman' ne matche pas 'American'."""
        assert _title_matches_prefix_dir("Batman", "American") is False

    def test_excludes_ranges(self) -> None:
        """Ne matche pas les plages alphabétiques comme 'Ba-Bi'."""
        assert _title_matches_prefix_dir("Batman", "Ba-Bi") is False

    def test_excludes_single_letter(self) -> None:
        """Ne matche pas les lettres simples comme 'A'."""
        assert _title_matches_prefix_dir("American Beauty", "A") is False

    def test_case_insensitive(self) -> None:
        """Le matching est insensible à la casse."""
        assert _title_matches_prefix_dir("american beauty", "American") is True

    def test_with_article_le(self) -> None:
        """'Le Monde' matche 'Monde'."""
        assert _title_matches_prefix_dir("Le Monde", "Monde") is True

    def test_compound_word_prefix(self) -> None:
        """'Au-delà des Murs' matche 'Au-delà' (mot composé)."""
        assert _title_matches_prefix_dir("Au-delà des Murs", "Au-delà") is True

    def test_exact_prefix_match(self) -> None:
        """'American' seul matche 'American'."""
        assert _title_matches_prefix_dir("American", "American") is True

    def test_empty_title(self) -> None:
        """Titre vide ne matche rien."""
        assert _title_matches_prefix_dir("", "American") is False

    def test_empty_dirname(self) -> None:
        """Nom de répertoire vide ne matche rien."""
        assert _title_matches_prefix_dir("American Beauty", "") is False


# ====================
# Tests _find_matching_subdir avec préfixes
# ====================

class TestFindMatchingSubdirPrefix:
    """Tests pour _find_matching_subdir avec des répertoires préfixe."""

    def test_prefix_directory_match(self, tmp_path: Path) -> None:
        """Un répertoire 'American' matche le titre 'American Beauty'."""
        parent = tmp_path / "A-Ami"
        american_dir = parent / "American"
        american_dir.mkdir(parents=True)

        result = _find_matching_subdir(parent, "American Beauty")
        assert result == american_dir

    def test_prefix_preferred_over_nothing(self, tmp_path: Path) -> None:
        """Un préfixe est trouvé même sans plage correspondante."""
        parent = tmp_path / "test"
        prefix_dir = parent / "Amour"
        prefix_dir.mkdir(parents=True)

        result = _find_matching_subdir(parent, "L'Amour Fou")
        assert result == prefix_dir

    def test_range_takes_priority_over_prefix(self, tmp_path: Path) -> None:
        """Une plage qui matche est préférée au préfixe (pass 1 avant pass 2)."""
        parent = tmp_path / "test"
        range_dir = parent / "Am-An"
        prefix_dir = parent / "American"
        range_dir.mkdir(parents=True)
        prefix_dir.mkdir(parents=True)

        # La plage Am-An matche "American Beauty" en pass 1 → on ne teste pas le préfixe
        result = _find_matching_subdir(parent, "American Beauty")
        assert result == range_dir

    def test_prefix_not_matched_when_unrelated(self, tmp_path: Path) -> None:
        """Un préfixe qui ne correspond pas n'est pas retourné."""
        parent = tmp_path / "test"
        prefix_dir = parent / "Barbara"
        prefix_dir.mkdir(parents=True)

        result = _find_matching_subdir(parent, "Batman Begins")
        assert result is None


# ====================
# Tests navigation complète avec préfixes
# ====================

class TestNavigateToLeafWithPrefix:
    """Tests pour _navigate_to_leaf traversant des répertoires préfixe."""

    def test_navigate_into_prefix_dir(self, tmp_path: Path) -> None:
        """Descente dans A-Ami/American/ pour 'American Beauty'."""
        from src.services.organizer import _navigate_to_leaf

        # Structure : genre/A-Ami/American/
        genre_dir = tmp_path / "Films" / "Drame"
        a_ami_dir = genre_dir / "A-Ami"
        american_dir = a_ami_dir / "American"
        american_dir.mkdir(parents=True)
        # Ajouter un fichier media pour que has_media_files = True
        (american_dir / "American Beauty (1999) MULTi HEVC 1080p.mkv").touch()

        result = _navigate_to_leaf(genre_dir, "American Beauty")
        assert result == american_dir

    def test_navigate_prefix_with_article(self, tmp_path: Path) -> None:
        """Descente dans A-Ami/Amant/ pour 'L'Amant (1992)'."""
        from src.services.organizer import _navigate_to_leaf

        # Structure : genre/A-Ami/Amant/
        genre_dir = tmp_path / "Films" / "Drame"
        a_ami_dir = genre_dir / "A-Ami"
        amant_dir = a_ami_dir / "Amant"
        amant_dir.mkdir(parents=True)
        (amant_dir / "L'Amant (1992) FR HEVC 1080p.mkv").touch()

        result = _navigate_to_leaf(genre_dir, "L'Amant")
        assert result == amant_dir

    def test_movie_destination_with_prefix_dir(self, tmp_path: Path) -> None:
        """Test intégré complet : get_movie_video_destination avec structure préfixe."""
        # Structure : video/Films/Drame/A-Ami/American/
        genre_dir = tmp_path / "Films" / "Drame"
        a_ami_dir = genre_dir / "A-Ami"
        american_dir = a_ami_dir / "American"
        american_dir.mkdir(parents=True)
        (american_dir / "American History X (1998) MULTi HEVC 1080p.mkv").touch()

        movie = Movie(
            title="American Beauty",
            year=1999,
            genres=("Drame",),
        )

        result = get_movie_video_destination(movie, tmp_path)
        assert result == american_dir
