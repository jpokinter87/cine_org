---
phase: 42-overrides-manuels
plan: 02
subsystem: library
tags: [overrides, poster, synopsis, cast, metadata, enricher, htmx, sqlmodel]

requires:
  - phase: 06-validation
    provides: MovieModel, SeriesModel, repositories
  - phase: 09-manual-associations
    provides: enricher & reassociation architecture
  - phase: 42-01
    provides: conventions override (flag booléen + colonnes dédiées)

provides:
  - MovieModel/SeriesModel : 4 colonnes poster_override, overview_override, cast_override_json, preserve_overrides
  - Entités Movie/Series : champ preserve_overrides propagé via repository
  - Service src/services/metadata_overrides.py : upload + URL + delete + find (fichiers sous storage/.metadata/posters/)
  - Routes GET/POST /library/{movies,series}/{id}/edit + route statique /library/metadata/posters/{filename}
  - Overlay HTMX _edit_metadata.html avec 3 modes poster (keep/upload/url/clear), textarea synopsis, cast dynamique (nom+rôle)
  - Affichage prioritaire des overrides sur fiches détaillées + grille /library/ + page suggest
  - movies_enricher + series_enricher + reassociate respectent preserve_overrides
  - Calcul automatique du flag preserve_overrides (auto-True quand un override existe, auto-False quand tout est effacé)

affects:
  - phase 43 (à venir) : correctifs bibliothèque (collections, recherche accents, tri récemment ajouté)

tech-stack:
  added: []
  patterns:
    - "Colonnes *_override sur les modèles DB, les valeurs API ne sont jamais perdues"
    - "preserve_overrides calculé automatiquement côté serveur (pas de case UX explicite)"
    - "Helper _effective_poster_url(override, path) centralise la priorité override → API"
    - "Check preserve_overrides dans les enrichers / reassociate avant d'écraser poster/overview/director/cast"

key-files:
  created:
    - src/services/metadata_overrides.py
    - src/web/routes/library/edit_metadata.py
    - src/web/templates/library/_edit_metadata.html
    - tests/unit/test_metadata_overrides.py
    - tests/unit/test_edit_metadata_routes.py
    - tests/unit/test_enricher_preserve_overrides.py
  modified:
    - src/infrastructure/persistence/models.py (4 colonnes override × MovieModel + SeriesModel)
    - src/infrastructure/persistence/database.py (migrations 11 + 12)
    - src/infrastructure/persistence/repositories/movie_repository.py (mapping preserve_overrides)
    - src/infrastructure/persistence/repositories/series_repository.py (idem)
    - src/core/entities/media.py (Movie.preserve_overrides, Series.preserve_overrides)
    - src/services/movies_enricher.py (skip protected fields si preserve)
    - src/services/series_enricher.py (idem)
    - src/web/routes/library/__init__.py (include edit_metadata router)
    - src/web/routes/library/reassociate.py (respect preserve_overrides sur 2 sites)
    - src/web/routes/library/detail.py (inchangé côté Python, consommé par template)
    - src/web/routes/library/browse.py (grille : _effective_poster_url)
    - src/web/routes/library/suggest.py (idem + overview_override fallback)
    - src/web/routes/library/helpers.py (_effective_poster_url)
    - src/web/templates/library/movie_detail.html (bouton Éditer + container overlay + effective_poster/overview/cast + badges)
    - src/web/templates/library/series_detail.html (idem)
    - src/web/templates/library/_progress.html (inchangé — non concerné)
    - src/web/static/css/style.css (~270 lignes .edit-overlay, .edit-*, .override-badge)

key-decisions:
  - "Colonnes DB *_override plutôt que fichier JSON : cohérent avec le pattern SQLModel"
  - "Posters stockés dans storage/.metadata/posters/ (JPG/PNG/WEBP) + route /library/metadata/posters/{filename}"
  - "Casting JSON [{name, role}] en colonne dédiée cast_override_json (setter/getter comme cast)"
  - "preserve_overrides calculé automatiquement : présence d'un override ⇒ True"
  - "Fallback SearchResult n'est pas nécessaire ici : l'utilisateur travaille directement sur le modèle DB"
  - "UX : radio auto-coché à la sélection de fichier ou saisie d'URL, fichier custom stylé masquant l'input natif"
  - "Checkpoint human-verify utilisé pour valider visuellement le cycle édition + protection"

patterns-established:
  - "Helper _effective_poster_url(poster_override, poster_path) appliqué à toutes les surfaces d'affichage"
  - "Protection enricher : if not entity.preserve_overrides avant d'écraser les 4 champs protégés"
  - "Overlay HTMX isolé par zone id=edit-metadata-container pour ne pas collisionner avec reassociate-container"
  - "Bloquage navigation clavier globale pendant overlay ouvert : check .edit-overlay dans handler keydown parent"

duration: ~4h
started: 2026-04-14T20:00:00Z
completed: 2026-04-14T22:30:00Z
---

# Phase 42 Plan 02 : Overrides métadonnées manuels — Summary

**Édition web des fiches films/séries (affiche, synopsis, casting) avec protection automatique contre les re-enrichissements, stockage des posters sous `storage/.metadata/posters/`, affichage prioritaire sur toutes les surfaces (fiche détaillée, grille, suggestion).**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~4h (session continue) |
| Started | 2026-04-14 fin d'après-midi |
| Completed | 2026-04-14 22:30 |
| Tasks | 3 auto + 1 checkpoint + 1 correctif UX post-checkpoint |
| Files modified | 17 (+ 6 créés) |
| Tests ajoutés | 46 (24 metadata_overrides + 17 routes + 5 enricher preserve) |
| Tests globaux | 1186/1186 (zéro régression) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Stockage des overrides en DB + fichiers | ✓ | Migrations 11+12 idempotentes, round-trip des 4 colonnes validé |
| AC-2: Upload d'affiche | ✓ | `save_poster_upload` écrit sous `.metadata/posters/{type}-{id}.{ext}`, ValueError sur extensions non supportées |
| AC-3: Téléchargement depuis URL | ✓ | `save_poster_from_url` avec respx mocks, rejet 404 + content-type non-image |
| AC-4: Bouton éditer + overlay HTMX | ✓ | Validé visuellement sur Forever + Millenium + Millénium (2009) |
| AC-5: Enregistrement des overrides | ✓ | Upload + URL + multipart tous couverts + HX-Redirect |
| AC-6: Affichage priorité override | ✓ | Fiches + grille + page suggest → tous utilisent `_effective_poster_url`, badge `✎ modifié` visible |
| AC-7: Enricher respecte preserve_overrides | ✓ | Canari `CANARY_TEST_*` inséré avant enrich-series reste intact sur 2 séries |
| AC-8: CLI fonctionnel inchangé | ✓ | 199/200 séries enrichies normalement, comportement identique sans override |
| AC-9: Vérification manuelle | ✓ | Cycle édition → protection → re-enrich validé end-to-end |

## Accomplishments

- **Cycle édition complet fonctionnel** : upload d'affiche, synopsis custom, casting manuel avec rôles, protection systématique contre re-enrichissements, tous visibles sur l'ensemble des surfaces web.
- **Protection validée end-to-end** : canaris `CANARY_TEST_*` insérés avant enrich-series, restés intacts après un enrich forcé sur 200 séries — zéro écrasement.
- **UX repensée post-checkpoint** : auto-coche du radio au choix fichier / saisie URL, bouton fichier custom dans la charte amber, suppression de la case "Protéger" (devenue automatique), blocage navigation clavier gauche/droite pendant overlay ouvert.

## Task Commits

| Task | Commit | Type | Description |
|------|--------|------|-------------|
| Task 1: socle DB + helpers fichiers | (à commiter) | feat | SeasonOverrideModel colonnes + migrations 11/12 + service metadata_overrides + 24 tests |
| Task 2: UI édition + overlay + CSS | (à commiter) | feat | Routes edit_metadata + overlay HTMX + modifs fiches + CSS + 17 tests |
| Task 3: preserve_overrides dans enrichers | (à commiter) | feat | movies_enricher + series_enricher + reassociate + 5 tests |
| Post-checkpoint UX fixes | (à commiter) | fix | Auto-check radios + file button styled + preserve auto + arrow keys blocked + override dans grille/suggest |

**À commiter** : un seul commit groupé `feat(phase-42-02): édition manuelle des métadonnées avec protection automatique`.

## Files Created/Modified

Voir frontmatter `key-files`. En résumé :
- **6 fichiers créés** : 1 service, 1 route module, 1 template partial, 3 tests
- **17 fichiers modifiés** : 2 modèles DB, 1 migration, 2 repositories, 1 entités core, 2 enrichers, 1 reassociate, 1 helpers, 1 init routes, 1 browse, 1 suggest, 1 detail, 2 templates fiches, 1 CSS

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Colonnes DB *_override plutôt que fichier JSON | Cohérent avec SQLModel, requêtable, backup inclus | Aucun stockage séparé hors les posters binaires |
| Posters sous `storage/.metadata/posters/` | Même volume, backup inclus, convention simple `{type}-{id}.{ext}` | Route `/library/metadata/posters/{filename}` dédiée au service des fichiers |
| `preserve_overrides` auto (pas de case UX) | L'utilisateur qui crée un override veut qu'il soit protégé, c'est sémantiquement évident | UX simplifiée, 1 concept de moins à expliquer |
| Helper `_effective_poster_url` centralisé | Propager facilement l'override à toutes les surfaces (fiche, grille, suggest) | Une seule source de vérité pour la résolution poster |
| Cast stocké comme `[{name, role}]` JSON | Permet saisie d'un rôle optionnel contrairement à `cast` API (liste de noms seule) | Cast override visible avec italique role dans la fiche |
| Navigation clavier bloquée via `.edit-overlay` | Pattern identique à `.reassociate-overlay` déjà en place | Cohérence du comportement |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed (post-checkpoint) | 5 | UX améliorée, fonctionnel identique |
| Scope additions | 1 | Propagation override à grille + suggest (non prévu au plan, utile) |
| Deferred | 3 | Bugs pré-existants découverts, hors scope 42-02 → phase 43 |

### Auto-fixed (post-checkpoint human-verify)

**1. Radio upload non auto-coché à la sélection de fichier**
- **Fix** : `onchange="onFileChosen"` coche `pmode-upload` + remplace label du bouton custom + preview

**2. Radio URL non auto-coché à la saisie**
- **Fix** : `oninput` + `onfocus` → `onUrlInput()` coche `pmode-url`

**3. Input file natif hors charte graphique**
- **Fix** : input `visibility:hidden` + `<label class="edit-file-button">` stylé (border, hover amber, text-ellipsis)

**4. Case "Protéger ces modifications" superflue**
- **Fix** : retirée du template, calculée automatiquement dans la route POST : `preserve = bool(poster_override or overview_override or cast_override_json)`. Note discrète en tête d'overlay pour informer l'utilisateur.

**5. Touches flèches gauche/droite naviguaient vers fiche suivante pendant overlay ouvert**
- **Fix** : ajout de `.edit-overlay` au selector du check dans handler keydown de `movie_detail.html` et `series_detail.html`

### Scope Additions

**Override sur la grille bibliothèque + page suggest**
- Remonté par l'utilisateur après test initial : jaquette présente sur fiche détaillée mais absente du résultat de recherche
- Ajout de `_effective_poster_url` dans `src/web/routes/library/helpers.py` + propagation dans `browse.py` (films + séries) et `suggest.py`
- Non prévu dans le plan initial mais essentiel pour la cohérence d'affichage

### Deferred Items (phase 43 à venir)

- **Millénium (2009) id=5798** : `collection_id=NULL` au lieu de 24761 (saga Millénium suédoise). `enrich-collections` relancé en parallèle de UNIFY.
- **Recherche insensible aux accents** : `search_variants` gère les ligatures mais pas les accents, donc « Millenium » ne trouve pas « Millénium ». Fix non trivial (UDF SQLite `unaccent()` ou colonne dénormalisée).
- **Tri « récemment ajouté » partiel** : sur les 3 films Millénium, seul le 1er apparaît. À investiguer (created_at hétérogène ou dédup par collection ?).

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| `TestClient` list-of-tuples form encoding ne duplique pas les clés `cast_names[]` | Utiliser `data={"cast_names[]": ["A", "B"]}` (dict avec valeurs listes) à la place |
| Template Jinja `{% set %}` complexe pour construire `effective_poster` | Gardé dans les templates (simple) — alternative future : tout faire côté route |
| Confusion initiale sur le comportement enricher (poster_path mis à jour malgré preserve=True) | Faux positif : les valeurs affichées POST-enrich étaient les valeurs TMDB d'un enrich antérieur (avant activation preserve). Test avec canari `CANARY_TEST_*` prouve que la protection fonctionne à 100% |

## Next Phase Readiness

**Ready:**
- Phase 42 (Overrides Manuels) complète : 2 plans livrés, 2 cas d'usage validés (épisodes hors canon, métadonnées manuelles)
- Prochaine étape logique : **phase 41 Jellyfin** (montage volumes Docker) restée à planifier, OU phase 43 correctifs bibliothèque
- Les 3 deferred issues offrent un plan 43 prêt à cadrer immédiatement

**Concerns:**
- Aucune régression introduite
- Aucune dette technique critique ajoutée

**Blockers:** None

**Commit à créer :** `feat(phase-42-02): édition manuelle des métadonnées avec protection automatique`

---
*Phase: 42-overrides-manuels, Plan: 02*
*Completed: 2026-04-14*
