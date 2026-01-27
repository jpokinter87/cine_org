# Phase 6: Validation - Research

**Researched:** 2026-01-27
**Domain:** CLI interactive validation workflow avec Typer et Rich
**Confidence:** HIGH

## Summary

Cette phase implemente le workflow de validation des correspondances API pour CineOrg. Elle couvre la validation automatique (score >= 85% et resultat unique), la validation manuelle interactive via CLI, et la confirmation batch avant transfert.

Le projet utilise deja Typer (0.15.0) comme framework CLI et Rich (13.9.4) est installe comme dependance de Typer. Ces deux bibliotheques sont parfaitement adaptees pour construire une interface de validation interactive avec affichage de cartes candidats, selection par numero, et barres de progression pour le transfert batch.

L'architecture hexagonale existante (ports/adapters) permet de separer clairement la logique metier de validation (service) de l'interface CLI (adapter). Les entites `PendingValidation` et `SearchResult` sont deja definies et le repository `PendingValidationRepository` est implemente.

**Primary recommendation:** Creer un `ValidationService` orchestrant la logique metier et un module `src/adapters/cli/validation.py` pour l'interface interactive utilisant Rich (Panel, Table, Progress) avec Typer pour les commandes.

## Standard Stack

Les bibliotheques/outils etablis pour ce domaine.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| typer | 0.15.0+ | Framework CLI avec types hints | Deja utilise, integre avec Rich, valide types automatiquement |
| rich | 13.9.4+ | Affichage terminal riche (panels, tables, progress) | Inclus avec Typer, API moderne, output structure |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| rich.panel | - | Cartes candidats avec bordures | Affichage detaille d'un candidat API |
| rich.table | - | Tableaux recapitulatifs | Batch confirmation, liste des fichiers |
| rich.progress | - | Barres de progression | Transfert batch avec % et fichier en cours |
| rich.prompt | - | Input utilisateur avec validation | Saisie libre, confirmation |
| rich.console | - | Console enrichie avec markup | Formatage couleurs, badges |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| rich.prompt | typer.prompt | typer.prompt plus simple mais moins de controle sur le formatage |
| Manual loop | questionary | questionary ajoute une dependance, Rich suffit pour ce cas |

**Installation:**
```bash
# Deja installe via typer[all]
pip install typer[all]  # Inclut rich, shellingham
```

## Architecture Patterns

### Recommended Project Structure
```
src/
├── services/
│   └── validation.py     # ValidationService - logique metier
├── adapters/
│   └── cli/
│       ├── __init__.py
│       ├── commands.py   # Commandes Typer principales
│       └── validation.py # CLI interactive de validation
├── core/
│   └── entities/
│       └── video.py      # PendingValidation (existe deja)
```

### Pattern 1: Service Layer pour la logique metier
**What:** ValidationService encapsule les regles de validation (seuil 85%, unicite)
**When to use:** Toute operation de validation (auto ou manuelle)
**Example:**
```python
# Source: Architecture hexagonale CineOrg
class ValidationService:
    THRESHOLD = 85

    def __init__(
        self,
        pending_repo: SQLModelPendingValidationRepository,
        matcher: MatcherService,
        tmdb_client: TMDBClient,
        tvdb_client: TVDBClient,
    ):
        self._pending_repo = pending_repo
        self._matcher = matcher
        self._tmdb = tmdb_client
        self._tvdb = tvdb_client

    def should_auto_validate(self, candidates: list[SearchResult]) -> bool:
        """Retourne True si auto-validation possible."""
        if len(candidates) != 1:
            return False
        return candidates[0].score >= self.THRESHOLD

    async def validate_candidate(
        self,
        pending_id: str,
        candidate_id: str,
        source: str,
    ) -> MediaDetails:
        """Valide un candidat et recupere ses details."""
        client = self._tmdb if source == "tmdb" else self._tvdb
        details = await client.get_details(candidate_id)
        # Mettre a jour le statut
        pending = self._pending_repo.get_by_id(pending_id)
        pending.validation_status = ValidationStatus.VALIDATED
        pending.selected_candidate_id = candidate_id
        self._pending_repo.save(pending)
        return details
```

### Pattern 2: CLI Interactive Loop avec Rich
**What:** Boucle principale gerant les commandes utilisateur
**When to use:** Validation manuelle fichier par fichier
**Example:**
```python
# Source: Rich + Typer documentation
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

console = Console()

def validation_loop(pending: PendingValidation) -> str | None:
    """Boucle de validation interactive."""
    candidates = pending.candidates
    page = 0
    page_size = 5

    while True:
        # Afficher les candidats de la page courante
        display_candidates(candidates[page*page_size:(page+1)*page_size], page)

        # Prompt utilisateur
        choice = Prompt.ask(
            "[bold]Choix[/]",
            choices=["1","2","3","4","5","s","t","r","i","d","?","q"],
            default="1",
        )

        if choice.isdigit():
            idx = int(choice) - 1 + (page * page_size)
            if 0 <= idx < len(candidates):
                return candidates[idx]["id"]
        elif choice == "s":  # skip
            return None
        elif choice == "n":  # next page
            if (page + 1) * page_size < len(candidates):
                page += 1
        # ... autres actions
```

### Pattern 3: Affichage Carte Candidat avec Panel
**What:** Panel Rich pour afficher un candidat avec details
**When to use:** Chaque candidat dans la liste de selection
**Example:**
```python
# Source: Rich documentation - Panel
from rich.panel import Panel
from rich.text import Text

def render_candidate_card(candidate: dict, rank: int, is_best: bool = False) -> Panel:
    """Genere une carte Rich pour un candidat."""
    content = Text()
    content.append(f"{candidate['title']}", style="bold white")
    if candidate.get('year'):
        content.append(f" ({candidate['year']})", style="dim")
    content.append("\n")
    content.append(f"Score: {candidate['score']:.1f}%", style="green" if candidate['score'] >= 85 else "yellow")
    content.append(f" | Source: {candidate['source'].upper()}", style="cyan")

    if candidate.get('genres'):
        content.append(f"\nGenres: {', '.join(candidate['genres'][:3])}", style="dim")
    if candidate.get('overview'):
        overview = candidate['overview'][:150] + "..." if len(candidate['overview']) > 150 else candidate['overview']
        content.append(f"\n{overview}", style="italic dim")

    title = f"[{rank}]"
    if is_best:
        title += " [green bold]* RECOMMANDE[/]"

    return Panel(content, title=title, border_style="green" if is_best else "white")
```

### Pattern 4: Detection automatique des IDs externes
**What:** Regex pour detecter IMDB, TMDB, TVDB IDs dans l'input
**When to use:** Commande [i] saisie ID externe
**Example:**
```python
# Source: IMDB format standard tt\d{7,8}
import re

IMDB_PATTERN = re.compile(r"^tt\d{7,8}$")
NUMERIC_PATTERN = re.compile(r"^\d+$")

def detect_external_id(user_input: str) -> tuple[str | None, str | None]:
    """
    Detecte le type d'ID externe saisi.

    Returns:
        (id_type, id_value) ou (None, None) si non reconnu.
        id_type: 'imdb', 'tmdb', 'tvdb', ou None
    """
    user_input = user_input.strip().lower()

    if IMDB_PATTERN.match(user_input):
        return ("imdb", user_input)

    if NUMERIC_PATTERN.match(user_input):
        # Demander la source
        return ("numeric", user_input)  # Caller doit demander tmdb/tvdb

    return (None, None)
```

### Pattern 5: Batch Confirmation avec Table
**What:** Affichage tableau recapitulatif avant transfert
**When to use:** Validation finale batch (VALID-04)
**Example:**
```python
# Source: Rich documentation - Table
from rich.table import Table
from rich.console import Console

def display_batch_summary(transfers: list[dict]) -> None:
    """Affiche le recapitulatif batch avant transfert."""
    console = Console()

    table = Table(title="Recapitulatif des transferts")
    table.add_column("#", style="dim", width=4)
    table.add_column("Fichier source", style="cyan", no_wrap=True)
    table.add_column("Destination", style="green")
    table.add_column("Action", style="yellow")

    for i, transfer in enumerate(transfers, 1):
        table.add_row(
            str(i),
            str(transfer["source"].name),
            str(transfer["destination"]),
            transfer.get("action", "move"),
        )

    console.print(table)
```

### Pattern 6: Progress Bar pour transfert
**What:** Barre de progression Rich avec details
**When to use:** Pendant le transfert batch
**Example:**
```python
# Source: Rich documentation - Progress
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

async def execute_batch_transfer(transfers: list[dict]) -> None:
    """Execute les transferts avec progression."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("({task.completed}/{task.total})"),
    ) as progress:
        task = progress.add_task("Transfert en cours...", total=len(transfers))

        for transfer in transfers:
            progress.update(task, description=f"[cyan]{transfer['source'].name}[/]")
            # Effectuer le transfert
            result = await do_transfer(transfer)
            progress.advance(task)
```

### Anti-Patterns to Avoid
- **Logique metier dans le CLI:** La validation du seuil 85% doit etre dans ValidationService, pas dans les commandes
- **Prompts bloquants sans timeout:** Utiliser des defaults sensibles pour les tests automatises
- **Etat global:** Utiliser l'injection de dependances via Container, pas de singletons CLI
- **Modification directe des entites:** Passer par les repositories pour toute modification de statut

## Don't Hand-Roll

Problemes qui semblent simples mais ont des solutions existantes.

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Formatage terminal couleurs | ANSI codes manuels | Rich Console + markup | Compatibilite terminal, themes |
| Progress bar | print("\r...") | Rich Progress | Multi-tasks, ETA, customizable |
| Input avec validation | input() + try/except | Rich Prompt + choices | Retry automatique, type hints |
| Tableaux ASCII | Format strings | Rich Table | Wrapping auto, styles colonnes |
| Bordures/cartes | Print de caracteres | Rich Panel | Box styles, titres, responsif |

**Key insight:** Rich fournit une abstraction complete du terminal qui gere automatiquement les largeurs, les couleurs degradees, et la compatibilite Windows/Linux.

## Common Pitfalls

### Pitfall 1: Async dans le CLI Typer
**What goes wrong:** Typer ne gere pas nativement async, les appels API bloquent
**Why it happens:** Typer est synchrone, les clients API CineOrg sont async
**How to avoid:** Wrapper asyncio.run() ou utiliser anyio/trio dans les commandes
**Warning signs:** RuntimeWarning about unawaited coroutine

```python
# Solution
import asyncio

@app.command()
def validate():
    """Commande de validation (wrapper sync)."""
    asyncio.run(_validate_async())

async def _validate_async():
    """Implementation async reelle."""
    client = TMDBClient(...)
    results = await client.search("Avatar")
```

### Pitfall 2: Session DB non fermee
**What goes wrong:** Sessions SQLModel restent ouvertes, locks database
**Why it happens:** Utilisation du Container sans contexte propre
**How to avoid:** Utiliser un scope de session par commande
**Warning signs:** sqlite3.OperationalError: database is locked

```python
# Solution - scope de session
from contextlib import contextmanager

@contextmanager
def db_session():
    session = container.session()
    try:
        yield session
    finally:
        session.close()

@app.command()
def validate():
    with db_session() as session:
        repo = SQLModelPendingValidationRepository(session)
        # ...
```

### Pitfall 3: Rich Prompt vs Typer Prompt
**What goes wrong:** Mixing des deux systemes de prompt cause des conflits
**Why it happens:** Typer et Rich ont des APIs similaires mais differentes
**How to avoid:** Choisir Rich.prompt pour l'interactivite avancee, Typer.prompt pour les CLI options
**Warning signs:** Output mal formate, couleurs perdues

```python
# Typer prompt - pour options CLI declaratives
@app.command()
def cmd(name: Annotated[str, typer.Option(prompt="Your name")]):
    pass

# Rich prompt - pour interactivite dynamique
from rich.prompt import Prompt
choice = Prompt.ask("Select", choices=["1", "2", "3"])
```

### Pitfall 4: Pagination manuelle des candidats
**What goes wrong:** Off-by-one errors dans l'indexation
**Why it happens:** Melange index 0-based et affichage 1-based
**How to avoid:** Encapsuler dans une classe Paginator
**Warning signs:** IndexError, mauvais candidat selectionne

```python
# Solution - Paginator dedicate
class CandidatePaginator:
    def __init__(self, candidates: list, page_size: int = 5):
        self.candidates = candidates
        self.page_size = page_size
        self.current_page = 0

    @property
    def current_items(self) -> list:
        start = self.current_page * self.page_size
        return self.candidates[start:start + self.page_size]

    def select(self, display_number: int) -> dict | None:
        """Selectionne par numero affiche (1-based)."""
        idx = (self.current_page * self.page_size) + display_number - 1
        if 0 <= idx < len(self.candidates):
            return self.candidates[idx]
        return None
```

### Pitfall 5: Tests CLI interactifs
**What goes wrong:** Tests echouent car attendent input
**Why it happens:** Prompts bloquent l'execution des tests
**How to avoid:** Injection de stdin mock ou mode non-interactif
**Warning signs:** Tests timeout, CI bloque

```python
# Solution - injection de Console
from io import StringIO
from rich.console import Console

def create_console(input_text: str = "") -> Console:
    """Console avec stdin mock pour tests."""
    return Console(file=StringIO(), force_terminal=True)

# Dans les tests
def test_validation_selection(monkeypatch):
    monkeypatch.setattr('builtins.input', lambda _: "1")
    # ou utiliser CliRunner de Typer
```

## Code Examples

Patterns verifies depuis les sources officielles.

### Commande Typer avec subcommands
```python
# Source: Typer documentation
import typer

app = typer.Typer(
    name="cineorg",
    help="Application de gestion de videotheque",
    rich_markup_mode="rich",
)

validate_app = typer.Typer(help="Commandes de validation")
app.add_typer(validate_app, name="validate")

@validate_app.command("auto")
def validate_auto():
    """Valide automatiquement les fichiers avec score >= 85%."""
    pass

@validate_app.command("manual")
def validate_manual():
    """Lance la validation manuelle interactive."""
    pass

@validate_app.command("batch")
def validate_batch():
    """Affiche et confirme le batch de transferts."""
    pass
```

### Rich Console avec Typer
```python
# Source: Typer + Rich integration
from rich.console import Console
from rich.panel import Panel

console = Console()

@app.command()
def info():
    """Affiche les infos avec Rich."""
    console.print(
        Panel.fit(
            "[bold green]CineOrg[/] - Gestionnaire de videotheque",
            title="Bienvenue",
        )
    )
```

### Prompt avec choix et validation
```python
# Source: Rich documentation - prompt.py
from rich.prompt import Prompt, IntPrompt, Confirm

# Choix contraint
choice = Prompt.ask(
    "Action",
    choices=["1", "2", "3", "s", "r", "q"],
    default="1",
)

# Entier avec range
page = IntPrompt.ask("Page", default=1)

# Confirmation
if Confirm.ask("Confirmer le transfert?"):
    execute_transfer()
```

### Recherche manuelle avec detection ID
```python
# Source: Implementation CineOrg
import re
from rich.prompt import Prompt

IMDB_PATTERN = re.compile(r"^tt\d{7,8}$", re.IGNORECASE)

def handle_manual_search() -> tuple[str, str]:
    """Gere la recherche manuelle avec detection auto."""
    query = Prompt.ask("[bold]Recherche[/]")

    # Detection IMDB
    if IMDB_PATTERN.match(query):
        console.print(f"[green]ID IMDB detecte: {query}[/]")
        return ("imdb", query.lower())

    # Detection numerique - demander source
    if query.isdigit():
        source = Prompt.ask(
            "Source",
            choices=["tmdb", "tvdb"],
            default="tmdb",
        )
        return (source, query)

    # Recherche textuelle
    return ("search", query)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Click pour CLI | Typer | 2019+ | Type hints, validation auto, Rich integre |
| colorama/termcolor | Rich | 2020+ | API unifiee, panels/tables/progress |
| argparse subparsers | Typer groups | 2020+ | Declaration intuitive, help auto |
| input() + validation | Rich Prompt | 2020+ | Choices, types, retry integre |

**Deprecated/outdated:**
- `typer.echo()`: Preferer `console.print()` de Rich pour le formatage
- `typer.secho()`: Obsolete avec Rich disponible

## Open Questions

Questions non completement resolues.

1. **Gestion des erreurs pendant le transfert batch**
   - What we know: Le contexte (06-CONTEXT.md) mentionne "Claude's Discretion" pour ce point
   - What's unclear: Continuer et reporter vs pause et choix utilisateur
   - Recommendation: Implementer continue + rapport final avec liste des erreurs, option retry

2. **Format recherche series**
   - What we know: Contexte dit "Claude's discretion - titre seul puis navigation saison/episode"
   - What's unclear: UX exacte de la navigation apres selection de la serie
   - Recommendation: Selection serie -> affichage saisons -> selection saison -> episodes ou auto-match

3. **Recherche sans resultat**
   - What we know: Contexte dit "Claude's discretion - retry simple ou suggestions"
   - What's unclear: Quelles suggestions proposer
   - Recommendation: Retry simple avec message + option de modifier la requete

## Sources

### Primary (HIGH confidence)
- [Typer Official Documentation - Prompts](https://typer.tiangolo.com/tutorial/prompt/) - typer.prompt(), typer.confirm()
- [Rich Official Documentation - Progress](https://rich.readthedocs.io/en/latest/progress.html) - Progress, track()
- [Rich Official Documentation - Panel](https://rich.readthedocs.io/en/latest/panel.html) - Panel.fit(), styling
- [Rich Official Documentation - Table](https://rich.readthedocs.io/en/latest/tables.html) - Table, columns
- [Rich Official Documentation - Prompt](https://rich.readthedocs.io/en/latest/prompt.html) - Prompt.ask(), IntPrompt, Confirm
- Code source CineOrg existant (src/services/matcher.py, src/core/entities/video.py)

### Secondary (MEDIUM confidence)
- [Building Modern CLI with Typer and Rich](https://www.codecentric.de/en/knowledge-hub/blog/lets-build-a-modern-cmd-tool-with-python-using-typer-and-rich) - Patterns d'architecture CLI
- [Interactive CLIs with Typer and Rich](https://pybash.medium.com/interactive-cli-1-40bc1df37df9) - Integration Typer/Rich
- [IMDB ID Format - Wikidata](https://www.wikidata.org/wiki/Property:P345) - Format tt\d{7,8}

### Tertiary (LOW confidence)
- None required - stack well-documented

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Typer et Rich deja installes, documentation officielle verifiee
- Architecture: HIGH - Architecture hexagonale CineOrg documentee, patterns standards
- Pitfalls: HIGH - Issues communes bien documentees (async, sessions, prompts)

**Research date:** 2026-01-27
**Valid until:** 2026-02-27 (stack stable, 30 jours)
