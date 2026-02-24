---
phase: 09-correction-manuelle-associations
plan: 01
subsystem: ui
tags: [htmx, tmdb, reassociation, overlay, mediainfo]

requires:
  - phase: 08-fiches-detaillees-enrichies
    provides: Fiches détaillées avec tmdb_id, liens TMDB, crédits
provides:
  - Correction manuelle d'associations TMDB depuis la fiche web
  - Indicateurs de confiance durée (films) et saisons/épisodes (séries)
  - Dialog de confirmation stylisé (remplace confirm() natif)
affects: [phase-10-detection-automatique, phase-11-tableau-bord-qualite]

tech-stack:
  added: []
  patterns: [overlay HTMX avec recherche live, mediainfo pour durée fichier physique, symlink resolution]

key-files:
  created:
    - src/web/templates/library/_reassociate_overlay.html
    - src/web/templates/library/_reassociate_results.html
  modified:
    - src/web/routes/library.py
    - src/web/static/css/style.css
    - src/web/templates/library/movie_detail.html
    - src/web/templates/library/series_detail.html

key-decisions:
  - "Durée locale via mediainfo sur fichier physique (résolution symlink), pas la valeur DB"
  - "Indicateurs séries basés sur nombre saisons/épisodes locaux vs TMDB"
  - "Dialog de confirmation custom en CSS (pas de confirm() natif)"
  - "Tri des candidats par proximité (durée films, épisodes séries)"

patterns-established:
  - "Résolution symlink video/ → storage/ pour accéder aux fichiers physiques"
  - "Overlay HTMX avec recherche live et fragments HTML partiels"
  - "Dialog de confirmation custom réutilisable (reassociate-confirm-overlay)"

duration: ~120min
started: 2026-02-24T10:00:00Z
completed: 2026-02-24T12:00:00Z
---

# Phase 9 Plan 01: Correction Manuelle Associations Summary

**Overlay de ré-association TMDB depuis les fiches web avec indicateurs de confiance durée/saisons et dialog de confirmation stylisé**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~120 min |
| Tasks | 3 completed (dont 1 checkpoint) |
| Files created | 2 |
| Files modified | 4 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Bouton correction visible | Pass | Bouton "Corriger" dans la zone badges des fiches film et série |
| AC-2: Recherche TMDB dans overlay | Pass | Overlay avec champ pré-rempli, recherche auto au chargement, résultats enrichis |
| AC-3: Ré-association complète | Pass | POST met à jour toutes les métadonnées TMDB, HX-Redirect recharge la page |
| AC-4: Indicateurs durée (films) | Pass | Durée locale via mediainfo + badges colorés (vert/jaune/rouge) + tri par proximité |
| AC-5: Indicateurs séries | Pass | Saisons/épisodes locaux vs TMDB avec badges colorés + tri par proximité |

## Accomplishments

- Overlay de recherche TMDB fonctionnel pour films et séries avec résultats enrichis (poster, année, synopsis, crédits)
- Indicateurs de confiance colorés : durée comparée pour les films (mediainfo vs TMDB), saisons/épisodes pour les séries
- Tri automatique des candidats par pertinence (proximité durée ou nombre d'épisodes)
- Dialog de confirmation stylisé dans la charte graphique sombre (remplace le confirm() natif du navigateur)
- Ré-association complète : mise à jour de toutes les métadonnées TMDB + auto-liaison du fichier physique via symlink

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/routes/library.py` | Modified (+480 lines) | 6 routes (GET overlay/search + POST) pour films et séries, helpers `_get_file_duration`, `_duration_indicator`, `_series_indicator`, `_get_local_series_counts` |
| `src/web/templates/library/_reassociate_overlay.html` | Created | Overlay de recherche avec champ auto-rempli, info locale (durée/saisons), auto-search |
| `src/web/templates/library/_reassociate_results.html` | Created | Cartes candidats enrichies avec badges confiance, dialog de confirmation custom |
| `src/web/static/css/style.css` | Modified (+379 lines) | Styles overlay, cartes, badges durée/saisons, dialog confirmation, responsive |
| `src/web/templates/library/movie_detail.html` | Modified | Bouton "Corriger" + container overlay |
| `src/web/templates/library/series_detail.html` | Modified | Bouton "Corriger" + container overlay |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Durée via mediainfo (pas la DB) | La durée DB vient de TMDB et peut correspondre à une mauvaise association | Résolution symlink obligatoire pour trouver le fichier physique |
| Indicateurs séries par épisodes | Pas de durée unitaire fiable pour les séries (formatées) | Comparaison saisons + épisodes locaux vs TMDB |
| Dialog custom au lieu de confirm() | Le confirm() natif ne respecte pas la charte graphique sombre | Pattern réutilisable avec overlay CSS |
| Auto-search au chargement | L'overlay doit montrer les résultats immédiatement | `htmx.ajax()` au lieu de `htmx.trigger()` qui ne fonctionnait pas |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 3 | Essentiels, aucun scope creep |
| Scope additions | 1 | Indicateur séries enrichi |
| Deferred | 0 | - |

**Total impact:** Corrections itératives sur les indicateurs de durée et le dialog de confirmation. Le résultat final dépasse le plan initial.

### Auto-fixed Issues

**1. URL entity_type double-s pour séries**
- **Found during:** Task 2
- **Issue:** `{{ entity_type }}s` avec `entity_type="series"` donnait `/library/seriess/...` (404)
- **Fix:** Conditionnel Jinja2 `entity_type ~ 's' if entity_type == 'movie' else entity_type`
- **Files:** `_reassociate_overlay.html`, `_reassociate_results.html`

**2. Durée locale depuis mediainfo au lieu de la DB**
- **Found during:** Task 2 (feedback utilisateur)
- **Issue:** `duration_seconds` en DB vient de TMDB, potentiellement de la mauvaise association
- **Fix:** Ajout `_get_file_duration()` qui résout le symlink video/ → storage/ puis extrait la durée via MediaInfoExtractor

**3. Dialog natif remplacé par custom**
- **Found during:** Task 3 checkpoint
- **Issue:** `hx-confirm` déclenche le `confirm()` natif du navigateur, incohérent avec le thème sombre
- **Fix:** Dialog overlay custom avec classes CSS dédiées

### Scope Addition

**Indicateur saisons/épisodes pour les séries**
- Ajouté `_series_indicator()` et `_get_local_series_counts()` pour comparer le contenu local (DB episodes) avec les données TMDB
- Tri des candidats séries par proximité du nombre d'épisodes

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| `htmx.trigger()` ne lance pas la recherche initiale | Remplacé par `htmx.ajax('GET', url, {target})` |
| 1306 films sans `file_path` en DB | Commande `link-movies` existante pour backfill ; auto-liaison ajoutée au POST |
| Serveur non rechargé après modifications Python | Templates Jinja2 rechargés à chaud, mais routes Python nécessitent `--reload` |

## Next Phase Readiness

**Ready:**
- Mécanisme de correction manuelle en place (films + séries)
- Indicateurs de confiance fonctionnels pour guider la Phase 10 (détection automatique)
- Pattern overlay HTMX réutilisable

**Concerns:**
- 1306 films sans `file_path` — l'indicateur de durée ne fonctionne pas pour eux
- Code routes library.py grossit (+480 lignes) — extraction possible dans un module dédié

**Blockers:**
- None

---
*Phase: 09-correction-manuelle-associations, Plan: 01*
*Completed: 2026-02-24*
