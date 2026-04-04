---
phase: 39-hardlinks-seeding
plan: 02
subsystem: transfer
tags: [hardlink, purge, cli, systemd, timer]

requires:
  - phase: 39-01
    provides: HardlinkModel, config hardlink_retention_days
provides:
  - HardlinkService (purge, list, stats)
  - Commande CLI purge-hardlinks
  - Timer systemd cineorg-purge.timer
affects: [deploy]

tech-stack:
  added: []
  patterns: [oneshot systemd timer, purge avec nettoyage dossiers]

key-files:
  created:
    - src/services/hardlink_service.py
    - src/adapters/cli/commands/hardlink_commands.py
    - deploy/cineorg-purge.service
    - deploy/cineorg-purge.timer
    - tests/unit/test_hardlink_service.py
  modified:
    - src/container.py
    - src/main.py
    - src/adapters/cli/commands/__init__.py

key-decisions:
  - "Purge via select+unlink+rmdir (pas de bulk delete SQL)"
  - "Nettoyage dossiers vides remonte jusqu'à downloads_dir"
  - "Timer avec RandomizedDelaySec=300 pour éviter charge simultanée"

patterns-established:
  - "Service autonome avec get_engine() direct (pas injecté)"
  - "Commande CLI oneshot pour timer systemd"

duration: 10min
started: 2026-04-04T15:25:00Z
completed: 2026-04-04T15:35:00Z
---

# Phase 39 Plan 02: Hardlinks Seeding — Purge + CLI + Timer

**Service de rotation des hardlinks avec commande CLI purge-hardlinks (--dry-run, --force) et timer systemd quotidien.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~10min |
| Tasks | 3 completed |
| Files created | 5 |
| Files modified | 3 |
| Tests | 1075 passent (8 nouveaux) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Purge des hardlinks expirés | Pass | unlink + rmdir parents + delete DB |
| AC-2: Commande CLI purge-hardlinks | Pass | --dry-run, --force, affichage Rich |
| AC-3: Timer systemd quotidien | Pass | cineorg-purge.timer + service oneshot |

## Accomplishments

- `HardlinkService` avec purge_expired (dry-run/force), list_active, get_stats
- Commande CLI `cineorg purge-hardlinks` avec affichage Rich (stats, table, erreurs)
- Timer systemd `cineorg-purge.timer` quotidien avec Persistent=true et RandomizedDelaySec
- 8 tests couvrant purge, dry-run, force, fichier absent, dossiers vides, stats

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/services/hardlink_service.py` | Created | Service purge/list/stats |
| `src/adapters/cli/commands/hardlink_commands.py` | Created | Commande CLI |
| `deploy/cineorg-purge.service` | Created | Service systemd oneshot |
| `deploy/cineorg-purge.timer` | Created | Timer quotidien |
| `tests/unit/test_hardlink_service.py` | Created | 8 tests unitaires |
| `src/container.py` | Modified | Provider hardlink_service |
| `src/main.py` | Modified | Enregistrement commande |
| `src/adapters/cli/commands/__init__.py` | Modified | Export purge_hardlinks |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| get_engine() direct dans service | Cohérent avec plan 01, pas d'injection complexe | Simple et fonctionnel |
| RandomizedDelaySec=300 | Évite pic de charge si plusieurs timers au même moment | Purge entre 00:00 et 00:05 |
| rmdir en boucle ascendante | Supprime tous les dossiers vides, s'arrête au premier non-vide | Nettoyage propre |

## Deviations from Plan

None — plan exécuté exactement comme spécifié.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- Phase 39 complète : hardlinks seeding opérationnel de bout en bout
- Timer systemd prêt à installer sur le serveur
- Phase 40 (Jellyfin) peut commencer

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 39-hardlinks-seeding, Plan: 02*
*Completed: 2026-04-04*
