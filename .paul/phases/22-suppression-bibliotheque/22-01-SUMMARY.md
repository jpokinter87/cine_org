---
phase: 22-suppression-bibliotheque
plan: 01
subsystem: ui, api, database
tags: [fastapi, htmx, jinja2, sqlite, trash, batch-delete, sessionStorage]

requires:
  - phase: 20-navigation-affichage
    provides: bibliothèque avec filtres, grille jaquettes, thème sombre
  - phase: 13-refactoring-code
    provides: package library/ découpé en sous-modules
provides:
  - Suppression batch avec corbeille provisoire réversible
  - Filtres enrichis (langue, sans fichier, sans poster)
  - Mode sélection avec persistance sessionStorage
  - Page corbeille (consultation, restauration, vidage définitif)
  - Sécurité localhost (suppression/restauration/vidage bloqués en distant)
affects: []

tech-stack:
  added: []
  patterns: [sessionStorage persistence, localhost security check, JSON model serialization]

key-files:
  created:
    - src/web/routes/library/delete.py
    - src/web/routes/library/trash.py
    - src/web/static/js/delete.js
    - src/web/templates/library/trash.html
    - src/infrastructure/persistence/repositories/trash_repository.py
  modified:
    - src/web/routes/library/browse.py
    - src/web/templates/library/index.html
    - src/web/templates/library/_filters.html
    - src/web/static/css/style.css
    - src/web/routes/library/__init__.py
    - src/infrastructure/persistence/repositories/__init__.py
    - src/container.py

key-decisions:
  - "Corbeille provisoire réversible avant suppression physique"
  - "Suppression restreinte à la machine maître (localhost only)"
  - "sessionStorage pour persistance sélection entre pages"
  - "Cascade série : _series_trash_id dans metadata_json épisodes"
  - "Restauration DB only — symlinks recréés via repair-links/cleanup"

patterns-established:
  - "Localhost security check: _LOCAL_HOSTS + request.client.host + 403"
  - "JSON serialization complète pour restauration fidèle des modèles"
  - "sessionStorage + htmx:afterSwap pour état UI persistant"

duration: ~3h
started: 2026-02-27
completed: 2026-02-27
---

# Phase 22 Plan 01: Corbeille + suppression + restauration Summary

**Suppression batch depuis la bibliothèque avec filtres enrichis, mode sélection visuel, corbeille provisoire réversible, et sécurité localhost.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~3h |
| Started | 2026-02-27 |
| Completed | 2026-02-27 |
| Tasks | 3 (2 auto + 1 checkpoint) |
| Files created | 5 |
| Files modified | 7 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Filtres enrichis | Pass | Langue, sans fichier, sans poster fonctionnels. Langue exclut les séries (pas de languages_json au niveau série). |
| AC-2: Mode sélection avec cases à cocher | Pass | Checkboxes sur jaquettes, compteur flottant, persistance sessionStorage entre pages. |
| AC-3: Suppression par lot vers corbeille | Pass | Symlinks supprimés, storage conservé, cascade série complète. |
| AC-4: Page corbeille | Pass | Consultation, restauration individuelle (avec cascade série), vidage définitif avec confirmation. |

## Accomplishments

- Workflow complet filtrage → sélection → suppression → corbeille → restauration/vidage
- Sécurité : bouton masqué + routes bloquées (403) pour les clients distants
- Cascade bidirectionnelle séries : suppression et restauration incluent tous les épisodes
- Sérialisation JSON complète des modèles pour restauration fidèle

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/routes/library/delete.py` | Created | Route POST /library/delete-batch avec sécurité localhost |
| `src/web/routes/library/trash.py` | Created | Routes corbeille : consultation, restauration, vidage |
| `src/web/static/js/delete.js` | Created | Mode sélection JS avec persistance sessionStorage |
| `src/web/templates/library/trash.html` | Created | Page corbeille avec liste, restauration, vidage |
| `src/infrastructure/persistence/repositories/trash_repository.py` | Created | CRUD sur TrashModel |
| `src/web/routes/library/browse.py` | Modified | 3 filtres ajoutés (langue, no_file, no_poster) + is_local |
| `src/web/templates/library/index.html` | Modified | Bouton sélection, barre flottante, overlay confirmation |
| `src/web/templates/library/_filters.html` | Modified | Select langue, checkboxes sans fichier/poster |
| `src/web/static/css/style.css` | Modified | ~300 lignes : mode sélection, barre flottante, page corbeille |
| `src/web/routes/library/__init__.py` | Modified | Enregistrement routers delete + trash |
| `src/infrastructure/persistence/repositories/__init__.py` | Modified | Export SQLModelTrashRepository |
| `src/container.py` | Modified | Factory trash_repository |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Corbeille provisoire | Filet de sécurité — suppression physique uniquement au vidage | Restauration possible tant que corbeille non vidée |
| Localhost only | Suppression = acte grave, doit être restreint à la machine maître | Bouton masqué + 403 en distant |
| sessionStorage | Persistance sélection entre navigation fiche détail et retour | État survit aux changements de page sans polluer localStorage |
| Restauration sans symlinks | Recréer les symlinks nécessite OrganizerService + contexte complexe | Symlinks régénérables via repair-links/cleanup existants |
| _series_trash_id | Lien épisodes→série dans metadata_json trash | Restauration groupée fidèle |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 2 | Corrections mineures, fonctionnalité préservée |
| Scope additions | 1 | Sécurité localhost (demande utilisateur) |
| Deferred | 0 | - |

**Total impact:** Corrections essentielles + sécurité ajoutée à la demande, pas de scope creep.

### Auto-fixed Issues

**1. Filtre langue excluait pas les séries**
- **Found during:** Task 3 (checkpoint)
- **Issue:** Quand le filtre langue était actif avec type=all, les séries (sans languages_json) diluaient les résultats
- **Fix:** Ajout `and not language` et `and not no_file` à la condition d'exclusion séries dans browse.py
- **Verification:** Utilisateur confirme filtre langue fonctionnel

**2. Sélection perdue à la navigation**
- **Found during:** Task 3 (checkpoint)
- **Issue:** État sélection en mémoire JS uniquement, perdu au changement de page
- **Fix:** Réécriture delete.js avec persistance sessionStorage (save/load/clear)
- **Verification:** Utilisateur confirme persistance entre pages

### Scope Addition

**Sécurité localhost (demande utilisateur)**
- **Rationale:** "La suppression est un acte grave et irréversible. Elle ne devrait être possible que depuis la machine maître."
- **Implementation:** `_LOCAL_HOSTS` check sur toutes les routes destructives + `is_local` dans templates
- **Impact:** Positif — sécurité renforcée sans complexité excessive

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Ruff F401 unused imports | Supprimés (get_session dans trash_repo, json dans trash.py) |
| Ruff E402 import order | _LOCAL_HOSTS déplacé après les imports dans delete.py |
| Filtre langue inopérant | Séries exclues quand filtre technique actif |
| Sélection non persistante | sessionStorage avec save/load/clear |

## Skill Audit

Skill audit: All required skills invoked ✓
- /frontend-design : invoqué avant Task 2 (templates + CSS)

## Next Phase Readiness

**Ready:**
- Phase 22 complète — suppression et corbeille opérationnels
- Prêt pour Phase 23 (Lectures Simultanées)

**Concerns:**
- Filtre langue ne s'applique pas aux séries (limitation structurelle, pas bloquant)
- Test depuis machine distante non effectué (différé — vérifier bouton masqué + 403)

**Blockers:**
- None

---
*Phase: 22-suppression-bibliotheque, Plan: 01*
*Completed: 2026-02-27*
