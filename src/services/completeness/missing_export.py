"""
Inventaire exportable des épisodes manquants.

Le verdict de complétude vit en base sous forme de JSON par série. Ce module
l'aplatit en une liste de lignes — une par manque — enrichie de la qualité à
rechercher, pour préparer une session de mise à jour de la vidéothèque.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Optional, Sequence

from sqlmodel import Session, select

from src.infrastructure.persistence.models import EpisodeModel, SeriesModel
from src.services.completeness.quality_profile import (
    compute_quality_profile,
    format_profile,
    profile_for_season,
)

_CSV_HEADER = ["serie", "annee", "saison", "episode", "titre", "diffusion", "qualite"]


@dataclass(frozen=True)
class MissingEntry:
    """Un manque à combler : un épisode, ou une saison entière."""

    series_title: str
    series_year: Optional[int]
    season: int
    episode: Optional[int]
    episode_title: str = ""
    air_date: Optional[str] = None
    quality: str = ""

    @property
    def is_whole_season(self) -> bool:
        """Vrai quand c'est la saison entière qui manque."""
        return self.episode is None

    @property
    def code(self) -> str:
        """Code du manque : « S01E11 » ou « Saison 02 »."""
        if self.is_whole_season:
            return f"Saison {self.season:02d}"
        return f"S{self.season:02d}E{self.episode:02d}"


def _series_label(entry: MissingEntry) -> str:
    """Titre de série suivi de son année, quand elle est connue."""
    if entry.series_year:
        return f"{entry.series_title} ({entry.series_year})"
    return entry.series_title


def build_missing_entries(
    session: Session, series_ids: Optional[Sequence[int]] = None
) -> list[MissingEntry]:
    """
    Construit l'inventaire des manques à partir des verdicts persistés.

    Args:
        session: session SQLModel active.
        series_ids: restreint l'inventaire à ces séries (toutes si None).

    Returns:
        Les manques, triés par série puis par ordre de diffusion. Les séries
        complètes, non vérifiables ou au verdict illisible sont ignorées.
    """
    statement = select(SeriesModel).where(
        SeriesModel.completeness_status == "incomplete"
    )
    if series_ids is not None:
        statement = statement.where(SeriesModel.id.in_(list(series_ids)))

    entries: list[MissingEntry] = []
    for series in session.exec(statement).all():
        if not series.completeness_missing_json:
            continue
        try:
            detail = json.loads(series.completeness_missing_json)
        except (ValueError, TypeError):
            continue

        episodes = session.exec(
            select(EpisodeModel).where(EpisodeModel.series_id == series.id)
        ).all()
        series_profile = compute_quality_profile(episodes, "Série")

        for missing in detail.get("missing_episodes") or []:
            season = missing.get("season")
            if season is None:
                continue
            entries.append(
                MissingEntry(
                    series_title=series.title,
                    series_year=series.year,
                    season=season,
                    episode=missing.get("episode"),
                    episode_title=missing.get("title") or "",
                    air_date=missing.get("air_date"),
                    quality=format_profile(
                        profile_for_season(episodes, season, series_profile)
                    ),
                )
            )

        series_quality = format_profile(series_profile)
        for season in detail.get("missing_seasons") or []:
            entries.append(
                MissingEntry(
                    series_title=series.title,
                    series_year=series.year,
                    season=season,
                    episode=None,
                    quality=series_quality,
                )
            )

    entries.sort(
        key=lambda e: (
            e.series_title.lower(),
            e.season,
            # Une saison entière précède les épisodes isolés de cette saison.
            e.episode if e.episode is not None else -1,
        )
    )
    return entries


def format_entries(entries: Sequence[MissingEntry], fmt: str = "text") -> str:
    """
    Rend l'inventaire dans le format demandé.

    Args:
        entries: les manques à écrire.
        fmt: « text » (une ligne par manque, prête à coller dans une
            recherche) ou « csv » (détail complet, pour un tableur).

    Returns:
        Le contenu formaté, chaîne vide s'il n'y a rien à exporter.

    Raises:
        ValueError: si le format demandé est inconnu.
    """
    if not entries:
        return ""

    if fmt == "text":
        lines = []
        for entry in entries:
            parts = [_series_label(entry), entry.code]
            if entry.is_whole_season:
                parts.append("(complète)")
            line = " ".join(parts)
            if entry.quality:
                line += f" — {entry.quality}"
            lines.append(line)
        return "\n".join(lines)

    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(_CSV_HEADER)
        for entry in entries:
            writer.writerow(
                [
                    entry.series_title,
                    entry.series_year or "",
                    entry.season,
                    entry.episode if entry.episode is not None else "",
                    entry.episode_title,
                    entry.air_date or "",
                    entry.quality,
                ]
            )
        return buffer.getvalue()

    raise ValueError(f"Format d'export inconnu : {fmt}")
