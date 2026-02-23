---
phase: 02-validation-visuelle
plan: 02
subsystem: ui
tags: [htmx, fastapi, validation, search, reject, pagination, lightbox]

requires:
  - phase: 02-validation-visuelle
    provides: Routes GET validation, templates candidate cards avec data-attributes
provides:
  - Actions HTMX complètes : valider, rejeter, recherche titre, recherche ID
  - Pagination des candidats
  - Dialogue de rejet custom avec explication
  - Lightbox zoom poster
affects: [03-orchestration-workflow, 04-transfert-conflits]

tech-stack:
  added:
    - python-multipart>=0.0.7
  patterns:
    - "HTMX hx-post/hx-get avec hx-target pour fragments HTML"
    - "HX-Redirect header pour redirection post-action"
    - "Dialogue custom (overlay+dialog) remplaçant hx-confirm natif"
    - "hx-on::after-request pour scroll automatique"

key-files:
  created:
    - src/web/templates/validation/_search_form.html
    - src/web/templates/validation/_search_results.html
  modified:
    - src/web/routes/validation.py
    - src/web/templates/validation/detail.html
    - src/web/templates/validation/_candidate_card.html
    - src/web/static/css/style.css
    - pyproject.toml

key-decisions:
  - "HX-Redirect plutôt que <script> pour redirection post-validation/rejet"
  - "hx-target='closest .candidate-card' pour feedback inline visible"
  - "Dialogue custom pour le rejet avec explication (fichier non effacé)"
  - "Pagination côté serveur (?page=N) au lieu de tout charger"
  - "Lightbox CSS pur avec JS minimal pour zoom poster"

patterns-established:
  - "Routes POST retournent des fragments HTML + HX-Redirect"
  - "Formulaires HTMX avec hx-on::after-request pour scroll"
  - "Overlay dialog pattern pour confirmations destructives"

duration: ~120min
started: 2026-02-23T17:00:00Z
completed: 2026-02-23T19:00:00Z
---

# Phase 2 Plan 02: Interactions HTMX validation — Summary

**Actions HTMX complètes (valider/rejeter/recherche) avec pagination, dialogue custom, zoom poster et auto-scroll recherche**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~120min |
| Tasks | 2 auto + 1 checkpoint |
| Files created | 2 |
| Files modified | 5 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Valider un candidat | Pass | POST HTMX, feedback inline remplaçant la carte, HX-Redirect vers liste |
| AC-2: Rejeter un fichier | Pass | Dialogue custom dans le thème avec explication, HX-Redirect |
| AC-3: Recherche manuelle par titre | Pass | GET HTMX, résultats inline avec boutons Valider, auto-scroll |
| AC-4: Recherche par ID externe | Pass | GET HTMX, TMDB/TVDB/IMDB, résultat inline |
| AC-5: Feedback visuel | Pass | Messages succès/erreur/warning, spinner HTMX |

## Accomplishments

- Actions HTMX fonctionnelles pour le flux complet de validation manuelle
- Dialogue de rejet custom expliquant que le fichier n'est pas effacé mais ignoré pour traitement
- Pagination des candidats avec navigation précédent/suivant
- Zoom poster via lightbox plein écran (clic ou Escape pour fermer)
- Auto-scroll vers la section recherche après soumission du formulaire

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/routes/validation.py` | Modified | 4 routes ajoutées (POST validate/reject, GET search/search-id), pagination |
| `src/web/templates/validation/detail.html` | Modified | Bouton rejet, dialogue custom, pagination, lightbox, feedback zone |
| `src/web/templates/validation/_candidate_card.html` | Modified | Bouton Valider HTMX, poster zoomable |
| `src/web/templates/validation/_search_form.html` | Created | Formulaires recherche titre et ID avec auto-scroll |
| `src/web/templates/validation/_search_results.html` | Created | Fragment résultats de recherche avec candidate cards |
| `src/web/static/css/style.css` | Modified | Styles actions, pagination, dialogue, lightbox, zoom hint |
| `pyproject.toml` | Modified | Ajout python-multipart |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 2 | Mineurs |
| Scope additions | 3 | Améliorations UX |
| Deferred | 0 | - |

**Total impact:** Améliorations UX significatives suite au feedback utilisateur

### Auto-fixed Issues

**1. python-multipart manquant**
- **Issue:** FastAPI Form() requiert python-multipart
- **Fix:** Installation + ajout pyproject.toml

**2. Feedback invisible (hx-target en haut de page)**
- **Issue:** Le div #action-feedback était en haut, invisible si scrollé
- **Fix:** hx-target="closest .candidate-card" pour remplacer la carte inline

### Scope Additions (suite au feedback utilisateur)

1. **Pagination** : navigation entre pages de 10 candidats (non prévu dans le plan)
2. **Dialogue de rejet custom** : remplace le hx-confirm natif, dans le thème, avec explication
3. **Zoom poster** : lightbox plein écran au clic sur l'affiche

## Skill Audit

Skill audit: All required skills invoked ✓
- /frontend-design : invoqué pour les styles des interactions

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Feedback validation invisible | Changé hx-target vers carte elle-même + HX-Redirect |
| Rejet confus (quoi est rejeté ?) | Dialogue custom + bouton renommé "Ignorer ce fichier" |
| Recherche : résultats non visibles | Auto-scroll via hx-on::after-request |

## Next Phase Readiness

**Ready:**
- Validation visuelle complète : l'utilisateur peut valider, rejeter, rechercher manuellement
- Les fichiers validés sont en statut VALIDATED en base, prêts pour le transfert (Phase 4)
- Le workflow process existe côté CLI, prêt à être exposé en web (Phase 3)

**Concerns:**
- L'enrichissement synchrone peut être lent avec beaucoup de candidats (atténué par la pagination)

**Blockers:**
- None

---
*Phase: 02-validation-visuelle, Plan: 02*
*Completed: 2026-02-23*
