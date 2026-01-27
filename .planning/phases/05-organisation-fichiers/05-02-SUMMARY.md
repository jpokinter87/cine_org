---
phase: 05
plan: 02
subsystem: file-organization
tags: [transfer, atomic-move, symlinks, conflict-detection, hash]
dependency-graph:
  requires: [05-01]
  provides: [TransfererService, atomic_move, symlink_creation]
  affects: [06-cli]
tech-stack:
  added: []
  patterns: [Protocol, rollback, atomic-operation]
key-files:
  created:
    - src/services/transferer.py
    - tests/unit/services/test_transferer.py
  modified:
    - src/adapters/file_system.py
    - src/container.py
decisions: []
metrics:
  duration: 4 min
  completed: 2026-01-27
---

# Phase 5 Plan 2: Service Transfert Atomique Summary

**One-liner:** TransfererService avec deplacement atomique, detection de conflits via hash XXH3-64, et symlinks relatifs vers storage/

## What Was Built

### TransfererService (src/services/transferer.py)

Service de transfert de fichiers avec:
- **check_conflict()**: Detection de conflits via hash xxhash
  - `ConflictType.DUPLICATE`: meme hash = fichier identique
  - `ConflictType.NAME_COLLISION`: meme nom mais contenu different
- **transfer_file()**: Deplacement atomique avec rollback
  - Verification de conflit avant deplacement
  - Deplacement via atomic_move
  - Creation symlink optionnelle
  - Rollback si erreur apres le move
- **_create_mirror_symlink()**: Symlinks relatifs dans video/
  - Structure miroir de storage/
  - Chemins relatifs via os.path.relpath (Python 3.11 compatible)

### FileSystemAdapter Extension (src/adapters/file_system.py)

Nouvelle methode **atomic_move()**:
- `os.replace` pour meme filesystem (atomique)
- Fallback staged copy pour cross-filesystem
- Fichier temporaire unique pour eviter les collisions
- Nettoyage du temp en cas d'erreur

### Integration DI (src/container.py)

Nouveaux providers:
- `renamer_service`: Singleton
- `organizer_service`: Singleton
- `quality_scorer_service`: Singleton
- `transferer_service`: Factory (necessite storage_dir, video_dir)

## Key Patterns

### Protocol pour IAtomicFileSystem

Utilisation de `typing.Protocol` au lieu d'importer les interfaces ports:
```python
class IAtomicFileSystem(Protocol):
    def exists(self, path: Path) -> bool: ...
    def atomic_move(self, source: Path, destination: Path) -> bool: ...
```

Avantages:
- Pas de dependance cyclique avec ports
- Duck typing explicite
- Facile a mocker dans les tests

### Rollback Pattern

En cas d'erreur apres le move, tentative de rollback:
```python
try:
    symlink_path = self._create_mirror_symlink(destination)
except Exception as e:
    # Rollback: remettre le fichier a sa position originale
    try:
        self._fs.atomic_move(destination, source)
    except Exception:
        pass  # Le rollback peut echouer
    return TransferResult(success=False, error=str(e))
```

### Relative Symlinks (Python 3.11)

Utilise `os.path.relpath` au lieu de `Path.relative_to(walk_up=True)`:
```python
target_relative = os.path.relpath(storage_path, symlink_path.parent)
symlink_path.symlink_to(target_relative)
```

## Deviations from Plan

None - plan executed exactly as written.

## Test Coverage

17 tests added for TransfererService:
- TestCheckConflict (3 tests): detection de conflits
- TestTransferFileReal (4 tests): integration avec fichiers reels
- TestTransferFileMocked (2 tests): scenarios d'erreur
- TestRelativeSymlinks (3 tests): creation symlinks relatifs
- TestAtomicMove (4 tests): atomic_move dans FileSystemAdapter
- TestRollback (1 test): rollback apres erreur

Total tests Phase 5: 141 tests passing
Total tests projet: 266 tests passing

## Commits

| Hash | Type | Description |
|------|------|-------------|
| d068424 | test | add failing tests for TransfererService |
| f459a91 | feat | implement TransfererService with atomic move and symlinks |
| f7272aa | feat | integrate Phase 5 services into DI container |

## Files Modified

| File | Lines | Description |
|------|-------|-------------|
| src/services/transferer.py | 232 | TransfererService complet |
| src/adapters/file_system.py | 269 | +atomic_move method |
| src/container.py | 110 | +4 service providers |
| tests/unit/services/test_transferer.py | 268 | 17 tests |

## Next Phase Readiness

Phase 5 (Organisation Fichiers) complete:
- [x] 05-01: RenamerService, OrganizerService, QualityScorerService
- [x] 05-02: TransfererService avec atomic move et symlinks

Ready for Phase 6 (CLI Interface):
- Tous les services de renommage et organisation disponibles via DI
- TransfererService pret pour l'integration CLI
- 266 tests passants, couverture adequate
