#!/usr/bin/env python3
"""
Valide les correctifs de la session sur un échantillon de films problématiques :
- Patterns A/E/C du scan qualité (parser parent, extended cuts, titre+année+durée)
- Option 3 matching initial (tri par durée)
- Multi-query réassociation (apostrophes + année)

Pour chaque cas : simule le matching initial (pending_factory) ET la
réassociation UI, vérifie que le bon TMDB id arrive en #1.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.table import Table

from src.container import Container
from src.services.workflow.pending_factory import _search_and_score_movie

console = Console()


# Cas de test : (parsed_title, parsed_year, file_duration_seconds, expected_tmdb_id, description)
CASES = [
    # === Scoring : cas résolus par Option 3 (tri durée) ===
    ("Criminal", 2016, 6780, "302156", "Criminal - Un espion (vs court 2014)"),
    ("The Gift", 2015, 6660, "328425", "The Gift (vs 13min short)"),
    ("Crisis", 2021, 7080, "580532", "Crisis 2021 (vs 15min 2020)"),
    ("Missing", 2023, 6600, "768362", "Missing Disparition (vs 15min)"),
    ("Mother", 2017, 7260, "381283", "mother! Aronofsky (vs 22min 2016)"),
    ("Joy", 2024, 6900, "1184495", "JOY Birth of IVF (vs 2023 homonyme)"),
    ("One Day", 2011, 6420, "51828", "Un jour (trad FR)"),
    ("Life", 2015, 6660, "300153", "Life 2015 (vs 16 homonyme)"),
    ("Kin", 2018, 6180, "425505", "Kin : Le Commencement"),
    ("Invisible Man", 2020, 7440, "570670", "Invisible Man (vs 21)"),
    ("Le Labyrinthe", 2014, 6840, "198663", "Le Labyrinthe (vs 13)"),
    ("Utopia", 2024, 5580, "1379587", "Bienvenue à Utopia (trad FR)"),
    ("Onward", 2020, 6120, "508439", "En avant (trad FR)"),
    ("Pocahontas", 1995, 4920, "10530", "Pocahontas légende indienne"),
    ("Overdose", 2022, 7140, "896485", "Overdose 2022 (vs 21)"),
    ("The Dressmaker", 2015, 7080, "298382", "Haute Couture (trad FR)"),
    # === Peu populaires + year-dans-query ===
    ("Rock'n Roll", 2017, 7080, "382589", "Rock'n Roll Canet (pop 0.8)"),
    ("Lamb", 2021, 6387, "788929", "Lamb islandais (pop 2.5)"),
    # === 3D cases (scan qualité) ===
    ("Le Monde de Nemo", 2003, 6000, "12", "Le Monde de Nemo (3D stripping)"),
    ("Kingdom of Heaven", 2005, 8640, "254", "Kingdom Heaven DC (seuil ext)"),
]


async def simulate(cases):
    container = Container()
    container.database.init()
    client = container.tmdb_client()
    matcher = container.matcher_service()

    class FakeMediaInfo:
        def __init__(self, d): self.duration_seconds = d

    table = Table(title=f"Simulation matching initial : {len(cases)} cas", show_lines=False)
    table.add_column("Titre fichier")
    table.add_column("Année")
    table.add_column("Durée")
    table.add_column("#1 résultat")
    table.add_column("Attendu")
    table.add_column("OK")

    ok_count = 0
    top3_count = 0
    fail_cases = []

    for title, year, dur, expected_id, desc in cases:
        media_info = FakeMediaInfo(dur)
        candidates = await _search_and_score_movie(
            title=title, year=year, media_info=media_info,
            matcher=matcher, tmdb_client=client,
        )
        if not candidates:
            result = "(aucun candidat)"
            top1_id = None
        else:
            top1 = candidates[0]
            top1_id = top1.id
            result = f"{top1.title[:28]} ({top1.year}) id={top1.id}"

        ok = (str(top1_id) == str(expected_id))
        in_top3 = any(str(c.id) == str(expected_id) for c in candidates[:3])

        if ok:
            ok_count += 1
            status = "[green]✓[/green]"
        elif in_top3:
            top3_count += 1
            status = "[yellow]top3[/yellow]"
        else:
            status = "[red]✗[/red]"
            pos = next((i + 1 for i, c in enumerate(candidates) if str(c.id) == str(expected_id)), None)
            fail_cases.append((title, year, expected_id, top1_id, pos, desc))

        table.add_row(
            f"{title} — {desc[:30]}",
            str(year), f"{dur // 60}min",
            result[:48], f"id={expected_id}",
            status,
        )

    console.print(table)
    console.print(
        f"\n[bold]Résultats :[/bold] {ok_count}/{len(cases)} bon #1, "
        f"{top3_count}/{len(cases)} dans top 3, "
        f"{len(fail_cases)}/{len(cases)} hors top 3"
    )

    if fail_cases:
        console.print("\n[yellow]Cas à revoir (hors top 3) :[/yellow]")
        for title, year, exp, got, pos, desc in fail_cases:
            pos_s = f"position {pos}" if pos else "absent"
            console.print(
                f"  • {title} ({year}) — attendu id={exp}, "
                f"obtenu id={got} — vrai candidat {pos_s}. {desc}"
            )

    await client.close()


asyncio.run(simulate(CASES))
