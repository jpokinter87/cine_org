---
phase: 20-navigation-affichage
plan: 01
subsystem: ui
tags: [jinja2, htmx, genres, sorting, navigation]

provides:
  - Cartouches accueil cliquables (liens directs biblio/validation)
  - Genres normalisés EN→FR dans filtres bibliothèque
  - Tri "Récemment ajouté" par date created_at
affects: [21-donnees-manquantes]

key-files:
  created: []
  modified:
    - src/web/templates/home.html
    - src/web/static/css/style.css
    - src/web/routes/library/browse.py
    - src/web/templates/library/_filters.html

key-decisions:
  - "Normalisation genres à l'affichage uniquement, pas en base"
  - "Genres Soap/Talk/Sport exclus du filtre (rares, sans équivalent FR pertinent)"
  - "Filtre genre multi-variantes via OR SQL pour capturer EN et FR"

completed: 2026-02-27
---

# Phase 20 Plan 01: Améliorations Navigation & Affichage Summary

**Cartouches accueil cliquables, genres normalisés FR, tri par date d'ajout**

## Performance

| Metric | Value |
|--------|-------|
| Tasks | 2/2 completed |
| Files modified | 4 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Cartouches accueil cliquables | Pass | Films→/library/?type=movie, Séries→/library/?type=series, En attente→/validation |
| AC-2: Genres dédoublonnés | Pass | 10 genres EN normalisés vers FR, filtre multi-variantes OR SQL |
| AC-3: Tri récemment ajoutés | Pass | Option "Récemment ajouté" avec tri par created_at desc |

## Accomplishments

- 4 cartouches stats transformées en liens `<a>` cliquables avec navigation directe
- 10 genres anglais/composés normalisés vers le français (Drama→Drame, Family→Familial, etc.)
- Filtre genre enrichi avec variantes EN automatiques (filtrer "Drame" capture aussi "Drama" en base)
- Nouveau critère de tri "Récemment ajouté" exploitant le champ `created_at` des modèles

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/templates/home.html` | Modified | `<div>` → `<a>` sur les 4 cartouches stats |
| `src/web/static/css/style.css` | Modified | Styles liens sur `.stat-card` (text-decoration, color, cursor) |
| `src/web/routes/library/browse.py` | Modified | Table normalisation `_GENRE_NORMALIZE`, variantes `_GENRE_VARIANTS`, filtre OR multi-variantes, tri `created_at`, `created_at` dans items dict |
| `src/web/templates/library/_filters.html` | Modified | Option "Tri: Récemment ajouté" dans le select sort |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Normalisation à l'affichage uniquement | Ne pas modifier les données en base — on normalise lors de la collecte des genres pour le dropdown | Réversible, pas de migration DB |
| Genres Soap/Talk/Sport exclus (None) | Très rares, pas d'équivalent français pertinent | N'apparaissent plus dans le filtre |
| Filtre OR multi-variantes | Filtrer "Drame" doit aussi capturer les films tagués "Drama" en base | Transparent pour l'utilisateur |

## Deviations from Plan

None — plan exécuté tel que spécifié.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- Navigation accueil → bibliothèque fluide
- Filtres genres propres sans doublons
- Tri par date d'ajout opérationnel

**Concerns:**
- Le chemin S01E01 était déjà implémenté mais n'apparaît pas sur certaines séries (file_path manquant en base) — à traiter en Phase 21

**Blockers:**
None.

---
*Phase: 20-navigation-affichage, Plan: 01*
*Completed: 2026-02-27*
