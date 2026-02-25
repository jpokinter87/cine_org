---
phase: 13-refactoring-code
plan: 01
subsystem: workflow
tags: [refactoring, matching, pending-factory, tests]

requires:
  - phase: 12-dette-technique-donnees
    provides: données stabilisées avant refactoring
provides:
  - Module partagé pending_factory.py pour le matching CLI/web
  - Test test_auto_repair_multi_season corrigé
affects: [14-workflow-fluide]

tech-stack:
  added: []
  patterns: [standalone factory functions au lieu de mixin methods pour code partagé CLI/web]

key-files:
  created: [src/services/workflow/pending_factory.py]
  modified: [src/services/workflow/matching_step.py, src/web/routes/workflow.py, tests/unit/services/test_workflow.py, tests/unit/adapters/cli/test_repair_helpers.py]

key-decisions:
  - "Factory functions standalone plutôt que classe abstraite pour le partage CLI/web"
  - "Tests filter_by_episode_count adaptés pour appeler directement le factory"

patterns-established:
  - "Code partagé CLI/web dans src/services/workflow/ comme fonctions standalone"

duration: ~20min
completed: 2026-02-25
---

# Phase 13 Plan 01: Fix test + extraction matching — Summary

**Module `pending_factory.py` extrait pour partager le code matching entre CLI et web, et 2 tests auto-repair corrigés.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~20min |
| Completed | 2026-02-25 |
| Tasks | 2 completed |
| Files modified | 5 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Test corrigé | Pass | `test_auto_repair_multi_season` + `test_auto_repair_picks_best_candidate_in_confirmed_dir` corrigés |
| AC-2: Matching partagé | Pass | `pending_factory.py` importé par matching_step.py et workflow.py, zéro duplication |

## Accomplishments

- Créé `pending_factory.py` avec `create_pending_validation()`, `filter_by_episode_count()`, `_search_and_score_movie()`, `_search_and_score_series()`
- Supprimé ~190 lignes dupliquées dans `matching_step.py` (4 méthodes remplacées par 1 délégation)
- Supprimé ~110 lignes dupliquées dans `workflow.py` (2 fonctions supprimées)
- Corrigé 2 tests auto-repair : noms de fichiers link incluent maintenant le pattern SxxExx requis
- 875 tests passent (0 échec), lint propre

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/services/workflow/pending_factory.py` | Created | Module partagé : recherche API, scoring, enrichissement, filtrage épisodes |
| `src/services/workflow/matching_step.py` | Modified | `_create_pending_validation` délègue au factory, 4 méthodes supprimées |
| `src/web/routes/workflow.py` | Modified | `_create_pending` et `_filter_by_episode_count` supprimées, import factory |
| `tests/unit/services/test_workflow.py` | Modified | Tests `TestFilterByEpisodeCount` appellent directement `filter_by_episode_count` du factory |
| `tests/unit/adapters/cli/test_repair_helpers.py` | Modified | 2 tests corrigés : noms de fichiers link avec pattern SxxExx |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Factory functions standalone | Plus simple qu'une classe abstraite, les deux appelants passent leurs deps explicitement | Facile à tester et à maintenir |
| Tests adaptés vers le factory | Les tests testent la logique métier, pas l'implémentation du mixin | Tests plus robustes |
| Aussi corrigé `test_auto_repair_picks_best_candidate_in_confirmed_dir` | Même pattern de bug (nom de fichier sans SxxExx) | 2 tests réparés au lieu de 1 |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Correction d'un 2e test avec le même bug |
| Scope additions | 0 | - |
| Deferred | 0 | - |

**Total impact:** Correction bonus d'un test supplémentaire avec le même problème.

### Auto-fixed Issues

**1. Test `test_auto_repair_picks_best_candidate_in_confirmed_dir` aussi cassé**
- **Found during:** Task 1
- **Issue:** Même pattern que `test_auto_repair_multi_season` — nom de fichier link sans SxxExx
- **Fix:** Changé les noms de fichiers pour inclure le pattern SxxExx
- **Verification:** 21 tests auto-repair passent

## Issues Encountered

None

## Next Phase Readiness

**Ready:**
- Code matching partagé, fondation solide pour Phase 14 (Workflow Fluide)
- Tous les tests passent

**Concerns:**
- `library.py` (~1250 lignes) reste à découper (Plan 13-02)

**Blockers:**
- None

---
*Phase: 13-refactoring-code, Plan: 01*
*Completed: 2026-02-25*
