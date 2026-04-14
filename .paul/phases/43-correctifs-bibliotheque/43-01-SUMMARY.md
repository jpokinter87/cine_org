---
phase: 43-correctifs-bibliotheque
plan: 01
subsystem: library
tags: [search, sqlite, udf, accents, unicode, i18n]

requires:
  - phase: 01-foundation-web
    provides: routes bibliothèque + filtre SQL _title_search_filter
  - phase: 12-dette-technique-donnees
    provides: search_variants (gestion ligatures)

provides:
  - UDF SQLite ``unaccent(text)`` enregistrée via listener SQLAlchemy
  - ``search_variants`` étendu avec variantes accent-stripped
  - ``_title_search_filter`` insensible aux accents dans les deux sens
  - Base technique réutilisable pour d'autres recherches (titres épisodes, overview)

affects:
  - Aucune phase future : gain purement UX, pas de nouvelle API

tech-stack:
  added: []
  patterns:
    - "UDF SQLite enregistrée via @event.listens_for(Engine, 'connect') : extensible pour d'autres fonctions (regex, normalize_title…)"
    - "Combinaison LIKE direct + LIKE unaccent() côté SQL : robustesse max sans index"

key-files:
  created:
    - tests/unit/test_search_accents.py
  modified:
    - src/infrastructure/persistence/database.py (listener UDF)
    - src/utils/helpers.py (search_variants étendu)
    - src/web/routes/library/helpers.py (_title_search_filter)

key-decisions:
  - "UDF unaccent() plutôt que colonne title_normalized dénormalisée : pas de migration, pas de maintien double-écriture"
  - "deterministic=True sur la create_function avec fallback silencieux TypeError (compat ancien SQLite)"
  - "Fonction interne _safe_unaccent gère le cas text IS NULL côté UDF"
  - "Combinaison LIKE direct + LIKE unaccent() dans le filtre : le LIKE direct couvre les cas ligature non touchés par normalize_accents, le LIKE unaccent couvre le cas général accent"
  - "Pas de modification de normalize_accents (réutilisé tel quel)"

patterns-established:
  - "@event.listens_for(Engine, 'connect') avec isinstance(sqlite3.Connection) pour n'activer UDF que sur SQLite"
  - "Import de database.py dans les tests déclenche l'enregistrement du listener (via import side effect)"

duration: ~40min
started: 2026-04-14T22:45:00Z
completed: 2026-04-14T23:25:00Z
---

# Phase 43 Plan 01 : Recherche bibliothèque insensible aux accents — Summary

**UDF SQLite `unaccent()` enregistrée sur chaque connexion + `search_variants` étendu aux variantes accent-stripped + `_title_search_filter` utilisant le double LIKE (variantes directes + unaccent pattern) pour que « Millenium » et « Millénium » retournent les mêmes résultats.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~40 min |
| Started | 2026-04-14 22:45 |
| Completed | 2026-04-14 23:25 |
| Tasks | 1 auto |
| Files modified | 3 + 1 créé |
| Tests ajoutés | 18 (5 UDF + 3 search_variants + 9 filter + 1 extended) |
| Tests globaux | 1204/1204 (zéro régression) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: UDF unaccent enregistrée | ✓ | `SELECT unaccent('Millénium')` → `'Millenium'` validé |
| AC-2: Recherche accent → sans accent | ✓ | `test_unaccented_query_finds_accented_title` + `test_all_millenium_variants_found_with_unaccented_query` |
| AC-3: Recherche sans accent → accent | ✓ | `test_accented_query_finds_unaccented_title` (Bokeh/Bokéh) |
| AC-4: Ligatures préservées | ✓ | `test_ligatures_still_work_in_search` + `test_ligatures_and_accents_combined` |
| AC-5: Aucune régression | ✓ | 1204/1204 tests verts, +18 nouveaux |

## Accomplishments

- **Levée d'un irritant utilisateur quotidien** : l'incohérence des résultats selon la présence ou l'absence d'accent dans la query est résolue dans les deux sens.
- **Scénario Millénium validé par test** : `test_all_millenium_variants_found_with_unaccented_query` reproduit exactement le cas utilisateur (saga 3 films + remakes) et vérifie que « Millenium » ramène tous les films accentués.
- **Fondation réutilisable** : le mécanisme d'UDF via listener SQLAlchemy peut maintenant être étendu à d'autres fonctions (normalize_title, unaccent_lower…) sans reconfiguration DB.

## Task Commits

| Task | Commit | Type | Description |
|------|--------|------|-------------|
| Task 1: UDF + search_variants + filter + tests | (à commiter) | feat | Recherche bibliothèque insensible aux accents via UDF SQLite + 18 tests |

**À commiter** : un seul commit `feat(phase-43-01): recherche bibliothèque insensible aux accents via UDF SQLite unaccent`.

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/infrastructure/persistence/database.py` | Modified | Ajout listener `@event.listens_for(Engine, "connect")` qui enregistre l'UDF `unaccent(text)` sur chaque connexion SQLite |
| `src/utils/helpers.py` | Modified | `search_variants` inclut désormais les variantes accent-stripped (`normalize_accents(v) for v in variants`) |
| `src/web/routes/library/helpers.py` | Modified | `_title_search_filter` combine LIKE direct (toutes variantes) + LIKE sur `unaccent(title)` avec query accent-stripped |
| `tests/unit/test_search_accents.py` | Created | 18 tests : UDF basic (5), search_variants (3), filter comportement (9), extended overview (1) |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| UDF SQLite plutôt que colonne dénormalisée | Pas de migration, pas de synchronisation double-écriture à chaque save | Solution centralisée dans `database.py` |
| Listener global `event.listens_for(Engine, "connect")` | Se déclenche automatiquement sur toutes les connexions, y compris celles créées par les tests | Les tests unitaires bénéficient de l'UDF sans setup explicite |
| `isinstance(dbapi_connection, sqlite3.Connection)` guard | L'UDF est spécifique SQLite, futur PostgreSQL utiliserait `unaccent` natif | Portabilité préservée |
| Fallback `TypeError` sur `deterministic=True` | SQLite 3.8.3+ requis mais pas garanti sur tous les environnements | Dégradation silencieuse sans crasher |
| Combinaison LIKE direct + LIKE unaccent | Le LIKE direct gère les ligatures (cœur/coeur), le LIKE unaccent gère les accents — les deux mondes couverts sans redondance | 2 conditions SQL OR par variante, perf OK sur ~6000 lignes |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 0 | — |
| Scope additions | 0 | — |
| Deferred | 0 | — |

### Deferred Items

Aucun — le plan couvre exactement ce qui a été exécuté.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Initial confusion utilisateur sur les films Millénium 2/3 absents de la recherche | Diagnostic : c'était l'effet du bug de la recherche insensible aux accents (ce plan), pas un doublon ni une absence en DB |
| « Bug 3 » (tri récemment ajouté incomplet) supposé | Investigation : pas un bug — les films 2 et 3 étaient en DB depuis 2 mois, seul Millénium 1 a créé une nouvelle entité aujourd'hui |

## Next Phase Readiness

**Ready:**
- Phase 43 (Correctifs Bibliothèque) réduite à ce seul plan, donc **complète** au commit
- Prochaine phase logique : **phase 41 Jellyfin** (volumes Docker) pour terminer la milestone v2.1

**Concerns:**
- Aucun
- Éventuellement à surveiller : perf de la recherche plein-texte si la bibliothèque dépasse les 10 000 entités (index FTS5 serait alors pertinent — pas nécessaire maintenant)

**Blockers:** None

**Commit à créer :** `feat(phase-43-01): recherche bibliothèque insensible aux accents via UDF SQLite`

---
*Phase: 43-correctifs-bibliotheque, Plan: 01*
*Completed: 2026-04-14*
