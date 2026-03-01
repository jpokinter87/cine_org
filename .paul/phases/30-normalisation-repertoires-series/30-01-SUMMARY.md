---
phase: 30-normalisation-repertoires-series
plan: 01
subsystem: organizer
tags: [directory-structure, jellyfin, series, normalization]

requires:
  - phase: 29-films-multi-parties
    provides: pipeline stable pour les films
provides:
  - Noms de répertoires séries normalisés dans tout le code source
  - Routage documentaire vers Documentaires/Series documentaires/
  - MANAGED_SUBDIRS étendu à 3 racines (Films, Series, Documentaires)
affects: [30-02 migration physique, cleanup, repair]

tech-stack:
  added: []
  patterns: [routing conditionnel par genre pour séries documentaires]

key-files:
  created: []
  modified:
    - src/services/organizer.py
    - src/services/cleanup/dataclasses.py
    - src/services/cleanup/analyzers.py
    - src/adapters/cli/helpers.py
    - src/adapters/cli/validation/batch_display.py
    - src/adapters/cli/repair/helpers.py
    - src/adapters/cli/commands/fix_symlinks_command.py
    - src/adapters/cli/commands/fix_bad_links_command.py

key-decisions:
  - "Séries documentaires routées sous Documentaires/ (pas sous Series/)"
  - "Noms sans accents : Séries→Series, Séries TV→TV"
  - "scanner.py garde rétrocompat double variante pour downloads"

patterns-established:
  - "Routing conditionnel dans get_series_video_destination : if series_type == 'Series documentaires' → Documentaires/"

duration: ~45min
completed: 2026-03-01
---

# Phase 30 Plan 01: Normalisation code source — Summary

**Tous les noms de répertoires séries normalisés (Séries→Series, Séries TV→TV) + nouveau routage documentaire vers Documentaires/Series documentaires/**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~45min |
| Completed | 2026-03-01 |
| Tasks | 3 completed |
| Files modified | 8 source + 9 tests |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Mapping types séries normalisé | Pass | TV, Animation, Mangas retournés correctement |
| AC-2: Séries documentaires routées vers Documentaires/ | Pass | Nouveau genre + routing conditionnel |
| AC-3: MANAGED_SUBDIRS inclut nouvelles racines | Pass | ("Films", "Series", "Documentaires") |
| AC-4: Scanner accepte deux variantes | Pass | Pas de changement nécessaire, déjà OK |
| AC-5: Tous les tests passent | Pass | 933 passed, 0 failed |

## Accomplishments

- `get_series_type()` retourne "TV", "Animation", "Mangas", "Series documentaires" (plus de noms accentués)
- `get_series_video_destination()` route conditionnellement les documentaires vers `Documentaires/` et les autres vers `Series/`
- 9 fichiers de tests mis à jour avec nouveau test documentaire

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/services/organizer.py` | Modified | get_series_type() + get_series_video_destination() normalisés |
| `src/services/cleanup/dataclasses.py` | Modified | MANAGED_SUBDIRS étendu |
| `src/services/cleanup/analyzers.py` | Modified | _is_under_series() accepte Series + Documentaires |
| `src/adapters/cli/helpers.py` | Modified | Arbre Rich avec branches conditionnelles |
| `src/adapters/cli/validation/batch_display.py` | Modified | Détection racine + arbre Rich |
| `src/adapters/cli/repair/helpers.py` | Modified | Extraction noms séries depuis nouveaux chemins |
| `src/adapters/cli/commands/fix_symlinks_command.py` | Modified | Itération 3 sous-répertoires |
| `src/adapters/cli/commands/fix_bad_links_command.py` | Modified | Itération 3 sous-répertoires |
| `tests/unit/services/test_organizer.py` | Modified | Assertions + test documentaire |
| `tests/unit/adapters/cli/test_repair_helpers.py` | Modified | Fixtures chemins normalisés |
| `tests/unit/test_association_checker.py` | Modified | Fixtures chemins normalisés |
| `tests/unit/services/cleanup/test_scope.py` | Modified | Séries→Series, scope ajusté |
| `tests/unit/services/cleanup/test_duplicates.py` | Modified | Séries→Series, scope ajusté |
| `tests/unit/services/cleanup/test_refinement.py` | Modified | Séries TV→TV |
| `tests/unit/services/cleanup/test_scan.py` | Modified | Séries→Series |
| `tests/unit/services/cleanup/test_subdivision.py` | Modified | Séries→Series, Séries TV→TV |
| `tests/unit/services/cleanup/test_edge_cases.py` | Modified | Séries→Series |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Documentaires sous racine séparée | Demande utilisateur + structure Jellyfin distincte | Nouveau routing conditionnel |
| Pas d'accents dans les noms de répertoire | Compatibilité Jellyfin cross-platform | Migration physique nécessaire (plan 02) |
| Scanner garde double variante | Rétrocompat downloads existants | Aucun impact |

## Deviations from Plan

### Auto-fixed Issues

**1. Tests cleanup non listés dans le plan**
- **Found during:** Task 3
- **Issue:** 7 fichiers de tests cleanup utilisaient encore "Séries" dans les fixtures
- **Fix:** Mise à jour de tous les fichiers cleanup/test_*.py
- **Verification:** 933 tests pass

**2. _is_under_series() non listé dans le plan**
- **Found during:** Task 1 (vérification tests)
- **Issue:** analyzers.py vérifiait `parts[0] == "Séries"` au lieu de "Series"/"Documentaires"
- **Fix:** Changé en `parts[0] in ("Series", "Documentaires")`
- **Verification:** test_scan_oversized_series_anime_not_flagged passe

**Total impact:** Corrections essentielles, pas de scope creep.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| 8 tests cleanup en échec (1er run) | Fixtures chemins mis à jour dans 7 fichiers |
| test_scope "Documentaires" devenu in-scope | Changé en "Autre" pour tester l'exclusion |
| 5 fichiers mal formatés post-édition | ruff format appliqué |

## Next Phase Readiness

**Ready:**
- Code source entièrement normalisé pour les nouveaux noms de répertoires
- Prêt pour le plan 30-02 de migration physique

**Concerns:**
- La migration physique (plan 02) cassera temporairement les symlinks existants
- Les file_path en DB devront être mis à jour en batch

**Blockers:** None

---
*Phase: 30-normalisation-repertoires-series, Plan: 01*
*Completed: 2026-03-01*
