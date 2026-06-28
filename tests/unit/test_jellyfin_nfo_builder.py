"""Tests des générateurs de NFO Jellyfin."""

import xml.etree.ElementTree as ET
from datetime import date

from src.infrastructure.persistence.models import EpisodeModel, MovieModel, SeriesModel
from src.services.jellyfin.nfo_builder import (
    build_episode_nfo,
    build_movie_nfo,
    build_tvshow_nfo,
)


def _parse(xml_str: str) -> ET.Element:
    return ET.fromstring(xml_str)


def test_movie_nfo_uniqueids_and_titles():
    movie = MovieModel(
        title="Inception",
        original_title="Inception",
        year=2010,
        tmdb_id=27205,
        imdb_id="tt1375666",
        duration_seconds=8880,  # 148 min
        overview="Un voleur…",
        vote_average=8.4,
        vote_count=30000,
        imdb_rating=8.8,
        imdb_votes=2400000,
        personal_rating=9,
        director="Christopher Nolan",
        collection_name="Saga Inception",
    )
    movie.genres = ["Action", "Science-Fiction"]
    movie.cast = ["Leonardo DiCaprio", "Elliot Page"]

    root = _parse(build_movie_nfo(movie))

    assert root.tag == "movie"
    assert root.findtext("title") == "Inception"
    assert root.findtext("originaltitle") == "Inception"
    assert root.findtext("year") == "2010"
    assert root.findtext("runtime") == "148"
    assert root.findtext("plot") == "Un voleur…"

    ids = {u.get("type"): (u.text, u.get("default")) for u in root.findall("uniqueid")}
    assert ids["tmdb"] == ("27205", "true")
    assert ids["imdb"][0] == "tt1375666"

    genres = [g.text for g in root.findall("genre")]
    assert genres == ["Action", "Science-Fiction"]

    actors = [a.findtext("name") for a in root.findall("actor")]
    assert actors == ["Leonardo DiCaprio", "Elliot Page"]

    assert root.findtext("set/name") == "Saga Inception"
    assert root.findtext("userrating") == "9"


def test_movie_nfo_overrides_take_precedence():
    movie = MovieModel(title="X", year=2000, tmdb_id=1, overview="ancien")
    movie.overview_override = "nouveau synopsis"
    movie.poster_override = "http://poster/override.jpg"
    movie.poster_path = "http://poster/origin.jpg"
    movie.cast_override_json = '[{"name": "Acteur Surchargé", "role": "Héros"}]'

    root = _parse(build_movie_nfo(movie))

    assert root.findtext("plot") == "nouveau synopsis"
    assert root.findtext("art/poster") == "http://poster/override.jpg"
    actors = [(a.findtext("name"), a.findtext("role")) for a in root.findall("actor")]
    assert actors == [("Acteur Surchargé", "Héros")]


def test_movie_nfo_omits_absent_fields():
    movie = MovieModel(title="Minimal", tmdb_id=42)
    root = _parse(build_movie_nfo(movie))
    assert root.findtext("title") == "Minimal"
    assert root.find("year") is None
    assert root.find("plot") is None
    assert root.find("set") is None


def test_movie_nfo_escapes_special_chars():
    movie = MovieModel(title="Tom & Jerry <Le film>", year=2021, tmdb_id=5)
    xml_str = build_movie_nfo(movie)
    root = _parse(xml_str)
    assert root.findtext("title") == "Tom & Jerry <Le film>"


def test_tvshow_nfo_uniqueids():
    series = SeriesModel(
        title="12 Monkeys",
        year=2015,
        tvdb_id=272644,
        tmdb_id=60948,
        imdb_id="tt3148266",
        overview="Voyage temporel…",
    )
    series.genres = ["Science-Fiction"]
    series.cast = ["Aaron Stanford"]
    root = ET.fromstring(build_tvshow_nfo(series))

    assert root.tag == "tvshow"
    assert root.findtext("title") == "12 Monkeys"
    ids = {u.get("type"): (u.text, u.get("default")) for u in root.findall("uniqueid")}
    assert ids["tvdb"] == ("272644", "true")
    assert ids["tmdb"][0] == "60948"
    assert ids["imdb"][0] == "tt3148266"
    assert [g.text for g in root.findall("genre")] == ["Science-Fiction"]


def test_episode_nfo_fields():
    ep = EpisodeModel(
        series_id=1,
        season_number=1,
        episode_number=3,
        title="Le Syndrome de Cassandra",
        air_date=date(2015, 1, 30),
        overview="Cole et Railly…",
        duration_seconds=2580,  # 43 min
    )
    root = ET.fromstring(build_episode_nfo(ep))

    assert root.tag == "episodedetails"
    assert root.findtext("title") == "Le Syndrome de Cassandra"
    assert root.findtext("season") == "1"
    assert root.findtext("episode") == "3"
    assert root.findtext("aired") == "2015-01-30"
    assert root.findtext("plot") == "Cole et Railly…"
    assert root.findtext("runtime") == "43"
