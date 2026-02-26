---
phase: 15-que-regarder-ce-soir
plan: 01
subsystem: ui, database
tags: [htmx, sqlmodel, watched, rating, stars, filter]

requires:
  - phase: 13-refactoring-code
    provides: package library/ découpé en sous-modules
provides:
  - Colonnes watched et personal_rating sur MovieModel et SeriesModel
  - Toggle "Déjà vu" et widget étoiles sur fiches film et série
  - Filtre "Non-vus" sur la page bibliothèque
  - Badge visuel "vu" sur les jaquettes de la grille
affects: [15-02-suggestion-page]

tech-stack:
  added: []
  patterns: [fragments HTMX pour toggle/rate, checkbox filtre avec préservation pagination]

key-files:
  created:
    - src/web/templates/library/_watched_btn.html
    - src/web/templates/library/_star_rating.html
    - src/web/templates/library/_watched_btn_series.html
    - src/web/templates/library/_star_rating_series.html
  modified:
    - src/infrastructure/persistence/models.py
    - src/infrastructure/persistence/database.py
    - src/web/routes/library/detail.py
    - src/web/routes/library/browse.py
    - src/web/templates/library/movie_detail.html
    - src/web/templates/library/series_detail.html
    - src/web/templates/library/_filters.html
    - src/web/templates/library/_grid.html
    - src/web/static/css/style.css

key-decisions:
  - "Extension aux séries : watched et personal_rating ajoutés aussi à SeriesModel (demande utilisateur pendant checkpoint)"
  - "Badge vu en pastille verte œil côte à côte avec badge type Film/Série (conteneur flex .lib-card-badges)"
  - "Routes directes dans detail.py plutôt que via movie_repository (accès session direct, cohérent avec les autres routes)"

patterns-established:
  - "Fragments HTMX _watched_btn.html / _star_rating.html pour swap innerHTML"
  - "Checkbox filtre avec trigger change + préservation dans base_params"

duration: ~45min
completed: 2026-02-25
---

# Phase 15 Plan 01: Fondations Watched & Rating — Summary

**Toggle "Déjà vu", widget étoiles 1-5, et filtre "Non-vus" sur films et séries avec fragments HTMX et persistance DB**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~45min |
| Completed | 2026-02-25 |
| Tasks | 4 + 1 checkpoint |
| Files created | 4 |
| Files modified | 9 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Champs DB watched et personal_rating | Pass | MovieModel + SeriesModel (extension) |
| AC-2: Toggle "Déjà vu" sur fiche film | Pass | HTMX swap, icône œil ouvert/fermé |
| AC-3: Widget étoiles sur fiche film | Pass | 5 étoiles cliquables, toggle off, hover CSS :has() |
| AC-4: Tests unitaires | Pass | 875 tests, aucune régression |
| AC-5: Filtre "Non-vus" bibliothèque | Pass | Checkbox, compatible filtres existants et pagination |

## Accomplishments

- Colonnes `watched` (bool, indexé) et `personal_rating` (int nullable) sur MovieModel ET SeriesModel avec migrations automatiques
- Toggle "Déjà vu" et widget étoiles fonctionnels sur fiches film et série via HTMX (4 fragments HTML)
- Case à cocher "Non-vus" sur la page bibliothèque filtrant films et séries
- Badge visuel pastille verte œil sur les jaquettes de la grille pour les éléments marqués "vu"
- Checkbox custom stylé pour le thème sombre (accent amber)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/infrastructure/persistence/models.py` | Modified | Champs watched + personal_rating sur MovieModel et SeriesModel |
| `src/infrastructure/persistence/database.py` | Modified | Migrations 7 (movies) et 8 (series) |
| `src/web/routes/library/detail.py` | Modified | Routes toggle-watched et rate pour films et séries |
| `src/web/routes/library/browse.py` | Modified | Paramètre unwatched, filtre SQL, watched dans items |
| `src/web/templates/library/_watched_btn.html` | Created | Fragment HTMX bouton watched film |
| `src/web/templates/library/_star_rating.html` | Created | Fragment HTMX étoiles film |
| `src/web/templates/library/_watched_btn_series.html` | Created | Fragment HTMX bouton watched série |
| `src/web/templates/library/_star_rating_series.html` | Created | Fragment HTMX étoiles série |
| `src/web/templates/library/movie_detail.html` | Modified | Zone personnelle (watched + étoiles) |
| `src/web/templates/library/series_detail.html` | Modified | Zone personnelle (watched + étoiles) |
| `src/web/templates/library/_filters.html` | Modified | Checkbox "Non-vus" + trigger étendu |
| `src/web/templates/library/_grid.html` | Modified | Badge vu sur jaquettes (conteneur .lib-card-badges) |
| `src/web/static/css/style.css` | Modified | Styles watched-btn, star-rating, lib-filter-checkbox, lib-card-badges, lib-card-watched |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Extension watched/rating aux séries | Demande utilisateur pendant checkpoint — cohérent d'avoir les mêmes fonctions partout | 4 fichiers supplémentaires, migration 8 ajoutée |
| Routes directes dans detail.py (pas via repository) | Cohérent avec les autres routes existantes qui accèdent session directement | Pas de méthodes ajoutées à movie_repository.py |
| Badge vu = pastille verte + badge type côte à côte | Pastille seule chevauchait le badge type — conteneur flex résout le problème | Nouveau conteneur .lib-card-badges wrappant les deux |
| Hover étoiles via CSS :has() | Pas de JS nécessaire, colore les étoiles de gauche à droite au survol | Navigateurs modernes uniquement (OK pour usage personnel) |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Scope additions | 2 | Extension séries + badge grille |
| Auto-fixed | 1 | Repositionnement badge vu |

**Total impact:** Extensions demandées par l'utilisateur, améliorent la cohérence UX.

### Scope Additions

**1. Extension watched/rating aux séries**
- **Demandé par:** Utilisateur pendant checkpoint
- **Impact:** SeriesModel modifié, migration 8, 2 routes séries, 2 fragments HTML séries, template série modifié
- **Justification:** Incohérent d'avoir la fonctionnalité sur les films mais pas les séries

**2. Badge "vu" sur jaquettes dans la grille**
- **Demandé par:** Utilisateur après approbation initiale
- **Impact:** _grid.html modifié, CSS ajouté, browse.py passe watched dans items
- **Justification:** Repère visuel nécessaire pour distinguer les films vus dans la bibliothèque

### Auto-fixed Issues

**1. Repositionnement badge vu**
- **Issue:** Pastille verte position:absolute chevauchait le badge type Film/Série
- **Fix:** Conteneur flex .lib-card-badges avec pastille + badge type côte à côte
- **Files:** _grid.html, style.css

## Skill Audit

Skill audit: All required skills invoked ✓
- /frontend-design : invoqué pour le design du widget étoiles, toggle watched, et checkbox

## Next Phase Readiness

**Ready:**
- Colonnes watched et personal_rating en place sur films ET séries
- Filtre "Non-vus" fonctionnel
- Fondations prêtes pour l'algorithme de suggestion (plan 02)

**Concerns:**
- Aucune

**Blockers:**
- None

---
*Phase: 15-que-regarder-ce-soir, Plan: 01*
*Completed: 2026-02-25*
