# Architecture CineOrg - Recherche et Recommandations

> Document de recherche sur les patterns d'architecture pour une application Python avec CLI + Web partageant un coeur metier.

## Table des matieres

1. [Resume executif](#resume-executif)
2. [Patterns d'architecture recommandes](#patterns-darchitecture-recommandes)
3. [Structure de repertoires](#structure-de-repertoires)
4. [Injection de dependances](#injection-de-dependances)
5. [Gestion des workflows async](#gestion-des-workflows-async)
6. [Flux de donnees](#flux-de-donnees)
7. [Ordre de build suggere](#ordre-de-build-suggere)
8. [Sources](#sources)

---

## Resume executif

Pour CineOrg, l'architecture **Hexagonale (Ports & Adapters)** combinee avec une **couche de services** est la solution optimale. Elle permet :

- **Separation stricte** : Le coeur metier ne connait ni FastAPI ni Typer
- **Reutilisation** : CLI et Web utilisent les memes services
- **Testabilite** : Le domaine peut etre teste sans infrastructure
- **Evolutivite** : Changer de framework ou de base de donnees sans toucher au coeur

### Principe fondamental

> "La logique metier ne doit jamais dependre de l'infrastructure."
> -- Robert C. Martin, Clean Architecture

---

## Patterns d'architecture recommandes

### 1. Architecture Hexagonale (Ports & Adapters)

L'application est divisee en trois zones concentriques :

```
┌─────────────────────────────────────────────────────────────┐
│                    ADAPTERS (Infrastructure)                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  CLI/Typer  │  │ Web/FastAPI │  │  Background Tasks   │  │
│  │  (Primary)  │  │  (Primary)  │  │     (Primary)       │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         │                │                     │             │
│  ┌──────▼────────────────▼─────────────────────▼──────┐     │
│  │                      PORTS                          │     │
│  │              (Interfaces/Abstractions)              │     │
│  └──────────────────────┬──────────────────────────────┘     │
│                         │                                    │
│  ┌──────────────────────▼──────────────────────────────┐     │
│  │              APPLICATION SERVICES                    │     │
│  │                  (Use Cases)                         │     │
│  └──────────────────────┬──────────────────────────────┘     │
│                         │                                    │
│  ┌──────────────────────▼──────────────────────────────┐     │
│  │                    DOMAIN                            │     │
│  │          (Entites, Value Objects, Regles)           │     │
│  └─────────────────────────────────────────────────────┘     │
│                         ▲                                    │
│  ┌──────────────────────┴──────────────────────────────┐     │
│  │              SECONDARY ADAPTERS                      │     │
│  │  ┌──────────┐  ┌──────────┐  ┌────────────────────┐ │     │
│  │  │ Database │  │ TMDb API │  │ File System Scanner│ │     │
│  │  │ SQLite   │  │ Client   │  │                    │ │     │
│  │  └──────────┘  └──────────┘  └────────────────────┘ │     │
│  └─────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

### 2. Types de Ports

#### Ports Primaires (Entree)
Les points d'entree qui exposent les fonctionnalites du domaine :

```python
# cine_org/application/ports/input_ports.py
from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID

class VideoLibraryService(ABC):
    """Port primaire pour la gestion de bibliotheque video."""

    @abstractmethod
    async def scan_directory(self, path: str) -> ScanResult:
        """Lance un scan de repertoire."""
        pass

    @abstractmethod
    async def get_video(self, video_id: UUID) -> Optional[Video]:
        """Recupere un video par son ID."""
        pass

    @abstractmethod
    async def search_videos(self, query: str) -> List[Video]:
        """Recherche des videos."""
        pass

    @abstractmethod
    async def enrich_metadata(self, video_id: UUID) -> Video:
        """Enrichit les metadonnees via TMDb."""
        pass
```

#### Ports Secondaires (Sortie)
Les interfaces pour communiquer avec l'exterieur :

```python
# cine_org/application/ports/output_ports.py
from abc import ABC, abstractmethod

class VideoRepository(ABC):
    """Port secondaire pour la persistence des videos."""

    @abstractmethod
    async def save(self, video: Video) -> Video:
        pass

    @abstractmethod
    async def get_by_id(self, video_id: UUID) -> Optional[Video]:
        pass

    @abstractmethod
    async def find_by_path(self, path: str) -> Optional[Video]:
        pass

    @abstractmethod
    async def search(self, query: str) -> List[Video]:
        pass


class MetadataProvider(ABC):
    """Port secondaire pour les APIs de metadonnees."""

    @abstractmethod
    async def search_movie(self, title: str, year: Optional[int] = None) -> List[MovieMatch]:
        pass

    @abstractmethod
    async def get_movie_details(self, external_id: str) -> MovieDetails:
        pass


class FileScanner(ABC):
    """Port secondaire pour le scan de fichiers."""

    @abstractmethod
    async def scan(self, path: str) -> AsyncIterator[ScannedFile]:
        pass

    @abstractmethod
    def supports_extension(self, ext: str) -> bool:
        pass
```

### 3. Couche de Services (Use Cases)

Les services implementent la logique metier en orchestrant les ports :

```python
# cine_org/application/services/library_service.py
from cine_org.application.ports.output_ports import (
    VideoRepository, MetadataProvider, FileScanner
)
from cine_org.domain.entities import Video
from cine_org.domain.value_objects import FilePath

class LibraryServiceImpl(VideoLibraryService):
    """Implementation du service de bibliotheque."""

    def __init__(
        self,
        video_repository: VideoRepository,
        metadata_provider: MetadataProvider,
        file_scanner: FileScanner
    ):
        self._repo = video_repository
        self._metadata = metadata_provider
        self._scanner = file_scanner

    async def scan_directory(self, path: str) -> ScanResult:
        """Scan un repertoire et ajoute les videos trouvees."""
        added = 0
        skipped = 0
        errors = []

        async for scanned_file in self._scanner.scan(path):
            try:
                # Verifier si deja en base
                existing = await self._repo.find_by_path(scanned_file.path)
                if existing:
                    skipped += 1
                    continue

                # Creer l'entite Video
                video = Video.from_scanned_file(scanned_file)
                await self._repo.save(video)
                added += 1

            except Exception as e:
                errors.append(ScanError(path=scanned_file.path, error=str(e)))

        return ScanResult(added=added, skipped=skipped, errors=errors)

    async def enrich_metadata(self, video_id: UUID) -> Video:
        """Enrichit un video avec les metadonnees TMDb."""
        video = await self._repo.get_by_id(video_id)
        if not video:
            raise VideoNotFoundError(video_id)

        # Rechercher sur TMDb
        matches = await self._metadata.search_movie(
            title=video.parsed_title,
            year=video.parsed_year
        )

        if matches:
            best_match = matches[0]  # Logique de selection
            details = await self._metadata.get_movie_details(best_match.id)
            video.apply_metadata(details)
            await self._repo.save(video)

        return video
```

---

## Structure de repertoires

### Structure recommandee pour CineOrg

```
cine_org/
├── pyproject.toml
├── README.md
│
├── src/
│   └── cine_org/
│       │
│       ├── __init__.py
│       ├── __main__.py              # Point d'entree CLI
│       │
│       ├── domain/                   # COUCHE DOMAINE (pur Python)
│       │   ├── __init__.py
│       │   ├── entities/
│       │   │   ├── __init__.py
│       │   │   ├── video.py          # Entite Video
│       │   │   ├── collection.py     # Entite Collection
│       │   │   └── scan_job.py       # Entite ScanJob
│       │   ├── value_objects/
│       │   │   ├── __init__.py
│       │   │   ├── file_path.py
│       │   │   ├── video_metadata.py
│       │   │   └── resolution.py
│       │   ├── events/
│       │   │   ├── __init__.py
│       │   │   ├── video_added.py
│       │   │   └── scan_completed.py
│       │   └── exceptions.py         # Exceptions domaine
│       │
│       ├── application/              # COUCHE APPLICATION
│       │   ├── __init__.py
│       │   ├── ports/
│       │   │   ├── __init__.py
│       │   │   ├── input_ports.py    # Interfaces de services
│       │   │   └── output_ports.py   # Interfaces d'adapters
│       │   ├── services/
│       │   │   ├── __init__.py
│       │   │   ├── library_service.py
│       │   │   ├── scan_service.py
│       │   │   └── metadata_service.py
│       │   ├── dto/
│       │   │   ├── __init__.py
│       │   │   ├── video_dto.py
│       │   │   └── scan_dto.py
│       │   └── use_cases/            # Use cases specifiques
│       │       ├── __init__.py
│       │       ├── scan_directory.py
│       │       └── enrich_video.py
│       │
│       ├── infrastructure/           # COUCHE INFRASTRUCTURE
│       │   ├── __init__.py
│       │   ├── persistence/
│       │   │   ├── __init__.py
│       │   │   ├── database.py       # Config SQLAlchemy
│       │   │   ├── models/           # Modeles ORM
│       │   │   │   ├── __init__.py
│       │   │   │   └── video_model.py
│       │   │   └── repositories/     # Implementations
│       │   │       ├── __init__.py
│       │   │       ├── video_repository.py
│       │   │       └── collection_repository.py
│       │   ├── external/
│       │   │   ├── __init__.py
│       │   │   ├── tmdb_client.py    # Client API TMDb
│       │   │   └── omdb_client.py    # Client API OMDb (fallback)
│       │   ├── file_system/
│       │   │   ├── __init__.py
│       │   │   ├── scanner.py        # Scan de fichiers
│       │   │   └── parser.py         # Parsing noms de fichiers
│       │   └── config/
│       │       ├── __init__.py
│       │       └── settings.py       # Configuration Pydantic
│       │
│       ├── adapters/                 # ADAPTERS PRIMAIRES
│       │   ├── __init__.py
│       │   ├── cli/                  # Interface CLI (Typer)
│       │   │   ├── __init__.py
│       │   │   ├── app.py            # Application Typer
│       │   │   ├── commands/
│       │   │   │   ├── __init__.py
│       │   │   │   ├── scan.py
│       │   │   │   ├── search.py
│       │   │   │   └── config.py
│       │   │   └── formatters/       # Formatage output CLI
│       │   │       ├── __init__.py
│       │   │       └── table.py
│       │   └── web/                  # Interface Web (FastAPI)
│       │       ├── __init__.py
│       │       ├── app.py            # Application FastAPI
│       │       ├── routes/
│       │       │   ├── __init__.py
│       │       │   ├── videos.py
│       │   │   │   ├── collections.py
│       │   │   │   └── scan.py
│       │       ├── schemas/          # Schemas Pydantic API
│       │       │   ├── __init__.py
│       │       │   └── video_schemas.py
│       │       └── dependencies.py   # DI FastAPI
│       │
│       └── bootstrap/                # ASSEMBLAGE
│           ├── __init__.py
│           ├── container.py          # Container DI
│           └── factories.py          # Factories de services
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   │   ├── domain/
│   │   └── application/
│   ├── integration/
│   │   ├── infrastructure/
│   │   └── adapters/
│   └── e2e/
│       ├── cli/
│       └── web/
│
└── config/
    ├── config.yaml
    └── config.dev.yaml
```

### Explications des couches

| Couche | Responsabilite | Dependances |
|--------|---------------|-------------|
| **Domain** | Entites, regles metier, value objects | Aucune (pur Python) |
| **Application** | Use cases, orchestration, ports | Domain uniquement |
| **Infrastructure** | Implementations concretes (DB, APIs) | Application + librairies |
| **Adapters** | Points d'entree (CLI, Web) | Application + frameworks |
| **Bootstrap** | Assemblage, injection de dependances | Toutes les couches |

---

## Injection de dependances

### Option 1 : Container manuel (recommande pour demarrer)

```python
# cine_org/bootstrap/container.py
from dataclasses import dataclass
from cine_org.application.ports.output_ports import (
    VideoRepository, MetadataProvider, FileScanner
)
from cine_org.application.services.library_service import LibraryServiceImpl
from cine_org.infrastructure.persistence.repositories import SQLAlchemyVideoRepository
from cine_org.infrastructure.external.tmdb_client import TMDbClient
from cine_org.infrastructure.file_system.scanner import AsyncFileScanner


@dataclass
class Container:
    """Container d'injection de dependances."""

    video_repository: VideoRepository
    metadata_provider: MetadataProvider
    file_scanner: FileScanner
    library_service: LibraryServiceImpl

    @classmethod
    def create(cls, settings: Settings) -> "Container":
        """Factory pour creer le container avec toutes les dependances."""

        # Infrastructure
        video_repo = SQLAlchemyVideoRepository(settings.database_url)
        tmdb_client = TMDbClient(api_key=settings.tmdb_api_key)
        scanner = AsyncFileScanner(
            extensions=settings.video_extensions
        )

        # Services
        library_service = LibraryServiceImpl(
            video_repository=video_repo,
            metadata_provider=tmdb_client,
            file_scanner=scanner
        )

        return cls(
            video_repository=video_repo,
            metadata_provider=tmdb_client,
            file_scanner=scanner,
            library_service=library_service
        )
```

### Option 2 : dependency-injector (pour projets plus grands)

```python
# cine_org/bootstrap/container.py
from dependency_injector import containers, providers
from cine_org.infrastructure.persistence.repositories import SQLAlchemyVideoRepository
from cine_org.infrastructure.external.tmdb_client import TMDbClient
from cine_org.application.services.library_service import LibraryServiceImpl


class Container(containers.DeclarativeContainer):
    """Container declaratif avec dependency-injector."""

    wiring_config = containers.WiringConfiguration(
        modules=[
            "cine_org.adapters.cli.commands",
            "cine_org.adapters.web.routes",
        ]
    )

    # Configuration
    config = providers.Configuration()

    # Infrastructure
    video_repository = providers.Singleton(
        SQLAlchemyVideoRepository,
        database_url=config.database.url
    )

    tmdb_client = providers.Singleton(
        TMDbClient,
        api_key=config.tmdb.api_key
    )

    file_scanner = providers.Factory(
        AsyncFileScanner,
        extensions=config.scan.video_extensions
    )

    # Services
    library_service = providers.Factory(
        LibraryServiceImpl,
        video_repository=video_repository,
        metadata_provider=tmdb_client,
        file_scanner=file_scanner
    )
```

### Utilisation dans CLI (Typer)

```python
# cine_org/adapters/cli/commands/scan.py
import typer
from cine_org.bootstrap.container import Container

app = typer.Typer()

def get_container() -> Container:
    """Recupere ou cree le container."""
    from cine_org.infrastructure.config.settings import get_settings
    settings = get_settings()
    return Container.create(settings)


@app.command()
def scan(
    path: str = typer.Argument(..., help="Repertoire a scanner"),
    recursive: bool = typer.Option(True, help="Scanner recursivement")
):
    """Scanne un repertoire pour trouver des videos."""
    import asyncio

    container = get_container()

    async def run_scan():
        result = await container.library_service.scan_directory(path)
        typer.echo(f"Videos ajoutees: {result.added}")
        typer.echo(f"Videos ignorees: {result.skipped}")
        if result.errors:
            typer.echo(f"Erreurs: {len(result.errors)}")

    asyncio.run(run_scan())
```

### Utilisation dans Web (FastAPI)

```python
# cine_org/adapters/web/dependencies.py
from functools import lru_cache
from fastapi import Depends
from cine_org.bootstrap.container import Container
from cine_org.infrastructure.config.settings import Settings, get_settings


@lru_cache()
def get_container(settings: Settings = Depends(get_settings)) -> Container:
    """Singleton du container pour FastAPI."""
    return Container.create(settings)


def get_library_service(
    container: Container = Depends(get_container)
) -> LibraryServiceImpl:
    """Injecte le service de bibliotheque."""
    return container.library_service


# cine_org/adapters/web/routes/videos.py
from fastapi import APIRouter, Depends
from cine_org.adapters.web.dependencies import get_library_service

router = APIRouter(prefix="/videos", tags=["videos"])


@router.get("/{video_id}")
async def get_video(
    video_id: UUID,
    service: LibraryServiceImpl = Depends(get_library_service)
):
    """Recupere un video par son ID."""
    video = await service.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404)
    return VideoResponse.from_domain(video)


@router.post("/scan")
async def start_scan(
    request: ScanRequest,
    service: LibraryServiceImpl = Depends(get_library_service)
):
    """Demarre un scan de repertoire."""
    result = await service.scan_directory(request.path)
    return ScanResponse(
        added=result.added,
        skipped=result.skipped,
        errors=len(result.errors)
    )
```

---

## Gestion des workflows async

### Pattern pour le scan de fichiers

```python
# cine_org/infrastructure/file_system/scanner.py
import asyncio
from pathlib import Path
from typing import AsyncIterator
from cine_org.application.ports.output_ports import FileScanner
from cine_org.domain.value_objects import ScannedFile


class AsyncFileScanner(FileScanner):
    """Scanner de fichiers asynchrone."""

    def __init__(self, extensions: list[str]):
        self._extensions = set(extensions)

    def supports_extension(self, ext: str) -> bool:
        return ext.lower() in self._extensions

    async def scan(self, path: str) -> AsyncIterator[ScannedFile]:
        """Scan async avec yield pour ne pas bloquer."""
        root = Path(path)

        # Utiliser run_in_executor pour les I/O fichiers
        loop = asyncio.get_event_loop()
        files = await loop.run_in_executor(
            None,
            lambda: list(root.rglob("*"))
        )

        for file_path in files:
            if file_path.is_file() and self.supports_extension(file_path.suffix):
                # Yield pour traitement progressif
                yield ScannedFile(
                    path=str(file_path),
                    size=file_path.stat().st_size,
                    modified=file_path.stat().st_mtime
                )
                # Permettre a d'autres taches de s'executer
                await asyncio.sleep(0)
```

### Pattern pour les appels API (TMDb)

```python
# cine_org/infrastructure/external/tmdb_client.py
import httpx
from typing import Optional
from cine_org.application.ports.output_ports import MetadataProvider


class TMDbClient(MetadataProvider):
    """Client async pour l'API TMDb."""

    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self, api_key: str, timeout: float = 30.0):
        self._api_key = api_key
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=self._timeout,
                params={"api_key": self._api_key}
            )
        return self._client

    async def search_movie(
        self,
        title: str,
        year: Optional[int] = None
    ) -> list[MovieMatch]:
        """Recherche un film sur TMDb."""
        client = await self._get_client()

        params = {"query": title}
        if year:
            params["year"] = year

        response = await client.get("/search/movie", params=params)
        response.raise_for_status()

        data = response.json()
        return [
            MovieMatch(
                id=r["id"],
                title=r["title"],
                release_date=r.get("release_date"),
                overview=r.get("overview")
            )
            for r in data.get("results", [])
        ]

    async def close(self):
        """Ferme le client HTTP."""
        if self._client:
            await self._client.aclose()
```

### Background Tasks pour operations longues

```python
# cine_org/application/services/scan_service.py
from enum import Enum
from uuid import UUID, uuid4
import asyncio


class ScanStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ScanJobService:
    """Service pour gerer les jobs de scan en arriere-plan."""

    def __init__(self, library_service: LibraryServiceImpl):
        self._library = library_service
        self._jobs: dict[UUID, ScanJob] = {}

    async def start_scan(self, path: str) -> ScanJob:
        """Demarre un scan en arriere-plan."""
        job_id = uuid4()
        job = ScanJob(id=job_id, path=path, status=ScanStatus.PENDING)
        self._jobs[job_id] = job

        # Lancer en arriere-plan
        asyncio.create_task(self._run_scan(job))

        return job

    async def _run_scan(self, job: ScanJob):
        """Execute le scan en arriere-plan."""
        job.status = ScanStatus.RUNNING

        try:
            result = await self._library.scan_directory(job.path)
            job.result = result
            job.status = ScanStatus.COMPLETED
        except Exception as e:
            job.error = str(e)
            job.status = ScanStatus.FAILED

    def get_job(self, job_id: UUID) -> Optional[ScanJob]:
        """Recupere le statut d'un job."""
        return self._jobs.get(job_id)
```

### Integration avec FastAPI BackgroundTasks

```python
# cine_org/adapters/web/routes/scan.py
from fastapi import APIRouter, BackgroundTasks, Depends

router = APIRouter(prefix="/scan", tags=["scan"])


@router.post("/async")
async def start_async_scan(
    request: ScanRequest,
    background_tasks: BackgroundTasks,
    service: ScanJobService = Depends(get_scan_service)
):
    """Demarre un scan asynchrone."""
    job = await service.start_scan(request.path)
    return {"job_id": str(job.id), "status": job.status.value}


@router.get("/{job_id}")
async def get_scan_status(
    job_id: UUID,
    service: ScanJobService = Depends(get_scan_service)
):
    """Recupere le statut d'un scan."""
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404)
    return ScanJobResponse.from_domain(job)
```

---

## Flux de donnees

### Flux typique : Scan de repertoire

```
┌─────────┐     ┌──────────────┐     ┌────────────────┐     ┌──────────────┐
│   CLI   │────>│ LibraryService│────>│  FileScanner   │────>│ File System  │
│ scan /x │     │ scan_directory│     │  (async gen)   │     │              │
└─────────┘     └───────┬──────┘     └────────────────┘     └──────────────┘
                        │
                        │ Pour chaque fichier
                        ▼
                ┌───────────────┐
                │    Domain     │
                │ Video.from_   │
                │ scanned_file  │
                └───────┬───────┘
                        │
                        ▼
                ┌───────────────┐     ┌──────────────┐
                │VideoRepository│────>│   Database   │
                │    .save()    │     │   (SQLite)   │
                └───────────────┘     └──────────────┘
```

### Flux typique : Enrichissement metadonnees

```
┌─────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   API   │────>│MetadataService│────>│VideoRepository│────>│   Database   │
│ PATCH   │     │ enrich_video │     │  .get_by_id  │     │              │
│/videos/1│     └───────┬──────┘     └──────────────┘     └──────────────┘
└─────────┘             │
                        │ Video trouve
                        ▼
                ┌───────────────┐     ┌──────────────┐
                │  TMDbClient   │────>│   TMDb API   │
                │ search_movie  │     │              │
                └───────┬───────┘     └──────────────┘
                        │
                        │ Resultats
                        ▼
                ┌───────────────┐
                │    Domain     │
                │ Video.apply_  │
                │   metadata    │
                └───────┬───────┘
                        │
                        ▼
                ┌───────────────┐     ┌──────────────┐
                │VideoRepository│────>│   Database   │
                │    .save()    │     │              │
                └───────────────┘     └──────────────┘
```

---

## Ordre de build suggere

### Phase 1 : Fondations (Semaine 1)

```
1.1 Domain Layer
    ├── Entites: Video, Collection
    ├── Value Objects: FilePath, VideoMetadata
    └── Exceptions domaine

1.2 Application Ports
    ├── VideoRepository (interface)
    ├── MetadataProvider (interface)
    └── FileScanner (interface)

1.3 Configuration
    ├── Settings Pydantic
    └── Config loader
```

**Livrables** : Domaine testable independamment, interfaces definies

### Phase 2 : Infrastructure (Semaine 2)

```
2.1 Persistence
    ├── SQLAlchemy models
    ├── VideoRepository implementation
    └── Migrations Alembic

2.2 File System
    ├── AsyncFileScanner
    └── Filename parser

2.3 External APIs
    └── TMDbClient (mock pour tests)
```

**Livrables** : Infrastructure testable avec mocks

### Phase 3 : Services (Semaine 3)

```
3.1 Application Services
    ├── LibraryService
    ├── ScanService
    └── MetadataService

3.2 Container DI
    ├── Container manuel
    └── Factories
```

**Livrables** : Logique metier complete, testee unitairement

### Phase 4 : Adapters (Semaine 4)

```
4.1 CLI Adapter
    ├── Commande scan
    ├── Commande search
    └── Commande config

4.2 Web Adapter
    ├── Routes videos
    ├── Routes scan
    └── Routes collections
```

**Livrables** : Application utilisable via CLI et API

### Phase 5 : Polish (Semaine 5)

```
5.1 Tests E2E
5.2 Documentation API (OpenAPI)
5.3 Logging et monitoring
5.4 CI/CD
```

### Graphe de dependances

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  Phase 1: Domain + Ports + Config                          │
│     │                                                       │
│     ▼                                                       │
│  Phase 2: Infrastructure (Repository, Scanner, TMDb)       │
│     │                                                       │
│     ▼                                                       │
│  Phase 3: Services + Container DI                          │
│     │                                                       │
│     ├─────────────────┬─────────────────┐                   │
│     ▼                 ▼                 ▼                   │
│  Phase 4a: CLI    Phase 4b: Web    Phase 4c: Background    │
│     │                 │                 │                   │
│     └─────────────────┴─────────────────┘                   │
│                       │                                     │
│                       ▼                                     │
│                 Phase 5: Polish                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Sources

### Articles et tutoriels

- [Building Maintainable Python Applications with Hexagonal Architecture and Domain-Driven Design](https://dev.to/hieutran25/building-maintainable-python-applications-with-hexagonal-architecture-and-domain-driven-design-chp)
- [Python Design Patterns for Clean Architecture](https://www.glukhov.org/post/2025/11/python-design-patterns-for-clean-architecture/)
- [Hexagonal Architecture in Python](https://blog.szymonmiks.pl/p/hexagonal-architecture-in-python/)
- [Layered Architecture & Dependency Injection: A Recipe for Clean and Testable FastAPI Code](https://dev.to/markoulis/layered-architecture-dependency-injection-a-recipe-for-clean-and-testable-fastapi-code-3ioo)
- [Python Design Patterns: Service Layer + Repository + Specification](https://craftedstack.com/blog/python/design-patterns-repository-service-layer-specification/)
- [Python Background Task Processing in 2025](https://danielsarney.com/blog/python-background-task-processing-2025-handling-asynchronous-work-modern-applications/)

### Documentation officielle

- [FastAPI Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/)
- [FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [Dependency Injector - FastAPI Example](https://python-dependency-injector.ets-labs.org/examples/fastapi.html)
- [AWS - Structure a Python project in hexagonal architecture](https://docs.aws.amazon.com/prescriptive-guidance/latest/patterns/structure-a-python-project-in-hexagonal-architecture-using-aws-lambda.html)

### Repositories GitHub

- [hexagonal-architecture-with-python](https://github.com/marcosvs98/hexagonal-architecture-with-python) - FastAPI avec Ports & Adapters
- [py-clean-arch](https://github.com/cdddg/py-clean-arch) - Clean Architecture complete
- [python-clean-architecture](https://github.com/pcah/python-clean-architecture) - Toolkit pour Clean Architecture
- [ports-adapters-sample](https://github.com/LucasRGoes/ports-adapters-sample) - Microservice avec Ports & Adapters

---

## Resume des recommandations pour CineOrg

| Aspect | Recommandation |
|--------|---------------|
| **Architecture** | Hexagonal (Ports & Adapters) |
| **Injection de dependances** | Container manuel au debut, puis `dependency-injector` si besoin |
| **CLI** | Typer avec acces direct au container |
| **Web** | FastAPI avec `Depends()` pour injection |
| **Base de donnees** | SQLAlchemy async + SQLite (dev) / PostgreSQL (prod) |
| **API externe** | httpx async pour TMDb |
| **Background tasks** | FastAPI BackgroundTasks + asyncio.create_task |
| **Tests** | Pytest avec repositories in-memory |

Cette architecture garantit que le coeur metier reste identique que l'on utilise la CLI ou l'API Web.
