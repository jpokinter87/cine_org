"""
Fonctions utilitaires partagées pour les routes de la bibliothèque.
"""

import json
from pathlib import Path

from sqlmodel import select

from ....infrastructure.persistence.database import get_session
from ....infrastructure.persistence.models import EpisodeModel
from ....utils.constants import GENRE_FOLDER_MAPPING
from ....utils.helpers import search_variants


ITEMS_PER_PAGE = 24


def _title_search_filter(model_class, q: str, extended: bool = False):
    """Construit un filtre SQL de recherche par titre avec gestion des ligatures."""
    from sqlalchemy import or_

    variants = search_variants(q)
    title_conditions = [model_class.title.contains(v) for v in variants]
    if extended and hasattr(model_class, "overview"):
        overview_conditions = [model_class.overview.contains(v) for v in variants]
        return or_(*title_conditions, *overview_conditions)
    return or_(*title_conditions)


def _parse_genres(genres_json: str | None) -> list[str]:
    """Parse le champ genres_json en liste de strings."""
    if genres_json:
        try:
            return json.loads(genres_json)
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def _get_storage_genre_info(
    genres: list[str],
) -> tuple[str | None, str | None]:
    """Détermine le genre de rangement et le dossier correspondant.

    Retourne (genre_prioritaire, dossier_rangement).
    Le genre prioritaire est celui qui a la plus haute priorité dans GENRE_HIERARCHY.
    La comparaison est insensible aux accents via GENRE_FOLDER_MAPPING.
    """
    if not genres:
        return None, None

    # Trouver le genre prioritaire via le folder mapping (gère les accents)
    from ....utils.constants import GENRE_HIERARCHY

    best_genre = None
    best_priority = len(GENRE_HIERARCHY)
    for g in genres:
        folder = GENRE_FOLDER_MAPPING.get(g.lower())
        if folder is None:
            continue
        # Trouver la priorité de ce genre dans la hiérarchie
        for i, h in enumerate(GENRE_HIERARCHY):
            if h.lower() == g.lower() or GENRE_FOLDER_MAPPING.get(h.lower()) == folder:
                if i < best_priority:
                    best_priority = i
                    best_genre = g
                break

    if best_genre is None:
        best_genre = genres[0]

    storage_folder = GENRE_FOLDER_MAPPING.get(best_genre.lower())
    return best_genre, storage_folder


def _genre_json_escaped(genre: str) -> str:
    """Retourne la version JSON-escaped d'un genre pour LIKE SQL.

    Les genres_json en DB utilisent json.dumps(ensure_ascii=True) par défaut,
    donc "Comédie" est stocké comme "Com\\u00e9die". Ce helper génère
    la version escaped pour que le LIKE SQL fonctionne.
    """
    # json.dumps produit '"Com\\u00e9die"', on retire les guillemets
    return json.dumps(genre)[1:-1]


def _format_duration(seconds: int | None) -> str:
    """Formate une duree en secondes en 'Xh XXmin'."""
    if not seconds:
        return ""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes:02d}min"
    return f"{minutes}min"


def _resolution_label(resolution: str | None) -> str:
    """Convertit '1920x1080' en '1080p' via Resolution.label."""
    if not resolution or "x" not in resolution:
        return resolution or ""
    try:
        w, h = resolution.split("x")
        from ....core.value_objects.media_info import Resolution

        return Resolution(width=int(w), height=int(h)).label
    except (ValueError, TypeError):
        return resolution


def _resolution_pixels(resolution: str | None) -> int:
    """Convertit '1920x1080' en nombre total de pixels pour le tri."""
    if not resolution or "x" not in resolution:
        return 0
    try:
        w, h = resolution.split("x")
        return int(w) * int(h)
    except (ValueError, TypeError):
        return 0


def _poster_url(poster_path: str | None) -> str | None:
    """Construit l'URL poster TMDB."""
    if poster_path:
        if poster_path.startswith("http"):
            return poster_path
        return f"https://image.tmdb.org/t/p/w300{poster_path}"
    return None


def _best_rating(vote_average: float | None, imdb_rating: float | None) -> float | None:
    """Retourne la meilleure note disponible : IMDb en priorite, sinon TMDB."""
    if imdb_rating is not None:
        return imdb_rating
    return vote_average


def _find_movie_file(title: str, year: int | None, original_title: str | None = None) -> dict | None:
    """
    Recherche le fichier d'un film dans video/Films/ par titre et annee,
    puis en fallback dans les VideoFiles en DB par titre approche.

    Strategie : file_path en DB, sinon resolution du symlink via glob,
    sinon recherche dans VideoFileModel par titre approche (LIKE SQL).

    Returns:
        Dict avec symlink_path et storage_path, ou None si non trouve
    """
    from ....config import Settings
    from ....infrastructure.persistence.models import VideoFileModel

    try:
        settings = Settings()
        video_dir = Path(settings.video_dir) / "Films"
    except Exception:
        video_dir = None

    def _normalize(s: str) -> str:
        """Retire les caracteres speciaux pour comparaison."""
        return "".join(c.lower() for c in s if c.isalnum() or c == " ").strip()

    # 1) Glob dans video/Films/ par titre + annee (exact)
    if video_dir and video_dir.exists() and year:
        norm_title = _normalize(title)
        year_str = f"({year})"
        for f in video_dir.rglob(f"*{year_str}*"):
            if not f.is_file():
                continue
            fname = f.name
            idx = fname.find(year_str)
            if idx <= 0:
                continue
            file_title = fname[:idx].strip()
            if _normalize(file_title) == norm_title:
                try:
                    storage_path = str(f.resolve()) if f.is_symlink() else None
                except OSError:
                    storage_path = None
                return {"symlink_path": str(f), "storage_path": storage_path}

    # 2) Recherche dans VideoFileModel par titre approche
    session = next(get_session())
    try:
        # Chercher avec le titre principal puis le titre original
        search_titles = [title]
        if original_title and original_title != title:
            search_titles.append(original_title)

        for search_title in search_titles:
            # Extraire les mots significatifs (>= 3 chars) pour la recherche
            words = [w for w in search_title.split() if len(w) >= 3]
            if not words:
                continue
            # Utiliser le mot le plus long comme terme principal
            main_word = max(words, key=len)
            candidates = session.exec(
                select(VideoFileModel)
                .where(VideoFileModel.path.contains(main_word))
                .where(VideoFileModel.path.contains("/Films/"))
            ).all()

            for vf in candidates:
                fp = Path(vf.path)
                fname_norm = _normalize(fp.stem)
                title_norm = _normalize(search_title)
                # Match si le titre normalise est contenu dans le nom de fichier
                if title_norm in fname_norm or fname_norm.startswith(title_norm[:15]):
                    return {
                        "symlink_path": vf.symlink_path,
                        "storage_path": str(vf.path),
                        "video_file": vf,
                    }
    finally:
        session.close()

    return None


def _get_file_duration(movie) -> int | None:
    """
    Extrait la duree reelle d'un fichier video via mediainfo.

    Strategie : file_path en DB, sinon resolution du symlink via _find_movie_file.
    """
    from ....adapters.parsing.mediainfo_extractor import MediaInfoExtractor

    # 1. file_path direct en DB
    physical_path = movie.file_path

    # 2. Sinon, trouver le symlink dans video/ et resoudre vers le storage
    if not physical_path:
        file_info = _find_movie_file(movie.title, movie.year)
        if file_info:
            physical_path = file_info.get("storage_path") or file_info.get(
                "symlink_path"
            )

    if not physical_path:
        return None

    path = Path(physical_path)
    # Si c'est un symlink, resoudre vers le fichier physique
    if path.is_symlink():
        path = path.resolve()
    if not path.exists():
        return None

    try:
        info = MediaInfoExtractor().extract(path)
        return info.duration_seconds if info else None
    except Exception:
        return None


def _duration_indicator(local_seconds: int | None, tmdb_seconds: int | None) -> dict:
    """
    Compare les durees locale et TMDB, retourne un indicateur visuel.

    Memes seuils que le CLI (candidate_display._get_duration_color) :
    - < 5 min : vert (coherent)
    - 5-15 min : jaune (ecart modere)
    - >= 15 min : rouge (tres different)
    """
    if not local_seconds or not tmdb_seconds:
        return {"show": False}

    diff = abs(local_seconds - tmdb_seconds)
    if diff < 5 * 60:
        return {"show": True, "css": "duration-match", "label": "Durée cohérente"}
    elif diff < 15 * 60:
        return {"show": True, "css": "duration-warn", "label": "Écart modéré"}
    else:
        return {
            "show": True,
            "css": "duration-danger",
            "label": "Durée très différente",
        }


def _series_indicator(
    local_seasons: int | None,
    local_episodes: int | None,
    tmdb_seasons: int | None,
    tmdb_episodes: int | None,
) -> dict:
    """Compare saisons/episodes locaux et TMDB pour indicateur de confiance."""
    if not local_episodes or not tmdb_episodes:
        return {"show": False}

    ep_diff = abs(local_episodes - tmdb_episodes)
    season_match = (
        local_seasons == tmdb_seasons if local_seasons and tmdb_seasons else True
    )

    if ep_diff == 0 and season_match:
        return {"show": True, "css": "duration-match", "label": "Correspondance exacte"}
    elif ep_diff <= 3 and season_match:
        return {"show": True, "css": "duration-match", "label": "Très proche"}
    elif ep_diff <= 10:
        return {"show": True, "css": "duration-warn", "label": "Écart modéré"}
    else:
        return {"show": True, "css": "duration-danger", "label": "Très différent"}


def _get_local_series_counts(series_id: int) -> tuple[int, int]:
    """Compte les saisons et episodes locaux depuis la DB."""
    session = next(get_session())
    try:
        episodes = session.exec(
            select(EpisodeModel).where(EpisodeModel.series_id == series_id)
        ).all()
        if not episodes:
            return 0, 0
        seasons = set()
        for ep in episodes:
            seasons.add(ep.season_number)
        return len(seasons), len(episodes)
    finally:
        session.close()
