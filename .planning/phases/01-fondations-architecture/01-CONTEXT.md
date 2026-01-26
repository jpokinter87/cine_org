# Phase 1: Fondations Architecture - Context

**Gathered:** 2026-01-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Etablir l'architecture hexagonale avec separation stricte des couches pour garantir la reutilisabilite entre CLI et Web. Inclut: structure de repertoires, container DI, configuration via pydantic-settings, et logging structure.

</domain>

<decisions>
## Implementation Decisions

### Structure hexagonale
- Nommage des couches: `core/` (metier, entites, ports), `services/` (orchestration, use cases), `adapters/` (implementations CLI, Web, DB, API)
- Organisation des adapters: a la discretion de Claude

### Container DI
- Framework DI: a la discretion de Claude (dependency-injector, punq, ou manual)
- Gestion des contextes (CLI/Web/Tests): a la discretion de Claude
- Lifecycle (eager vs lazy): a la discretion de Claude
- Strategie de tests: a la discretion de Claude

### Configuration
- Format du fichier config: a la discretion de Claude
- Priorite env/fichier: a la discretion de Claude
- Comportement validation: a la discretion de Claude
- **Cles API (TMDB, TVDB): optionnelles** — l'app demarre sans, les features API sont desactivees

### Logging structure
- Format de sortie: a la discretion de Claude
- **Destination: fichier + stderr** — fichier rotatif pour historique, stderr pour supervision temps reel
- **Rotation: par taille (10MB)** — rotation a 10MB, garder 5 fichiers
- **Logs API: en DEBUG** — logger URL, temps de reponse, status code au niveau DEBUG

### Claude's Discretion
- Placement des ports (interfaces abstraites)
- Type d'entites (dataclasses pures vs SQLModel)
- Organisation des adapters (dans adapters/ ou top-level)
- Choix du framework DI
- Gestion des contextes DI
- Format de configuration
- Comportement de validation des configs

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-fondations-architecture*
*Context gathered: 2026-01-26*
