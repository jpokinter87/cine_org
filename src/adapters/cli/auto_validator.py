"""
Logique d'auto-validation pour les fichiers video.

Ce module fournit les fonctions pour auto-valider les fichiers selon
differents criteres de confiance (score, duree, etc.).

Responsabilites:
- Auto-validation par score (cas evidents)
- Auto-validation par duree (verification TMDB)
- Filtrage des fichiers necessitant une validation manuelle
"""

from typing import TYPE_CHECKING

from rich.console import Console
from rich.progress import (
    BarColumn,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    Progress,
)

from src.core.entities.video import ValidationStatus
from src.utils.helpers import parse_candidate

if TYPE_CHECKING:
    from src.adapters.api.tvdb_client import TVDBClient
    from src.core.ports.api_clients import TMDBClient
    from src.core.entities.video import PendingValidation
    from src.services.validation import ValidationService


console = Console()


class ValidationResult:
    """
    Resultat de l'auto-validation.

    Attributs:
        auto_validated: Fichiers valides automatiquement
        remaining: Fichiers necessitant une validation manuelle
    """

    def __init__(
        self,
        auto_validated: list["PendingValidation"],
        remaining: list["PendingValidation"],
    ):
        self.auto_validated = auto_validated
        self.remaining = remaining


def _get_score(candidate: dict | object) -> float:
    """
    Extrait le score d'un candidat (dict ou SearchResult).

    Args:
        candidate: Candidat (dict avec 'score' ou objet avec attribut score)

    Returns:
        Le score (0.0 par defaut si non trouve)
    """
    return (
        candidate.get("score", 0)
        if isinstance(candidate, dict)
        else getattr(candidate, "score", 0)
    )


def _filter_by_score_confidence(
    pending_list: list["PendingValidation"],
) -> tuple[list["PendingValidation"], list["PendingValidation"]]:
    """
    Filtre les fichiers selon leur score de confiance.

    Cas d'auto-validation:
    - 1 seul candidat avec score >= 95%
    - Premier >= 95% et tous les autres < 70% (haute confiance)
    - Premier >= 90% et ecart >= 12 points avec le 2eme

    Args:
        pending_list: Liste des fichiers en attente

    Returns:
        Tuple (auto_validated, remaining)
    """
    auto_validated = []
    remaining = []

    for pending in pending_list:
        if not pending.candidates:
            remaining.append(pending)
            continue

        first_score = _get_score(pending.candidates[0])

        # Cas 1: un seul candidat >= 95%
        if len(pending.candidates) == 1 and first_score >= 95:
            auto_validated.append(pending)
            continue

        # Cas 2: premier >= 95% et tous les autres < 70% (haute confiance)
        if first_score >= 95 and len(pending.candidates) > 1:
            others_low = all(_get_score(c) < 70 for c in pending.candidates[1:])
            if others_low:
                auto_validated.append(pending)
                continue

        # Cas 3: premier >= 90% et ecart >= 12 points avec le 2eme
        if first_score >= 90 and len(pending.candidates) > 1:
            second_score = _get_score(pending.candidates[1])
            if first_score - second_score >= 12:
                auto_validated.append(pending)
                continue

        remaining.append(pending)

    return auto_validated, remaining


def _is_duration_compatible(file_duration: int, tmdb_duration: int) -> bool:
    """
    Verifie si la duree TMDB est compatible (±30%) avec la duree fichier.

    Args:
        file_duration: Duree du fichier en secondes
        tmdb_duration: Duree TMDB en secondes

    Returns:
        True si compatible (ratio entre 0.7 et 1.3)
    """
    if not file_duration or not tmdb_duration:
        return False
    ratio = tmdb_duration / file_duration
    return 0.7 <= ratio <= 1.3


async def _filter_by_duration_compatibility(
    remaining: list["PendingValidation"],
    tmdb_client: "TMDBClient | None",
) -> tuple[list["PendingValidation"], list["PendingValidation"]]:
    """
    Filtre les fichiers selon la compatibilite de duree avec TMDB.

    Un seul candidat avec une duree compatible (±30%) est auto-valide.

    Args:
        remaining: Liste des fichiers restants apres filtrage par score
        tmdb_client: Client TMDB pour recuperer les durees

    Returns:
        Tuple (duration_validated, still_remaining)
    """
    if not remaining or not tmdb_client:
        return [], remaining

    duration_validated = []
    still_remaining = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("[dim]{task.fields[status]}[/dim]"),
        console=console,
    ) as progress:
        task = progress.add_task(
            "Verification durees TMDB...",
            total=len(remaining),
            status=""
        )

        for pending in remaining:
            filename = pending.video_file.filename[:40] if pending.video_file else "?"
            progress.update(task, advance=1, status=filename)

            # Verifier qu'on a la duree du fichier
            file_duration = None
            if pending.video_file and pending.video_file.media_info:
                file_duration = pending.video_file.media_info.duration_seconds

            if not file_duration or len(pending.candidates) < 2:
                still_remaining.append(pending)
                continue

            # Recuperer la duree TMDB des 3 premiers candidats
            compatible_candidates = []
            for candidate in pending.candidates[:3]:
                candidate_id = (
                    candidate.get("id")
                    if isinstance(candidate, dict)
                    else candidate.id
                )
                candidate_source = (
                    candidate.get("source", "")
                    if isinstance(candidate, dict)
                    else getattr(candidate, "source", "")
                )

                # Ne traiter que les candidats TMDB (pas TVDB pour les series)
                if candidate_source != "tmdb":
                    continue

                try:
                    details = await tmdb_client.get_details(str(candidate_id))
                    if details and details.duration_seconds:
                        if _is_duration_compatible(
                            file_duration, details.duration_seconds
                        ):
                            compatible_candidates.append((candidate, details))
                except Exception:
                    pass

            # Si UN SEUL candidat a une duree compatible, auto-valider
            if len(compatible_candidates) == 1:
                candidate, details = compatible_candidates[0]
                pending._duration_validated_candidate = candidate
                duration_validated.append(pending)
            else:
                still_remaining.append(pending)

    return duration_validated, still_remaining


async def _filter_by_episode_count_compatibility(
    remaining: list["PendingValidation"],
    tvdb_client: "TVDBClient | None",
) -> tuple[list["PendingValidation"], list["PendingValidation"]]:
    """
    Filtre les fichiers series selon la compatibilite du nombre d'episodes.

    Pour chaque fichier, verifie si le numero d'episode existe dans la saison
    pour chaque candidat TVDB. Si un seul candidat est compatible et a un
    score >= 60%, le fichier est auto-valide.

    Args:
        remaining: Liste des fichiers restants apres filtrage par score/duree
        tvdb_client: Client TVDB pour verifier les episodes

    Returns:
        Tuple (episode_validated, still_remaining)
    """
    if not remaining or not tvdb_client:
        return [], remaining

    from src.adapters.cli.helpers import _extract_series_info

    episode_validated = []
    still_remaining = []

    for pending in remaining:
        filename = pending.video_file.filename if pending.video_file else ""
        if not filename:
            still_remaining.append(pending)
            continue

        # Extraire saison/episode du nom de fichier
        season, episode = _extract_series_info(filename)
        # _extract_series_info retourne (1, 1) par defaut, ignorer ce cas
        if season == 1 and episode == 1 and "s01e01" not in filename.lower():
            still_remaining.append(pending)
            continue

        # Verifier chaque candidat TVDB
        compatible_candidates = []
        for candidate in pending.candidates:
            candidate_source = (
                candidate.get("source", "")
                if isinstance(candidate, dict)
                else getattr(candidate, "source", "")
            )
            if candidate_source != "tvdb":
                continue

            candidate_id = (
                candidate.get("id")
                if isinstance(candidate, dict)
                else candidate.id
            )

            try:
                count = await tvdb_client.get_season_episode_count(
                    str(candidate_id), season
                )
                if count is not None and episode <= count:
                    compatible_candidates.append(candidate)
            except Exception:
                # En cas d'erreur, ne pas compter comme compatible
                pass

        # Auto-valider si un seul candidat TVDB compatible avec score >= 60%
        if len(compatible_candidates) == 1:
            score = _get_score(compatible_candidates[0])
            if score >= 60:
                pending._episode_validated_candidate = compatible_candidates[0]
                episode_validated.append(pending)
                continue

        still_remaining.append(pending)

    return episode_validated, still_remaining


async def auto_validate_files(
    pending_list: list["PendingValidation"],
    service: "ValidationService",
    tmdb_client: "TMDBClient | None" = None,
    tvdb_client: "TVDBClient | None" = None,
) -> ValidationResult:
    """
    Auto-valide les fichiers selon differents criteres de confiance.

    Critères d'auto-validation:
    1. Score >= 95% avec 1 seul candidat
    2. Score >= 95% et autres < 70%
    3. Score >= 90% et ecart >= 12 points
    4. Un seul candidat avec duree compatible (±30%)
    5. Un seul candidat TVDB avec episode compatible et score >= 60%

    Args:
        pending_list: Liste des fichiers en attente de validation
        service: ValidationService pour effectuer les validations
        tmdb_client: Client TMDB optionnel pour verification des durees
        tvdb_client: Client TVDB optionnel pour verification des episodes

    Returns:
        ValidationResult avec les fichiers auto-valides et restants
    """
    # Filtrer les non-auto-valides (status PENDING)
    pending_list = [
        p
        for p in pending_list
        if p.validation_status == ValidationStatus.PENDING and not p.auto_validated
    ]

    if not pending_list:
        return ValidationResult(auto_validated=[], remaining=[])

    console.print(f"[bold]{len(pending_list)}[/bold] fichier(s) a valider.\n")

    # Etape 1: Filtrage par score de confiance
    auto_validated, remaining = _filter_by_score_confidence(pending_list)

    # Etape 2: Filtrage par compatibilite de duree (TMDB)
    if remaining and tmdb_client:
        duration_validated, still_remaining = await _filter_by_duration_compatibility(
            remaining, tmdb_client
        )

        if duration_validated:
            console.print(
                f"[bold cyan]Auto-validation (duree)[/bold cyan]: "
                f"{len(duration_validated)} fichier(s) "
                f"(1 seul candidat avec duree compatible)\n"
            )
            for pending in duration_validated:
                candidate = pending._duration_validated_candidate
                filename = (
                    pending.video_file.filename if pending.video_file else "?"
                )

                search_result = parse_candidate(candidate)

                details = await service.validate_candidate(pending, search_result)
                console.print(
                    f"[green]{filename}[/green] -> {details.title} (duree compatible)"
                )

        auto_validated.extend(duration_validated)
        remaining = still_remaining

    # Etape 3: Filtrage par compatibilite nombre d'episodes (TVDB)
    if remaining and tvdb_client:
        episode_validated, still_remaining = await _filter_by_episode_count_compatibility(
            remaining, tvdb_client
        )

        if episode_validated:
            console.print(
                f"[bold cyan]Auto-validation (episodes)[/bold cyan]: "
                f"{len(episode_validated)} fichier(s) "
                f"(1 seul candidat avec episode compatible)\n"
            )
            for pending in episode_validated:
                candidate = pending._episode_validated_candidate
                filename = (
                    pending.video_file.filename if pending.video_file else "?"
                )

                search_result = parse_candidate(candidate)

                details = await service.validate_candidate(pending, search_result)
                console.print(
                    f"[green]{filename}[/green] -> {details.title} (episode compatible)"
                )

        auto_validated.extend(episode_validated)
        remaining = still_remaining

    # Valider automatiquement les cas evidents par score
    if auto_validated:
        console.print(
            f"[bold cyan]Auto-validation[/bold cyan]: "
            f"{len(auto_validated)} fichier(s) (haute confiance)\n"
        )
        for pending in auto_validated:
            candidate = pending.candidates[0]
            filename = pending.video_file.filename if pending.video_file else "?"

            search_result = parse_candidate(candidate)

            details = await service.validate_candidate(pending, search_result)
            console.print(
                f"[green]{filename}[/green] -> {details.title} "
                f"({_get_score(candidate):.0f}%)"
            )

        console.print()

    return ValidationResult(auto_validated=auto_validated, remaining=remaining)
