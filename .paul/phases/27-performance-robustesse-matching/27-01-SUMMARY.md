---
phase: 27-performance-robustesse-matching
plan: 01
subsystem: backend
tags: [tvdb, cache, workflow, guessit, vostfr, parsing, renamer]

requires:
  - phase: 26-corrections-ux-mineures
    provides: workflow reset route, popover dynamique, logs serveur
provides:
  - Cache TVDB bulk par saison (1 requête au lieu de N par épisode)
  - Compteurs workflow web cohérents avec l'état réel en DB
  - Champ subtitle_language dans ParsedFilename + renommage VOSTFR
  - Normalisation "mul" → "Multi" dans le parsing
  - Filtrage warnings pytest tiers (ipywidgets, datetime.utcnow)
affects: [phase-28]

tech-stack:
  added: []
  patterns:
    - "Bulk fetch TVDB par saison : 1 requête FR + 1 EN → cache individuel par épisode"
    - "Bulk marker cache : clé tvdb:season_bulk:{id}:S{nn} empêche les re-fetches"
    - "VOSTFR : subtitle_language FR + audio non-FR/non-Multi → suffixe VOSTFR"
    - "Multi : guessit alpha2 'mul' normalisé en 'Multi' (pas 'MUL')"

key-files:
  modified:
    - src/adapters/api/tvdb_client.py
    - src/web/routes/workflow.py
    - src/core/value_objects/parsed_info.py
    - src/adapters/parsing/guessit_parser.py
    - src/services/renamer.py
    - pyproject.toml
    - tests/unit/adapters/api/test_tvdb_client.py
    - tests/unit/test_guessit_parser.py
    - tests/unit/services/test_renamer.py

key-decisions:
  - "Bulk fetch FR+EN séparé plutôt que requête unique : fallback titre EN quand FR vide"
  - "Bulk marker dans le cache (TTL 7j) : évite de re-fetcher la saison si déjà peuplée"
  - "scanned = len(created_video_file_ids) : reflète les fichiers réellement sauvegardés en DB"
  - "fallback_language conserve la casse 'Multi' pour l'affichage (pas .upper())"
  - "filterwarnings dans pyproject.toml pour warnings tiers (rich ipywidgets, pydantic utcnow)"

patterns-established:
  - "Bulk fetch + cache individuel : charger toute une saison puis servir depuis le cache"
  - "subtitle_language séparé de language dans ParsedFilename"
  - "VOSTFR conditionnel : seulement si audio non-FR et non-Multi"

duration: ~60min
started: 2026-02-28T19:00:00Z
completed: 2026-02-28T20:00:00Z
---

# Phase 27 Plan 01: Performance & Robustesse Matching Summary

**Cache TVDB bulk par saison, compteurs workflow fiables, parsing/renommage VOSTFR, warnings pytest filtrés**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~60min |
| Tasks | 3 planned + 2 bonus (warnings + couverture) |
| Files modified | 9 |
| Tests | 911 passed (était 891) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Cache TVDB bulk par saison | Pass | `_fetch_season_episodes()` charge FR+EN, cache individuel par épisode + count + bulk marker |
| AC-2: Compteurs workflow cohérents | Pass | `scanned = len(created_video_file_ids)`, filtre simplifié, vérification cohérence avec warning log |
| AC-3: Parsing et renommage VOSTFR | Pass | `subtitle_language=FR` pour VOSTFR, suffixe VOSTFR dans le renommage |
| AC-4: Compatibilité MULTI existante | Pass | `language=Multi` (pas MUL), pas de VOSTFR ajouté quand MULTI |

## Accomplishments

- Cache TVDB bulk : 1 requête API par saison au lieu de N par épisode, avec fallback titre FR→EN
- Compteurs workflow web : `scanned` reflète les fichiers réellement sauvegardés en DB, plus de décalage
- Parsing VOSTFR : `subtitle_language` dans ParsedFilename, VOSTFR dans le suffixe technique du renommage
- Normalisation Multi : guessit "mul" → "Multi" au lieu de "MUL"
- Warnings pytest filtrés : ipywidgets (rich) et datetime.utcnow (pydantic) supprimés de la sortie
- Couverture améliorée : tvdb_client 84%→91%, guessit_parser 91%→97%

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/adapters/api/tvdb_client.py` | Modified | `_fetch_season_episodes()`, `_fetch_all_season_episodes_raw()`, refactorisé `get_episode_details()` et `get_season_episode_count()` pour utiliser le bulk fetch |
| `src/web/routes/workflow.py` | Modified | `scanned` basé sur `created_video_file_ids`, `scanned_files` peuplé à l'étape 3, filtre simplifié, vérification cohérence |
| `src/core/value_objects/parsed_info.py` | Modified | Ajout `subtitle_language: Optional[str]` à ParsedFilename |
| `src/adapters/parsing/guessit_parser.py` | Modified | `_extract_subtitle_language()`, normalisation "mul"→"Multi" dans `_extract_language()` |
| `src/services/renamer.py` | Modified | `fallback_subtitle_language` dans `_build_tech_suffix()`, `generate_movie_filename()`, `generate_series_filename()` |
| `pyproject.toml` | Modified | `filterwarnings` pour warnings tiers |
| `tests/unit/adapters/api/test_tvdb_client.py` | Modified | 6 tests bulk fetch + adaptation test pagination/cache |
| `tests/unit/test_guessit_parser.py` | Modified | 9 tests VOSTFR/Multi/edge cases |
| `tests/unit/services/test_renamer.py` | Modified | 5 tests renommage VOSTFR |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Bulk fetch FR+EN séparé | Fallback titre EN quand FR vide (fréquent pour séries anciennes) | 2 requêtes API par saison au lieu de 1, mais couverture titres maximale |
| Bulk marker cache (TTL 7j) | Évite de re-fetcher si saison déjà peuplée | Clé supplémentaire dans le cache |
| scanned basé sur created_video_file_ids | Reflète la réalité DB, pas le scan brut | Compteurs finaux cohérents |
| "Multi" préservé en casse | Affichage "Multi" au lieu de "MULTI" dans les noms de fichiers | Cohérence avec la convention existante |
| VOSTFR exclu si audio Multi | VOSTFR est implicite quand le fichier est Multi | Pas de redondance dans le nom |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Scope additions | 2 | Qualité : warnings pytest + couverture tests |

**Total impact:** Améliorations qualité au-delà du plan, aucun changement de périmètre fonctionnel

### Scope Additions

**1. Filtrage warnings pytest**
- **Ajouté car:** L'utilisateur a demandé de régler les warnings
- **Change:** `filterwarnings` dans `pyproject.toml`
- **Impact:** Sortie pytest propre (0 warnings)

**2. Amélioration couverture tests**
- **Ajouté car:** L'utilisateur a demandé d'améliorer la couverture
- **Change:** 20 tests supplémentaires pour les branches non couvertes
- **Impact:** tvdb_client 84%→91%, guessit_parser 91%→97%

## Issues Encountered

None

## Next Phase Readiness

**Ready:**
- Phase 28 (Films Spéciaux) peut démarrer sans blocage
- Le système de parsing/renommage est extensible pour les films multi-parties

**Concerns:**
- Aucun

**Blockers:**
- None

---
*Phase: 27-performance-robustesse-matching, Plan: 01*
*Completed: 2026-02-28*
