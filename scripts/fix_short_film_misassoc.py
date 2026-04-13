#!/usr/bin/env python3
"""
Corrige les films mal associés à des courts-métrages.

Cible : entrées du cache scan qualité (~/.cineorg/quality_scan_cache.json) où
la durée TMDB < 60min mais la durée fichier > 60min (typiquement, titre exact
court-métrage a battu le vrai film au titre localisé long).

Pour chaque cas :
  - Parse titre+année depuis le nom du fichier réel (file_path)
  - Recherche TMDB sur ce titre+année
  - Fetch details pour les top 10 candidats (durée incluse)
  - Score avec calculate_movie_score (50/25/25 titre/année/durée)
  - Propose le meilleur candidat si score ≥ 80 ET durée dans ±15% du fichier

Modes :
  --dry-run (défaut) : affiche seulement les propositions
  --apply            : applique les réassociations en DB
"""

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from guessit import guessit
from rich.console import Console
from rich.table import Table
from sqlmodel import Session, select

from src.container import Container
from src.infrastructure.persistence.database import init_db, get_session
from src.infrastructure.persistence.models import (
    ConfirmedAssociationModel,
    MovieModel,
)
from src.services.matcher import calculate_movie_score

CACHE_FILE = Path.home() / ".cineorg" / "quality_scan_cache.json"
DURATION_REGEX = re.compile(r"(\d+)min \(fichier\) vs (\d+)min \(TMDB\)")

console = Console()


def load_short_film_cases() -> list[dict]:
    """Charge les cas où TMDB<60min mais fichier>60min."""
    data = json.loads(CACHE_FILE.read_text())
    cases = []
    for r in data["results"]:
        if r["entity_type"] != "movie":
            continue
        for reason in r["reasons"]:
            m = DURATION_REGEX.search(reason)
            if m:
                f_min, t_min = int(m.group(1)), int(m.group(2))
                if t_min < 60 and f_min > 60:
                    cases.append({
                        "movie_id": r["entity_id"],
                        "tmdb_title_wrong": r["title_tmdb"],
                        "year_tmdb_wrong": r["year_tmdb"],
                        "file_duration_seconds": f_min * 60,
                    })
                    break
    return cases


def parse_filename(file_path: str) -> tuple[str | None, int | None]:
    """Extrait titre+année depuis le nom du fichier via guessit."""
    try:
        parsed = guessit(Path(file_path).name)
        title = parsed.get("title")
        year = parsed.get("year")
        if isinstance(year, list):
            year = year[0] if year else None
        return title, year
    except Exception:
        return None, None


async def find_best_candidate(
    tmdb_client,
    query_title: str,
    query_year: int | None,
    file_duration: int,
    top_n: int = 10,
) -> tuple[dict | None, float, str]:
    """Recherche TMDB et retourne (best_candidate_dict, score, raison)."""
    results = await tmdb_client.search(query_title, year=query_year)
    if not results:
        return None, 0.0, "Aucun résultat TMDB"

    scored = []
    for cand in results[:top_n]:
        try:
            details = await tmdb_client.get_details(cand.id)
            if not details or not details.duration_seconds:
                continue
            score = calculate_movie_score(
                query_title=query_title,
                query_year=query_year,
                query_duration=file_duration,
                candidate_title=cand.title,
                candidate_year=cand.year,
                candidate_duration=details.duration_seconds,
                candidate_original_title=(
                    cand.original_title or details.original_title
                ),
            )
            duration_diff_pct = abs(details.duration_seconds - file_duration) / file_duration * 100
            scored.append({
                "tmdb_id": cand.id,
                "title": cand.title,
                "year": cand.year,
                "duration_seconds": details.duration_seconds,
                "duration_diff_pct": duration_diff_pct,
                "score": score,
                "details": details,
            })
        except Exception as e:
            console.print(f"[dim]  Erreur get_details({cand.id}): {e}[/dim]")

    if not scored:
        return None, 0.0, "Aucun candidat avec détails exploitables"

    scored.sort(key=lambda c: c["score"], reverse=True)
    best = scored[0]

    if best["score"] < 80:
        return best, best["score"], f"Score trop bas ({best['score']:.1f} < 80)"
    if best["duration_diff_pct"] > 15:
        return best, best["score"], f"Écart de durée trop grand ({best['duration_diff_pct']:.0f}% > 15%)"

    return best, best["score"], "OK"


async def apply_reassociation(
    session: Session,
    tmdb_client,
    movie: MovieModel,
    best: dict,
) -> None:
    """Applique la réassociation (mirror de movie_reassociate_apply)."""
    details = best["details"]
    ext_ids = await tmdb_client.get_external_ids(str(best["tmdb_id"]))
    imdb_id = ext_ids.get("imdb_id") if ext_ids else None

    movie.tmdb_id = int(best["tmdb_id"])
    movie.imdb_id = imdb_id
    movie.title = details.title
    movie.original_title = details.original_title
    movie.year = details.year
    movie.genres_json = json.dumps(list(details.genres)) if details.genres else None
    movie.duration_seconds = details.duration_seconds
    movie.overview = details.overview
    movie.poster_path = details.poster_url
    movie.director = details.director
    movie.cast_json = json.dumps(list(details.cast)) if details.cast else None
    movie.vote_average = details.vote_average
    movie.vote_count = details.vote_count
    movie.collection_id = (
        details.collection_id if details.collection_id is not None else 0
    )
    movie.collection_name = details.collection_name
    movie.updated_at = datetime.utcnow()

    existing = session.exec(
        select(ConfirmedAssociationModel).where(
            ConfirmedAssociationModel.entity_type == "movie",
            ConfirmedAssociationModel.entity_id == movie.id,
        )
    ).first()
    if not existing:
        session.add(ConfirmedAssociationModel(entity_type="movie", entity_id=movie.id))
    session.add(movie)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Applique les changements")
    args = parser.parse_args()

    container = Container()
    container.database.init()
    container.wire(modules=[__name__])
    tmdb_client = container.tmdb_client()

    cases = load_short_film_cases()
    console.print(f"\n[bold]{len(cases)} cas détectés (TMDB<60min / fichier>60min)[/bold]\n")

    session = next(get_session())

    proposed = []
    skipped = []
    try:
        for case in cases:
            movie = session.get(MovieModel, case["movie_id"])
            if not movie or not movie.file_path:
                skipped.append((case["movie_id"], "movie introuvable / file_path manquant"))
                continue

            filename = Path(movie.file_path).name
            q_title, q_year = parse_filename(movie.file_path)
            if not q_title:
                skipped.append((case["movie_id"], f"parse échoué : {filename}"))
                continue

            best, score, status = await find_best_candidate(
                tmdb_client,
                q_title,
                q_year,
                case["file_duration_seconds"],
            )
            entry = {
                "movie_id": case["movie_id"],
                "filename": filename,
                "q_title": q_title,
                "q_year": q_year,
                "file_min": case["file_duration_seconds"] // 60,
                "current_tmdb_id": movie.tmdb_id,
                "current_title": case["tmdb_title_wrong"],
                "current_year": case["year_tmdb_wrong"],
                "best": best,
                "score": score,
                "status": status,
            }
            if status == "OK":
                proposed.append(entry)
            else:
                skipped.append((case["movie_id"], f"{filename[:50]} — {status}"))

        table = Table(title=f"Proposition : {len(proposed)} réassociations", show_lines=True)
        table.add_column("ID", style="cyan")
        table.add_column("Fichier (parse)")
        table.add_column("Actuel (faux)")
        table.add_column("Proposé")
        table.add_column("Score")

        for e in proposed:
            b = e["best"]
            table.add_row(
                str(e["movie_id"]),
                f"{e['q_title']} ({e['q_year']}) - {e['file_min']}min",
                f"{e['current_title']} ({e['current_year']}) [tmdb={e['current_tmdb_id']}]",
                f"{b['title']} ({b['year']}) - {b['duration_seconds']//60}min [tmdb={b['tmdb_id']}]",
                f"{e['score']:.1f}",
            )
        console.print(table)

        if skipped:
            console.print(f"\n[yellow]{len(skipped)} cas ignorés (revue manuelle nécessaire) :[/yellow]")
            for mid, reason in skipped:
                console.print(f"  [dim]id={mid}[/dim] {reason}")

        if args.apply and proposed:
            console.print(f"\n[bold red]APPLICATION de {len(proposed)} réassociations en DB...[/bold red]")
            for e in proposed:
                movie = session.get(MovieModel, e["movie_id"])
                await apply_reassociation(session, tmdb_client, movie, e["best"])
            session.commit()
            console.print("[green]✓ Appliqué. Pense à invalider le cache scan qualité.[/green]")
        elif args.apply:
            console.print("[yellow]Rien à appliquer.[/yellow]")
        else:
            console.print("\n[dim]Dry-run. Utilise --apply pour appliquer.[/dim]")
    finally:
        session.close()
        await tmdb_client.close()


if __name__ == "__main__":
    asyncio.run(main())
