---
phase: 31-detection-doublons
plan: 01
subsystem: cli
tags: [duplicates, quality-scorer, whitelist, tmdb-id, rich]

requires:
  - phase: 30-01
    provides: structure séries normalisée
provides:
  - Commande check-duplicates (détection par tmdb_id, scoring qualité, whitelist)
affects: [31-02-duplicates-web]

tech-stack:
  added: []
  patterns:
    - Reconstruction MediaInfo depuis champs string MovieModel
    - calculate_quality_score() en import direct (sans DI)
    - Whitelist JSON avec notes par tmdb_id

key-files:
  created:
    - src/adapters/cli/commands/duplicates_command.py
    - tests/unit/adapters/cli/test_duplicates.py
  modified:
    - src/adapters/cli/commands/__init__.py
    - src/main.py

key-decisions:
  - "Import direct calculate_quality_score plutôt que via DI — commande purement informative"
  - "Pas de --dry-run : la commande est toujours informative (pas d'action destructive)"
  - "Whitelist dans config/duplicates_whitelist.json avec notes explicatives par tmdb_id"

patterns-established:
  - "Reconstruction MediaInfo depuis strings DB pour scoring sans appel mediainfo"

duration: ~30min
started: 2026-03-01T17:40:00Z
completed: 2026-03-01T18:10:00Z
---

# Phase 31 Plan 01: Commande check-duplicates — Summary

**Commande CLI check-duplicates : détection des films en double par tmdb_id avec scoring qualité multi-critères et whitelist**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30min |
| Started | 2026-03-01 17:40 |
| Completed | 2026-03-01 18:10 |
| Tasks | 2 completed |
| Files created | 2 |
| Files modified | 2 |
| Tests | 29 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Détection par tmdb_id | Pass | 6 groupes détectés sur la DB réelle |
| AC-2: Comparaison de qualité | Pass | Scoring via calculate_quality_score, ★ sur la meilleure version |
| AC-3: Whitelist | Pass | Ajout/suppression/filtrage fonctionnels, section séparée |
| AC-4: Mode verbose | Pass | --verbose affiche le détail des scores par critère |
| AC-5: Tests unitaires | Pass | 29 tests passent (BuildMediaInfo, Scoring, Whitelist, Formatters) |

## Accomplishments

- **check-duplicates** : commande complète de détection des doublons par GROUP BY tmdb_id
- Scoring qualité via `calculate_quality_score` existant, avec reconstruction MediaInfo depuis les champs string de MovieModel
- Whitelist JSON avec gestion via --whitelist-add/remove et notes explicatives
- Affichage Rich soigné : tables par groupe, indicateur ★, résumé Panel avec taille récupérable
- 6 doublons réels détectés sur la vidéothèque (dont des cas de mauvaise association TMDB)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/adapters/cli/commands/duplicates_command.py` | Created | Commande check-duplicates |
| `tests/unit/adapters/cli/test_duplicates.py` | Created | 29 tests unitaires |
| `src/adapters/cli/commands/__init__.py` | Modified | Export check_duplicates |
| `src/main.py` | Modified | Enregistrement commande CLI |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Pas de --dry-run | Commande purement informative, pas d'action destructive | Interface simplifiée |
| Import direct calculate_quality_score | Pas besoin du container DI pour une fonction stateless | Code plus simple |
| Whitelist config/duplicates_whitelist.json | Séparé de la DB, éditable manuellement | Flexible |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Minor adjustments | 1 | --dry-run retiré car non pertinent (commande informative) |

**Total impact:** Simplification mineure, aucun impact fonctionnel.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Certains doublons sont en fait des mauvaises associations TMDB | Informatif — l'outil les met en évidence |
| Beaucoup de file_size_bytes NULL en DB | Score taille/bitrate à 0, scoring partiel reste utile |

## Next Phase Readiness

**Ready:**
- Commande CLI fonctionnelle, prête pour intégration web
- Fonctions utilitaires testées et réutilisables (_build_media_info, _format_*, _load_whitelist)
- Données de doublons accessibles via SQL simple

**Concerns:**
- Certains "doublons" sont des mauvaises associations TMDB (même tmdb_id, films différents)
- file_size_bytes souvent NULL → scoring partiel

**Blockers:**
- None

---
*Phase: 31-detection-doublons, Plan: 01*
*Completed: 2026-03-01*
