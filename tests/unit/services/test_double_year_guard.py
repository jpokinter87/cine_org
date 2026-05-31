"""Garde-fou anti double année : un titre embarquant déjà « (AAAA) » ne doit pas
produire « Titre (AAAA) (AAAA) » dans les dossiers ni les noms de fichiers.

Couvre les 3 sites : organizer (dossier série), renamer (film + série).
"""

from pathlib import Path

from src.core.entities.media import Episode, Movie, Series
from src.services.organizer import get_series_video_destination
from src.services.renamer import generate_movie_filename, generate_series_filename


def test_organizer_serie_titre_avec_annee_pas_de_double(tmp_path: Path):
    """« Surface (2025) » + year=2025 -> dossier « Surface (2025) », pas « (2025) (2025) »."""
    series = Series(title="Surface (2025)", year=2025, genres=("Drame",))
    dest = get_series_video_destination(series, 1, tmp_path)
    assert "(2025) (2025)" not in str(dest)
    assert "Surface (2025)" in str(dest)
    assert dest.name == "Saison 01"
    assert dest.parent.name == "Surface (2025)"


def test_organizer_serie_titre_sans_annee_inchange(tmp_path: Path):
    """Titre sans année embarquée : comportement habituel « Titre (Année) »."""
    series = Series(title="Detectorists", year=2014, genres=("Comédie",))
    dest = get_series_video_destination(series, 1, tmp_path)
    assert dest.parent.name == "Detectorists (2014)"


def test_renamer_film_titre_avec_annee_pas_de_double():
    """Film « Wind (2025) » + year=2025 -> « Wind (2025) … », pas de double année."""
    movie = Movie(title="Wind (2025)", year=2025)
    name = generate_movie_filename(movie, None, ".mkv")
    assert "(2025) (2025)" not in name
    assert name.startswith("Wind (2025)")


def test_renamer_serie_titre_avec_annee_pas_de_double():
    """Épisode d'une série dont le titre embarque l'année -> pas de double année."""
    series = Series(title="Surface (2025)", year=2025)
    episode = Episode(season_number=1, episode_number=1, title="Crise")
    name = generate_series_filename(series, episode, None, ".mkv")
    assert "(2025) (2025)" not in name
    assert name.startswith("Surface (2025) - S01E01")
