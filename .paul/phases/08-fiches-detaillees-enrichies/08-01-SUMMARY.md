---
phase: 08-fiches-detaillees-enrichies
plan: 01
subsystem: web, ui
tags: [htmx, jinja2, imdb, tmdb, filters, credits]

requires:
  - phase: 06-01
    provides: Films enrichis (ratings, imdb_id, tmdb_id)
  - phase: 07-01
    provides: Séries enrichies (tmdb_id, imdb_id)
provides:
  - Liens externes IMDb/TMDB cliquables sur fiches détaillées
  - Crédits cliquables avec filtre bibliothèque par personne
  - Label source rating (IMDb/TMDB) dans la grille
affects: []

tech-stack:
  added: []
  patterns: [filtre personne via query param + LIKE sur director/cast_json]

key-files:
  created: []
  modified:
    - src/web/routes/library.py
    - src/web/templates/library/movie_detail.html
    - src/web/templates/library/series_detail.html
    - src/web/templates/library/_grid.html
    - src/web/templates/library/_filters.html
    - src/web/static/css/style.css

key-decisions:
  - "Filtre personne via LIKE sur director + cast_json (pas de full-text search)"
  - "Liens externes dans la zone badges (pas dans la section dépliable)"

patterns-established:
  - "Query param person= pour filtre par personne dans la bibliothèque"
  - "Classe lib-credit-link pour crédits cliquables"

duration: 15min
started: 2026-02-23
completed: 2026-02-23
---

# Phase 8 Plan 01: Fiches Détaillées Enrichies Summary

**Liens IMDb/TMDB, crédits cliquables filtrants et label source rating ajoutés à l'interface web**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15min |
| Started | 2026-02-23 |
| Completed | 2026-02-23 |
| Tasks | 3 completed |
| Files modified | 6 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Liens externes cliquables | Pass | Boutons IMDb + TMDB visibles sur fiches film et série, target="_blank" |
| AC-2: Crédits cliquables avec filtre | Pass | Réalisateur et acteurs → /library/?person=X, tag filtre actif avec × |
| AC-3: Label source rating dans grille | Pass | Chaque badge affiche "IMDb" ou "TMDB" en petit |

## Accomplishments

- Liens externes IMDb/TMDB avec styles distinctifs (jaune IMDb, bleu TMDB)
- Réalisateur et acteurs transformés en liens cliquables sur films et séries
- Backend filtre `person` ajouté à la route library_index (LIKE sur director + cast_json)
- Tag filtre actif "Personne" avec icône et bouton de suppression
- Label source rating intégré aux badges de la grille bibliothèque

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/routes/library.py` | Modified | Ajout query param `person`, filtre LIKE sur director/cast_json |
| `src/web/templates/library/movie_detail.html` | Modified | Liens IMDb/TMDB, crédits cliquables |
| `src/web/templates/library/series_detail.html` | Modified | Liens IMDb/TMDB, crédits cliquables, tmdb_id dans IDs |
| `src/web/templates/library/_grid.html` | Modified | Label source rating (IMDb/TMDB) dans badge |
| `src/web/templates/library/_filters.html` | Modified | Hidden input person, tag filtre actif personne |
| `src/web/static/css/style.css` | Modified | Styles lib-credit-link, lib-external-link, lib-card-rating-source |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| LIKE sur director + cast_json | Simple et suffisant pour le cas d'usage | Pas besoin de full-text search |
| Liens externes dans zone badges | Visibilité immédiate sans déplier | Meilleure découvrabilité |

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- v1.1 milestone complet (3/3 phases)
- Interface web exploite pleinement les données enrichies
- Navigation par personne fonctionnelle

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 08-fiches-detaillees-enrichies, Plan: 01*
*Completed: 2026-02-23*
