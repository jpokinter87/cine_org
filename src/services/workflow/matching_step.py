"""
Etape de matching du workflow : recherche API, scoring et filtrage des candidats.
"""

from typing import Optional

from loguru import logger
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from src.core.entities.video import PendingValidation, ValidationStatus
from src.core.value_objects.parsed_info import MediaType

from .dataclasses import WorkflowState


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

        Effectue la recherche API et le scoring.
        """
        from src.core.entities.video import VideoFile

        # Créer VideoFile
        video_file = VideoFile(
            path=scan_result.video_file.path,
            filename=scan_result.video_file.filename,
            media_info=scan_result.media_info,
        )

        # Rechercher les candidats via API
        title = scan_result.parsed_info.title
        year = scan_result.parsed_info.year
        candidates = []

        if scan_result.detected_type == MediaType.MOVIE:
            candidates = await self._search_and_score_movie(
                title, year, scan_result.media_info
            )
        else:
            candidates = await self._search_and_score_series(title, year)

            # Filtrer les candidats incompatibles par nombre d'episodes
            season = scan_result.parsed_info.season
            episode = scan_result.parsed_info.episode
            if candidates and season and episode:
                filtered = await self._filter_by_episode_count(
                    candidates, season, episode, max_episode_in_batch
                )
                if filtered:
                    candidates = filtered
                else:
                    logger.warning(
                        f"Tous les candidats elimines par episode count pour "
                        f"{scan_result.video_file.filename}, conservation des originaux"
                    )

        # Convertir en dict pour stockage
        candidates_data = [
            {
                "id": c.id,
                "title": c.title,
                "year": c.year,
                "score": c.score,
                "source": c.source,
            }
            for c in candidates
        ]

        pending = PendingValidation(
            video_file=video_file,
            candidates=candidates_data,
        )

        return video_file, pending

    async def _filter_by_episode_count(
        self,
        candidates: list,
        season: int,
        episode: int,
        max_episode_in_batch: Optional[int] = None,
    ) -> list:
        """
        Filtre les candidats series incompatibles par nombre d'episodes.

        Phase 1 - Elimination des impossibles :
        - La saison n'existe pas (get_season_episode_count retourne None)
        - Le numero d'episode depasse le nombre d'episodes de la saison

        Phase 2 - Raffinement par contexte batch :
        Si max_episode_in_batch est fourni et que plusieurs candidats restent,
        prefere ceux dont le nombre d'episodes de la saison correspond exactement
        au max_episode du batch.

        En cas d'erreur API, le candidat est conserve par precaution.

        Args:
            candidates: Liste de SearchResult candidats
            season: Numero de saison du fichier
            episode: Numero d'episode du fichier
            max_episode_in_batch: Numero d'episode max dans le batch pour cette serie/saison

        Returns:
            Liste filtree de SearchResult compatibles
        """
        if not self._tvdb_client:
            return candidates

        # Elimination des candidats dont la saison n'a pas assez d'episodes
        compatible = []
        for candidate in candidates:
            try:
                count = await self._tvdb_client.get_season_episode_count(
                    candidate.id, season
                )
                if count is not None and episode <= count:
                    compatible.append(candidate)
                elif count is None:
                    # Pas de données pour cette saison → garder par précaution
                    compatible.append(candidate)
            except Exception:
                # En cas d'erreur API, conserver le candidat par precaution
                compatible.append(candidate)

        return compatible

    async def _search_and_score_movie(
        self, title: str, year: Optional[int], media_info
    ) -> list:
        """Recherche et score les films via TMDB."""
        candidates = []

        if not self._tmdb_client or not getattr(self._tmdb_client, "_api_key", None):
            return candidates

        try:
            api_results = await self._tmdb_client.search(title, year=year)
            duration = None
            if media_info and media_info.duration_seconds:
                duration = media_info.duration_seconds

            # Premier scoring sans durée API
            candidates = self._matcher.score_results(
                api_results, title, year, duration
            )

            # Enrichir les top 3 avec durée et re-scorer
            if candidates and duration:
                top_candidates = candidates[:3]
                enriched_candidates = []

                for cand in top_candidates:
                    try:
                        details = await self._tmdb_client.get_details(cand.id)
                        if details and details.duration_seconds:
                            from src.services.matcher import calculate_movie_score
                            from dataclasses import replace

                            new_score = calculate_movie_score(
                                query_title=title,
                                query_year=year,
                                query_duration=duration,
                                candidate_title=cand.title,
                                candidate_year=cand.year,
                                candidate_duration=details.duration_seconds,
                                candidate_original_title=(
                                    cand.original_title or details.original_title
                                ),
                            )
                            cand = replace(cand, score=new_score)
                    except Exception:
                        pass
                    enriched_candidates.append(cand)

                candidates = enriched_candidates + candidates[3:]
                candidates.sort(key=lambda c: c.score, reverse=True)

        except Exception as e:
            self._console.print(f"[yellow]Erreur TMDB pour {title}: {e}[/yellow]")

        return candidates

    async def _search_and_score_series(
        self, title: str, year: Optional[int]
    ) -> list:
        """Recherche et score les séries via TVDB."""
        candidates = []

        if not self._tvdb_client or not getattr(self._tvdb_client, "_api_key", None):
            return candidates

        try:
            api_results = await self._tvdb_client.search(title, year=year)
            candidates = self._matcher.score_results(
                api_results, title, year, None, is_series=True
            )
        except Exception as e:
            self._console.print(f"[yellow]Erreur TVDB pour {title}: {e}[/yellow]")

        return candidates

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
