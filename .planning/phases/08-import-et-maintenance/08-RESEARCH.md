# Phase 8: Import et Maintenance - Research

**Researched:** 2026-01-28
**Domain:** CLI Commands, Database Import, Symlink Management, API Enrichment
**Confidence:** HIGH

## Summary

Cette phase implemente quatre commandes CLI pour gerer une videotheque existante: `import` (scanner et importer dans la BDD), `enrich` (enrichir via API), `repair-links` (reparer symlinks casses), et `check` (verifier l'integrite). Le domaine est bien couvert par les patterns existants dans le codebase avec Typer/Rich pour la CLI et SQLModel pour la persistance.

Le codebase existant fournit deja:
- Pattern CLI avec Typer et Rich (commands.py, validation.py)
- Services d'import/scan (ScannerService)
- Clients API avec rate limiting (TMDBClient, TVDBClient avec tenacity)
- Gestion de symlinks (FileSystemAdapter.find_broken_links)
- Hash de fichiers (hash_service.py avec xxhash)
- Repositories SQLModel (video_file_repository, pending_validation_repository)

**Primary recommendation:** Reutiliser les patterns CLI existants (Progress bars Rich, Confirm prompts, async patterns) et creer des services dedies (ImporterService, EnricherService, RepairService, IntegrityChecker) qui orchestrent les repositories et adapters existants.

## Standard Stack

The established libraries/tools for this domain:

### Core (Already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| typer | 0.9+ | CLI framework | Deja utilise pour process/pending/validate |
| rich | 13+ | Progress bars, tables, prompts | Deja utilise pour l'interface CLI |
| sqlmodel | 0.0.14+ | ORM SQLite | Deja utilise pour persistance |
| loguru | 0.7+ | Logging avec rotation | Deja configure dans le projet |
| xxhash | 3+ | Hash rapide de fichiers | Deja utilise dans hash_service.py |
| tenacity | 8+ | Retry avec backoff | Deja utilise dans retry.py |
| httpx | 0.25+ | Client HTTP async | Deja utilise pour TMDB/TVDB |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pathlib | stdlib | Manipulation chemins, symlinks | Detection symlinks casses |
| asyncio | stdlib | Async execution | Rate limiting enrichissement |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| xxhash | hashlib/md5 | xxhash 10x plus rapide pour gros fichiers |
| tenacity | custom retry | tenacity plus robuste, deja integre |
| rich Progress | tqdm | rich deja integre, plus flexible |

**Installation:**
Aucune dependance supplementaire requise - tout est deja dans requirements.txt.

## Architecture Patterns

### Recommended Project Structure
```
src/
├── services/                   # Services existants
│   ├── importer.py            # NOUVEAU: ImporterService
│   ├── enricher.py            # NOUVEAU: EnricherService
│   ├── repair.py              # NOUVEAU: RepairService (ou dans integrity.py)
│   └── integrity.py           # NOUVEAU: IntegrityChecker
├── adapters/
│   └── cli/
│       ├── commands.py        # Ajouter import, enrich, repair-links, check
│       └── validation.py      # Existant - patterns a reutiliser
└── container.py               # Ajouter nouveaux services
```

### Pattern 1: Service Layer Orchestration
**What:** Les commandes CLI delegent toute la logique aux services, qui orchestrent repositories et adapters.
**When to use:** Toujours - separe la presentation (CLI) de la logique metier (services).
**Example:**
```python
# Source: Pattern existant dans commands.py
class ImporterService:
    """Service d'import de videotheque existante."""

    def __init__(
        self,
        file_system: FileSystemAdapter,
        filename_parser: IFilenameParser,
        media_info_extractor: IMediaInfoExtractor,
        video_file_repo: SQLModelVideoFileRepository,
        movie_repo: SQLModelMovieRepository,
        series_repo: SQLModelSeriesRepository,
        hash_service: Callable[[Path], str],
    ) -> None:
        self._file_system = file_system
        self._filename_parser = filename_parser
        self._media_info_extractor = media_info_extractor
        self._video_file_repo = video_file_repo
        self._movie_repo = movie_repo
        self._series_repo = series_repo
        self._compute_hash = hash_service
```

### Pattern 2: Progress Bar with Generator
**What:** Utiliser un generateur pour alimenter une barre de progression Rich.
**When to use:** Pour les operations longues comme le scan de videotheque.
**Example:**
```python
# Source: Pattern existant dans commands.py/_process_async
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

async def _import_async(storage_dir: Path) -> None:
    """Implementation async de la commande import."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Import en cours...", total=None)
        imported = 0
        skipped = 0

        for result in importer.scan_library(storage_dir):
            progress.update(task, description=f"[cyan]{result.filename}")

            if result.already_known:
                skipped += 1
            else:
                imported += 1

        progress.update(task, total=imported + skipped, completed=imported + skipped)

    console.print(f"[green]{imported}[/green] importe(s), [yellow]{skipped}[/yellow] ignore(s)")
```

### Pattern 3: Interactive Confirmation Loop
**What:** Boucle interactive avec confirmation utilisateur avant chaque action.
**When to use:** Pour repair-links en mode interactif.
**Example:**
```python
# Source: Inspire de validation.py/validation_loop et Rich docs
from rich.prompt import Confirm

async def repair_interactive(broken_links: list[Path]) -> RepairResult:
    """Repare les symlinks casses avec confirmation utilisateur."""
    repaired = 0
    skipped = 0

    for link in broken_links:
        console.print(f"\n[bold]Symlink casse:[/bold] {link}")
        console.print(f"  Cible: {link.resolve(strict=False)}")

        choice = Prompt.ask(
            "Action",
            choices=["r", "s", "d", "q"],  # repair, skip, delete, quit
            default="s"
        )

        if choice == "r":
            # Trouver la nouvelle cible
            new_target = find_new_target(link)
            if new_target and Confirm.ask(f"Pointer vers {new_target} ?"):
                link.unlink()
                link.symlink_to(new_target)
                repaired += 1
        elif choice == "d":
            if Confirm.ask("Supprimer le symlink ?"):
                link.unlink()
        elif choice == "q":
            break
        else:
            skipped += 1

    return RepairResult(repaired=repaired, skipped=skipped)
```

### Pattern 4: Rate-Limited API Enrichment
**What:** Enrichissement avec respect des limites API et reprise naturelle.
**When to use:** Pour la commande enrich qui appelle les APIs externes.
**Example:**
```python
# Source: Pattern existant dans tmdb_client.py avec retry.py
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential

class EnricherService:
    """Service d'enrichissement via API."""

    # TMDB: 40 requetes / 10 secondes = 4 req/s = 0.25s entre chaque
    RATE_LIMIT_DELAY = 0.25
    MAX_RETRIES = 3

    async def enrich_batch(
        self,
        items: list[PendingEnrichment],
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> EnrichmentResult:
        """Enrichit un lot de fichiers avec rate limiting."""
        enriched = 0
        failed = 0

        for item in items:
            if progress_callback:
                progress_callback(item.filename)

            try:
                # request_with_retry gere deja le backoff sur 429
                details = await self._get_details(item)
                if details:
                    self._save_enrichment(item, details)
                    enriched += 1

                # Pause entre les requetes pour respecter le rate limit
                await asyncio.sleep(self.RATE_LIMIT_DELAY)

            except Exception as e:
                logger.warning(f"Enrichissement echoue pour {item.filename}: {e}")
                failed += 1

        return EnrichmentResult(enriched=enriched, failed=failed)
```

### Anti-Patterns to Avoid
- **Logique metier dans les commandes CLI:** Toujours deleguer aux services
- **Commits DB dans les boucles:** Utiliser des batches ou commit a la fin
- **Ignorer les erreurs silencieusement:** Toujours logger et compter les erreurs
- **Modification de fichiers sans confirmation:** Mode interactif par defaut pour les actions destructives

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Detection symlinks casses | os.walk + manual checks | FileSystemAdapter.find_broken_links | Deja implemente, gere les edge cases |
| Rate limiting | Sleep fixe | tenacity + request_with_retry | Gere backoff exponentiel, retry intelligent |
| Hash de fichier | hashlib full file | hash_service.compute_file_hash | xxhash echantillonne (10x plus rapide) |
| Progress bars | print() | rich.progress.Progress | Deja utilise, thread-safe, multi-taches |
| Confirmation interactive | input() | rich.prompt.Confirm | Style coherent, gestion erreurs |
| Logging fichier | open/write | loguru.logger.add | Rotation, compression, niveaux |

**Key insight:** Le codebase fournit deja tous les outils necessaires. La phase 8 consiste a les orchestrer dans de nouveaux services et commandes CLI.

## Common Pitfalls

### Pitfall 1: Fichiers deja connus retraites
**What goes wrong:** L'import retraite des fichiers deja dans la BDD, creant des doublons.
**Why it happens:** On verifie par path mais le fichier peut avoir ete deplace.
**How to avoid:** Verifier par hash AVANT le path. Si meme hash existe, ignorer silencieusement.
**Warning signs:** Nombre d'imports ne correspond pas aux fichiers reellement nouveaux.

```python
def should_import(self, file_path: Path) -> ImportDecision:
    """Decide si un fichier doit etre importe."""
    # 1. Calculer le hash
    file_hash = self._compute_hash(file_path)

    # 2. Verifier si hash existe deja
    existing = self._video_file_repo.get_by_hash(file_hash)
    if existing:
        return ImportDecision.SKIP_KNOWN

    # 3. Verifier si path existe (fichier deplace/renomme)
    existing_path = self._video_file_repo.get_by_path(file_path)
    if existing_path:
        return ImportDecision.UPDATE_PATH

    return ImportDecision.IMPORT
```

### Pitfall 2: Rate limiting non respecte
**What goes wrong:** Les APIs retournent 429, les requetes echouent en cascade.
**Why it happens:** Enrichissement trop rapide sans pause entre les requetes.
**How to avoid:** Utiliser request_with_retry existant + asyncio.sleep entre requetes.
**Warning signs:** Logs avec "429 Too Many Requests" ou RateLimitError.

### Pitfall 3: Symlinks orphelins supprimes sans backup
**What goes wrong:** Un symlink pointe vers un fichier deplace, on le supprime, on perd la reference.
**Why it happens:** Mode non-interactif qui supprime automatiquement.
**How to avoid:** Mode interactif par defaut. Deplacer vers trash/orphans au lieu de supprimer.
**Warning signs:** Fichiers video inaccessibles depuis video/ apres reparation.

```python
def handle_orphan_symlink(self, link: Path, trash_dir: Path) -> None:
    """Deplace un symlink orphelin vers trash/orphans."""
    orphans_dir = trash_dir / "orphans"
    orphans_dir.mkdir(parents=True, exist_ok=True)

    # Garder le nom relatif pour retrouver l'origine
    dest = orphans_dir / link.name
    if dest.exists():
        dest = orphans_dir / f"{link.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{link.suffix}"

    # Copier les infos du symlink avant de le supprimer
    target = link.resolve(strict=False)  # Cible meme si cassee
    link.rename(dest)

    logger.info(f"Symlink orphelin deplace: {link} -> {dest} (cible: {target})")
```

### Pitfall 4: Coherence BDD/filesystem partielle
**What goes wrong:** La commande check ne detecte pas toutes les incoherences.
**Why it happens:** On verifie seulement BDD -> filesystem, pas l'inverse.
**How to avoid:** Verifier dans les deux sens: entrees fantomes ET fichiers orphelins.
**Warning signs:** Des fichiers existent sans entree BDD correspondante.

```python
def check_integrity(self) -> IntegrityReport:
    """Verifie la coherence dans les deux sens."""
    report = IntegrityReport()

    # 1. Entrees fantomes: dans BDD mais pas sur disque
    for video_file in self._video_file_repo.list_all():
        if not video_file.path.exists():
            report.add_ghost_entry(video_file)

    # 2. Fichiers orphelins: sur disque mais pas dans BDD
    for path in self._file_system.list_video_files(self._storage_dir):
        if self._video_file_repo.get_by_path(path) is None:
            report.add_orphan_file(path)

    # 3. Symlinks casses
    for link in self._file_system.find_broken_links(self._video_dir):
        report.add_broken_symlink(link)

    return report
```

### Pitfall 5: Logs de reparation perdus
**What goes wrong:** Pas de trace des actions effectuees par repair-links.
**Why it happens:** On affiche dans la console mais on ne persiste pas.
**How to avoid:** Ecrire un fichier log horodate (repair-YYYY-MM-DD.log).
**Warning signs:** Impossible de savoir ce qui a ete repare apres coup.

```python
def create_repair_log(self, actions: list[RepairAction]) -> Path:
    """Cree un fichier log des reparations."""
    log_path = Path(f"repair-{datetime.now().strftime('%Y-%m-%d')}.log")

    with open(log_path, "a") as f:
        f.write(f"\n=== Reparation {datetime.now().isoformat()} ===\n")
        for action in actions:
            f.write(f"{action.type}: {action.link} -> {action.result}\n")

    return log_path
```

## Code Examples

Verified patterns from official sources and existing codebase:

### Import Command Structure
```python
# Source: Pattern commands.py existant
@app.command()
def import_library(
    storage_dir: Annotated[
        Path,
        typer.Argument(help="Repertoire de la videotheque a importer"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Simule sans modifier la BDD"),
    ] = False,
) -> None:
    """Importe une videotheque existante dans la base de donnees."""
    asyncio.run(_import_async(storage_dir or Path(config.storage_dir), dry_run))
```

### Enrich Command with Progress
```python
# Source: Pattern commands.py/_process_async
async def _enrich_async() -> None:
    """Enrichit les fichiers non enrichis via API."""
    container = Container()
    container.database.init()

    enricher = container.enricher_service()
    pending = enricher.list_pending_enrichment()

    if not pending:
        console.print("[yellow]Aucun fichier a enrichir.[/yellow]")
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[green]Enrichissement...", total=len(pending))

        result = await enricher.enrich_batch(
            pending,
            progress_callback=lambda f: progress.update(task, description=f"[green]{f}"),
            advance_callback=lambda: progress.advance(task),
        )

    console.print(f"\n[bold green]{result.enriched}[/bold green] enrichi(s)")
    if result.failed > 0:
        console.print(f"[bold red]{result.failed}[/bold red] echec(s)")
```

### Check Command with JSON Output
```python
# Source: Pattern CLI standard
@app.command()
def check(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Format de sortie JSON"),
    ] = False,
    verify_hash: Annotated[
        bool,
        typer.Option("--verify-hash", help="Verifier les hash (lent)"),
    ] = False,
) -> None:
    """Verifie l'integrite de la videotheque."""
    container = Container()
    container.database.init()

    checker = container.integrity_checker()
    report = checker.check(verify_hash=verify_hash)

    if json_output:
        console.print(report.to_json())
    else:
        _display_integrity_report(report)
```

### Repair-Links Interactive Mode
```python
# Source: Pattern validation.py/validation_loop
async def _repair_links_async() -> None:
    """Repare les symlinks casses interactivement."""
    container = Container()
    repair_service = container.repair_service()

    broken = repair_service.find_broken_symlinks()

    if not broken:
        console.print("[green]Aucun symlink casse detecte.[/green]")
        return

    console.print(f"[bold]{len(broken)}[/bold] symlink(s) casse(s) detecte(s).\n")

    actions = []
    for link in broken:
        console.print(Panel(
            f"[bold]Symlink:[/bold] {link}\n"
            f"[dim]Cible manquante:[/dim] {link.resolve(strict=False)}",
            border_style="red"
        ))

        choice = Prompt.ask(
            "Action",
            choices=["chercher", "supprimer", "ignorer", "quitter"],
            default="ignorer"
        )

        if choice == "quitter":
            break
        elif choice == "chercher":
            # Chercher le fichier dans storage par nom
            matches = repair_service.find_possible_targets(link)
            if matches:
                for i, match in enumerate(matches, 1):
                    console.print(f"  [{i}] {match}")
                idx = Prompt.ask("Selectionner", default="1")
                new_target = matches[int(idx) - 1] if idx.isdigit() else None
                if new_target:
                    repair_service.repair_symlink(link, new_target)
                    actions.append(RepairAction(link, "repaired", new_target))
        elif choice == "supprimer":
            repair_service.move_to_orphans(link)
            actions.append(RepairAction(link, "orphaned"))

    # Sauvegarder le log
    log_path = repair_service.save_log(actions)
    console.print(f"\n[dim]Log sauvegarde: {log_path}[/dim]")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| os.path pour symlinks | pathlib.Path.is_symlink() | Python 3.4+ | API orientee objet plus claire |
| md5/sha256 full file | xxhash echantillonnage | Performance | 10x plus rapide sur gros fichiers |
| custom retry loops | tenacity decorators | N/A | Plus robuste, configurable |
| print() progress | rich.progress.Progress | N/A | Thread-safe, multi-barres |

**Deprecated/outdated:**
- os.path.islink() - Prefer pathlib.Path.is_symlink()
- Simple time.sleep() retry - Utiliser tenacity avec backoff exponentiel

## Open Questions

Things that couldn't be fully resolved:

1. **Ordre de traitement pour enrich**
   - What we know: La decision utilisateur est "Claude's discretion"
   - What's unclear: Par date d'import? Par score de matching? Alphabetique?
   - Recommendation: Ordre chronologique (created_at) - traiter les plus anciens d'abord

2. **Structure videotheque existante variee**
   - What we know: Respecter Films/ pour films, Series/ pour series
   - What's unclear: Comment gerer les structures non-standard (tout en vrac, sous-dossiers arbitraires)?
   - Recommendation: Scanner recursivement, detecter type par pattern du nom de fichier

3. **Fichiers sans match API**
   - What we know: Ajouter en pending_validation
   - What's unclear: Comment les distinguer des fichiers "normaux" en pending?
   - Recommendation: Ajouter un flag `import_source: imported | processed` sur PendingValidation

## Sources

### Primary (HIGH confidence)
- `/fastapi/typer` Context7 - Progress bars, callbacks, commands
- `/textualize/rich` Context7 - Progress, Console, Prompt, Panel
- `/delgan/loguru` Context7 - File logging with rotation
- Codebase existant: `src/adapters/cli/commands.py`, `src/adapters/cli/validation.py`
- Codebase existant: `src/adapters/file_system.py` (find_broken_links)
- Codebase existant: `src/infrastructure/persistence/hash_service.py` (xxhash)

### Secondary (MEDIUM confidence)
- [Typer Prompts](https://typer.tiangolo.com/tutorial/prompt/) - Confirmation patterns
- [Rich Prompt](https://rich.readthedocs.io/en/stable/prompt.html) - Interactive prompts
- [Python pathlib](https://docs.python.org/3/library/pathlib.html) - Symlink detection

### Tertiary (LOW confidence)
- WebSearch patterns for symlink repair - A valider avec tests

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Toutes les libs sont deja dans le projet
- Architecture: HIGH - Patterns CLI existants a reutiliser
- Pitfalls: HIGH - Bases sur l'analyse du codebase et les decisions CONTEXT.md

**Research date:** 2026-01-28
**Valid until:** 2026-02-28 (stable - patterns CLI matures)
