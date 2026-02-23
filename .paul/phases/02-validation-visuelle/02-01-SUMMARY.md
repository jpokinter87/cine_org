---
phase: 02-validation-visuelle
plan: 01
subsystem: ui
tags: [fastapi, jinja2, htmx, tmdb, tvdb, validation, poster]

requires:
  - phase: 01-foundation-web
    provides: FastAPI app, lifespan DI, base layout, CSS theme, deps.py pattern
provides:
  - Routes GET /validation et GET /validation/{id}
  - Templates liste pending + détail candidats enrichis
  - Composant _candidate_card réutilisable (HTMX-ready)
affects: [02-02 interactions HTMX]

tech-stack:
  added: []
  patterns:
    - "Enrichissement API dans la route (get_details pour chaque candidat)"
    - "Template partiel _candidate_card.html avec data-attributes pour HTMX"

key-files:
  created:
    - src/web/routes/validation.py
    - src/web/templates/validation/list.html
    - src/web/templates/validation/detail.html
    - src/web/templates/validation/_candidate_card.html
    - src/web/templates/validation/not_found.html
  modified:
    - src/web/app.py
    - src/web/static/css/style.css

key-decisions:
  - "Enrichissement synchrone dans la route (pas de cache intermédiaire)"
  - "Limite à 10 candidats enrichis par page détail"
  - "data-candidate-id et data-source sur les cards pour préparer 02-02"

patterns-established:
  - "Route validation suit le même pattern DI que home (request.app.state.container)"
  - "Templates validation dans sous-répertoire validation/ avec partials _prefixed"
  - "Score classes: score-high (>=85), score-medium (>=60), score-low (<60)"

duration: ~90min
started: 2026-02-23T15:00:00Z
completed: 2026-02-23T16:30:00Z
---

# Phase 2 Plan 01: Routes et templates validation visuelle — Summary

**Pages de validation avec liste pending et détail candidats enrichis (jaquettes TMDB/TVDB, scores colorés, synopsis, cast, durée comparée)**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~90min |
| Tasks | 2 auto + 1 checkpoint |
| Files created | 5 |
| Files modified | 2 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Liste des fichiers en attente | Pass | GET /validation affiche les pending avec filename, type, candidats, score |
| AC-2: Page vide quand aucun pending | Pass | Message "Aucun fichier en attente" + lien accueil |
| AC-3: Détail avec candidats enrichis | Pass | Jaquettes, scores colorés, synopsis, cast, durée comparée |
| AC-4: Candidat non trouvé | Pass | GET /validation/999 → 404 avec message explicite |
| AC-5: Navigation cohérente | Pass | nav_validation active, lien retour sur la page détail |

## Accomplishments

- Routes validation fonctionnelles avec enrichissement API (jaquettes, synopsis, acteurs via TMDB/TVDB)
- Système de score coloré (vert/jaune/rouge) et comparaison de durée fichier vs API
- Templates HTMX-ready avec data-attributes sur les candidate cards pour le plan 02-02

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/routes/validation.py` | Created | Routes GET /validation et /validation/{id} avec enrichissement API |
| `src/web/templates/validation/list.html` | Created | Liste des fichiers pending avec badges et scores |
| `src/web/templates/validation/detail.html` | Created | Détail fichier avec grille de candidats enrichis |
| `src/web/templates/validation/_candidate_card.html` | Created | Carte candidat réutilisable (poster, score, synopsis, cast) |
| `src/web/templates/validation/not_found.html` | Created | Page 404 pour pending inexistant |
| `src/web/app.py` | Modified | Ajout include du router validation |
| `src/web/static/css/style.css` | Modified | Styles validation : pending-list, candidate-card, score/source badges, responsive |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Enrichissement dans la route | Simple et suffisant pour le volume attendu (<100 pending) | Peut être lent si beaucoup de candidats ; acceptable pour v1 |
| Limite 10 candidats enrichis | Éviter des dizaines d'appels API par page | Affichage tronqué avec message si >10 |
| data-attributes HTMX-ready | Préparer les interactions du plan 02-02 sans code mort | Pas de JS/HTMX actif dans ce plan |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Mineur |
| Scope additions | 1 | Mineur |
| Deferred | 0 | - |

**Total impact:** Ajouts mineurs cohérents avec l'objectif

### Auto-fixed Issues

**1. TestClient lifespan**
- **Found during:** Task 2 (vérification)
- **Issue:** `TestClient(app)` sans context manager ne déclenche pas le lifespan → AttributeError
- **Fix:** Utilisation de `with TestClient(app) as client:` dans les vérifications
- **Verification:** Tests passent correctement

### Scope Additions

**1. Template not_found.html**
- Ajout d'une page 404 dédiée (non explicitement dans le plan mais requis par AC-4)

## Skill Audit

Skill audit: All required skills invoked ✓
- /frontend-design : invoqué pour Task 2 (styles CSS validation)

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Fichiers test auto-validés (score >= 85%) | Reset manuel du status en DB pour tester l'UI |

## Next Phase Readiness

**Ready:**
- Templates candidate cards ont les data-attributes pour HTMX (data-candidate-id, data-source)
- Routes retournent les données enrichies nécessaires aux interactions
- CSS prêt pour les boutons d'action (placeholder dans le design)

**Concerns:**
- L'enrichissement synchrone pourrait ralentir si beaucoup de candidats ; à surveiller

**Blockers:**
- None

---
*Phase: 02-validation-visuelle, Plan: 01*
*Completed: 2026-02-23*
