# Phase 7: CLI Principale - Research

**Researched:** 2026-01-28
**Domain:** CLI orchestration avec Typer/Rich pour workflow video
**Confidence:** HIGH

## Summary

Cette phase orchestre les commandes CLI principales pour le workflow de traitement video : `process` (workflow complet), `pending` (affichage en attente), et `validate` (validation specifique). L'infrastructure CLI existe deja dans le projet via Typer (src/main.py), Rich (src/adapters/cli/validation.py), et les services metier (scanner, matcher, validation, transferer).

La recherche confirme que l'approche Typer avec callbacks pour etat partage (verbose/quiet) et asyncio.run() pour les commandes async est le pattern standard. Rich fournit Progress pour les barres de progression avec ETA, et Panel/Table pour l'affichage structure. Le code existant dans `src/adapters/cli/` fournit des patterns robustes pour la pagination, les cartes candidats, et les transferts batch.

**Primary recommendation:** Etendre main.py avec les nouvelles commandes (process, pending, validate) en reutilisant les patterns existants de validation.py et commands.py, avec un callback Typer pour gerer verbose/quiet globalement.

## Standard Stack

Les bibliotheques sont deja installees et configurees dans le projet.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| typer | (installe) | Framework CLI | Deja utilise dans src/main.py, supporte Rich nativement |
| rich | 13.9.4 | Affichage terminal | Deja utilise pour Progress, Panel, Table dans validation.py |
| loguru | (installe) | Logging JSON | Deja configure dans logging_config.py avec rotation |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asyncio | stdlib | Async runtime | Commandes async avec asyncio.run() |
| dependency-injector | (installe) | DI container | Services via Container() |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| callback global | ctx.obj | ctx.obj plus idiomatique Click mais callback plus simple pour etat basique |
| rich.progress.track | Progress context | track() plus simple, mais Progress requis pour plusieurs taches |

**Installation:**
Pas de nouvelles dependances requises - tout est deja installe.

## Architecture Patterns

### Structure existante (a conserver)
```
src/
├── main.py              # CLI entry point avec @app.command()
├── adapters/cli/        # Modules CLI specifiques
│   ├── commands.py      # validate_app avec auto/manual/batch
│   └── validation.py    # Fonctions Rich (panels, progress, loop)
└── container.py         # DI avec tous les services
```

### Pattern 1: Callback Typer pour verbose/quiet global

**What:** Un callback sur l'app principale pour capturer --verbose/-v et --quiet/-q avant toute commande
**When to use:** Options globales partagees entre toutes les commandes
**Example:**
```python
# Source: https://typer.tiangolo.com/tutorial/commands/callback/
import typer

app = typer.Typer()
state = {"verbose": 0, "quiet": False}

@app.callback()
def main(
    verbose: int = typer.Option(0, "--verbose", "-v", count=True,
        help="Niveau de verbosity (-v, -vv, -vvv)"),
    quiet: bool = typer.Option(False, "--quiet", "-q",
        help="Mode silencieux (erreurs uniquement)"),
) -> None:
    """CineOrg - Gestion de videotheque personnelle."""
    if quiet:
        state["quiet"] = True
    else:
        state["verbose"] = verbose
```

### Pattern 2: Async Command Wrapper

**What:** Wrapper asyncio.run() pour commandes async
**When to use:** Commandes utilisant des services async (API clients)
**Example:**
```python
# Source: https://github.com/fastapi/typer/discussions/864
from asyncio import run as aiorun

@app.command()
def process() -> None:
    """Execute le workflow complet."""
    aiorun(_process_async())

async def _process_async() -> None:
    container = Container()
    await container.database.init()
    # ... logic async
```

### Pattern 3: Progress avec ETA et description dynamique

**What:** Rich Progress avec colonnes personnalisees et description mise a jour
**When to use:** Operations longues (scan, matching) avec retour visuel
**Example:**
```python
# Source: https://rich.readthedocs.io/en/stable/progress.html
# Pattern existant dans validation.py execute_batch_transfer
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn,
    TaskProgressColumn, TimeRemainingColumn
)

with Progress(
    SpinnerColumn(),
    TextColumn("[progress.description]{task.description}"),
    BarColumn(),
    TaskProgressColumn(),
    TimeRemainingColumn(),
    console=console,
) as progress:
    task = progress.add_task("Scan...", total=None)  # Indetermine
    for result in scanner.scan_downloads():
        progress.update(task, description=f"[cyan]{result.video_file.filename}[/cyan]")
    # Quand on connait le total:
    progress.update(task, total=count, completed=count)
```

### Pattern 4: Dry-run mode

**What:** Option --dry-run qui simule sans modifier
**When to use:** Commande process pour preview des actions
**Example:**
```python
# Source: https://srcco.de/posts/writing-python-command-line-scripts.html
@app.command()
def process(
    dry_run: bool = typer.Option(False, "--dry-run", help="Simule sans modifier les fichiers"),
) -> None:
    if dry_run:
        console.print("[yellow]Mode dry-run active - aucune modification[/yellow]")

    for file in files_to_process:
        if dry_run:
            console.print(f"[dim]DRYRUN: Deplacera {file} vers {dest}[/dim]")
        else:
            transferer.transfer_file(file, dest)
```

### Anti-Patterns to Avoid
- **Logique metier dans les commandes:** Garder les commandes comme couche mince appelant les services
- **asyncio.run() dans une boucle:** Utiliser une seule fonction async englobante
- **Console.print sans console globale:** Reutiliser la console singleton de validation.py
- **Creer Container() plusieurs fois:** Instancier une fois au debut de la commande

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Pagination affichage | Pagination custom | CandidatePaginator de validation.py | Deja teste et fonctionnel |
| Cartes candidats | Formatage manuel | render_candidate_card | Badge RECOMMANDE, couleurs score |
| Barre progression | print() avec \r | Rich Progress | ETA, spinner, descriptions |
| Validation interactive | input() + if/else | validation_loop | Gere search, skip, trash, quit |
| Transfert batch | Boucle simple | execute_batch_transfer | Progress + error handling |
| Detection serie | Regex ad-hoc | determine_is_series | Patterns TVDB + SxxExx robustes |

**Key insight:** Le module validation.py contient deja toute l'infrastructure CLI Rich. Phase 7 doit reutiliser ces fonctions, pas les reimplementer.

## Common Pitfalls

### Pitfall 1: Event loop deja actif
**What goes wrong:** `asyncio.run()` dans un contexte qui a deja un event loop (pytest-asyncio, Jupyter)
**Why it happens:** Typer ne gere pas nativement async def
**How to avoid:** Wrapper pattern `def command(): asyncio.run(_async_impl())`
**Warning signs:** RuntimeError "Cannot run event loop within a running event loop"

### Pitfall 2: Container instantiation multiple
**What goes wrong:** Services utilisant des sessions DB differentes causent des problemes de coherence
**Why it happens:** Container() cree des instances Factory a chaque appel
**How to avoid:** Instancier Container() une seule fois au debut de la commande, passer les services explicitement
**Warning signs:** "Object already attached to session" ou donnees pas persistees

### Pitfall 3: verbose/quiet position
**What goes wrong:** `cineorg process --verbose` echoue, "Unknown option --verbose"
**Why it happens:** Options du callback doivent preceder la sous-commande
**How to avoid:** Documenter l'ordre: `cineorg --verbose process`
**Warning signs:** Tests CLI echouent avec options globales

### Pitfall 4: Dry-run incomplet
**What goes wrong:** Dry-run bypass l'affichage mais certaines operations ont quand meme lieu
**Why it happens:** Logique dry-run dispersee, certains appels oublies
**How to avoid:** Dry-run au niveau le plus haut (avant appel services), affichage uniforme
**Warning signs:** Fichiers deplaces en mode dry-run

### Pitfall 5: Exit codes inconsistents
**What goes wrong:** Scripts appelant cineorg ne detectent pas les erreurs
**Why it happens:** Pas de raise typer.Exit(code=1) sur erreur
**How to avoid:** Codes standards: 0=success, 1=error, 2=user cancel (Abort)
**Warning signs:** `echo $?` retourne 0 apres une erreur

## Code Examples

Verified patterns from official sources and existing codebase:

### Process command structure
```python
# Pattern combine: callback + async + progress
# Source: Patterns Typer + validation.py existant

from typing import Annotated
from enum import Enum
import typer
from asyncio import run as aiorun

from src.adapters.cli.validation import console
from src.container import Container

class MediaFilter(str, Enum):
    """Filtre par type de media."""
    ALL = "movies-and-series"
    MOVIES = "movies-only"
    SERIES = "series-only"

@app.command()
def process(
    filter_type: Annotated[MediaFilter, typer.Option(
        "--filter", "-f",
        help="Type de medias a traiter"
    )] = MediaFilter.ALL,
    dry_run: Annotated[bool, typer.Option(
        "--dry-run",
        help="Simule sans modifier les fichiers"
    )] = False,
) -> None:
    """Execute le workflow complet: scan -> matching -> validation -> transfert."""
    aiorun(_process_async(filter_type, dry_run))

async def _process_async(filter_type: MediaFilter, dry_run: bool) -> None:
    container = Container()
    await container.database.init()

    scanner = container.scanner_service()
    validation_svc = container.validation_service()

    # ... implementation
```

### Pending command with Rich Table
```python
# Source: rich.readthedocs.io/en/stable/tables.html + validation.py

from rich.table import Table
from rich.panel import Panel

@app.command()
def pending(
    all_files: Annotated[bool, typer.Option("--all", "-a",
        help="Afficher tous les fichiers (sans pagination)")] = False,
) -> None:
    """Affiche les fichiers en attente de validation."""
    container = Container()
    # ... init

    pending_list = validation_svc.list_pending()

    if not pending_list:
        console.print("[yellow]Aucun fichier en attente.[/yellow]")
        raise typer.Exit(0)

    # Tri par score decroissant
    pending_list.sort(
        key=lambda p: max((c.get("score", 0) for c in p.candidates), default=0),
        reverse=True
    )

    page_size = len(pending_list) if all_files else 15
    for pending in pending_list[:page_size]:
        panel = _render_pending_panel(pending)
        console.print(panel)
```

### Error handling with exit codes
```python
# Source: https://typer.tiangolo.com/tutorial/terminating/

from loguru import logger

@app.command()
def validate(
    file_id: Annotated[str, typer.Argument(help="ID du fichier a valider")],
) -> None:
    """Valide un fichier specifique par son ID."""
    try:
        aiorun(_validate_async(file_id))
    except ValueError as e:
        console.print(f"[red]Erreur:[/red] {e}")
        logger.error("Validation echouee", file_id=file_id, error=str(e))
        raise typer.Exit(code=1)
```

### Progress for workflow stages
```python
# Source: validation.py execute_batch_transfer + rich progress docs

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

async def _run_workflow_with_progress(scanner, matcher, files) -> dict:
    """Execute le workflow avec progression visuelle."""
    stats = {"scanned": 0, "matched": 0, "errors": 0}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        # Phase 1: Scan (total inconnu)
        scan_task = progress.add_task("[cyan]Scan...", total=None)
        scan_results = []
        for result in scanner.scan_downloads():
            scan_results.append(result)
            progress.update(scan_task,
                description=f"[cyan]Scan: {result.video_file.filename}")
        progress.update(scan_task, total=len(scan_results), completed=len(scan_results))
        stats["scanned"] = len(scan_results)

        # Phase 2: Matching (total connu)
        match_task = progress.add_task("[green]Matching...", total=len(scan_results))
        for result in scan_results:
            # ... matching logic
            progress.advance(match_task)

    return stats
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Click | Typer | 2020+ | Type hints, auto-completion |
| argparse | Typer | 2020+ | Moins de boilerplate |
| print() | Rich Console | 2020+ | Couleurs, formatage |
| tqdm | Rich Progress | 2020+ | Integration Rich, colonnes custom |

**Deprecated/outdated:**
- Click callbacks manuels: Typer les genere depuis les type hints
- ANSI escape codes: Rich gere automatiquement

## Open Questions

Things that couldn't be fully resolved:

1. **Nombre exact de fichiers pour pagination pending**
   - What we know: 10-20 mentionne dans CONTEXT.md, PAGE_SIZE=5 dans validation.py pour candidats
   - What's unclear: Preference exacte utilisateur
   - Recommendation: Utiliser 15 comme defaut, ajustable via option si demande

2. **Format exact des erreurs JSON**
   - What we know: Loguru avec serialize=True produit du JSON
   - What's unclear: Structure exacte des champs pour les erreurs process
   - Recommendation: Utiliser logger.error() avec kwargs structures, le format JSON est automatique

## Sources

### Primary (HIGH confidence)
- Typer official docs (https://typer.tiangolo.com/) - Callbacks, termination, options
- Rich official docs (https://rich.readthedocs.io/) - Progress, Console, Tables
- Codebase existant: src/adapters/cli/validation.py, src/main.py, tests/unit/adapters/cli/

### Secondary (MEDIUM confidence)
- GitHub discussions Typer async (https://github.com/fastapi/typer/discussions/864)
- srcco.de CLI best practices (https://srcco.de/posts/writing-python-command-line-scripts.html)

### Tertiary (LOW confidence)
- Aucune source non verifiee utilisee

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Bibliotheques deja utilisees dans le projet
- Architecture: HIGH - Patterns documentes officiellement + existants dans codebase
- Pitfalls: HIGH - Bases sur docs officiels et experience codebase

**Research date:** 2026-01-28
**Valid until:** 60 jours (stack stable, pas de changements majeurs attendus)
