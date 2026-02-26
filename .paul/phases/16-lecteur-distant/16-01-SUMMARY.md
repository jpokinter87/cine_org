---
phase: 16-lecteur-distant
plan: 01
subsystem: ui
tags: [player, ssh, config, subprocess]

requires: []
provides:
  - Lecteur configurable (programme, cible local/remote)
  - Lancement SSH avec mapping de chemins
  - Section Lecteur dans la page /config
affects:
  - 16-lecteur-distant/16-02 (profils lecteur)

tech-stack:
  added: []
  patterns:
    - "Lancement SSH via subprocess.Popen avec BatchMode=yes et ConnectTimeout=5"
    - "Feedback erreurs SSH via polling HTMX du status process"

key-files:
  modified:
    - src/config.py
    - src/web/routes/library/player.py
    - src/web/routes/config.py
    - src/web/templates/config/index.html
    - tests/unit/test_player.py

key-decisions:
  - "SSH BatchMode=yes pour éviter les prompts interactifs"
  - "Path mapping par remplacement de préfixe (simple et cross-platform)"
  - "Fallback local si SSH non configuré (gracious degradation)"

completed: 2026-02-26
---

# Phase 16 Plan 01: Lecteur Configurable — Summary

**Lecteur vidéo configurable avec support SSH distant et mapping de chemins cross-platform**

## Performance

| Metric | Value |
|--------|-------|
| Completed | 2026-02-26 |
| Tasks | 2 auto + 1 checkpoint |
| Files modified | 5 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Configuration lecteur local | Pass | player_command configurable, mpv/vlc testés |
| AC-2: Configuration lecteur distant SSH | Pass | SSH avec mapping chemins fonctionnel |
| AC-3: Fallback local si SSH non configuré | Pass | Tests unitaires couvrent les cas |
| AC-4: Section Lecteur dans /config | Pass | 6 champs éditables dans la page config |
| AC-5: Feedback visuel SSH | Pass | Messages d'erreur explicites (connexion refusée, auth, hostname) |

## Accomplishments

- 6 paramètres lecteur ajoutés à Settings (player_command, player_target, SSH host/user, préfixes chemins)
- player.py refactoré : _launch_local, _launch_ssh, _map_path avec détection d'erreurs SSH
- Section "Lecteur" dans /config avec tous les champs
- 10 tests unitaires (5 map_path + 5 launch_player)
- Testé avec succès sur machine Xubuntu distante (SSH + mpv)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/config.py` | Modified | 6 champs player_* ajoutés à Settings |
| `src/web/routes/library/player.py` | Modified | Support local + SSH + mapping chemins |
| `src/web/routes/config.py` | Modified | Section Lecteur dans _SECTIONS |
| `src/web/templates/config/index.html` | Modified | Icône play pour la section |
| `tests/unit/test_player.py` | Modified | 10 tests (map_path + launch_player) |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| BatchMode=yes + ConnectTimeout=5 | Évite blocages SSH interactifs | Erreurs rapides et claires |
| Mapping par préfixe simple | Cross-platform Linux→Linux et Linux→Windows | Suffisant pour NFS/SMB |
| Les 2 montages NFS nécessaires | Les symlinks se résolvent localement | Documenté pour l'utilisateur |

## Deviations from Plan

- /frontend-design non invoqué (section config utilise le pattern existant)
- Champs player_* ensuite retirés de Settings dans plan 16-02 (migration vers profils JSON)

## Next Phase Readiness

**Ready:**
- Base fonctionnelle pour le plan 16-02 (profils lecteur)

---
*Phase: 16-lecteur-distant, Plan: 01*
*Completed: 2026-02-26*
