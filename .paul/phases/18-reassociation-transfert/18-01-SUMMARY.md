---
phase: 18-reassociation-transfert
plan: 01
subsystem: ui, service
tags: [htmx, validation, transfer, sqlalchemy]

requires:
  - phase: 17-visionner-surprends-moi
    provides: bouton Visionner sur page Surprends-moi
provides:
  - Route POST /transfer/send-back/{pending_id}
  - Méthode ValidationService.reset_to_pending()
  - Bouton "Renvoyer en validation" sur chaque fichier page transfert
  - Cascade inverse séries (renvoi de tous les épisodes)
  - Dialogues custom remplacement confirm() natif
  - Fix NullPool pour SQLite (QueuePool exhaustion)
affects: [config/player_profiles.html]

tech-stack:
  added: []
  patterns: [NullPool pour SQLite, dialogues overlay custom]

key-files:
  created: []
  modified:
    - src/services/validation.py
    - src/web/routes/transfer.py
    - src/web/templates/transfer/_batch_tree.html
    - src/web/templates/transfer/index.html
    - src/web/templates/config/player_profiles.html
    - src/web/static/css/style.css
    - src/infrastructure/persistence/database.py
    - tests/unit/services/test_validation.py

key-decisions:
  - "NullPool pour SQLite — supprime le QueuePool qui s'épuisait avec providers.Factory"
  - "Cascade inverse séries : renvoyer un épisode renvoie tous les épisodes du même candidat"
  - "Dialogues custom overlay au lieu de confirm() natif — cohérence charte graphique"
  - "Macro Jinja2 tree_leaf pour factoriser les 4 blocs identiques dans _batch_tree.html"

patterns-established:
  - "Pattern overlay dialogue : reject-overlay + reject-dialog (réutilisable partout)"

duration: ~45min
completed: 2026-02-26
---

# Phase 18 Plan 01: Ré-association Transfert — Page Transfert

**Bouton "Renvoyer en validation" par fichier sur la page transfert + fix systémique QueuePool + dialogues custom**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~45min |
| Completed | 2026-02-26 |
| Tasks | 3 completed (2 auto + 1 checkpoint) |
| Files modified | 8 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Bouton visible par fichier | Pass | Icône rose, visible au survol, feedback hover |
| AC-2: Renvoi en validation | Pass | reset_to_pending() + HX-Redirect /transfer |
| AC-3: Compteurs à jour | Pass | Page rechargée via HX-Redirect |
| AC-4: Tests unitaires | Pass | 2 tests TestResetToPending (890 total) |

## Accomplishments

- `ValidationService.reset_to_pending()` : remet status=PENDING, selected_candidate_id=None, auto_validated=False
- Route `POST /transfer/send-back/{pending_id}` avec cascade inverse séries
- Bouton icône rose (accent-rose) par fichier dans _batch_tree.html (macro Jinja2)
- Dialogue custom overlay pour renvoi en validation (remplace confirm() natif)
- Dialogue custom overlay pour confirmation transfert (remplace confirm() natif)
- Dialogue custom overlay pour suppression profil lecteur config (remplace confirm() natif)
- Fix critique : `NullPool` pour SQLite dans database.py — résout définitivement le QueuePool exhaustion

## Files Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/services/validation.py` | Modified | reset_to_pending() + nettoyage list_validated() |
| `src/web/routes/transfer.py` | Modified | Route send-back + pending_id dans tree_data |
| `src/web/templates/transfer/_batch_tree.html` | Modified | Macro tree_leaf + bouton sendback |
| `src/web/templates/transfer/index.html` | Modified | Dialogues overlay sendback + transfert |
| `src/web/templates/config/player_profiles.html` | Modified | Dialogue overlay suppression profil |
| `src/web/static/css/style.css` | Modified | Styles tree-leaf-sendback (rose) |
| `src/infrastructure/persistence/database.py` | Modified | NullPool pour SQLite |
| `tests/unit/services/test_validation.py` | Modified | 2 tests TestResetToPending |

## Deviations from Plan

| Deviation | Reason |
|-----------|--------|
| Cascade inverse séries ajoutée | Demande utilisateur — miroir de l'auto-validation cascade |
| Dialogues custom overlay (3) | Demande utilisateur — remplacement de tous les confirm() natifs |
| Fix NullPool database.py | Bug critique découvert pendant le test |

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| QueuePool exhaustion (systémique) | NullPool pour SQLite — connexions créées/fermées à la demande |
| confirm() natif hors charte | Dialogues overlay custom (pattern reject-overlay) |

## Next Phase Readiness

**Ready:**
- Plan 18-02 prêt (section auto-validés sur page /validation)
- reset_to_pending() disponible pour réutilisation

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 18-reassociation-transfert, Plan: 01*
*Completed: 2026-02-26*
