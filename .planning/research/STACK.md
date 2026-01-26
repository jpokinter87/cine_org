# Stack Technique CineOrg - Recherche 2025

> Date de recherche : 2026-01-26
> Sources : WebSearch, Context7, documentation officielle

---

## 1. Architecture CLI + API Web avec Coeur Metier Partage

### Recommandation : Architecture Hexagonale (Ports & Adapters)

**Niveau de confiance : ELEVE (95%)**

L'architecture hexagonale est le pattern recommande pour separer les interfaces (CLI, Web API) du coeur metier.

#### Structure recommandee

```
cine_org/
|-- adapters/              # Implementations concretes des ports
|   |-- cli/               # Adaptateur CLI (Typer)
|   |-- api/               # Adaptateur API (FastAPI)
|   |-- persistence/       # Adaptateur DB (SQLModel/SQLAlchemy)
|   |-- external/          # Adaptateurs APIs externes (TMDB, TVDB)
|
|-- domain/                # Coeur metier (pur Python, sans dependances externes)
|   |-- models/            # Entites du domaine
|   |-- services/          # Logique metier
|   |-- ports/             # Interfaces abstraites (ABC)
|
|-- application/           # Use cases / orchestration
|   |-- commands/          # Actions (scanner, renommer, organiser)
|   |-- queries/           # Requetes de lecture
|
|-- infrastructure/        # Configuration, logging, etc.
```

#### Rationale
- **Testabilite** : La logique metier est isolee et testable sans framework
- **Flexibilite** : On peut changer FastAPI pour Flask, ou Typer pour Click sans toucher au coeur
- **Maintenabilite** : Separation claire des responsabilites
- **Reutilisation** : CLI et API appellent les memes services du domaine

#### Sources
- [The Architecture Blueprint Every Python Backend Project Needs](https://medium.com/the-pythonworld/the-architecture-blueprint-every-python-backend-project-needs-207216931123)
- [Hexagonal Architecture in Python](https://blog.szymonmiks.pl/p/hexagonal-architecture-in-python/)
- [AWS Prescriptive Guidance - Hexagonal Architecture](https://docs.aws.amazon.com/prescriptive-guidance/latest/patterns/structure-a-python-project-in-hexagonal-architecture-using-aws-lambda.html)

---

## 2. ORM : SQLModel vs Alternatives

### Recommandation Principale : SQLModel 0.0.24+

**Niveau de confiance : ELEVE (90%)**

| Critere | SQLModel | SQLAlchemy 2.0 | Tortoise ORM |
|---------|----------|----------------|--------------|
| Integration FastAPI | Excellente (meme auteur) | Bonne | Bonne |
| Type hints natifs | Oui (Pydantic integre) | Oui (v2.0+) | Oui |
| Async natif | Via SQLAlchemy | Oui | Oui (async-first) |
| Courbe d'apprentissage | Faible | Moyenne-Elevee | Faible |
| Maturite | Moyenne | Tres elevee | Moyenne |
| Flexibilite | Moyenne | Tres elevee | Moyenne |

#### Pourquoi SQLModel ?

1. **Un seul modele** : Meme classe pour DB et validation Pydantic
2. **Integration FastAPI native** : Response models, OpenAPI automatique
3. **Fallback SQLAlchemy** : Acces direct a SQLAlchemy quand necessaire
4. **Type safety** : Detection d'erreurs a l'IDE

```python
from sqlmodel import SQLModel, Field

class Movie(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    year: int
    tmdb_id: int | None = None
```

#### Alternative consideree : SQLAlchemy 2.0 pur

**Quand preferer SQLAlchemy directement :**
- Patterns avances (inheritance, polymorphisme)
- Migrations complexes avec Alembic
- Besoin de controle fin sur les requetes

#### CE QU'IL NE FAUT PAS UTILISER

| Librairie | Raison |
|-----------|--------|
| **Peewee** | Moins de support async, communaute plus petite |
| **Pony ORM** | License AGPL restrictive pour usage commercial |
| **Django ORM** (seul) | Depend de Django, surdimensionne pour ce projet |

#### Sources
- [Is SQLModel Still Worth It in 2025?](https://python.plainenglish.io/sqlmodel-in-2025-the-hidden-gem-of-fastapi-backends-20ee8c9bf8a6)
- [SQLModel Documentation](https://sqlmodel.tiangolo.com/)
- [TortoiseORM vs SQLAlchemy](https://betterstack.com/community/guides/scaling-python/tortoiseorm-vs-sqlalchemy/)

---

## 3. Partage du Code entre CLI et Web

### Recommandation : Pattern Service Layer + Dependency Injection

**Niveau de confiance : ELEVE (90%)**

#### Pattern recommande

```python
# domain/services/scanner_service.py
class ScannerService:
    def __init__(self, media_repo: MediaRepository, identifier: MediaIdentifier):
        self.media_repo = media_repo
        self.identifier = identifier

    async def scan_directory(self, path: Path) -> list[Media]:
        """Logique metier pure, utilisable partout"""
        # ...

# adapters/cli/commands/scan.py
@app.command()
def scan(path: Path):
    """CLI utilise le service"""
    service = get_scanner_service()  # DI
    asyncio.run(service.scan_directory(path))

# adapters/api/routes/scan.py
@router.post("/scan")
async def scan(path: Path, service: ScannerService = Depends(get_scanner_service)):
    """API utilise le meme service"""
    return await service.scan_directory(path)
```

#### Options de Dependency Injection

| Outil | Usage | Recommandation |
|-------|-------|----------------|
| **FastAPI Depends** | API uniquement | UTILISER pour les routes |
| **dependency-injector** | Cross-framework | CONSIDERER pour apps complexes |
| **punq** | Leger, IoC complet | BON pour liaison CLI/API |
| **Manuel (factory)** | Simple | OK pour commencer |

#### FastAPI Injectable (nouveau)

Pour utiliser le DI de FastAPI en dehors des routes (CLI, background tasks) :

```bash
pip install fastapi-injectable
```

#### Sources
- [Mastering Dependency Injection in FastAPI](https://medium.com/@azizmarzouki/mastering-dependency-injection-in-fastapi-clean-scalable-and-testable-apis-5f78099c3362)
- [Dependency Injector Documentation](https://python-dependency-injector.ets-labs.org/examples/fastapi.html)
- [FastAPI Injectable](https://github.com/jaspersui/fastapi-injectable)

---

## 4. Rate Limiting pour APIs Externes (TMDB/TVDB)

### Recommandation : Combinaison aiolimiter + tenacity

**Niveau de confiance : ELEVE (85%)**

#### TMDB Rate Limits actuels
- ~50 requetes/seconde (CDN limit)
- ~20 connexions simultanees par IP
- Pas de limite quotidienne explicite

#### Stack recommande

```bash
pip install aiolimiter tenacity httpx
```

| Librairie | Role | Version |
|-----------|------|---------|
| **aiolimiter** | Rate limiting async (leaky bucket) | 1.2.1+ |
| **tenacity** | Retry avec backoff exponentiel | 9.0+ |
| **httpx** | Client HTTP async moderne | 0.28+ |

#### Implementation recommandee

```python
from aiolimiter import AsyncLimiter
from tenacity import retry, wait_exponential, stop_after_attempt
import httpx

# 40 requetes par seconde (marge de securite)
tmdb_limiter = AsyncLimiter(40, 1)

class TMDBClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            base_url="https://api.themoviedb.org/3",
            limits=httpx.Limits(max_connections=15)  # Sous la limite de 20
        )

    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=60),
        stop=stop_after_attempt(5)
    )
    async def search_movie(self, title: str, year: int | None = None):
        async with tmdb_limiter:
            response = await self.client.get(
                "/search/movie",
                params={"query": title, "year": year, "api_key": self.api_key}
            )
            response.raise_for_status()
            return response.json()
```

#### Alternatives considerees

| Librairie | Verdict |
|-----------|---------|
| **pyrate-limiter** | Bon mais plus complexe |
| **ratelimit** | Sync only, pas adapte |
| **limits** | Bon pour Redis-backed limiting |

#### Sources
- [TMDB Rate Limiting Documentation](https://developer.themoviedb.org/docs/rate-limiting)
- [aiolimiter Documentation](https://aiolimiter.readthedocs.io/)
- [OpenAI Cookbook - Rate Limits](https://cookbook.openai.com/examples/how_to_handle_rate_limits)

---

## 5. Fuzzy Matching de Titres

### Recommandation Principale : RapidFuzz

**Niveau de confiance : TRES ELEVE (95%)**

```bash
pip install rapidfuzz
```

| Critere | RapidFuzz | TheFuzz (fuzzywuzzy) | difflib |
|---------|-----------|----------------------|---------|
| Performance | Tres rapide (C++) | Lent | Tres lent |
| License | MIT | GPL | Python |
| Maintenance | Active | Maintenance | Standard lib |
| Fonctionnalites | Complete | Complete | Basique |

#### Pourquoi RapidFuzz ?

1. **Performance** : 10-100x plus rapide que TheFuzz
2. **License MIT** : Pas de contrainte GPL
3. **API compatible** : Drop-in replacement pour fuzzywuzzy
4. **Algorithmes multiples** : Levenshtein, Jaro-Winkler, etc.

#### Implementation pour titres de films

```python
from rapidfuzz import fuzz, process

def find_best_match(query: str, candidates: list[str], threshold: int = 80) -> str | None:
    """Trouve le meilleur match pour un titre de film."""

    # token_set_ratio est ideal pour les titres avec mots dans un ordre different
    # Ex: "The Dark Knight" vs "Dark Knight, The"
    result = process.extractOne(
        query,
        candidates,
        scorer=fuzz.token_set_ratio,
        score_cutoff=threshold
    )

    return result[0] if result else None

# Pour les recherches TMDB avec resultats multiples
def rank_matches(query: str, results: list[dict], key: str = "title") -> list[dict]:
    """Classe les resultats TMDB par similarite."""
    scored = [
        (r, fuzz.token_set_ratio(query.lower(), r[key].lower()))
        for r in results
    ]
    return [r for r, score in sorted(scored, key=lambda x: -x[1])]
```

#### Methodes de scoring recommandees

| Methode | Usage |
|---------|-------|
| `fuzz.ratio` | Comparaison exacte |
| `fuzz.partial_ratio` | Sous-chaines (utile pour titres tronques) |
| `fuzz.token_sort_ratio` | Ignore l'ordre des mots |
| `fuzz.token_set_ratio` | **RECOMMANDE** - Ignore ordre + doublons |

#### CE QU'IL NE FAUT PAS UTILISER

| Librairie | Raison |
|-----------|--------|
| **fuzzywuzzy** | Remplace par RapidFuzz (plus rapide, MIT) |
| **TheFuzz** | Meme probleme, GPL license |
| **jellyfish** | Moins de fonctionnalites |
| **difflib.SequenceMatcher** | Trop lent pour usage intensif |

#### Sources
- [RapidFuzz GitHub](https://github.com/rapidfuzz/RapidFuzz)
- [Fuzzy String Matching in Python - Typesense](https://typesense.org/learn/fuzzy-string-matching-python/)
- [Best Libraries for Fuzzy Matching in Python](https://medium.com/codex/best-libraries-for-fuzzy-matching-in-python-cbb3e0ef87dd)

---

## 6. Stack Complet Recommande

### Versions Specifiques (Janvier 2026)

```toml
[project]
requires-python = ">=3.11"

[project.dependencies]
# Web Framework
fastapi = ">=0.115.0"
uvicorn = { version = ">=0.32.0", extras = ["standard"] }

# CLI
typer = { version = ">=0.15.0", extras = ["all"] }

# ORM & Database
sqlmodel = ">=0.0.24"
alembic = ">=1.14.0"            # Migrations

# Media Parsing
guessit = ">=3.8.0"             # Parsing de noms de fichiers
pymediainfo = ">=6.1.0"         # Metadata techniques

# API Clients
httpx = ">=0.28.0"              # Client HTTP async
aiolimiter = ">=1.2.0"          # Rate limiting
tenacity = ">=9.0.0"            # Retry logic

# Fuzzy Matching
rapidfuzz = ">=3.10.0"

# Validation & Settings
pydantic = ">=2.10.0"
pydantic-settings = ">=2.6.0"

# Utilities
python-dotenv = ">=1.0.0"
rich = ">=13.9.0"               # Output CLI formatte
```

### Outils de developpement

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=6.0.0",
    "ruff>=0.8.0",              # Linting + formatting
    "mypy>=1.13.0",
    "pre-commit>=4.0.0",
]
```

---

## 7. Ce qu'il NE FAUT PAS Utiliser

| Technologie | Raison | Alternative |
|-------------|--------|-------------|
| **Flask** | Moins de typage, pas d'async natif | FastAPI |
| **Click** (seul) | Moins de typage que Typer | Typer (base sur Click) |
| **requests** | Sync only | httpx |
| **fuzzywuzzy** | GPL, lent | RapidFuzz |
| **Django** | Trop lourd pour ce projet | FastAPI + SQLModel |
| **aiohttp** | httpx est plus moderne | httpx |
| **peewee** | Moins de support async | SQLModel |
| **time.sleep** pour rate limiting | Bloquant | aiolimiter |

---

## 8. Resume des Niveaux de Confiance

| Recommandation | Confiance | Maturite | Risque |
|----------------|-----------|----------|--------|
| Architecture hexagonale | 95% | Pattern etabli | Faible |
| SQLModel | 90% | En evolution | Faible-Moyen |
| RapidFuzz | 95% | Stable | Tres faible |
| aiolimiter + tenacity | 85% | Stable | Faible |
| FastAPI + Typer | 95% | Tres mature | Tres faible |
| guessit | 90% | Stable | Faible |

---

## 9. Considerations Specifiques CineOrg

### Integration TMDB/TVDB

- Utiliser `append_to_response` de TMDB pour reduire les appels API
- Implementer un cache local (SQLite ou Redis) pour les metadonnees
- Considerer `aiocache` pour le caching async

### Gestion des fichiers

- Utiliser `pathlib.Path` exclusivement (pas `os.path`)
- Eviter `shutil.move` pour les symlinks, utiliser `Path.symlink_to`
- Considerer `watchdog` pour le monitoring de repertoires

### Performance

- Utiliser `asyncio.gather` pour les appels TMDB paralleles
- Implementer le batch processing pour les gros volumes
- Considerer `aiofiles` pour I/O fichiers async

---

*Document genere automatiquement - A mettre a jour regulierement*
