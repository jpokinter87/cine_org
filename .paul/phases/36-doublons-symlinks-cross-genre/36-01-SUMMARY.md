---
phase: 36-doublons-symlinks-cross-genre
plan: 01
subsystem: cleanup
tags: [symlinks, doublons, genres, cleanup]

requires:
  - phase: 35-maintenance-web
    provides: cleanup pipeline (analyzers, executors, service, web)
provides:
  - scan_cross_genre_duplicates analyzer
  - fix_cross_genre_duplicates executor
  - CLI --only option for targeted cleanup
  - Bouton Visionner en validation manuelle
affects: [cleanup, maintenance]

tech-stack:
  added: []
  patterns: [readlink batch 2 passes, is_tv flag TMDB]

key-files:
  created:
    - tests/unit/test_cross_genre_duplicates.py
  modified:
    - src/services/cleanup/analyzers.py
    - src/services/cleanup/dataclasses.py
    - src/services/cleanup/executors.py
    - src/services/cleanup/cleanup_service.py
    - src/adapters/cli/cleanup_helpers.py
    - src/adapters/cli/commands/cleanup_command.py
    - src/web/routes/maintenance.py
    - src/web/templates/maintenance/_cleanup_results.html
    - src/web/templates/maintenance/_cleanup_fix_results.html
    - src/core/ports/api_clients.py
    - src/adapters/api/tmdb_client.py
    - src/services/validation.py
    - src/web/routes/validation.py
    - src/adapters/cli/batch_builder.py

key-decisions:
  - "Optimisation 2 passes readlink/resolve pour scan cross-genre"
  - "source tmdb_tv pour distinguer film/série TV TMDB dans tout le pipeline"
  - "is_tv flag sur MediaDetails plutôt que détection heuristique"

patterns-established:
  - "tmdb_tv source propagée : SearchResult → validation → batch_builder"

duration: ~3h (réparties sur 2 sessions)
started: 2026-03-08
completed: 2026-03-13
---

# Phase 36 Plan 01: Doublons Symlinks Cross-Genre Summary

**Détection/correction des symlinks cross-genre + fix TMDB séries TV via IMDB + améliorations UX (Visionner, --only, collapsed state)**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~3h (2 sessions) |
| Started | 2026-03-08 |
| Completed | 2026-03-13 |
| Tasks | 3 planifiées + 3 bonus |
| Files modified | 15+ |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Détection cross-genre | Pass | scan_cross_genre_duplicates regroupe par target résolu |
| AC-2: Respect GENRE_HIERARCHY | Pass | get_priority_genre() détermine le symlink conservé |
| AC-3: Intégration cleanup pipeline | Pass | CLI + web (analyse SSE + fix) |

## Accomplishments

- Analyseur `scan_cross_genre_duplicates` avec optimisation 2 passes (readlink batch puis resolve)
- Exécuteur `fix_cross_genre_duplicates` supprime les symlinks redondants
- 11 tests unitaires couvrant tous les cas (2/3 genres, priorité, edge cases)
- CLI `cleanup --only` pour cibler un type d'analyse spécifique
- Bouton "Visionner" en validation manuelle (mpv + polling HTMX)
- Fix TMDB séries TV trouvées via IMDB (source `tmdb_tv` propagée dans tout le pipeline)

## Task Commits

| Task | Commit | Type | Description |
|------|--------|------|-------------|
| Cross-genre | `6880e5f` | feat | Détection et correction doublons cross-genre |
| CLI --only | `bbf6284` | feat | Option --only pour ciblage cleanup |
| Visionner | `359f3b4` | feat | Bouton Visionner en validation manuelle |
| Collapsed | `bb67616` | fix | Persistance état collapsed doublons transfert |
| TMDB TV | `0ed804e` | fix | Séries TV TMDB via recherche IMDB |
| Misc | `3ec3124` | chore | Pagination + lock |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Scope additions | 3 | Améliorations UX connexes (Visionner, --only, collapsed) |
| Bug fix | 1 | Fix TMDB TV critique découvert pendant tests |

**Total impact:** Améliorations cohérentes avec la maintenance, aucun scope creep

### Bug fix hors plan

**TMDB "Tout le bleu du ciel" (tt35562998)**
- **Issue:** Film classé comme série TV sur TMDB, ID 259622 partagé entre un film (Undercity) et la série
- **Fix:** Champ `is_tv` sur MediaDetails, source `"tmdb_tv"` propagée dans validation + batch_builder
- **Files:** api_clients.py, tmdb_client.py, validation.py (service+routes), batch_builder.py

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| TMDB ID collision (259622 = film + série) | Source tmdb_tv + get_tv_details/get_tv_external_ids |
| Cache API avec anciennes données | Purge manuelle des entrées cache SQLite |

## Next Phase Readiness

**Ready:**
- Pipeline cleanup complet (broken, misplaced, duplicates, cross-genre, subdivide, empty)
- Fix TMDB TV réutilisable pour tout futur cas IMDB→série TV

**Concerns:**
- Aucune

**Blockers:**
- None

---
*Phase: 36-doublons-symlinks-cross-genre, Plan: 01*
*Completed: 2026-03-13*
