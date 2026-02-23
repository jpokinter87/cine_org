---
phase: 05-bibliotheque-maintenance
plan: 01
subsystem: ui
tags: [jinja2, htmx, library, filters, pagination, tmdb-tv, enrichment, credits]

requires:
  - phase: 01-foundation-web
    provides: FastAPI app, layout Jinja2, CSS theme sombre
  - phase: populate-series
    provides: Tables series/episodes peuplées depuis storage

provides:
  - Navigation bibliothèque films/séries avec filtres, tri, pagination
  - Pages détail film et série avec métadonnées, jaquettes, fichiers
  - Enrichissement séries via TMDB TV API (commande enrich-series)
  - Enrichissement crédits films via TMDB (commande enrich-movies-credits)
  - Director/cast sur modèles Movie et Series

affects: [05-02-configuration, 05-03-maintenance]

tech-stack:
  added: [TMDB TV API (search_tv, get_tv_details)]
  patterns: [HTMX partial swap avec hx-push-url, filtres actifs comme tags, lightbox poster CSS-only, refreshOnHistoryMiss pour navigation arrière]

key-files:
  created:
    - src/web/routes/library.py
    - src/web/templates/library/index.html
    - src/web/templates/library/_filters.html
    - src/web/templates/library/_grid.html
    - src/web/templates/library/_pagination.html
    - src/web/templates/library/_content.html
    - src/web/templates/library/movie_detail.html
    - src/web/templates/library/series_detail.html
    - src/web/templates/library/not_found.html
    - src/services/series_enricher.py
    - src/services/movies_enricher.py
  modified:
    - src/web/app.py
    - src/web/static/css/style.css
    - src/web/templates/base.html
    - src/adapters/api/tmdb_client.py
    - src/adapters/cli/commands/enrichment_commands.py
    - src/adapters/cli/commands/__init__.py
    - src/main.py
    - src/core/entities/media.py
    - src/infrastructure/persistence/models.py
    - src/infrastructure/persistence/repositories/movie_repository.py
    - src/infrastructure/persistence/repositories/series_repository.py
    - src/utils/constants.py

key-decisions:
  - "TMDB TV API pour enrichissement séries (pas TVDB) — même clé API, même cache"
  - "IMDb rating prioritaire sur TMDB vote_average (fonction _best_rating)"
  - "htmx.config.refreshOnHistoryMiss=true pour corriger navigation arrière navigateur"
  - "Normalisation titres pour résolution fichiers (strip caractères spéciaux)"
  - "Director/cast stockés dans MovieModel/SeriesModel (cast_json en JSON)"

patterns-established:
  - "Lightbox poster CSS-only avec onclick/Escape"
  - "Filtres HTMX avec tags actifs cliquables pour retirer un filtre"
  - "Collapsible details/summary natif HTML pour infos fichier et saisons"
  - "_find_movie_file() — résolution symlink video/ vers storage par titre normalisé"

duration: ~4h
started: 2026-02-23T10:00:00Z
completed: 2026-02-23T18:00:00Z
---

# Phase 5 Plan 01: Navigation Bibliothèque Summary

**Pages bibliothèque complètes avec grille filtrée HTMX, détails films/séries, enrichissement TMDB TV, crédits réalisateurs/acteurs et informations fichier.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~4h (multi-session) |
| Started | 2026-02-23 |
| Completed | 2026-02-23 |
| Tasks | 3 (dont 1 checkpoint) |
| Files created | 11 |
| Files modified | 12 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Page bibliothèque avec liste et filtres | Pass | Grille responsive 24 items/page, filtres type/genre/année/recherche |
| AC-2: Filtrage HTMX sans rechargement | Pass | hx-get + hx-push-url, tags actifs cliquables, recherche delay:300ms |
| AC-3: Détail d'un film | Pass | Jaquette, synopsis, notes IMDb/TMDB, durée, réalisateur, acteurs, infos fichier |
| AC-4: Détail d'une série avec épisodes | Pass | Saisons repliables, épisodes avec file_path, créateurs, acteurs |
| AC-5: Navigation active navbar | Pass | block nav_library active sur toutes les pages library |

## Accomplishments

- Navigation bibliothèque complète : grille films/séries avec filtres (type, genre, année, recherche texte), tri (titre, année, note), ordre (asc/desc) et pagination
- Pages détail enrichies : jaquette zoomable (lightbox), synopsis, notes IMDb/TMDB, crédits (réalisateur/créateurs + acteurs), informations fichier collapsibles (symlink, storage, codecs, résolution, taille)
- Enrichissement TMDB TV : nouvelle commande `enrich-series` avec search_tv + get_tv_details (poster, genres, notes, overview, crédits)
- Enrichissement crédits films : nouvelle commande `enrich-movies-credits` (réalisateur + 5 acteurs principaux)
- Fix navigation arrière navigateur avec `htmx.config.refreshOnHistoryMiss = true`
- Correction complète des accents français sur toute l'UI bibliothèque

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/routes/library.py` | Created | Routes /library, /library/movies/{id}, /library/series/{id} |
| `src/web/templates/library/index.html` | Created | Page principale bibliothèque |
| `src/web/templates/library/_filters.html` | Created | Panneau filtres HTMX + tags actifs |
| `src/web/templates/library/_grid.html` | Created | Grille responsive de cartes films/séries |
| `src/web/templates/library/_pagination.html` | Created | Pagination avec nav première/précédente/suivante/dernière |
| `src/web/templates/library/_content.html` | Created | Fragment HTMX (filtres + grille) pour swap partiel |
| `src/web/templates/library/movie_detail.html` | Created | Détail film avec jaquette, crédits, infos fichier |
| `src/web/templates/library/series_detail.html` | Created | Détail série avec saisons/épisodes, crédits |
| `src/web/templates/library/not_found.html` | Created | Page 404 pour entités inexistantes |
| `src/services/series_enricher.py` | Created | SeriesEnricherService — enrichissement TMDB TV |
| `src/services/movies_enricher.py` | Created | MoviesEnricherService — enrichissement crédits films |
| `src/web/app.py` | Modified | Enregistrement library_router |
| `src/web/static/css/style.css` | Modified | +736 lignes CSS bibliothèque |
| `src/web/templates/base.html` | Modified | refreshOnHistoryMiss config |
| `src/adapters/api/tmdb_client.py` | Modified | Ajout search_tv(), get_tv_details() |
| `src/utils/constants.py` | Modified | Ajout TMDB_TV_GENRE_MAPPING |
| `src/adapters/cli/commands/enrichment_commands.py` | Modified | Commandes enrich-series, enrich-movies-credits |
| `src/adapters/cli/commands/__init__.py` | Modified | Export nouvelles commandes |
| `src/main.py` | Modified | Enregistrement nouvelles commandes |
| `src/core/entities/media.py` | Modified | Ajout director/cast aux entités Movie, Series |
| `src/infrastructure/persistence/models.py` | Modified | Ajout director/cast_json aux modèles DB |
| `src/infrastructure/persistence/repositories/movie_repository.py` | Modified | Mapping director/cast entity↔model |
| `src/infrastructure/persistence/repositories/series_repository.py` | Modified | Mapping director/cast entity↔model |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| TMDB TV API (pas TVDB) pour séries | Même clé API, même infrastructure cache, endpoints similaires | Simplifie l'enrichissement, pas besoin d'auth TVDB séparée |
| IMDb rating prioritaire | IMDb plus reconnu par les utilisateurs | Cohérence affichage notes dans grille et détails |
| Director/cast dans MovieModel/SeriesModel | Données stables, pas besoin de table séparée | cast_json en JSON, max 5 acteurs principaux |
| Normalisation titres pour lookup fichier | Titres comme '71 ou #Chef ont des caractères spéciaux stripés dans les noms de fichiers | _find_movie_file() compare titres normalisés (alphanumériques uniquement) |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Scope additions | 4 | Enrichissement séries/films + crédits + infos fichier + fix accents |
| Auto-fixed | 2 | Navigation arrière + lookup fichier titres spéciaux |
| Deferred | 2 | Acteurs cliquables + exécution enrichissement |

**Total impact:** Ajouts essentiels demandés par l'utilisateur lors du checkpoint, pas de dérive de scope

### Scope Additions (demandées par l'utilisateur)

1. **Enrichissement séries TMDB TV** — Commande `enrich-series` avec recherche, matching, enrichissement poster/genres/notes/overview/crédits
2. **Enrichissement crédits films** — Commande `enrich-movies-credits` pour réalisateur + acteurs
3. **Informations fichier collapsibles** — Bouton dans les détails film/série montrant symlink, storage path, codecs, résolution, taille
4. **Correction accents français** — Vérification et correction de tous les mots français mal accentués dans l'UI

### Auto-fixed Issues

**1. Navigation arrière navigateur cassée**
- **Issue:** Le bouton page précédente du navigateur affichait un fragment HTMX sans layout
- **Fix:** Ajout `htmx.config.refreshOnHistoryMiss = true` dans base.html
- **Files:** src/web/templates/base.html

**2. Lookup fichier échouant pour titres avec caractères spéciaux**
- **Issue:** `_find_movie_file()` ne trouvait pas les fichiers pour '71, #Chef etc.
- **Fix:** Normalisation des titres (strip non-alphanumériques) pour comparaison
- **Files:** src/web/routes/library.py

### Deferred Items

- Rendre les noms d'acteurs et réalisateurs cliquables (filtre library par acteur/réalisateur)
- Exécution effective des commandes `enrich-series` et `enrich-movies-credits` (~938 séries, ~5650 films)

## Skill Audit

| Expected | Invoked | Notes |
|----------|---------|-------|
| /frontend-design | ○ | Non invoqué formellement — CSS et templates créés directement avec le design system existant (thème sombre, DM Sans, Instrument Serif) |

## Next Phase Readiness

**Ready:**
- Bibliothèque navigable et fonctionnelle
- Infrastructure enrichissement séries/films en place
- Pattern HTMX filtrage/pagination réutilisable pour futures pages

**Concerns:**
- ~938 séries et ~5650 films en attente d'enrichissement (commandes CLI à exécuter)
- CSS style.css grossit (+736 lignes) — envisager un split par module si nécessaire

**Blockers:**
- None

---
*Phase: 05-bibliotheque-maintenance, Plan: 01*
*Completed: 2026-02-23*
