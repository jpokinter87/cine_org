"""
CineOrg - Personal video library management application.

This package provides the core functionality for scanning, identifying,
renaming, and organizing video files using TMDB and TVDB metadata.

Architecture: Hexagonal (Ports and Adapters)
- core/: Domain layer (entities, ports, value objects)
- services/: Application layer (use cases, orchestration)
- adapters/: Infrastructure layer (CLI, Web, DB, API clients)
"""
