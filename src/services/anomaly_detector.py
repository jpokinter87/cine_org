"""
Detection d'anomalies de decoupage de saisons a l'issue du workflow.

Regroupe les fichiers en attente qui ont un numero d'episode superieur
au nombre d'episodes canonique declare par TVDB, afin de proposer a
l'utilisateur une resolution groupee (acceptation comme decoupage
alternatif, ignorance ponctuelle, ou mise a la corbeille).

Utilise en fin de ``_run_web_workflow`` pour peupler
``WorkflowProgress.anomaly_groups`` consomme par le template
``workflow/_results.html``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Optional

from loguru import logger
from sqlmodel import Session, select

from src.core.entities.video import PendingValidation, ValidationStatus
from src.infrastructure.persistence.models import EpisodeModel, SeriesModel


TITLE_SIMILARITY_THRESHOLD = 0.7


@dataclass
class ExcessEpisodeGroup:
    """
    Groupe de pendings (tvdb_id, season) avec episodes au-dela du canon.

    Attributs:
        tvdb_id: ID TVDB du candidat top pour tous les pendings du groupe.
        series_title: Titre localise depuis le candidat TVDB.
        series_year: Annee depuis le candidat TVDB (optionnelle).
        season_number: Numero de saison concerne.
        tvdb_count: Nombre d'episodes officiels TVDB pour la saison.
        pendings: Pendings du groupe dont episode_number > tvdb_count,
            tries par episode_number croissant.
        validated_seasons_count: Nombre de saisons distinctes deja
            presentes en DB pour cette serie (signal de confiance).
    """

    tvdb_id: int
    series_title: str
    series_year: Optional[int]
    season_number: int
    tvdb_count: int
    pendings: list[PendingValidation] = field(default_factory=list)
    validated_seasons_count: int = 0

    @property
    def episode_numbers(self) -> list[int]:
        """Numeros d'episode excedentaires, par ordre croissant."""
        nums: list[int] = []
        for p in self.pendings:
            _, ep = _parse_season_episode(p)
            if ep is not None:
                nums.append(ep)
        return sorted(nums)

    @property
    def max_episode_number(self) -> int:
        """Valeur max des episode_number du groupe."""
        nums = self.episode_numbers
        return max(nums) if nums else self.tvdb_count


class AnomalyDetector:
    """
    Detecte les groupes (serie, saison) dont des episodes depassent le canon.

    Le detecteur regroupe les fichiers en attente (PENDING) par top
    candidat TVDB et numero de saison, puis ne conserve que les groupes
    contenant au moins un episode au-dela du nombre declare par TVDB.
    """

    def __init__(self, session: Session, tvdb_client, pending_repo) -> None:
        self._session = session
        self._tvdb_client = tvdb_client
        self._pending_repo = pending_repo

    async def find_excess_episode_groups(self) -> list[ExcessEpisodeGroup]:
        """
        Retourne les groupes d'anomalies detectes.

        Pipeline :
        1. Parcourir les pendings en statut PENDING.
        2. Parser chaque filename (title, year, season, episode) via guessit.
        3. Grouper par (title_lower, year, season).
        4. Pour chaque groupe, refaire une recherche TVDB sur title+year
           (independante du filtrage du pipeline de matching qui a pu
           eliminer le bon candidat parce que episode > canon).
        5. Retenir le resultat TVDB dont le titre a la similarite la plus
           elevee (seuil `TITLE_SIMILARITY_THRESHOLD`).
        6. Appeler `get_season_episode_count(tvdb_id, season)`.
        7. Filtrer : ne garder que les pendings avec episode > count.
        8. Compter les saisons validees de la serie (DB).
        """
        if self._tvdb_client is None:
            return []

        pendings_all = self._pending_repo.list_pending()
        pendings = [
            p for p in pendings_all if p.validation_status == ValidationStatus.PENDING
        ]
        if not pendings:
            return []

        from src.adapters.parsing.guessit_parser import GuessitFilenameParser
        from src.core.value_objects.parsed_info import MediaType

        parser = GuessitFilenameParser()

        # Groupe par (title parsed, year parsed, season)
        groups: dict[
            tuple[str, Optional[int], int], list[tuple[int, PendingValidation]]
        ] = {}
        for pending in pendings:
            if not pending.video_file or not pending.video_file.filename:
                continue
            filename = pending.video_file.filename
            parsed = parser.parse(filename, MediaType.SERIES)
            if (
                not parsed.title
                or parsed.season is None
                or parsed.episode is None
            ):
                continue
            # Filtre defaut guessit (1, 1) quand filename n'indique pas s01e01
            if (
                parsed.season == 1
                and parsed.episode == 1
                and "s01e01" not in filename.lower()
            ):
                continue
            key = (parsed.title.lower(), parsed.year, parsed.season)
            groups.setdefault(key, []).append((parsed.episode, pending))

        if not groups:
            return []

        search_cache: dict[tuple[str, Optional[int]], list] = {}
        result_groups: list[ExcessEpisodeGroup] = []

        for (title_lower, year, season), items in groups.items():
            cache_key = (title_lower, year)
            if cache_key not in search_cache:
                try:
                    search_cache[cache_key] = await self._tvdb_client.search(
                        title_lower, year=year
                    )
                except Exception as exc:
                    logger.debug(
                        "TVDB search echec pour %s (%s): %s",
                        title_lower,
                        year,
                        exc,
                    )
                    search_cache[cache_key] = []

            results = search_cache[cache_key] or []
            if not results:
                continue

            # Selectionner le resultat TVDB dont le titre est le plus
            # proche du titre parse. Evite les faux positifs type
            # "The Big Bake" quand on cherche "The Big C".
            best = max(
                results,
                key=lambda r: _title_similarity(
                    getattr(r, "title", ""), title_lower
                ),
            )
            best_ratio = _title_similarity(
                getattr(best, "title", ""), title_lower
            )
            if best_ratio < TITLE_SIMILARITY_THRESHOLD:
                continue

            try:
                tvdb_id = int(best.id)
            except (TypeError, ValueError):
                continue

            try:
                canonical_count = await self._tvdb_client.get_season_episode_count(
                    str(tvdb_id), season
                )
            except Exception as exc:
                logger.debug(
                    "TVDB count echec pour (%s, S%02d): %s",
                    tvdb_id,
                    season,
                    exc,
                )
                continue

            if canonical_count is None:
                continue

            excess = [pending for ep, pending in items if ep > canonical_count]
            if not excess:
                continue

            excess.sort(key=lambda p: (_parse_season_episode(p)[1] or 0))

            result_groups.append(
                ExcessEpisodeGroup(
                    tvdb_id=tvdb_id,
                    series_title=str(
                        getattr(best, "title", None) or title_lower
                    ),
                    series_year=_safe_int(getattr(best, "year", None)),
                    season_number=season,
                    tvdb_count=canonical_count,
                    pendings=excess,
                    validated_seasons_count=self._count_validated_seasons(tvdb_id),
                )
            )

        result_groups.sort(key=lambda g: (g.series_title.lower(), g.season_number))
        return result_groups

    def _count_validated_seasons(self, tvdb_id: int) -> int:
        """Nombre de saisons distinctes deja en DB pour la serie."""
        try:
            rows = self._session.exec(
                select(EpisodeModel.season_number)
                .join(SeriesModel, SeriesModel.id == EpisodeModel.series_id)
                .where(SeriesModel.tvdb_id == tvdb_id)
            ).all()
        except Exception as exc:
            logger.debug("count_validated_seasons erreur (%s): %s", tvdb_id, exc)
            return 0
        return len({s for s in rows if s is not None})


def _title_similarity(candidate_title: str, target_lower: str) -> float:
    """Ratio de similarite SequenceMatcher, insensible a la casse."""
    if not candidate_title:
        return 0.0
    return SequenceMatcher(None, candidate_title.lower(), target_lower).ratio()


def _top_tvdb_candidate(candidates: list) -> Optional[dict]:
    """Retourne le candidat TVDB au score le plus eleve (dict ou None)."""
    best: Optional[dict] = None
    best_score = -1.0
    for cand in candidates or []:
        if isinstance(cand, dict):
            source = cand.get("source", "")
            score = float(cand.get("score", 0) or 0)
            as_dict = cand
        else:
            source = getattr(cand, "source", "")
            score = float(getattr(cand, "score", 0) or 0)
            as_dict = {
                "id": getattr(cand, "id", None),
                "title": getattr(cand, "title", None),
                "year": getattr(cand, "year", None),
                "score": score,
                "source": source,
            }
        if source != "tvdb":
            continue
        if score > best_score:
            best = as_dict
            best_score = score
    return best


def _parse_season_episode(
    pending: PendingValidation,
) -> tuple[Optional[int], Optional[int]]:
    """Extrait (season, episode) du nom de fichier via guessit."""
    if not pending.video_file or not pending.video_file.filename:
        return None, None
    from src.adapters.cli.helpers import _extract_series_info

    filename = pending.video_file.filename
    season, episode = _extract_series_info(filename)
    # _extract_series_info retourne (1, 1) par defaut : filtrer quand
    # le nom ne contient explicitement pas "s01e01".
    if season == 1 and episode == 1 and "s01e01" not in filename.lower():
        return None, None
    return season, episode


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
