"""Générateurs de fichiers NFO (XML) pour Jellyfin, à partir des modèles DB.

Fonctions pures : un modèle en entrée, une chaîne XML en sortie. Les champs
absents sont omis (pas de balise vide). Les valeurs surchargées (`*_override`)
priment sur les valeurs d'origine.
"""

import xml.etree.ElementTree as ET

from src.infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    SeriesModel,
)

_XML_DECL = '<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n'


def _text(parent: ET.Element, tag: str, value: object) -> None:
    """Ajoute <tag>value</tag> si value est non vide/non None."""
    if value is None:
        return
    s = str(value).strip()
    if s == "":
        return
    ET.SubElement(parent, tag).text = s


def _add_ratings(
    root: ET.Element,
    tmdb_avg: float | None,
    tmdb_votes: int | None,
    imdb_avg: float | None,
    imdb_votes: int | None,
) -> None:
    """Ajoute un bloc <ratings> + un <rating> de tête (compat Jellyfin)."""
    entries = []
    if tmdb_avg is not None:
        entries.append(("themoviedb", tmdb_avg, tmdb_votes, "true"))
    if imdb_avg is not None:
        entries.append(("imdb", imdb_avg, imdb_votes, "false"))
    if not entries:
        return
    ratings = ET.SubElement(root, "ratings")
    for name, value, votes, default in entries:
        r = ET.SubElement(
            ratings, "rating", {"name": name, "max": "10", "default": default}
        )
        ET.SubElement(r, "value").text = f"{value:.1f}"
        if votes is not None:
            ET.SubElement(r, "votes").text = str(votes)
    # compat Jellyfin : note de tête = premier fournisseur (TMDB si présent)
    _text(root, "rating", f"{entries[0][1]:.1f}")


def _add_actors(root: ET.Element, model: "MovieModel | SeriesModel") -> None:
    """Ajoute les <actor>. Priorité au cast surchargé (avec rôles)."""
    override = getattr(model, "cast_override", [])
    if override:
        for entry in override:
            actor = ET.SubElement(root, "actor")
            _text(actor, "name", entry.get("name"))
            _text(actor, "role", entry.get("role"))
        return
    for name in model.cast:
        actor = ET.SubElement(root, "actor")
        _text(actor, "name", name)


def _add_common(root: ET.Element, model: "MovieModel | SeriesModel") -> None:
    """Champs communs film/série : titres, année, plot, genres, notes, etc."""
    _text(root, "title", model.title)
    _text(root, "originaltitle", model.original_title)
    _text(root, "year", model.year)
    plot = model.overview_override or model.overview
    _text(root, "plot", plot)
    duration = getattr(model, "duration_seconds", None)
    if duration is not None:
        _text(root, "runtime", duration // 60)
    for genre in model.genres:
        _text(root, "genre", genre)
    _add_ratings(
        root, model.vote_average, model.vote_count, model.imdb_rating, model.imdb_votes
    )
    _text(root, "userrating", model.personal_rating)
    if model.director:
        for name in [d.strip() for d in model.director.split(",") if d.strip()]:
            _text(root, "director", name)
    _add_actors(root, model)
    poster = model.poster_override or model.poster_path
    if poster:
        art = ET.SubElement(root, "art")
        _text(art, "poster", poster)


def _serialize(root: ET.Element) -> str:
    return _XML_DECL + ET.tostring(root, encoding="unicode")


def build_movie_nfo(movie: MovieModel) -> str:
    """Construit le contenu de `movie.nfo`."""
    root = ET.Element("movie")
    _add_common(root, movie)
    if movie.tmdb_id is not None:
        ET.SubElement(root, "uniqueid", {"type": "tmdb", "default": "true"}).text = str(
            movie.tmdb_id
        )
    if movie.imdb_id:
        ET.SubElement(root, "uniqueid", {"type": "imdb"}).text = movie.imdb_id
    if movie.collection_name:
        s = ET.SubElement(root, "set")
        _text(s, "name", movie.collection_name)
    if movie.watched:
        _text(root, "playcount", 1)
        _text(root, "watched", "true")
    return _serialize(root)


def build_tvshow_nfo(series: SeriesModel) -> str:
    """Construit le contenu de `tvshow.nfo`."""
    root = ET.Element("tvshow")
    _add_common(root, series)
    if series.tvdb_id is not None:
        ET.SubElement(root, "uniqueid", {"type": "tvdb", "default": "true"}).text = str(
            series.tvdb_id
        )
    if series.tmdb_id is not None:
        ET.SubElement(root, "uniqueid", {"type": "tmdb"}).text = str(series.tmdb_id)
    if series.imdb_id:
        ET.SubElement(root, "uniqueid", {"type": "imdb"}).text = series.imdb_id
    return _serialize(root)


def build_episode_nfo(episode: EpisodeModel) -> str:
    """Construit le NFO d'un épisode (sidecar `{nom}.nfo`)."""
    root = ET.Element("episodedetails")
    _text(root, "title", episode.title)
    _text(root, "season", episode.season_number)
    _text(root, "episode", episode.episode_number)
    if episode.air_date is not None:
        _text(root, "aired", episode.air_date.isoformat())
    _text(root, "plot", episode.overview)
    if episode.duration_seconds:
        _text(root, "runtime", episode.duration_seconds // 60)
    return _serialize(root)
