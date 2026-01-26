"""
Infrastructure adapters layer.

Adapters implement the ports defined in core/ports/ and provide
concrete implementations for external systems.

Planned subpackages:
- cli/: Command-line interface (Typer)
- web/: Web interface (FastAPI + HTMX)
- db/: Database access (SQLModel + SQLite)
- api/: External API clients (TMDB, TVDB)
- filesystem/: File system operations

Each adapter depends on core/ but core/ never depends on adapters/.
This allows swapping implementations without affecting business logic.
"""
