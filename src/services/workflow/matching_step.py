"""
Etape de matching du workflow : recherche API, scoring et filtrage des candidats.
"""

from typing import Optional

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from src.core.entities.video import ValidationStatus
from src.core.value_objects.parsed_info import MediaType

from .dataclasses import WorkflowState
from .pending_factory import create_pending_validation


class MatchingStepMixin:
    """Mixin pour l'etape de matching et validation."""

    async def _perform_matching(self, state: WorkflowState) -> None:
        """
        Effectue le matching avec les APIs (TMDB/TVDB).

        Crée les enregistrements VideoFile et PendingValidation.
        """
        self._console.print("\n[bold cyan]Étape 2/4: Matching avec les APIs[/bold cyan]\n")

        pending_repo = self._container.pending_validation_repository()
        video_file_repo = self._container.video_file_repository()

        # Pre-calculer le max episode par (titre, saison) pour discriminer
        # les series avec des noms similaires (ex: Star-Crossed vs Crossed)
        max_ep_map: dict[tuple[str, int], int] = {}
        for result in state.scan_results:
            if result.detected_type == MediaType.SERIES:
                pi = result.parsed_info
                if pi.title and pi.season and pi.episode:
                    key = (pi.title.lower(), pi.season)
                    max_ep_map[key] = max(max_ep_map.get(key, 0), pi.episode)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=self._console,
        ) as progress:
            match_task = progress.add_task(
                "[green]Matching...", total=len(state.scan_results)
            )

            for result in state.scan_results:
                progress.update(
                    match_task, description=f"[green]{result.video_file.filename}"
                )

                # Determiner le max_episode_in_batch pour cette serie/saison
                max_ep = None
                if result.detected_type == MediaType.SERIES:
                    pi = result.parsed_info
                    if pi.title and pi.season:
                        max_ep = max_ep_map.get((pi.title.lower(), pi.season))

                # Créer VideoFile et PendingValidation
                video_file, pending = await self._create_pending_validation(
                    result, max_ep
                )

                saved_vf = video_file_repo.save(video_file)
                if saved_vf.id:
                    state.created_video_file_ids.append(saved_vf.id)

                pending.video_file = saved_vf
                pending_repo.save(pending)

                progress.advance(match_task)

        self._console.print(
            f"[bold]{len(state.scan_results)}[/bold] fichier(s) en attente de validation"
        )

    async def _create_pending_validation(
        self, scan_result, max_episode_in_batch: Optional[int] = None
    ) -> tuple:
        """
        Crée un VideoFile et PendingValidation à partir d'un résultat de scan.

        Délègue au module partagé pending_factory.
        """
        return await create_pending_validation(
            scan_result,
            self._matcher,
            self._tmdb_client,
            self._tvdb_client,
            max_episode_in_batch,
        )

    async def _auto_validate(self, state: WorkflowState) -> None:
        """
        Effectue l'auto-validation des fichiers.

        Utilise le ValidationService pour valider automatiquement
        les fichiers avec score >= 85% et candidat unique.
        """
        self._console.print("\n[bold cyan]Étape 3/4: Auto-validation[/bold cyan]\n")

        pending_list = self._validation_service.list_pending()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=self._console,
        ) as progress:
            auto_task = progress.add_task(
                "[magenta]Auto-validation...", total=len(pending_list)
            )

            for pend in pending_list:
                result = await self._validation_service.process_auto_validation(pend)
                if result.auto_validated:
                    state.auto_validated_count += 1
                progress.advance(auto_task)

        self._console.print(f"[bold]{state.auto_validated_count}[/bold] fichier(s) auto-validé(s)")

    async def _manual_validate(self, state: WorkflowState) -> None:
        """
        Effectue la validation manuelle interactive.

        Utilise validation_loop depuis src.adapters.cli.validation.
        """
        from src.adapters.cli.validation import validation_loop

        remaining = [
            p for p in self._validation_service.list_pending()
            if p.validation_status == ValidationStatus.PENDING and not p.auto_validated
        ]

        if not remaining:
            return

        self._console.print(
            f"\n[bold cyan]Étape 4/4: Validation manuelle[/bold cyan] "
            f"({len(remaining)} fichier(s))\n"
        )

        processed_ids: set[str] = set()

        for pend in remaining:
            if pend.id and pend.id in processed_ids:
                continue

            result = await validation_loop(pend, self._validation_service)

            if result == "quit":
                self._console.print("[yellow]Validation interrompue.[/yellow]")
                break
            elif result == "trash":
                self._validation_service.reject_pending(pend)
                filename = pend.video_file.filename if pend.video_file else "?"
                self._console.print(f"[red]Corbeille:[/red] {filename}")
            elif result is None:
                filename = pend.video_file.filename if pend.video_file else "?"
                self._console.print(f"[yellow]Passé:[/yellow] {filename}")
            else:
                candidate = result
                await self._validation_service.validate_candidate(pend, candidate)
                state.manual_validated_count += 1
                filename = pend.video_file.filename if pend.video_file else "?"
                self._console.print(f"[green]Validé:[/green] {filename}")

                # Auto-validation des autres épisodes de la même série
                if candidate.source == "tvdb":
                    await self._auto_validate_series_episodes(
                        pend, candidate, remaining, processed_ids, state
                    )

        self._console.print(
            f"\n[bold]{state.manual_validated_count}[/bold] fichier(s) validé(s) manuellement"
        )

    async def _auto_validate_series_episodes(
        self, pend, candidate, remaining: list, processed_ids: set, state: WorkflowState
    ) -> None:
        """Auto-valide les autres épisodes de la même série.

        Vérifie que chaque fichier a le même candidat TVDB (même ID)
        dans sa liste de candidats avant de l'auto-valider.
        """
        from src.utils.helpers import parse_candidates

        candidate_id = candidate.id

        auto_validated_episodes = 0

        for other in remaining:
            if other.id == pend.id or (other.id and other.id in processed_ids):
                continue

            # Vérifier que le candidat sélectionné est dans les candidats de l'autre fichier
            other_candidates = parse_candidates(other.candidates)
            matching = [c for c in other_candidates if c.id == candidate_id]
            if matching:
                await self._validation_service.validate_candidate(other, matching[0])
                processed_ids.add(other.id)
                state.manual_validated_count += 1
                auto_validated_episodes += 1
                other_filename = other.video_file.filename if other.video_file else "?"
                self._console.print(f"[green]  ↳ Auto-validé:[/green] {other_filename}")

        if auto_validated_episodes > 0:
            self._console.print(
                f"[cyan]{auto_validated_episodes} autre(s) episode(s) "
                f"auto-validé(s) pour cette série[/cyan]"
            )
