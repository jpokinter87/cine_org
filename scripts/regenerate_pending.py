#!/usr/bin/env python3
"""
Script pour régénérer les PendingValidation pour les fichiers existants.

Utilise la nouvelle logique de recherche (sans filtre strict d'année).
"""

import asyncio
import sys
from pathlib import Path

# Ajouter le répertoire racine au path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from sqlmodel import Session, select, create_engine
from guessit import guessit

from src.infrastructure.persistence.models import VideoFileModel, PendingValidationModel
from src.infrastructure.persistence.repositories.video_file_repository import SQLModelVideoFileRepository
from src.infrastructure.persistence.repositories.pending_validation_repository import SQLModelPendingValidationRepository
from src.core.entities.video import PendingValidation, VideoFile, ValidationStatus
from src.services.matcher import MatcherService
from src.container import Container

console = Console()

# Patterns pour détecter les séries
SERIES_PATTERNS = ["S\\d{2}E\\d{2}", "S\\d{2}", "Episode", "Saison"]
import re
SERIES_RE = [re.compile(p, re.IGNORECASE) for p in SERIES_PATTERNS]


def is_series(filename: str) -> bool:
    """Détermine si un fichier est une série basé sur son nom."""
    for pattern in SERIES_RE:
        if pattern.search(filename):
            return True
    return False


async def regenerate_pending():
    """Régénère les PendingValidation pour les fichiers sans validation."""

    container = Container()
    config = container.config()
    container.database.init()

    engine = create_engine(config.database_url)

    # Clients API via container
    tmdb_client = container.tmdb_client()
    tvdb_client = container.tvdb_client()
    matcher = MatcherService()

    with Session(engine) as session:
        video_file_repo = SQLModelVideoFileRepository(session)
        pending_repo = SQLModelPendingValidationRepository(session)

        # Trouver les VideoFiles sans PendingValidation
        all_vf = session.exec(select(VideoFileModel)).all()
        all_pv = session.exec(select(PendingValidationModel)).all()
        validated_vf_ids = {p.video_file_id for p in all_pv}

        missing = [vf for vf in all_vf if vf.id not in validated_vf_ids]

        console.print(f"[bold]{len(missing)}[/bold] fichiers à traiter")

        if not missing:
            console.print("[green]Tous les fichiers ont une validation.[/green]")
            return

        created = 0
        errors = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Régénération...", total=len(missing))

            for vf_model in missing:
                try:
                    filename = vf_model.filename or ""
                    progress.update(task, description=f"[cyan]{filename[:50]}...")

                    # Parser le nom de fichier
                    parsed = guessit(filename)
                    title = parsed.get("title", "")
                    year = parsed.get("year")

                    if not title:
                        progress.advance(task)
                        continue

                    # Déterminer si c'est une série
                    is_series_file = is_series(filename)

                    # Rechercher les candidats
                    if is_series_file:
                        if tvdb_client and config.tvdb_enabled:
                            results = await tvdb_client.search(title, year=year)
                        else:
                            results = []
                    else:
                        if tmdb_client and config.tmdb_enabled:
                            results = await tmdb_client.search(title, year=year)
                        else:
                            results = []

                    # Scorer les résultats
                    # Récupérer la durée si disponible
                    duration = vf_model.duration_seconds

                    candidates = matcher.score_results(
                        results,
                        query_title=title,
                        query_year=year,
                        query_duration=duration,
                        is_series=is_series_file,
                    )

                    # Convertir VideoFileModel en VideoFile entity
                    vf_entity = video_file_repo._to_entity(vf_model)

                    # Créer le PendingValidation
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
                        video_file=vf_entity,
                        candidates=candidates_data,
                        validation_status=ValidationStatus.PENDING,
                    )
                    pending_repo.save(pending)
                    created += 1

                except Exception as e:
                    errors += 1
                    console.print(f"[red]Erreur pour {vf_model.filename}: {e}[/red]")

                progress.advance(task)

        console.print(f"\n[bold green]{created}[/bold green] PendingValidation créés")
        if errors:
            console.print(f"[yellow]{errors} erreurs[/yellow]")


if __name__ == "__main__":
    asyncio.run(regenerate_pending())
