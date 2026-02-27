---
phase: 21-donnees-manquantes
plan: 02
subsystem: cli
tags: [tvdb, enrichment, episode-titles, matching]

requires:
  - phase: 21-donnees-manquantes (plan 01)
    provides: link-movies amélioré, _normalize_for_match()
provides:
  - Commande enrich-tvdb-ids pour peupler les tvdb_id manquants
  - 13 séries avec tvdb_id peuplé
  - 98 épisodes avec titre enrichi via TVDB
affects: [22 (suppression bibliothèque)]

tech-stack:
  added: []
  patterns: [recherche multi-stratégie TVDB avec racine titre, normalisation articles/année]

key-files:
  created: []
  modified:
    - src/adapters/cli/commands/import_commands.py
    - src/adapters/cli/commands/__init__.py
    - src/main.py

key-decisions:
  - "TMDB external_ids ne retourne pas tvdb_id — stratégie 1 non fonctionnelle"
  - "Seuil fuzzy 0.85 pour TVDB search — évite The Punisher→The Devil Punisher"
  - "Recherche par racine (avant tiret) — résout Dragons - Par delà les rives"
  - "Nettoyage année (YYYY) dans titres TVDB — résout Flash (2014) vs The Flash"

patterns-established:
  - "Recherche TVDB multi-titre : FR → original → racine (split sur ' - ')"
  - "Normalisation croisée : _normalize_for_match() + suppression (YYYY)"

duration: ~20min
started: 2026-02-27
completed: 2026-02-27
---

# Phase 21 Plan 02: Épisodes sans titres & tvdb_id manquants — Summary

**Commande enrich-tvdb-ids créée : 13/18 séries peuplées, 98 épisodes enrichis via enrich-episode-titles**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~20min |
| Started | 2026-02-27 |
| Completed | 2026-02-27 |
| Tasks | 2 completed (1 auto + 1 checkpoint) |
| Files modified | 3 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Commande enrich-tvdb-ids fonctionnelle | Pass | 13/18 séries peuplées, statistiques détaillées |
| AC-2: Matching TVDB robuste | Pass | Multi-stratégie (titre FR, original, racine), normalisation articles/année |
| AC-3: Enrichissement titres épisodes | Pass | 98 titres enrichis, 285 restants (limites TVDB) |
| AC-4: Option dry-run et limit | Pass | --dry-run affiche matchs sans modification, --limit fonctionne |

## Accomplishments

- **Commande enrich-tvdb-ids** : recherche TVDB multi-stratégie (titre FR → original → racine avant tiret), normalisation articles/accents/année
- **13/18 séries** avec tvdb_id peuplé (Dragons, The Flash, Shaka iLembe, etc.)
- **98 épisodes enrichis** avec titre via enrich-episode-titles (383 → 285 sans titre)
- **5 séries non trouvées** : cas légitimes (Dahmer="Monstre" sur TVDB, Ed Gein/Playgame/Suspect pas sur TVDB, Punisher=homonyme taïwanais)

## Task Commits

| Task | Commit | Type | Description |
|------|--------|------|-------------|
| Task 1: enrich-tvdb-ids | (à committer) | feat | Commande CLI avec matching TVDB multi-stratégie |
| Task 2: Checkpoint | — | verify | Exécution enrich-tvdb-ids + enrich-episode-titles |

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/adapters/cli/commands/import_commands.py` | Modified | Ajout enrich_tvdb_ids() et _enrich_tvdb_ids_async() |
| `src/adapters/cli/commands/__init__.py` | Modified | Export enrich_tvdb_ids |
| `src/main.py` | Modified | Enregistrement commande enrich-tvdb-ids |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Seuil fuzzy 0.85 pour TVDB | Évite faux positifs (The Punisher → The Devil Punisher) | Cohérent avec plan 21-01 |
| TMDB external_ids abandonné | L'endpoint ne retourne pas de tvdb_id pour les séries testées | Recherche TVDB directe uniquement |
| Recherche par racine titre | "Dragons - Par delà les rives" → racine "Dragons" matche sur TVDB | +1 série trouvée |
| Nettoyage (YYYY) dans résultats | "Flash (2014)" sur TVDB → "Flash" matche "The Flash" normalisé | +1 série trouvée |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Export __init__.py manquant |
| Scope additions | 2 | Recherche par racine titre + nettoyage année |
| Deferred | 1 | Outil de listage données manquantes |

**Total impact:** Améliorations nécessaires pour maximiser les matchs, pas de scope creep

### Deferred Items

- Outil CLI/web pour lister facilement les épisodes et séries avec données manquantes (pour correction manuelle par l'utilisateur)
- 285 épisodes restants sans titre (La Panthère Rose 124, Battlestar Galactica 58, séries rares/anciennes)
- 5 séries sans tvdb_id (correction manuelle requise)

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| TMDB external_ids ne retourne pas tvdb_id | Abandonné stratégie 1, recherche TVDB directe uniquement |
| Import manquant dans __init__.py | Ajout de l'export enrich_tvdb_ids |
| The Punisher → The Devil Punisher (faux positif) | Seuil fuzzy relevé de 0.80 à 0.85 |
| Dragons et The Flash non trouvés | Ajout recherche par racine + nettoyage (YYYY) |

## Next Phase Readiness

**Ready:**
- Phase 21 complète (plans 01 + 02)
- Phase 22 (Suppression depuis la Bibliothèque) prête à démarrer

**Concerns:**
- 285 épisodes et 220 films restent avec données manquantes — limites des APIs, correction manuelle à prévoir

**Blockers:**
- None

---
*Phase: 21-donnees-manquantes, Plan: 02*
*Completed: 2026-02-27*
