"""Structures de données pour le calcul de complétude des séries."""

from dataclasses import dataclass, field


@dataclass
class MissingEpisode:
    """Un épisode attendu (déjà diffusé) mais absent de la vidéothèque."""

    season: int
    episode: int
    air_date: str | None
    title: str


@dataclass
class CompletenessResult:
    """Verdict de complétude d'une série."""

    status: str  # "complete" | "incomplete"
    missing_seasons: list[int] = field(default_factory=list)
    missing_episodes: list[MissingEpisode] = field(default_factory=list)
    expected_aired: int = 0
    owned: int = 0
    source: str = "tvdb"
