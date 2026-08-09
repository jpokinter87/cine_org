"""
Calcul de la complétude d'une série TV.

Confronte les épisodes détenus en base aux épisodes attendus (TVDB) déjà
diffusés (date de diffusion <= aujourd'hui), en excluant la saison 0, les
épisodes numérotés 0 (SxxE00) et les épisodes hors canon (is_extra).
"""

from __future__ import annotations

import json
from datetime import date, datetime

from sqlmodel import Session, select

from src.infrastructure.persistence.models import EpisodeModel, SeriesModel
from src.services.completeness.dataclasses import (
    CompletenessResult,
    MissingEpisode,
)


def _parse_air_date(raw: str | None) -> date | None:
    """Parse une date de diffusion TVDB (format ISO 'YYYY-MM-DD')."""
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


class CompletenessChecker:
    """Calcule le verdict de complétude d'une série à partir de TVDB."""

    def __init__(self, tvdb_client) -> None:
        """
        Args:
            tvdb_client: client exposant ``get_all_episodes(series_id)``.
        """
        self._tvdb = tvdb_client

    async def compute(
        self,
        tvdb_id: str,
        owned: set[tuple[int, int]],
        today: date,
    ) -> CompletenessResult:
        """
        Calcule la complétude d'une série.

        Args:
            tvdb_id: ID TVDB de la série.
            owned: ensemble des (saison, épisode) détenus avec fichier (hors extra).
            today: date du jour (injectée pour des tests déterministes).

        Returns:
            CompletenessResult décrivant le verdict et les manques.
        """
        all_episodes = await self._tvdb.get_all_episodes(tvdb_id)

        # Filtre « attendu déjà diffusé » : saison>=1, épisode>=1, date<=today.
        expected: dict[tuple[int, int], MissingEpisode] = {}
        for ep in all_episodes:
            if ep.season_number < 1 or ep.episode_number < 1:
                continue
            aired = _parse_air_date(ep.air_date)
            if aired is None or aired > today:
                continue
            key = (ep.season_number, ep.episode_number)
            expected[key] = MissingEpisode(
                season=ep.season_number,
                episode=ep.episode_number,
                air_date=ep.air_date,
                title=ep.title,
            )

        expected_keys = set(expected.keys())
        owned_in_expected = expected_keys & owned

        # Regrouper l'attendu par saison.
        seasons: dict[int, set[int]] = {}
        for season, episode in expected_keys:
            seasons.setdefault(season, set()).add(episode)

        # Une saison n'est signalée comme « absente » que si la série détient
        # par ailleurs au moins un épisode attendu ; sinon (rien de détenu) on
        # liste les épisodes manquants un à un.
        owns_anything = bool(owned_in_expected)

        missing_seasons: list[int] = []
        missing_episodes: list[MissingEpisode] = []
        for season, episodes in seasons.items():
            season_keys = {(season, ep) for ep in episodes}
            if owns_anything and season_keys.isdisjoint(owned):
                # Aucun épisode détenu pour cette saison → saison absente.
                missing_seasons.append(season)
            else:
                for key in season_keys:
                    if key not in owned:
                        missing_episodes.append(expected[key])

        missing_seasons.sort()
        missing_episodes.sort(key=lambda m: (m.season, m.episode))

        status = "incomplete" if (missing_seasons or missing_episodes) else "complete"

        return CompletenessResult(
            status=status,
            missing_seasons=missing_seasons,
            missing_episodes=missing_episodes,
            expected_aired=len(expected_keys),
            owned=len(owned_in_expected),
            source="tvdb",
        )


def _owned_keys(models: list[EpisodeModel]) -> set[tuple[int, int]]:
    """
    Construit l'ensemble des (saison, épisode) réellement détenus.

    Un fichier multi-épisodes (``episode_end`` renseigné, ex. S01E01-E02)
    couvre toute la plage ``episode_number..episode_end`` : sans cela les
    épisodes suivants seraient signalés comme manquants à tort.

    Args:
        models: épisodes de la série (extras déjà exclus).

    Returns:
        Ensemble des clés (saison, épisode) couvertes par un fichier.
    """
    owned: set[tuple[int, int]] = set()
    for episode in models:
        if not episode.file_path:
            continue
        last = episode.episode_end or episode.episode_number
        for number in range(
            episode.episode_number, max(last, episode.episode_number) + 1
        ):
            owned.add((episode.season_number, number))
    return owned


def _result_to_json(result: CompletenessResult) -> str:
    """Sérialise le détail des manques pour la colonne DB."""
    return json.dumps(
        {
            "missing_seasons": result.missing_seasons,
            "missing_episodes": [
                {
                    "season": m.season,
                    "episode": m.episode,
                    "air_date": m.air_date,
                    "title": m.title,
                }
                for m in result.missing_episodes
            ],
            "expected_aired": result.expected_aired,
            "owned": result.owned,
            "source": result.source,
        },
        ensure_ascii=False,
    )


async def check_series_model(
    session: Session,
    checker: CompletenessChecker,
    series: SeriesModel,
    today: date,
) -> str:
    """
    Vérifie une série, persiste le verdict sur le modèle, et le retourne.

    Args:
        session: session SQLModel active.
        checker: CompletenessChecker configuré avec un client TVDB.
        series: la série à vérifier (objet attaché à la session).
        today: date du jour.

    Returns:
        Le verdict : "complete", "incomplete" ou "unverifiable".
    """
    now = datetime.utcnow()

    if not series.tvdb_id:
        series.completeness_status = None
        series.completeness_checked_at = now
        series.completeness_missing_json = None
        series.has_missing_episodes = False
        series.has_missing_seasons = False
        session.add(series)
        session.commit()
        return "unverifiable"

    owned_models = session.exec(
        select(EpisodeModel).where(
            EpisodeModel.series_id == series.id,
            EpisodeModel.is_extra == False,  # noqa: E712
        )
    ).all()
    owned = _owned_keys(owned_models)

    result = await checker.compute(str(series.tvdb_id), owned, today)

    series.completeness_status = result.status
    series.completeness_checked_at = now
    series.completeness_missing_json = _result_to_json(result)
    series.has_missing_episodes = bool(result.missing_episodes)
    series.has_missing_seasons = bool(result.missing_seasons)
    session.add(series)
    session.commit()

    return result.status
