---
phase: 09b-metadonnees-techniques
plan: 01
subsystem: ui, api, pipeline
tags: [htmx, mediainfo, tmdb, tvdb, filters, technical-metadata]

requires:
  - phase: 08-fiches-detaillees-enrichies
    provides: fiches détaillées avec champs techniques (resolution, codecs, languages)
  - phase: 09-correction-manuelle-associations
    provides: mécanisme de ré-association TMDB
provides:
  - Filtres avancés bibliothèque (résolution, codec vidéo/audio, recherche synopsis)
  - Cartouches techniques cliquables sur fiches détaillées
  - Badges Multi langues avec mini-cartouches
  - Navigation prev/next entre fiches avec prefetch
  - Propagation métadonnées techniques dans le pipeline workflow
  - Liens TVDB et premier épisode pour séries
  - Purge séries documentaires
affects: [11-tableau-de-bord-qualite, pipeline-workflow]

tech-stack:
  added: []
  patterns:
    - sessionStorage pour navigation inter-fiches
    - data-* attributes au lieu de onclick pour éviter les problèmes d'échappement HTML
    - prefetch natif avec <link rel="prefetch">

key-files:
  created: []
  modified:
    - src/web/routes/library.py
    - src/web/templates/library/movie_detail.html
    - src/web/templates/library/series_detail.html
    - src/web/templates/library/_filters.html
    - src/web/templates/library/_grid.html
    - src/web/templates/library/_reassociate_results.html
    - src/web/static/css/style.css
    - src/core/entities/media.py
    - src/adapters/cli/batch_builder.py
    - src/infrastructure/persistence/repositories/movie_repository.py
    - src/infrastructure/persistence/repositories/episode_repository.py
    - src/services/workflow/transfer_step.py

key-decisions:
  - "Filtres techniques sur labels résolution (4K/1080p/720p/SD) et non valeurs brutes"
  - "Navigation inter-fiches via sessionStorage (pas de paramètre URL)"
  - "data-* attributes + addEventListener pour éviter les bugs d'apostrophes dans onclick"
  - "Tri par défaut décroissant (meilleurs en premier)"
  - "Séries documentaires exclues du périmètre (identification trop difficile)"

patterns-established:
  - "Pattern tech-badge : cartouches techniques cliquables avec filtrage par clic"
  - "Pattern lib-detail-nav : navigation prev/next avec prefetch natif"
  - "Pattern _extract_tech_from_media_info : extraction standardisée des métadonnées techniques"

duration: ~4h (réparti sur 2 sessions)
started: 2026-02-24T10:00:00Z
completed: 2026-02-25T16:00:00Z
---

# Phase 9b Plan 01: Métadonnées Techniques et Filtres Avancés — Summary

**Filtres avancés (résolution, codecs, recherche synopsis), cartouches techniques cliquables, navigation inter-fiches avec prefetch, et propagation complète des métadonnées techniques dans le pipeline workflow.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~4h |
| Started | 2026-02-24 |
| Completed | 2026-02-25 |
| Tasks | 6 completed |
| Files modified | 12 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Cartouches techniques visibles sur fiche film | Pass | Résolution, codecs, langues avec badges colorés |
| AC-2: Clic sur résolution filtre la bibliothèque | Pass | + cartouche × déselectionnable |
| AC-3: Recherche étendue (synopsis) fonctionne | Pass | Mode titre/étendu avec toggle |
| AC-4: Tri par résolution fonctionne | Pass | Conversion label (4K > 1080p > 720p > SD) |
| AC-5: Badge Multi langues | Pass | Ajouté post-checkpoint |
| AC-6: Navigation prev/next | Pass | Flèches + keyboard + prefetch |
| AC-7: Pipeline propage métadonnées | Pass | Movie + Episode entities enrichies |

## Accomplishments

- Filtres avancés bibliothèque : résolution (4K/1080p/720p/SD), codec vidéo, codec audio, recherche étendue synopsis
- Cartouches techniques cliquables sur fiches films et séries (résolution, codecs, langues)
- Badge "Multi" pour contenus multilingues + mini-cartouches par langue
- Navigation prev/next entre fiches détaillées avec prefetch et flèches clavier
- Fix bug critique ré-association (apostrophes dans onclick cassaient le JS)
- Propagation complète des métadonnées techniques dans le pipeline workflow (codecs, résolution, langues, taille, director, cast)
- Sauvegarde Series/Episode en base lors du workflow séries (était absent)
- Mise à jour file_path après transfert réussi
- Fallback VideoFileModel pour films sans file_path
- Liens TVDB sur fiches séries + chemin premier épisode
- Enrichissement 923 séries avec tvdb_id via TMDB API
- Purge 29 séries documentaires (hors périmètre) + recréation 3 séries borderline

## Task Commits

| Task | Commit | Type | Description |
|------|--------|------|-------------|
| Filtres + cartouches techniques | `8fb50ac` | feat | Phase 9b initiale |
| Corrections UAT | `91d92ab` | fix | Délai recherche + navigation retour |
| Multi langues + navigation | `97fc6c7` | feat | Badges Multi, flèches navigation, genres |
| Fix ré-association + prefetch | `a36ffef` | fix | data-* au lieu onclick, prefetch, fallback VideoFile |
| TVDB + premier épisode + purge | `266fa1c` | feat | Liens TVDB, file_path épisode, 29 docs supprimées |
| Pipeline métadonnées | `f2897a6` | feat | Propagation MediaInfo → Movie/Episode |

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/core/entities/media.py` | Modified | Ajout champs techniques (file_path, codecs, resolution, languages) sur Movie et Episode |
| `src/adapters/cli/batch_builder.py` | Modified | Extraction MediaInfo + sauvegarde Series/Episode en DB |
| `src/services/workflow/transfer_step.py` | Modified | Update file_path après transfert réussi |
| `src/infrastructure/persistence/repositories/movie_repository.py` | Modified | Lecture/écriture champs techniques |
| `src/infrastructure/persistence/repositories/episode_repository.py` | Modified | Lecture/écriture champs techniques |
| `src/web/routes/library.py` | Modified | Filtres résolution/codec/audio, tri, recherche étendue, first_episode |
| `src/web/templates/library/movie_detail.html` | Modified | Cartouches techniques, Multi, navigation |
| `src/web/templates/library/series_detail.html` | Modified | Cartouches techniques, TVDB link, premier épisode |
| `src/web/templates/library/_filters.html` | Modified | Selects résolution/codec/audio, toggle recherche |
| `src/web/templates/library/_grid.html` | Modified | Script sessionStorage navigation |
| `src/web/templates/library/_reassociate_results.html` | Modified | Fix data-* au lieu onclick |
| `src/web/static/css/style.css` | Modified | Styles tech-badge, Multi, navigation, TVDB |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Tri décroissant par défaut | Plus logique de chercher les meilleurs en premier | UX améliorée |
| data-* au lieu de onclick | Les apostrophes dans les titres cassaient onclick via &#39; | Fix critique |
| Exclure séries documentaires | Identification trop difficile, hors périmètre | 29 séries supprimées |
| Garder séries Doc+Animation | Tu mourras moins bête et À table les enfants sont de l'animation | 2 séries gardées |
| Recréer 3 séries borderline | L'industrie, Marvel Legends, L'an un million ne sont pas des docs | Genres corrigés |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Scope additions | 5 | Améliorations UX majeures demandées post-checkpoint |
| Auto-fixed | 1 | Bug critique ré-association |

**Total impact:** Extensions naturelles du périmètre initial, toutes demandées par l'utilisateur.

### Scope Additions (demandées par l'utilisateur)

1. **Badge Multi langues** — Post-checkpoint : "Multi" + mini-cartouches
2. **Navigation prev/next** — Post-checkpoint : flèches + keyboard + prefetch
3. **Fix ré-association onclick** — Bug découvert pendant les tests
4. **Pipeline métadonnées techniques** — Comblement lacune architecturale majeure
5. **Enrichissement tvdb_id + purge documentaires** — Nettoyage données

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| 1307 films sans file_path | Fallback VideoFileModel pour retrouver le fichier en base |
| Bouton Sélectionner ré-association cassé | Apostrophes dans titres cassaient onclick. Remplacé par data-* + addEventListener |
| 443 films sans métadonnées techniques | Lacune historique import. Pipeline corrigé pour les futurs ajouts |

## UAT Issues (from 09b-01-UAT.md)

| Issue | Status |
|-------|--------|
| UAT-001: Recherche trop réactive | Corrigé (commit 91d92ab) |
| UAT-002: Navigation retour ne conserve pas filtres | Corrigé (retour + bibliothèque, commit 91d92ab) |

## Next Phase Readiness

**Ready:**
- Pipeline workflow propage maintenant toutes les métadonnées techniques
- Filtres avancés et cartouches techniques opérationnels
- Navigation inter-fiches fluide avec prefetch

**Concerns:**
- 1307 films historiques toujours sans file_path (nécessite un enrichissement batch)
- Routes library.py grossit (~650 lignes) — extraction module envisageable

**Blockers:**
- None

---
*Phase: 09b-metadonnees-techniques, Plan: 01*
*Completed: 2026-02-25*
