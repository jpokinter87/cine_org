"""Détection et nettoyage des fiches DB pointant vers des fichiers disparus.

Scanne ``MovieModel`` et ``EpisodeModel`` à la recherche d'entrées dont le
``file_path`` ne pointe plus sur un fichier existant. Permet d'envoyer les
fiches détectées en corbeille (réversible) sans toucher au filesystem.

Aligné sur la sémantique de ``/library/delete-batch`` :
* la fiche est sérialisée puis poussée dans ``TrashModel`` (restauration possible) ;
* le ``VideoFileModel`` associé est purgé (la cible était de toute façon
  manquante) ;
* le fichier storage n'est jamais touché — il l'est déjà ailleurs (ou pas).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from sqlmodel import Session, select

from src.infrastructure.persistence.models import (
    EpisodeModel,
    MovieModel,
    SeriesModel,
    TrashModel,
    VideoFileModel,
)


@dataclass(frozen=True)
class MissingRecord:
    """Fiche DB dont le ``file_path`` n'existe plus sur le filesystem."""

    entity_type: str  # "movie" | "episode"
    entity_id: int
    title: str  # libellé d'affichage (avec contexte série pour les épisodes)
    file_path: str


def _serialize_model(model) -> str:
    """Sérialise toutes les colonnes d'un SQLModel en JSON (pour la corbeille)."""
    data = {}
    for col in model.__class__.__table__.columns:
        val = getattr(model, col.name)
        if val is not None and hasattr(val, "isoformat"):
            val = val.isoformat()
        data[col.name] = val
    return json.dumps(data, ensure_ascii=False)


class MissingFilesScanner:
    """Recherche puis nettoyage des fiches orphelines (fichiers disparus)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find_missing(self) -> list[MissingRecord]:
        """Renvoie la liste triée des fiches dont le file_path n'existe plus.

        Tri stable : films d'abord (par titre), puis épisodes (par série,
        saison, épisode).
        """
        missing: list[MissingRecord] = []

        # Films
        movie_stmt = (
            select(MovieModel)
            .where(MovieModel.file_path.isnot(None))
            .order_by(MovieModel.title)
        )
        for movie in self._session.exec(movie_stmt).all():
            if Path(movie.file_path).exists():
                continue
            missing.append(
                MissingRecord(
                    entity_type="movie",
                    entity_id=int(movie.id),
                    title=movie.title or "",
                    file_path=movie.file_path,
                )
            )

        # Épisodes
        episode_stmt = (
            select(EpisodeModel)
            .where(EpisodeModel.file_path.isnot(None))
            .order_by(
                EpisodeModel.series_id,
                EpisodeModel.season_number,
                EpisodeModel.episode_number,
            )
        )
        # Cache série_id → titre série pour libellé lisible
        series_titles: dict[int, str] = {}
        for episode in self._session.exec(episode_stmt).all():
            if Path(episode.file_path).exists():
                continue
            if episode.series_id not in series_titles:
                series = self._session.get(SeriesModel, episode.series_id)
                series_titles[episode.series_id] = series.title if series else "?"
            series_title = series_titles[episode.series_id]
            label = (
                f"{series_title} — "
                f"S{episode.season_number:02d}E{episode.episode_number:02d} — "
                f"{episode.title}"
            )
            missing.append(
                MissingRecord(
                    entity_type="episode",
                    entity_id=int(episode.id),
                    title=label,
                    file_path=episode.file_path,
                )
            )

        return missing

    def prune(self, records: Iterable[MissingRecord]) -> int:
        """Envoie chaque fiche en corbeille (réversible). Retourne le compte.

        Le fichier storage n'est jamais touché (il est déjà absent par
        définition). Le ``VideoFileModel`` associé est purgé si présent.
        """
        pruned = 0
        for rec in records:
            if rec.entity_type == "movie":
                model = self._session.get(MovieModel, rec.entity_id)
            elif rec.entity_type == "episode":
                model = self._session.get(EpisodeModel, rec.entity_id)
            else:
                continue
            if model is None:
                continue

            metadata = _serialize_model(model)

            if getattr(model, "file_path", None):
                vf = self._session.exec(
                    select(VideoFileModel).where(VideoFileModel.path == model.file_path)
                ).first()
                if vf:
                    self._session.delete(vf)

            self._session.add(
                TrashModel(
                    entity_type=rec.entity_type,
                    original_id=rec.entity_id,
                    metadata_json=metadata,
                    deletion_reason="missing_file",
                )
            )
            self._session.delete(model)
            pruned += 1

        if pruned:
            self._session.commit()
        return pruned
