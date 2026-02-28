---
phase: 26-corrections-ux-mineures
plan: 01
subsystem: ui
tags: [css, jinja2, popover, loguru, uvicorn, workflow]

requires:
  - phase: 23-lectures-simultanees
    provides: popover sélecteur de profil lecteur, player_profiles.py
provides:
  - Popover lecteur avec placement dynamique (dessous/dessus selon espace viewport)
  - Suppression automatique du profil "Migré" vestigiel
  - Bouton réinitialisation workflow web avec dialogue de confirmation
  - Logs serveur horodatés via loguru (uvicorn intercepté)
  - Tooltips résultats workflow click-to-toggle (à vérifier)
affects: [phase-27, phase-28]

tech-stack:
  added: []
  patterns:
    - "Popover position: absolute + JS getBoundingClientRect() pour flip dynamique"
    - "overflow:hidden retiré du conteneur parent pour permettre le débordement popover"
    - "Uvicorn logging via custom Handler → loguru (log_config dict)"
    - "Click-to-toggle pour tooltips avec listes scrollables"

key-files:
  modified:
    - src/web/static/css/style.css
    - src/web/templates/library/_play_btn.html
    - src/web/templates/base.html
    - src/player_profiles.py
    - src/web/routes/workflow.py
    - src/web/templates/workflow/index.html
    - src/web/templates/workflow/_results.html
    - src/web/templates/workflow/_progress.html
    - src/main.py

key-decisions:
  - "overflow:hidden retiré de .lib-season-group — cause racine du popover tronqué"
  - "position: absolute (pas fixed) — fixed cassé par transforms CSS parents"
  - "Click-to-toggle remplace hover pour tooltips scrollables"
  - "log_config dict au lieu de log_config=None pour uvicorn"

patterns-established:
  - "Popover dynamique : ouvrir en dessous, mesurer getBoundingClientRect(), flip si déborde"
  - "Filtrage profil vestigiel au chargement avec auto-persistance"

duration: ~90min
started: 2026-02-28T16:30:00Z
completed: 2026-02-28T18:00:00Z
---

# Phase 26 Plan 01: Corrections UX Mineures Summary

**Popover lecteur dynamique (dessous/dessus), profil Migré supprimé, reset workflow web, logs serveur horodatés**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~90min |
| Started | 2026-02-28 16:30 |
| Completed | 2026-02-28 18:00 |
| Tasks | 3 completed |
| Files modified | 9 |
| Tests | 891 passed |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Popover lecteur bien positionné | Pass | Placement dynamique : dessous par défaut, bascule au-dessus si débordement viewport |
| AC-2: Option "Migré" supprimée | Pass | Filtrage automatique au chargement + auto-persistance |
| AC-3: Réinitialisation workflow depuis le web | Pass | Bouton + dialogue confirmation + bulk delete SQL |
| AC-4: Logs serveur avec horodatage | Pass | Uvicorn routé via loguru avec log_config custom |

## Accomplishments

- Popover lecteur avec placement dynamique JS (dessous/dessus) — corrige le bug des épisodes en bas de liste tronqués
- Cause racine identifiée : `overflow: hidden` sur `.lib-season-group` empêchait le popover de déborder
- Suppression automatique du profil "Migré" (vestige migration .env) avec nettoyage JSON persisté
- Bouton "Réinitialiser" sur la page workflow web avec dialogue de confirmation overlay
- Logs serveur uvicorn horodatés via loguru (format `YYYY-MM-DD HH:MM:SS | LEVEL | ...`)
- Tooltips résultats workflow passés de hover à click-to-toggle (scrollable sans disparition)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/static/css/style.css` | Modified | Popover position: absolute + classes popover-above, overflow:hidden retiré de season-group, border-radius sur enfants, reset-btn, tooltip click-to-toggle |
| `src/web/templates/library/_play_btn.html` | Modified | onclick → togglePlayPopover(this) |
| `src/web/templates/base.html` | Modified | JS togglePlayPopover() dynamique + toggleResultTooltip() + fermeture click-outside |
| `src/player_profiles.py` | Modified | Suppression _migrate_from_env(), filtrage profil "Migré" au chargement |
| `src/web/routes/workflow.py` | Modified | Route POST /workflow/reset avec bulk delete SQL |
| `src/web/templates/workflow/index.html` | Modified | Bouton reset + dialogue confirmation overlay |
| `src/web/templates/workflow/_results.html` | Modified | onclick toggleResultTooltip pour click-to-toggle |
| `src/web/templates/workflow/_progress.html` | Modified | onclick toggleResultTooltip dans résultats SSE dynamiques |
| `src/main.py` | Modified | _LoguruInterceptHandler + log_config dict pour uvicorn |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Retirer overflow:hidden de .lib-season-group | Cause racine du popover tronqué — le conteneur clippe les éléments absolus | border-radius appliqué sur header/last-child à la place |
| position: absolute (pas fixed) | position: fixed déplacé par les transforms CSS des parents | Plus fiable avec l'architecture CSS existante |
| Click-to-toggle tooltips | Le hover perd le focus quand la souris bouge vers la scrollbar | Meilleure UX pour listes longues de fichiers |
| log_config dict plutôt que None | log_config=None supprime tout logging uvicorn | Dict préserve la config en routant vers loguru |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 3 | Corrections essentielles |
| Scope additions | 1 | Bonus UX |
| Deferred | 1 | À vérifier ultérieurement |

**Total impact:** Corrections nécessaires liées à la cause racine (overflow:hidden), plus un bonus UX tooltips

### Auto-fixed Issues

**1. overflow:hidden cause racine popover tronqué**
- **Found during:** Task 1 (checkpoint feedback)
- **Issue:** Le popover avec position: absolute était tronqué par overflow:hidden sur .lib-season-group
- **Fix:** Retiré overflow:hidden, appliqué border-radius sur enfants directs
- **Verification:** Popover visible sur tous les épisodes (haut et bas de liste)

**2. position: fixed cassé par transforms**
- **Found during:** Task 1 (tentative position: fixed)
- **Issue:** position: fixed utilise le viewport comme référence sauf si un parent a transform, ce qui décale les coordonnées
- **Fix:** Retour à position: absolute + détection viewport via getBoundingClientRect()
- **Verification:** Popover correctement positionné sur films et épisodes

**3. log_config=None supprime tout logging**
- **Found during:** Task 2 (checkpoint feedback)
- **Issue:** Passer log_config=None à uvicorn.run() supprime tous les loggers, pas juste le format
- **Fix:** Passer un dict log_config routant les loggers uvicorn vers un handler loguru
- **Verification:** Logs avec horodatage confirmés par l'utilisateur

### Scope Additions

**1. Tooltips workflow click-to-toggle**
- **Ajouté car:** L'utilisateur a signalé que les tooltips hover disparaissent quand on essaie de scroller
- **Change:** CSS :hover → JS click-to-toggle avec .tooltip-open class
- **Impact:** Meilleure UX, à vérifier avec des fichiers à traiter

### Deferred Items

- Vérification tooltips workflow click-to-toggle : pas de fichiers à traiter pour tester (à vérifier lors du prochain workflow)

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Popover toujours en dessous malgré JS | Cause racine : overflow:hidden clippe le popover avant qu'il ne déborde du viewport |
| position: fixed déplacé loin du bouton | Transforms CSS sur parents créent un nouveau containing block |
| Logs disparus après log_config=None | log_config dict avec handler custom au lieu de None |

## Next Phase Readiness

**Ready:**
- UX corrigée, prête pour Phase 27 (Performance & Robustesse Matching)
- Patterns popover dynamique réutilisables pour futurs composants

**Concerns:**
- Aucun

**Blockers:**
- None

---
*Phase: 26-corrections-ux-mineures, Plan: 01*
*Completed: 2026-02-28*
