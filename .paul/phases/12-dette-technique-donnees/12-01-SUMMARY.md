---
phase: 12-dette-technique-donnees
plan: 01
subsystem: library, persistence
tags: [unicode, sorting, ligatures, search, sqlite]

requires:
  - phase: 9-bibliotheque-web
    provides: library routes avec tri par titre
provides:
  - Tri bibliothèque normalisé (accents, articles, ligatures, invisibles)
  - Recherche bibliothèque avec gestion des ligatures (œ/æ)
  - Nettoyage batch et préventif des titres en BDD
  - Fonction title_sort_key() centralisée et réutilisable
  - Fonction search_variants() pour recherche unicode-aware
affects: [13-refactoring-code, library-routes]

tech-stack:
  added: []
  patterns: [unicode normalization pipeline, ligature-aware search]

key-files:
  created: []
  modified:
    - src/utils/helpers.py
    - src/web/routes/library.py
    - src/services/organizer.py
    - src/infrastructure/persistence/repositories/movie_repository.py
    - src/infrastructure/persistence/repositories/series_repository.py
    - src/infrastructure/persistence/repositories/episode_repository.py
    - src/adapters/cli/commands/import_commands.py
    - src/adapters/cli/commands/__init__.py
    - src/main.py

key-decisions:
  - "Ligatures traitées par expansion explicite (œ→oe, æ→ae) plutôt que table Unicode"
  - "Recherche SQL via OR sur variantes plutôt que normalisation côté DB"
  - "Stripping non-alphanum en début de titre via isalnum() plutôt que liste fixe de caractères"

patterns-established:
  - "title_sort_key() pour tout tri de titres (bibliothèque, futures listes)"
  - "search_variants() pour toute recherche texte impliquant des titres"
  - "clean_title() préventif dans les save() des repositories"

duration: ~45min
completed: 2026-02-25T17:00:00Z
---

# Phase 12 Plan 01: Tri & Nettoyage Titres — Summary

**Tri bibliothèque normalisé avec gestion accents/articles/ligatures/invisibles + recherche unicode-aware + nettoyage batch titres BDD**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~45min |
| Tasks | 2 auto + 1 checkpoint |
| Files modified | 9 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Tri alphabétique normalisé | Pass | Accents, articles, ligatures, ponctuation de tête — tout vérifié |
| AC-2: Caractères invisibles nettoyés | Pass | 1 titre nettoyé sur 23 534 entrées |
| AC-3: Nettoyage préventif à l'entrée | Pass | clean_title() dans les 3 repositories save() |

## Accomplishments

- `title_sort_key()` centralise tout le pipeline de normalisation : invisibles → ligatures → non-alphanum de tête → articles → accents → lowercase
- `search_variants()` génère les variantes de recherche avec ligatures dépliées/repliées + variantes de casse (contourne la limitation SQLite LIKE unicode)
- Commande CLI `clean-titles` pour nettoyage batch one-shot
- Nettoyage préventif dans les 3 repositories (movie, series, episode)

## Files Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/utils/helpers.py` | Modified | Ajout strip_invisible_chars, clean_title, title_sort_key, _expand_ligatures, search_variants |
| `src/web/routes/library.py` | Modified | Tri via title_sort_key + recherche via _title_search_filter avec search_variants |
| `src/services/organizer.py` | Modified | Import strip_invisible_chars depuis helpers (au lieu de copie locale) |
| `src/infrastructure/persistence/repositories/movie_repository.py` | Modified | clean_title() préventif dans save() |
| `src/infrastructure/persistence/repositories/series_repository.py` | Modified | clean_title() préventif dans save() |
| `src/infrastructure/persistence/repositories/episode_repository.py` | Modified | clean_title() préventif dans save() |
| `src/adapters/cli/commands/import_commands.py` | Modified | Ajout commande clean_titles() |
| `src/adapters/cli/commands/__init__.py` | Modified | Export clean_titles |
| `src/main.py` | Modified | Enregistrement commande clean-titles |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Expansion ligatures explicite plutôt que table Unicode | Seules œ/æ sont pertinentes en contexte franco-anglais | Simple, maintenable |
| OR sur variantes SQL plutôt que collation custom | SQLite LIKE est case-insensitive ASCII uniquement | Fonctionne sans extension SQLite |
| isalnum() pour strip leading chars | Gère tous les caractères Unicode (…, ', ', etc.) | Plus robuste que liste fixe |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 3 | Essentiels, découverts pendant checkpoint |
| Scope additions | 1 | search_variants() — nécessaire pour la recherche |
| Deferred | 0 | — |

**Total impact:** Fixes essentiels, pas de scope creep

### Auto-fixed Issues

**1. Ponctuation de tête : lstrip fixe insuffisant**
- **Found during:** Task 1 checkpoint
- **Issue:** `…` (U+2026 ellipsis) et `'` (U+2018 left quote) pas dans la liste lstrip
- **Fix:** Remplacé lstrip() par boucle isalnum() qui skip tous les non-alphanum
- **Verification:** Testé avec titres BDD réels

**2. Ligatures œ/æ non décomposées par NFD**
- **Found during:** Checkpoint
- **Issue:** NFD ne décompose pas les ligatures → triées après Z
- **Fix:** Ajout _expand_ligatures() avant normalize_accents()
- **Verification:** Œil → oeil, Æon → aeon dans le tri

**3. Recherche SQL insensible ligatures**
- **Found during:** Checkpoint
- **Issue:** SQLite LIKE case-insensitive uniquement pour ASCII, pas pour œ/Œ/æ/Æ
- **Fix:** Ajout search_variants() + _title_search_filter() avec OR sur toutes variantes
- **Verification:** "oeil" trouve "L'Œil silencieux", "aeon" trouve "Æon Flux"

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Test pré-existant test_auto_repair_multi_season en échec | Confirmé non lié — reporté Phase 13 |

## Next Phase Readiness

**Ready:**
- Pipeline de normalisation centralisé dans helpers.py, réutilisable partout
- Recherche unicode-aware prête pour futures extensions
- Base titres nettoyée

**Concerns:**
- Aucune

**Blockers:**
- None

---
*Phase: 12-dette-technique-donnees, Plan: 01*
*Completed: 2026-02-25*
