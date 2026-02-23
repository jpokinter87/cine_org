# CineOrg

## What This Is

Application Python de gestion de vidéothèque personnelle. Scanne les téléchargements, identifie et formate les films et séries via guessit et les bases TMDB/TVDB, organise les fichiers en une zone de stockage physique et une zone de lecture (symlinks) pour médiacenter. L'organisation en sous-répertoires est alphabétique avec subdivision par plages pour maintenir moins de 50 fichiers par répertoire. Le CLI est fonctionnel ; la prochaine étape est l'interface graphique web.

## Core Value

Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements, sans effort manuel.

## Current State

| Attribute | Value |
|-----------|-------|
| Version | 1.1 (CLI + Web + Enrichissement) |
| Status | Production |
| Last Updated | 2026-02-23 |

## Requirements

### Validated (Shipped)

- [x] Scan des téléchargements et parsing via guessit/mediainfo
- [x] Matching TMDB (films) et TVDB (séries) avec scoring
- [x] Renommage standardisé des fichiers
- [x] Organisation en storage/ (physique) et video/ (symlinks)
- [x] Subdivision alphabétique automatique (max 50 fichiers/répertoire)
- [x] Validation automatique et manuelle des candidats
- [x] Réparation de symlinks cassés
- [x] Cleanup et consolidation de la vidéothèque
- [x] Import/enrichissement de vidéothèques existantes
- [x] CLI complet via Typer
- [x] Interface web graphique (FastAPI + Jinja2 + HTMX)
  - Foundation web : FastAPI app, layout Jinja2, HTMX, page d'accueil stats — Phase 1
  - Validation visuelle : liste pending, détail candidats enrichis, actions HTMX — Phase 2
  - Orchestration workflow : scan → matching → auto-validation avec SSE temps réel — Phase 3
  - Transfert et résolution de conflits via le web — Phase 4
  - Navigation bibliothèque films/séries avec filtres et détail — Phase 5
  - Page configuration (répertoires, clés API, seuils) — Phase 5
  - Maintenance : diagnostics intégrité et cleanup avec SSE temps réel — Phase 5
- [x] Enrichissement données (v1.1)
  - Ratings films enrichis à 100% (progress bar Rich) — Phase 6
  - Séries enrichies : tmdb_id 99.7%, imdb_id 98.3% — Phase 7
  - Fiches web enrichies : liens IMDb/TMDB, crédits cliquables, filtre par personne — Phase 8

### Active (In Progress)

(None — v1.1 milestone complete)

### Planned (Next)

(None defined yet)

### Out of Scope

- Streaming vidéo — CineOrg organise les fichiers, ne les lit pas
- Multi-utilisateur — usage personnel uniquement

## Target Users

**Primary:** Utilisateur unique gérant sa vidéothèque personnelle
- Télécharge régulièrement des films et séries
- Utilise un médiacenter (Plex, Jellyfin, Kodi)
- Veut une organisation propre et automatique

## Context

**Technical Context:**
- CLI existant complet et fonctionnel (Typer)
- Architecture hexagonale avec DI (dependency-injector)
- Stack : Python 3.11+, FastAPI, Jinja2+HTMX, SQLModel/SQLite, guessit, pymediainfo, httpx
- APIs externes : TMDB (films), TVDB (séries)

## Constraints

### Technical Constraints
- Python 3.11+
- SQLite (pas de serveur DB)
- APIs TMDB/TVDB avec rate limiting
- Symlinks uniquement dans video/ (jamais déplacer les fichiers storage/)
- Le CLI doit rester pleinement fonctionnel — l'interface web est un complément, pas un remplacement
- L'utilisateur doit pouvoir choisir entre CLI et web pour toutes les opérations

### Business Constraints
- Usage personnel uniquement
- Pas de stockage cloud

## Key Decisions

| Decision | Rationale | Date | Status |
|----------|-----------|------|--------|
| Architecture hexagonale | Séparation claire domaine/infra | - | Active |
| Symlinks pour video/ | Ne jamais déplacer les fichiers physiques lors de réorganisations | - | Active |
| HTMX pour le web | Interactivité sans SPA complexe, cohérent avec Jinja2 | 2026-02-23 | Active |
| Web = complément du CLI | L'utilisateur choisit son interface ; le CLI ne doit jamais régresser | 2026-02-23 | Active |
| Lifespan DI pattern | Container initialisé via asynccontextmanager dans FastAPI | 2026-02-23 | Active |
| deps.py pour partage | Templates Jinja2 dans module séparé pour éviter imports circulaires | 2026-02-23 | Active |
| CSS custom thème sombre | Instrument Serif + DM Sans, pas de framework CSS lourd | 2026-02-23 | Active |
| Fragments HTMX + HX-Redirect | Actions POST retournent des fragments HTML, redirect via header | 2026-02-23 | Active |
| Dialogue custom pour actions destructives | Overlay CSS avec explication plutôt que confirm() natif | 2026-02-23 | Active |
| SSE pour progression workflow | EventSource + StreamingResponse, état partagé via WorkflowProgress | 2026-02-23 | Active |
| Cascade auto-validation séries | Valider 1 épisode auto-valide les autres de la même série (même candidat TVDB) | 2026-02-23 | Active |
| SSE maintenance multi-phases | Progression par phase pour analyses longues (intégrité 3, cleanup 6) | 2026-02-23 | Active |
| Scope Films+Séries maintenance | Limiter les analyses aux sous-dossiers pertinents | 2026-02-23 | Active |

## Success Metrics

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Couverture tests | 90%+ | ~90% | On track |
| CLI fonctionnel | Toutes commandes | Complet | Achieved |
| Interface web | Workflow complet | Complet (5 phases) | Achieved |

## Tech Stack

| Layer | Technology | Notes |
|-------|------------|-------|
| Framework | FastAPI | Web API |
| Frontend | Jinja2 + HTMX | Templates + interactivité |
| CLI | Typer | Interface ligne de commande |
| Database | SQLModel (SQLite) | ORM |
| Parsing | guessit + pymediainfo | Extraction métadonnées |
| API clients | httpx (async) | TMDB, TVDB |
| DI | dependency-injector | Container IoC |

---
*PROJECT.md — Updated when requirements or context change*
*Last updated: 2026-02-24 after Phase 8 (v1.1 milestone complete)*
