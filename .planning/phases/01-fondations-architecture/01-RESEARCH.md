# Phase 1: Fondations Architecture - Research

**Researched:** 2026-01-26
**Domain:** Hexagonal Architecture, Dependency Injection, Configuration Management, Structured Logging
**Confidence:** HIGH

## Summary

This phase establishes the architectural foundation for CineOrg using hexagonal architecture (ports and adapters) to ensure clean separation between domain logic and infrastructure concerns. The research covers four key areas: directory structure following hexagonal patterns, dependency injection to share components between CLI and Web interfaces, configuration management with validation, and structured JSON logging with rotation.

The Python ecosystem offers mature solutions for all requirements. **pydantic-settings** (v2.12.0) provides type-safe configuration with env/file loading. **dependency-injector** (v4.48.3) offers a production-ready DI container with excellent FastAPI integration and Cython-optimized performance. **Loguru** (v0.7.3) simplifies structured logging with built-in rotation, while remaining compatible with the standard library for library code.

**Primary recommendation:** Use dependency-injector for DI (mature, well-documented, FastAPI-native), pydantic-settings for configuration (Pydantic v2 ecosystem consistency), and Loguru for logging (simpler than structlog, meets all rotation requirements).

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic-settings | 2.12.0 | Configuration management | FastAPI ecosystem standard, type-safe, env/file loading |
| dependency-injector | 4.48.3 | DI container | Mature (4+ years), Cython performance, FastAPI wiring |
| loguru | 0.7.3 | Structured logging | Built-in rotation/compression, zero-config start |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-dotenv | 1.x | .env file loading | Implicit via pydantic-settings |
| orjson | 3.x | Fast JSON serialization | Optional: if JSON logging performance is critical |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| dependency-injector | punq | Simpler/lighter but fewer features, no FastAPI wiring, less mature |
| dependency-injector | manual DI (bootstrap pattern) | No external dependency but more boilerplate, harder testing |
| loguru | structlog | Better for large teams/observability but steeper learning curve |
| loguru | stdlib logging | No extra dependency but much more configuration boilerplate |

**Installation:**
```bash
pip install pydantic-settings dependency-injector loguru
```

## Architecture Patterns

### Recommended Project Structure

Based on the decisions in CONTEXT.md (core/services/adapters naming):

```
src/
├── core/                    # Domain layer - business entities and ports
│   ├── __init__.py
│   ├── entities/            # Domain entities (dataclasses or SQLModel)
│   │   ├── __init__.py
│   │   ├── video.py         # Video, Movie, Episode entities
│   │   └── library.py       # Library, Collection entities
│   ├── ports/               # Abstract interfaces (ABCs)
│   │   ├── __init__.py
│   │   ├── repositories.py  # IVideoRepository, ILibraryRepository
│   │   ├── api_clients.py   # IMediaAPIClient (TMDB, TVDB)
│   │   ├── file_system.py   # IFileSystem, ISymlinkManager
│   │   └── notification.py  # INotificationService
│   └── value_objects/       # Immutable value objects
│       ├── __init__.py
│       └── media_info.py    # Resolution, Codec, etc.
├── services/                # Application layer - use cases
│   ├── __init__.py
│   ├── scanner.py           # ScanDownloadsUseCase
│   ├── matcher.py           # MatchMediaUseCase
│   ├── organizer.py         # OrganizeFilesUseCase
│   └── orchestrator.py      # WorkflowOrchestrator
├── adapters/                # Infrastructure layer - implementations
│   ├── __init__.py
│   ├── cli/                 # CLI adapter (Typer)
│   │   ├── __init__.py
│   │   └── commands.py
│   ├── web/                 # Web adapter (FastAPI)
│   │   ├── __init__.py
│   │   ├── app.py
│   │   └── routes/
│   ├── persistence/         # Database adapters
│   │   ├── __init__.py
│   │   ├── sqlmodel_repos.py
│   │   └── models.py        # SQLModel ORM models
│   ├── api/                 # External API adapters
│   │   ├── __init__.py
│   │   ├── tmdb.py
│   │   └── tvdb.py
│   └── filesystem/          # File system adapters
│       ├── __init__.py
│       └── local.py
├── container.py             # DI container definition
├── config.py                # Pydantic settings
├── logging_config.py        # Loguru configuration
└── main.py                  # CLI entry point
```

### Pattern 1: Ports as Abstract Base Classes

**What:** Define domain contracts using Python ABCs in `core/ports/`
**When to use:** Any external dependency the domain needs to interact with

```python
# Source: Cosmic Python book + hexagonal architecture best practices
# File: src/core/ports/repositories.py

from abc import ABC, abstractmethod
from typing import Optional, List
from ..entities.video import Video

class IVideoRepository(ABC):
    """Port for video persistence operations."""

    @abstractmethod
    def get_by_id(self, video_id: int) -> Optional[Video]:
        """Retrieve a video by its ID."""
        raise NotImplementedError

    @abstractmethod
    def save(self, video: Video) -> Video:
        """Persist a video entity."""
        raise NotImplementedError

    @abstractmethod
    def find_by_path(self, path: str) -> Optional[Video]:
        """Find a video by its file path."""
        raise NotImplementedError
```

### Pattern 2: DI Container with dependency-injector

**What:** Centralized container declaring all dependencies and their wiring
**When to use:** Application bootstrap, both CLI and Web entry points

```python
# Source: https://python-dependency-injector.ets-labs.org/
# File: src/container.py

from dependency_injector import containers, providers
from .config import Settings
from .core.ports.repositories import IVideoRepository
from .adapters.persistence.sqlmodel_repos import SQLModelVideoRepository
from .adapters.api.tmdb import TMDBClient
from .services.scanner import ScanDownloadsUseCase

class Container(containers.DeclarativeContainer):
    """Application DI container."""

    wiring_config = containers.WiringConfiguration(
        modules=[
            ".adapters.cli.commands",
            ".adapters.web.routes.videos",
        ]
    )

    # Configuration
    config = providers.Singleton(Settings)

    # Infrastructure - Repositories
    video_repository = providers.Singleton(
        SQLModelVideoRepository,
        database_url=config.provided.database_url,
    )

    # Infrastructure - API Clients (Factory for optional availability)
    tmdb_client = providers.Factory(
        TMDBClient,
        api_key=config.provided.tmdb_api_key,
    )

    # Services - Use Cases
    scan_downloads = providers.Factory(
        ScanDownloadsUseCase,
        video_repository=video_repository,
        config=config,
    )
```

### Pattern 3: Configuration with pydantic-settings

**What:** Type-safe configuration loading from env vars and files
**When to use:** Application settings with validation

```python
# Source: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
# File: src/config.py

from pathlib import Path
from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Application configuration."""

    model_config = SettingsConfigDict(
        env_prefix="CINEORG_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    # Paths
    downloads_dir: Path = Field(default=Path("~/Downloads"))
    storage_dir: Path = Field(default=Path("~/Videos/storage"))
    video_dir: Path = Field(default=Path("~/Videos/video"))

    # Database
    database_url: str = Field(default="sqlite:///cineorg.db")

    # API Keys (optional - features disabled if missing)
    tmdb_api_key: Optional[str] = Field(default=None)
    tvdb_api_key: Optional[str] = Field(default=None)

    # Processing
    min_file_size_mb: int = Field(default=100, ge=1)
    max_files_per_subdir: int = Field(default=50, ge=1)
    match_score_threshold: int = Field(default=85, ge=0, le=100)

    # Logging
    log_level: str = Field(default="INFO")
    log_file: Path = Field(default=Path("logs/cineorg.log"))
    log_rotation_size: str = Field(default="10 MB")
    log_retention_count: int = Field(default=5)

    @field_validator("downloads_dir", "storage_dir", "video_dir", mode="before")
    @classmethod
    def expand_path(cls, v):
        return Path(v).expanduser()
```

### Pattern 4: Structured Logging with Loguru

**What:** JSON logging with rotation to file + stderr
**When to use:** All application logging

```python
# Source: https://github.com/Delgan/loguru
# File: src/logging_config.py

import sys
from pathlib import Path
from loguru import logger

def configure_logging(
    log_level: str = "INFO",
    log_file: Path = Path("logs/cineorg.log"),
    rotation_size: str = "10 MB",
    retention_count: int = 5,
) -> None:
    """Configure application logging."""

    # Remove default handler
    logger.remove()

    # Console handler (stderr) - human-readable for real-time supervision
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
               "<level>{message}</level>",
        colorize=True,
    )

    # File handler - JSON for historical analysis
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_file,
        level="DEBUG",  # File captures all levels
        format="{message}",
        serialize=True,  # JSON output
        rotation=rotation_size,
        retention=retention_count,
        compression="zip",
        enqueue=True,  # Thread-safe
    )

    # API calls logged at DEBUG level
    logger.debug("Logging configured",
                 log_file=str(log_file),
                 rotation=rotation_size)
```

### Pattern 5: Bootstrap and Wiring

**What:** Application entry point that wires DI container
**When to use:** CLI and Web entry points

```python
# Source: dependency-injector docs + FastAPI integration
# File: src/main.py (CLI entry)

import typer
from dependency_injector.wiring import Provide, inject
from .container import Container
from .config import Settings
from .logging_config import configure_logging
from .services.scanner import ScanDownloadsUseCase

app = typer.Typer()
container = Container()

@app.command()
@inject
def scan(
    scanner: ScanDownloadsUseCase = Provide[Container.scan_downloads],
) -> None:
    """Scan downloads directory for new videos."""
    results = scanner.execute()
    typer.echo(f"Found {len(results)} new videos")

def main():
    # Initialize container
    container.wire(modules=[__name__])

    # Configure logging from settings
    settings = container.config()
    configure_logging(
        log_level=settings.log_level,
        log_file=settings.log_file,
        rotation_size=settings.log_rotation_size,
        retention_count=settings.log_retention_count,
    )

    # Run CLI
    app()

if __name__ == "__main__":
    main()
```

### Anti-Patterns to Avoid

- **Importing adapters in core:** Domain layer must never import from adapters. Ports define contracts, adapters implement them.
- **Global container instance:** Container should be created in entry point, not module-level global. Pass via wiring.
- **Configuration scattered across modules:** All config in one Settings class with pydantic validation.
- **Logging configuration in multiple places:** Single configure_logging() call at entry point.
- **Mixing sync/async in DI:** dependency-injector supports both; keep consistency per adapter.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Configuration loading | Custom env/file parser | pydantic-settings | Type validation, nested config, multiple sources |
| DI container | Dict of factories | dependency-injector | Lifecycle management, testing overrides, wiring |
| Log rotation | Custom file rotation | Loguru rotation= | Edge cases (crash during rotation, compression) |
| Log formatting | Custom JSON formatter | Loguru serialize=True | Structured tracebacks, consistent schema |
| Path validation | Manual Path checks | pydantic Path type | Automatic expansion, existence validation |

**Key insight:** Configuration and logging are "solved problems" - custom implementations waste time and introduce bugs that libraries have already fixed.

## Common Pitfalls

### Pitfall 1: Circular Import Between Layers
**What goes wrong:** `core/` imports from `adapters/`, breaking hexagonal architecture
**Why it happens:** Quick fix to access an adapter directly from domain code
**How to avoid:** Domain defines ports (ABCs), adapters implement them. Never import adapter from core.
**Warning signs:** ImportError cycles, "cannot import name" errors

### Pitfall 2: Optional API Keys Breaking Startup
**What goes wrong:** App crashes if TMDB/TVDB keys not set
**Why it happens:** Validation requires keys, but they should be optional
**How to avoid:** Use `Optional[str] = None` in Settings, check at runtime before API calls
**Warning signs:** ValidationError on startup without API keys

### Pitfall 3: Container Wiring Before Configuration
**What goes wrong:** DI container wired before logging/config initialized
**Why it happens:** Import-time side effects
**How to avoid:** Explicit initialization order in entry point: config -> logging -> container.wire()
**Warning signs:** Logs missing from startup, config defaults used instead of env values

### Pitfall 4: Sync Handlers in Async Context
**What goes wrong:** FastAPI routes blocking on sync operations
**Why it happens:** Mixing sync repository with async web framework
**How to avoid:** Use async adapters for web, sync for CLI, or run_in_executor for sync code in async
**Warning signs:** Slow API responses, thread pool exhaustion

### Pitfall 5: Log File Path Not Existing
**What goes wrong:** FileNotFoundError when logging starts
**Why it happens:** Log directory not created
**How to avoid:** `log_file.parent.mkdir(parents=True, exist_ok=True)` before logger.add()
**Warning signs:** Crash on first log statement

### Pitfall 6: Testing Without Container Overrides
**What goes wrong:** Tests hit real database/API
**Why it happens:** No override mechanism used
**How to avoid:** Use `container.provider.override(mock)` in test fixtures
**Warning signs:** Flaky tests, slow test suite, network errors in CI

## Code Examples

Verified patterns from official sources:

### Container Override for Testing
```python
# Source: https://python-dependency-injector.ets-labs.org/
# File: tests/conftest.py

import pytest
from unittest.mock import Mock
from src.container import Container
from src.core.ports.repositories import IVideoRepository

@pytest.fixture
def container():
    container = Container()
    yield container
    container.unwire()

@pytest.fixture
def mock_video_repository():
    return Mock(spec=IVideoRepository)

@pytest.fixture
def container_with_mocks(container, mock_video_repository):
    with container.video_repository.override(mock_video_repository):
        yield container
```

### FastAPI Integration with DI
```python
# Source: https://python-dependency-injector.ets-labs.org/examples/fastapi.html
# File: src/adapters/web/app.py

from fastapi import FastAPI
from ..container import Container
from . import routes

def create_app() -> FastAPI:
    container = Container()

    app = FastAPI(title="CineOrg")
    app.container = container

    # Wire routes
    container.wire(modules=[routes.videos])

    app.include_router(routes.videos.router)

    return app
```

### Injecting into FastAPI Routes
```python
# Source: https://python-dependency-injector.ets-labs.org/examples/fastapi.html
# File: src/adapters/web/routes/videos.py

from typing import Annotated
from fastapi import APIRouter, Depends
from dependency_injector.wiring import Provide, inject
from ...container import Container
from ...services.scanner import ScanDownloadsUseCase

router = APIRouter(prefix="/videos", tags=["videos"])

@router.post("/scan")
@inject
async def scan_downloads(
    scanner: Annotated[
        ScanDownloadsUseCase,
        Depends(Provide[Container.scan_downloads])
    ],
):
    """Trigger a scan of the downloads directory."""
    results = scanner.execute()
    return {"found": len(results)}
```

### Loading Config from JSON File
```python
# Source: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
# File: src/config.py (alternative with JSON file)

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CINEORG_",
        env_file=".env",
        json_file="config/config.json",  # File has lower priority than env
        env_nested_delimiter="__",
    )

    # ... fields ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| pydantic v1 BaseSettings | pydantic-settings v2 (separate package) | Pydantic v2 (2023) | Must install pydantic-settings separately |
| logging stdlib only | Loguru/structlog | 2020+ | Simpler config, built-in rotation |
| Manual DI / global singletons | dependency-injector | 2019+ | Type-safe, testable, framework integration |
| Flat src/ structure | Hexagonal layers | 2010s | Clear boundaries, testability |

**Deprecated/outdated:**
- `from pydantic import BaseSettings`: Moved to pydantic-settings package in Pydantic v2
- Implicit global loggers: Use explicit logger binding with context

## Open Questions

Things that couldn't be fully resolved:

1. **SQLModel vs Pure Dataclasses for Entities**
   - What we know: CONTEXT.md leaves this to Claude's discretion
   - What's unclear: SQLModel in core/ would couple domain to ORM
   - Recommendation: Use pure dataclasses in `core/entities/`, SQLModel only in `adapters/persistence/`. Map between them.

2. **Async vs Sync Repository Pattern**
   - What we know: FastAPI prefers async, Typer CLI is sync
   - What's unclear: Should repositories have async methods?
   - Recommendation: Start with sync repositories. CLI uses directly, FastAPI wraps with `run_in_executor`. Migrate to async later if needed.

3. **typer-di vs Manual Wiring for CLI**
   - What we know: typer-di (0.1.5) exists but is beta
   - What's unclear: Whether it's mature enough for production
   - Recommendation: Use dependency-injector's standard wiring with `@inject` decorator. Works with Typer, well-documented.

## Sources

### Primary (HIGH confidence)
- [pydantic-settings official docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) - Configuration, sources, validation
- [dependency-injector docs](https://python-dependency-injector.ets-labs.org/) - Container, providers, FastAPI integration
- [Loguru GitHub](https://github.com/Delgan/loguru) - Rotation, JSON, configuration
- [Cosmic Python book Ch.13](https://www.cosmicpython.com/book/chapter_13_dependency_injection.html) - Bootstrap pattern, manual DI

### Secondary (MEDIUM confidence)
- [PyPI pydantic-settings](https://pypi.org/project/pydantic-settings/) - Version 2.12.0, Python 3.10+
- [PyPI dependency-injector](https://pypi.org/project/dependency-injector/) - Version 4.48.3, Python 3.8+
- [PyPI loguru](https://pypi.org/project/loguru/) - Version 0.7.3, Python 3.5+
- [AWS hexagonal architecture in Python](https://docs.aws.amazon.com/prescriptive-guidance/latest/patterns/structure-a-python-project-in-hexagonal-architecture-using-aws-lambda.html) - Directory structure

### Tertiary (LOW confidence)
- [Hexagonal architecture blog](https://blog.szymonmiks.pl/p/hexagonal-architecture-in-python/) - Implementation patterns
- [Better Stack logging guide](https://betterstack.com/community/guides/logging/python/python-logging-best-practices/) - Best practices

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries verified on PyPI with current versions
- Architecture: HIGH - Patterns from official docs and authoritative sources
- Pitfalls: MEDIUM - Based on community patterns and library documentation

**Research date:** 2026-01-26
**Valid until:** 2026-02-26 (30 days - stable libraries)
