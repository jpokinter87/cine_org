---
phase: 28-films-speciaux
plan: 01
subsystem: database, api, ui
tags: tmdb, collections, sagas, enrichment, web

requires:
  - phase: 27-performance-robustesse-matching
    provides: cache TMDB stable, TMDBClient fonctionnel
provides:
  - Champs collection_id/collection_name dans MovieModel + entité Movie
  - Commande CLI enrich-collections avec skip_cache
  - Page web /library/collections avec recherche et tri
  - Badge collection sur cartes films et fiche détail
affects: future phases UI, enrichissement données

tech-stack:
  added: []
  patterns:
    - skip_cache parameter on TMDBClient.get_details() for cache invalidation
    - sentinel value 0 for "verified, no collection"

key-files:
  created:
    - src/web/routes/library/collections.py
    - src/web/templates/library/collections/index.html
    - src/web/templates/library/collections/_content.html
    - src/web/templates/library/collections/detail.html
  modified:
    - src/core/entities/media.py
    - src/core/ports/api_clients.py
    - src/infrastructure/persistence/models.py
    - src/infrastructure/persistence/repositories/movie_repository.py
    - src/infrastructure/persistence/database.py
    - src/adapters/api/tmdb_client.py
    - src/adapters/cli/commands/enrichment_commands.py
    - src/adapters/cli/commands/__init__.py
    - src/main.py
    - src/web/routes/library/__init__.py
    - src/web/routes/library/browse.py
    - src/web/templates/base.html
    - src/web/templates/library/_grid.html
    - src/web/templates/library/movie_detail.html
    - src/web/static/css/style.css
    - tests/fixtures/tmdb_responses.py
    - tests/unit/adapters/api/test_tmdb_client.py

key-decisions:
  - "skip_cache sur get_details() plutot que cache clear global — granulaire et non-destructif"
  - "sentinel collection_id=0 pour films sans collection — evite les re-verifications"
  - "nav Collections comme lien standard (pas sub-nav) — coherence visuelle"

patterns-established:
  - "skip_cache parameter pattern pour forcer refresh API sans invalider tout le cache"
  - "Route collections dans library/ sous-package (pas route standalone)"

duration: ~90min
started: 2026-03-01T00:00:00Z
completed: 2026-03-01T02:00:00Z
---

# Phase 28 Plan 01: Collections TMDB & Vue Sagas Summary

**Enrichissement de 5675 films avec collections TMDB (939 films dans 583 sagas) + page web Collections avec recherche/tri et badges sur les cartes.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~90 min |
| Started | 2026-03-01 00:00 |
| Completed | 2026-03-01 02:00 |
| Tasks | 4 completed |
| Files modified | 18 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Stockage collection TMDB | Pass | collection_id + collection_name dans Movie, MovieModel, MediaDetails, TMDBClient |
| AC-2: Enrichissement batch | Pass | 939 films dans 583 collections, 4736 sans collection, 0 non-verifies |
| AC-3: Vue Collections web | Pass | /library/collections avec grille, recherche, tri, detail par collection |
| AC-4: Badge collection cartes | Pass | Badge bleu sur cartes grille + lien saga sur fiche detail |

## Accomplishments

- 583 collections/sagas identifiees (James Bond 25 films, Harry Potter 6, Jurassic Park 6, etc.)
- Page /library/collections avec recherche temps reel HTMX et tri nom/nombre
- Parametere `skip_cache` sur TMDBClient.get_details() pour invalidation cache granulaire
- 21 tests TMDB (dont 3 nouveaux pour collections + skip_cache), 914 tests total

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/core/entities/media.py` | Modified | Champs collection_id/name sur Movie |
| `src/core/ports/api_clients.py` | Modified | Champs collection_id/name sur MediaDetails |
| `src/infrastructure/persistence/models.py` | Modified | Colonnes collection_id (indexe), collection_name |
| `src/infrastructure/persistence/database.py` | Modified | Migration 9: ALTER TABLE movies ADD collection_id/name |
| `src/infrastructure/persistence/repositories/movie_repository.py` | Modified | Mapper bidirectionnel collection fields |
| `src/adapters/api/tmdb_client.py` | Modified | Extraction belongs_to_collection + skip_cache param |
| `src/adapters/cli/commands/enrichment_commands.py` | Modified | Commande enrich_collections avec skip_cache=True |
| `src/adapters/cli/commands/__init__.py` | Modified | Export enrich_collections |
| `src/main.py` | Modified | Enregistrement commande enrich-collections |
| `src/web/routes/library/collections.py` | Created | Routes /library/collections et /library/collections/{id} |
| `src/web/routes/library/__init__.py` | Modified | Inclusion router collections |
| `src/web/routes/library/browse.py` | Modified | Passage collection_name/id aux items |
| `src/web/templates/base.html` | Modified | Lien nav Collections |
| `src/web/templates/library/_grid.html` | Modified | Badge collection sur cartes |
| `src/web/templates/library/movie_detail.html` | Modified | Lien collection sur fiche film |
| `src/web/templates/library/collections/index.html` | Created | Page principale collections |
| `src/web/templates/library/collections/_content.html` | Created | Contenu HTMX grille + recherche |
| `src/web/templates/library/collections/detail.html` | Created | Detail collection avec films |
| `src/web/static/css/style.css` | Modified | Styles collections grid, cards, badges |
| `tests/fixtures/tmdb_responses.py` | Modified | Credits dans INCEPTION fixture |
| `tests/unit/adapters/api/test_tmdb_client.py` | Modified | 3 tests: collection, no_collection, skip_cache |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| skip_cache param vs cache clear | Granulaire, ne detruit pas le cache existant | Pattern reutilisable pour futurs enrichissements |
| collection_id=0 sentinel | Evite re-verification des films sans saga | Performance batch |
| Nav Collections = lien standard | Coherence avec les autres onglets navbar | UX uniforme |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 2 | Essentiels, pas de scope creep |
| Scope additions | 0 | - |
| Deferred | 0 | - |

**Total impact:** Corrections essentielles, aucun scope creep

### Auto-fixed Issues

**1. Cache stale sans collection fields**
- **Found during:** Checkpoint 1 (enrich-collections retournait 0 collections)
- **Issue:** Le cache diskcache contenait des MediaDetails serialises avant l'ajout de collection_id — deserialisaient avec None
- **Fix:** Ajout parametre `skip_cache=True` sur get_details() utilise dans enrich-collections
- **Files:** src/adapters/api/tmdb_client.py, src/adapters/cli/commands/enrichment_commands.py
- **Verification:** Re-execution sur 50 films → 2 collections detectees, puis 5675 → 939

**2. total_pages undefined dans template collection detail**
- **Found during:** Checkpoint 2 (Internal Server Error au clic sur collection)
- **Issue:** _grid.html reference total_pages, non passe dans le contexte collection_detail
- **Fix:** Ajout total_pages=1, page=1 au contexte
- **Files:** src/web/routes/library/collections.py

### Skill Audit

| Expected | Invoked | Notes |
|----------|---------|-------|
| /frontend-design | Gap | Page collections construite sans le skill — corrections style necessaires apres feedback utilisateur |

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Cache diskcache stale apres ajout champs | Parametre skip_cache sur get_details() |
| total_pages undefined dans _grid.html | Ajout au contexte du detail |
| Style nav-link-sub desaligne | Supprime nav-link-sub, utilise nav-link standard |
| Input/select/bouton hauteurs differentes | Reutilise classes existantes lib-search-input + lib-filter-select |

## Next Phase Readiness

**Ready:**
- 583 collections enrichies et exploitables
- Architecture route collections en place (extensible)
- Pattern skip_cache reutilisable

**Concerns:**
- /frontend-design skill gap — invoquer systematiquement pour les phases UI futures
- ~200 collections avec 1 seul film (on pourrait filtrer celles avec 2+ films)

**Blockers:**
- None

---
*Phase: 28-films-speciaux, Plan: 01*
*Completed: 2026-03-01*
