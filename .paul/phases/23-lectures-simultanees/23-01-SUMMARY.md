---
phase: 23-lectures-simultanees
plan: 01
subsystem: ui, player
tags: [htmx, popover, multi-profile, simultaneous-playback]

requires:
  - phase: 20-bibliotheque-web
    provides: player routes, play button UI, profile system
provides:
  - Sélecteur de profil lecteur intégré au bouton Visionner
  - Lectures simultanées sur différents profils
  - Statut de lecture avec nom du profil
affects: []

tech-stack:
  added: []
  patterns:
    - Jinja2 partial template with {% include %} for reusable play button
    - Jinja2 global function for cross-template data access
    - CSS-only popover with click-outside-to-close

key-files:
  created:
    - src/web/templates/library/_play_btn.html
  modified:
    - src/web/routes/library/player.py
    - src/player_profiles.py
    - src/web/deps.py
    - src/web/templates/base.html
    - src/web/templates/library/movie_detail.html
    - src/web/templates/library/series_detail.html
    - src/web/templates/library/suggest.html
    - src/web/static/css/style.css
    - tests/unit/test_player.py

key-decisions:
  - "Partial Jinja2 _play_btn.html plutôt que HTML généré 100% côté Python — séparation propre"
  - "get_player_profiles en Jinja2 global plutôt que passage en contexte route par route"
  - "Popover épisodes s'ouvre vers le bas (overflow:hidden du conteneur saison)"

patterns-established:
  - "Template partials réutilisables avec {% with %} + {% include %}"

duration: ~90min
started: 2026-02-28T14:00:00Z
completed: 2026-02-28T15:30:00Z
---

# Phase 23 Plan 01: Lectures Simultanées Summary

**Sélecteur de profil lecteur popover + lectures parallèles multi-profils avec statut nommé**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~90 min |
| Started | 2026-02-28 |
| Completed | 2026-02-28 |
| Tasks | 3 completed |
| Files modified | 10 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Sélecteur de profil au clic Visionner | Pass | Popover avec 4 profils, profil actif marqué "(défaut)" |
| AC-2: Lancement direct si profil unique | Pass | Backend prêt, non testé visuellement (user a 4 profils) |
| AC-3: Lectures simultanées sur différents profils | Partial | Backend OK (3-tuple tracking), test réel déféré (ordi Windows indisponible) |
| AC-4: Statut de lecture avec nom du profil | Pass | "Lecture en cours… (NomProfil)" affiché, bouton restauré correctement |

## Accomplishments

- Popover sélecteur de profil intégré sur films, épisodes et page Surprends-moi
- Backend multi-profil : `_active_players` étendu en 3-tuple (Popen, is_remote, profile_name)
- Template partiel `_play_btn.html` réutilisable via `{% include %}` — élimine la duplication
- Bouton correctement restauré après fin de lecture (onclick handlers dans le HTML Python)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/templates/library/_play_btn.html` | Created | Template partiel réutilisable pour bouton play + popover |
| `src/web/routes/library/player.py` | Modified | Multi-profil : 3-tuple, ?profile= param, popover HTML, onclick handlers |
| `src/player_profiles.py` | Modified | Ajout `get_profile_by_name()` |
| `src/web/deps.py` | Modified | Jinja2 global `get_player_profiles` |
| `src/web/templates/base.html` | Modified | Script click-outside-to-close pour popover |
| `src/web/templates/library/movie_detail.html` | Modified | Bouton play → include _play_btn.html |
| `src/web/templates/library/series_detail.html` | Modified | Bouton play épisodes → include _play_btn.html |
| `src/web/templates/library/suggest.html` | Modified | Bouton play → include _play_btn.html |
| `src/web/static/css/style.css` | Modified | Styles popover, animation, variante épisode (ouverture vers le bas) |
| `tests/unit/test_player.py` | Modified | Adapté pour 3-tuple return values |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Partial Jinja2 plutôt que HTML 100% Python | Séparation template/logique, maintenabilité | Les deux coexistent : Jinja2 pour rendu initial, Python pour restauration post-lecture |
| Jinja2 global pour profils | Évite de modifier chaque route pour passer les profils | Accessible partout sans changement de contexte |
| Popover épisodes vers le bas | `overflow: hidden` sur `.lib-season-group` tronquait le popover vers le haut | Flèche inversée, tous les profils visibles |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 2 | Bugs corrigés pendant vérification |
| Deferred | 1 | Test lecture simultanée Windows |

**Total impact:** Corrections essentielles, pas de scope creep

### Auto-fixed Issues

**1. Bouton inactif après fin de lecture**
- **Found during:** Task 3 (checkpoint human-verify)
- **Issue:** Le HTML généré par `_play_button_html()` n'avait pas les `onclick` handlers pour ouvrir le popover
- **Fix:** Ajout de `onclick="this.parentElement.classList.toggle('popover-open')"` et `onclick="event.stopPropagation()"` dans le HTML Python
- **Files:** `src/web/routes/library/player.py`
- **Verification:** User a confirmé le bouton redevient cliquable après lecture

**2. Popover épisodes tronqué (2 profils sur 4 visibles)**
- **Found during:** Task 3 (checkpoint human-verify)
- **Issue:** `.lib-season-group` a `overflow: hidden` (pour border-radius), le popover vers le haut dépassait
- **Fix:** Popover épisodes ouvre vers le bas (`top: calc(100% + 6px)`) avec flèche inversée
- **Files:** `src/web/static/css/style.css`
- **Verification:** User a confirmé les 4 profils visibles

### Deferred Items

- Test lectures simultanées sur profils différents (ordi Windows indisponible) — déjà dans deferred issues

## Issues Encountered

None

## Skill Audit

Skill audit: All required skills invoked ✓
- /frontend-design: invoked before Task 2 ✓

## Next Phase Readiness

**Ready:**
- Milestone v1.6 à 100% (4/4 phases complètes)
- Toutes les fonctionnalités prévues livrées

**Concerns:**
- Test lecture simultanée Windows reste déféré

**Blockers:**
- None

---
*Phase: 23-lectures-simultanees, Plan: 01*
*Completed: 2026-02-28*
