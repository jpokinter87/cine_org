---
phase: 13-refactoring-code
plan: 02
subsystem: web
tags: [refactoring, library, package, routes]

requires:
  - phase: 13-refactoring-code/01
    provides: pending_factory extrait, code stabilisé
provides:
  - Package library/ avec 6 modules spécialisés
affects: [14-workflow-fluide]

tech-stack:
  added: []
  patterns: [APIRouter.include_router pour découpage en sous-modules]

key-files:
  created: [src/web/routes/library/__init__.py, src/web/routes/library/helpers.py, src/web/routes/library/browse.py, src/web/routes/library/detail.py, src/web/routes/library/player.py, src/web/routes/library/reassociate.py]
  modified: []

key-decisions:
  - "Package library/ avec sous-routers inclus dans __init__.py plutôt que router unique"
  - "Helpers partagés (indicateurs, find_movie_file, etc.) dans helpers.py centralisé"

patterns-established:
  - "Découpage routes web en package avec sous-routers FastAPI"

duration: ~10min
completed: 2026-02-25
---

# Phase 13 Plan 02: Split library.py en package — Summary

**Fichier monolithique `library.py` (1250 lignes) découpé en package `library/` de 6 modules spécialisés sans changement de comportement.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~10min |
| Completed | 2026-02-25 |
| Tasks | 1 completed |
| Files created | 6 |
| Files deleted | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Package fonctionnel | Pass | `app.py` importe toujours `from .routes.library import router`, 12 routes préservées |
| AC-2: Aucune régression | Pass | 875 tests passent, ruff check propre |

## Accomplishments

- Découpé `library.py` (1250 lignes) en 6 modules cohérents
- `helpers.py` (280 lignes) : fonctions utilitaires partagées
- `browse.py` (270 lignes) : listing avec filtres et pagination
- `detail.py` (155 lignes) : fiches film et série
- `player.py` (133 lignes) : lecture mpv intégrée
- `reassociate.py` (310 lignes) : correction manuelle associations TMDB
- `__init__.py` (15 lignes) : assemblage des sous-routers
- Aucune modification de `app.py` nécessaire (import transparent)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/routes/library/__init__.py` | Created | Assemblage router avec include_router |
| `src/web/routes/library/helpers.py` | Created | Fonctions utilitaires partagées |
| `src/web/routes/library/browse.py` | Created | Route listing bibliothèque |
| `src/web/routes/library/detail.py` | Created | Routes détail film/série |
| `src/web/routes/library/player.py` | Created | Routes lecture mpv |
| `src/web/routes/library/reassociate.py` | Created | Routes réassociation TMDB |
| `src/web/routes/library.py` | Deleted | Ancien fichier monolithique |

## Decisions Made

None — plan exécuté exactement comme spécifié.

## Deviations from Plan

None — plan exécuté exactement comme écrit.

## Issues Encountered

None

## Next Phase Readiness

**Ready:**
- Code refactoré et maintenable, prêt pour Phase 14 (Workflow Fluide)
- Tous les tests passent, lint propre

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 13-refactoring-code, Plan: 02*
*Completed: 2026-02-25*
