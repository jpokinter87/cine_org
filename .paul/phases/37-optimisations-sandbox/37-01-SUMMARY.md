---
phase: 37-optimisations-sandbox
plan: 01
subsystem: cleanup, web
tags: [cross-genre, db-query, trash, maintenance, symlinks]

requires:
  - phase: 36-doublons-symlinks-cross-genre
    provides: scan_cross_genre_duplicates, symlink_path en DB
provides:
  - Détection cross-genre via requête DB (sans filesystem scan)
  - Section corbeille intégrée à la page maintenance
  - Règle combinatoire Comédie+Drame → Comédie dramatique
affects: [37-02 sandbox, cleanup, organizer]

tech-stack:
  added: []
  patterns: [DB-first avec fallback filesystem, genres protégés pour règle combinatoire]

key-files:
  created:
    - tests/unit/test_cross_genre_db.py
  modified:
    - src/services/cleanup/analyzers.py
    - src/services/cleanup/cleanup_service.py
    - src/infrastructure/persistence/repositories/movie_repository.py
    - src/web/routes/maintenance.py
    - src/web/templates/maintenance/index.html
    - src/services/organizer.py
    - src/utils/constants.py

key-decisions:
  - "DB-first cross-genre : requête symlink_path groupée par file_path, fallback filesystem si DB vide"
  - "Corbeille maintenance : routes dédiées /maintenance/trash/* (pas réutilisation directe de /trash)"
  - "Comédie+Drame → Comédie dramatique, sauf si genre protégé (Animation, SF, etc.) présent"
  - "174 films existants reclassés de Comédie/Drame vers Comédie dramatique"

patterns-established:
  - "_build_cross_genre_result() : factorisation logique keep/remove partagée entre DB et filesystem"
  - "Genres protégés : ensemble de genres qui priment sur les règles combinatoires"

completed: 2026-03-20
---

# Phase 37 Plan 01: Optimisation cross-genre DB + corbeille maintenance

**Détection cross-genre par requête DB au lieu de scan filesystem, section corbeille dans la page maintenance, et règle Comédie+Drame → Comédie dramatique avec reclassement de 174 films.**

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Cross-genre via DB | Pass | get_cross_genre_candidates() + _scan_cross_genre_via_db() |
| AC-2: Performance cross-genre | Pass | Requêtes DB indexées, aucun rglob/readlink |
| AC-3: Corbeille sur page maintenance | Pass | Section avec liste, restauration HTMX, vidage avec dialog confirmation |

## Accomplishments

- `scan_cross_genre_duplicates()` utilise la DB comme source primaire (requête symlink_path groupée par file_path), avec fallback filesystem automatique
- Section corbeille ajoutée à `/maintenance` avec restauration individuelle (HTMX), vidage avec spinner et dialog de confirmation, restriction localhost
- Règle combinatoire Comédie+Drame → Comédie dramatique intégrée dans `get_priority_genre()`, protégée par les genres prioritaires (Animation, SF, Fantastique, Horreur, etc.)
- 174 films existants reclassés de Comédie/Drame vers Comédie dramatique (symlinks déplacés, DB mise à jour)
- 9 tests unitaires ajoutés pour la détection DB, 1045 tests passent

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/services/cleanup/analyzers.py` | Modified | Refactoring en _scan_cross_genre_via_db() + _scan_cross_genre_via_filesystem() + _build_cross_genre_result() |
| `src/services/cleanup/cleanup_service.py` | Modified | Passe movie_repo à scan_cross_genre_duplicates() |
| `src/infrastructure/persistence/repositories/movie_repository.py` | Modified | Ajout get_cross_genre_candidates() |
| `src/web/routes/maintenance.py` | Modified | Chargement corbeille dans GET /maintenance, routes POST restore/empty |
| `src/web/templates/maintenance/index.html` | Modified | Section corbeille avec liste, restauration, vidage, spinner |
| `src/services/organizer.py` | Modified | Règle Comédie+Drame → Comédie dramatique dans get_priority_genre() |
| `src/utils/constants.py` | Modified | Mapping "comédie dramatique" dans GENRE_FOLDER_MAPPING |
| `tests/unit/test_cross_genre_db.py` | Created | 9 tests : DB, priorité, fallback, exception |

## Deviations from Plan

| Type | Count | Impact |
|------|-------|--------|
| Scope additions | 1 | Règle Comédie+Drame + reclassement 174 films (demande utilisateur) |

**Règle Comédie+Drame :** Ajoutée à la demande de l'utilisateur pendant l'exécution. Intégrée dans `get_priority_genre()` avec protection des genres prioritaires. 174 films reclassés.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Server 500 sur /maintenance après ajout routes | Redémarrage serveur (hot-reload insuffisant pour nouveaux imports) |
| _PROTECTED_GENRES cassait le test Le Parrain (Drame+Crime) | Limité la logique protégée au seul cas Comédie+Drame |

## Next Phase Readiness

**Ready:**
- Plan 37-02 (Sandbox orphelins + UI) peut démarrer
- Infrastructure DB cross-genre en place

**Concerns:**
- Aucun

**Blockers:**
- Aucun

---
*Phase: 37-optimisations-sandbox, Plan: 01*
*Completed: 2026-03-20*
