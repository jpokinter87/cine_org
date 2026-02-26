---
phase: 17-visionner-surprends-moi
plan: 01
subsystem: ui
tags: [htmx, player, fastapi, suggest]

requires:
  - phase: 16-lecteur-distant
    provides: player routes (movies/play, episodes/play), profils lecteur
provides:
  - Route POST /library/series/{id}/play (premier épisode)
  - Bouton Visionner sur page Surprends-moi (films et séries)
affects: []

tech-stack:
  added: []
  patterns: [réutilisation routes play existantes via entity_type dynamique]

key-files:
  created: []
  modified:
    - src/web/routes/library/player.py
    - src/web/templates/library/suggest.html
    - src/web/static/css/style.css
    - tests/unit/test_player.py

key-decisions:
  - "Route series/play cherche le premier épisode (S01E01) avec fichier"
  - "Bouton Visionner réutilise le cycle polling existant via entity_type=series"

patterns-established:
  - "Route play par type d'entité : movies/{id}/play, episodes/{id}/play, series/{id}/play"

duration: ~20min
completed: 2026-02-26
---

# Phase 17 Plan 01: Visionner Surprends-moi Summary

**Bouton Visionner intégré dans la page Surprends-moi — lance le lecteur directement pour films et séries (premier épisode S01E01)**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~20min |
| Completed | 2026-02-26 |
| Tasks | 3 completed |
| Files modified | 4 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Bouton Visionner films | Pass | Bouton HTMX, polling statut, restauration auto |
| AC-2: Bouton Visionner séries | Pass | Route series/{id}/play → premier épisode avec fichier |
| AC-3: Fichier introuvable | Pass | Message d'erreur temporaire avec restauration bouton |
| AC-4: Tests | Pass | 13/13 tests player (10 existants + 3 nouveaux), 888 total |

## Accomplishments

- Route `POST /library/series/{id}/play` : cherche le premier épisode avec file_path (tri season_number, episode_number ASC)
- Bouton Visionner dans suggest.html avec endpoint dynamique (`movies` ou `series` selon result.type)
- Styles CSS `.suggest-play-btn` adaptés au contexte des boutons d'action Surprends-moi

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/routes/library/player.py` | Modified | Route series_play + import SeriesModel/select |
| `src/web/templates/library/suggest.html` | Modified | Bouton Visionner dans suggest-actions |
| `src/web/static/css/style.css` | Modified | Styles suggest-play-btn, play-launched, play-error |
| `tests/unit/test_player.py` | Modified | 3 tests TestSeriesPlay |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Route series/play plutôt que passer episode_id au template | Évite de modifier _build_item() et la logique suggest | Plus propre, réutilisable |
| entity_type="series" pour le cycle polling | _play_button_html génère `/library/series/{id}/play` automatiquement | Pas de code spécial nécessaire |

## Deviations from Plan

None — plan exécuté exactement comme écrit.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Lint : variable `episode_id` inutilisée dans series_play | Supprimée (seul `file_path` nécessaire) |

## Next Phase Readiness

**Ready:**
- Phase 17 complète (1 seul plan)
- Le système de lecture est maintenant accessible depuis la bibliothèque, les fiches détail ET la page suggestion

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 17-visionner-surprends-moi, Plan: 01*
*Completed: 2026-02-26*
