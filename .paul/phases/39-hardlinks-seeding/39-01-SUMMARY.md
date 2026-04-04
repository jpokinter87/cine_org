---
phase: 39-hardlinks-seeding
plan: 01
subsystem: transfer
tags: [hardlink, seeding, bittorrent, scanner, sqlite]

requires:
  - phase: 38-deploiement-production
    provides: pipeline de transfert stable
provides:
  - HardlinkModel (table SQLite hardlinks)
  - Hardlinks automatiques dans transfer_file()
  - Filtre scanner st_nlink pour ignorer les hardlinks
affects: [39-02 purge service, transfer workflow]

tech-stack:
  added: []
  patterns: [hardlink seeding post-transfer, nlink filtering]

key-files:
  created:
    - tests/unit/test_hardlink_transfer.py
  modified:
    - src/infrastructure/persistence/models.py
    - src/config.py
    - src/services/transferer.py
    - src/adapters/file_system.py
    - src/services/scanner.py
    - tests/unit/services/test_transferer.py

key-decisions:
  - "Session DB directe dans _create_seeding_hardlink (pas de changement de signature)"
  - "st_nlink > 1 comme filtre scanner (simple, pas de requête DB)"
  - "Hardlink non bloquant : fallback gracieux si cross-device ou DB indisponible"

patterns-established:
  - "Hardlink créé dans transfer_file() — point unique CLI+web"
  - "stat() unique combinant nlink + size dans list_video_files()"

duration: 15min
started: 2026-04-04T15:10:00Z
completed: 2026-04-04T15:25:00Z
---

# Phase 39 Plan 01: Hardlinks Seeding — Modèle DB + Transfert + Scanner

**Hardlinks automatiques dans downloads/ après transfert vers storage/ pour maintenir le seeding BitTorrent, avec filtre scanner nlink et registre SQLite.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15min |
| Tasks | 3 completed |
| Files modified | 7 |
| Tests | 1067 passent (8 nouveaux) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Hardlink créé après transfert | Pass | os.link(storage, download) + entrée HardlinkModel |
| AC-2: Fallback gracieux si cross-device | Pass | OSError capturé, warning loggé, transfert OK |
| AC-3: Scanner ignore les hardlinks | Pass | st_nlink > 1 dans list_video_files + fallback |

## Accomplishments

- `HardlinkModel` en SQLite avec download_path, storage_path, created_at, expires_at
- `_create_seeding_hardlink()` dans TransfererService — point unique CLI+web, non bloquant
- Filtre `st_nlink > 1` optimisé (stat() unique avec check taille) dans FileSystemAdapter et scanner fallback
- 8 tests couvrant création, enregistrement DB, fallback cross-device, fallback DB, et filtrage scanner

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/infrastructure/persistence/models.py` | Modified | Ajout HardlinkModel |
| `src/config.py` | Modified | Ajout hardlink_retention_days (30j) |
| `src/services/transferer.py` | Modified | _create_seeding_hardlink() après atomic_move |
| `src/adapters/file_system.py` | Modified | Filtre st_nlink > 1 dans list_video_files |
| `src/services/scanner.py` | Modified | Filtre st_nlink > 1 dans fallback |
| `tests/unit/test_hardlink_transfer.py` | Created | 8 tests hardlinks |
| `tests/unit/services/test_transferer.py` | Modified | Adaptation test_success_with_symlink |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Session DB directe (pas de param) | Cohérent avec _update_file_paths, pas de changement de signature | Zéro impact sur les appelants |
| st_nlink > 1 pour le scanner | Un stat() suffit, pas de requête DB | Simple et performant |
| Stat unique (nlink + size) | Évite double appel stat() | Optimisation mineure |

## Deviations from Plan

### Auto-fixed Issues

**1. Import `field` inutilisé dans transferer.py**
- **Found during:** Task 2
- **Fix:** Supprimé `field` de l'import dataclasses (déjà absent avant, ajouté par erreur)
- **Verification:** ruff check clean

**2. Test existant test_success_with_symlink**
- **Found during:** Task 3 (suite de tests complète)
- **Issue:** Le test vérifiait `not source.exists()` — incompatible avec le hardlink
- **Fix:** Remplacé par vérification que source existe ET partage le même inode que destination
- **Verification:** 1067 tests passent

### Deferred Items

None.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Lazy imports dans _create_seeding_hardlink empêchent le patch classique | Patch sur les modules source (database.get_engine, sqlmodel.Session) |

## Next Phase Readiness

**Ready:**
- HardlinkModel en place, prêt pour le service de purge (plan 39-02)
- Table hardlinks sera auto-créée au premier démarrage
- Config hardlink_retention_days accessible via Settings()

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 39-hardlinks-seeding, Plan: 01*
*Completed: 2026-04-04*
