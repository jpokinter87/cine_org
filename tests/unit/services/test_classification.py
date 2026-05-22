"""Tests de la classification dynamique MOVIE/SHORT/SERIES."""

from pathlib import Path

from src.core.value_objects import MediaInfo, MediaType
from src.services.classification import classify_media


THRESHOLD_SECONDS = 900  # 15 minutes


def _media_info(duration: int | None) -> MediaInfo:
    return MediaInfo(duration_seconds=duration)


class TestClassifyMedia:
    """Règles de classification entre MOVIE, SHORT et SERIES."""

    def test_long_film_under_films_dir_is_movie(self) -> None:
        path = Path("/media/storage/Films/Action/Heat (1995).mkv")
        result = classify_media(path, _media_info(7200), THRESHOLD_SECONDS)
        assert result is MediaType.MOVIE

    def test_short_film_under_films_dir_is_short(self) -> None:
        path = Path("/media/storage/Films/Animation/Mon_petit_court.mkv")
        result = classify_media(path, _media_info(420), THRESHOLD_SECONDS)
        assert result is MediaType.SHORT

    def test_episode_under_series_dir_stays_series_even_if_under_threshold(
        self,
    ) -> None:
        """La priorité absolue du chemin Séries/ doit l'emporter sur la durée."""
        path = Path("/media/storage/Séries/Breaking Bad (2008)/Saison 01/Pilot.mkv")
        result = classify_media(path, _media_info(1500), THRESHOLD_SECONDS)
        assert result is MediaType.SERIES

    def test_episode_under_series_dir_stays_series_when_short_duration(self) -> None:
        """Un épisode court (<15 min) sous Séries/ reste SERIES, jamais SHORT."""
        path = Path("/media/storage/Séries/Mini Series/Saison 01/E01.mkv")
        result = classify_media(path, _media_info(600), THRESHOLD_SECONDS)
        assert result is MediaType.SERIES

    def test_series_dir_without_accent_also_recognised(self) -> None:
        """Tolère l'orthographe sans accent (downloads/Series)."""
        path = Path("/media/downloads/Series/Show/S01E01.mkv")
        result = classify_media(path, _media_info(1800), THRESHOLD_SECONDS)
        assert result is MediaType.SERIES

    def test_short_under_animations_dir_is_short_not_series(self) -> None:
        """Animations/ ≠ Séries/ : un court y reste SHORT."""
        path = Path("/media/storage/Animations/Pixar/Lava.mkv")
        result = classify_media(path, _media_info(300), THRESHOLD_SECONDS)
        assert result is MediaType.SHORT

    def test_unknown_duration_falls_back_to_movie(self) -> None:
        """Sans info de durée, on suppose un MOVIE (comportement courant)."""
        path = Path("/media/storage/Films/Drame/Inconnu.mkv")
        result = classify_media(path, _media_info(None), THRESHOLD_SECONDS)
        assert result is MediaType.MOVIE

    def test_duration_equal_to_threshold_is_short(self) -> None:
        """Seuil inclusif : 900s exactement → SHORT."""
        path = Path("/media/storage/Films/Court.mkv")
        result = classify_media(path, _media_info(900), THRESHOLD_SECONDS)
        assert result is MediaType.SHORT

    def test_duration_just_above_threshold_is_movie(self) -> None:
        """901s → MOVIE (au-dessus du seuil)."""
        path = Path("/media/storage/Films/PetitFilm.mkv")
        result = classify_media(path, _media_info(901), THRESHOLD_SECONDS)
        assert result is MediaType.MOVIE
