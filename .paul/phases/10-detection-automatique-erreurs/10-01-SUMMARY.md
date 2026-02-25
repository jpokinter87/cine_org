---
phase: 10-detection-automatique-erreurs
plan: 01
subsystem: quality
tags: [association-checker, heuristics, sse, quality-page, tmdb]

requires:
  - phase: 09-correction-manuelle-associations
    provides: mécanisme de ré-association TMDB + overlay HTMX
provides:
  - service AssociationChecker avec heuristiques titre/année/durée
  - page web /quality/suspicious avec SSE temps réel
  - cache fichier persistant 24h
  - confirmation manuelle + exclusion futurs scans
affects: [11-tableau-de-bord-qualite]

tech-stack:
  added: []
  patterns: [SSE streaming avec asyncio, cache fichier JSON persistant]

key-files:
  created:
    - src/services/association_checker.py
    - src/web/routes/quality.py
    - src/web/templates/quality/suspicious.html
    - src/web/templates/quality/_suspicious_list.html
    - tests/unit/test_association_checker.py
  modified:
    - src/infrastructure/persistence/models.py
    - src/web/app.py
    - src/web/templates/base.html
    - src/web/static/css/style.css
    - src/web/routes/library.py

key-decisions:
  - "SSE au lieu de chargement synchrone pour le scan (5000+ fichiers)"
  - "Cache fichier persistant 24h au lieu de cache mémoire (survit aux redémarrages --reload)"
  - "Suppression ciblée du cache lors des ré-associations (pas d'invalidation totale)"
  - "Comparaison titre avec original_title en plus du titre localisé"
  - "Extraction titre série depuis le dossier parent (pas le nom d'épisode)"
  - "Seuils durée en pourcentage (30%/15%) au lieu de valeurs absolues"

patterns-established:
  - "SSE pattern pour opérations longues : asyncio.Queue + run_in_executor"
  - "Cache fichier JSON à ~/.cineorg/ pour données coûteuses à recalculer"
  - "ConfirmedAssociationModel pour exclusions utilisateur persistantes"

duration: ~4h (multi-session)
completed: 2026-02-25T22:00:00Z
---

# Phase 10 Plan 01: Détection Automatique d'Associations TMDB Suspectes

**Service de détection heuristique avec page web SSE, cache persistant 24h et confirmation manuelle**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~4h (multi-session) |
| Completed | 2026-02-25 |
| Tasks | 3 completed |
| Files created | 5 |
| Files modified | 5 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Détection films suspects par heuristiques | Pass | Titre (+ original_title), année, durée (% vs absolu) |
| AC-2: Détection séries suspectes par heuristiques | Pass | Titre extrait du dossier parent (pas du nom d'épisode) |
| AC-3: Page web listant les associations suspectes | Pass | SSE temps réel, cache 24h, filtres films/séries/tous |
| AC-4: Navigation intégrée | Pass | Lien "Qualité" dans la nav principale |

## Accomplishments

- Service `AssociationChecker` avec 3 heuristiques (titre, année, durée) et score de confiance 0-100
- Page `/quality/suspicious` avec progression SSE temps réel (scan ~5000 fichiers)
- Cache fichier persistant 24h à `~/.cineorg/quality_scan_cache.json`
- Bouton "Confirmer" avec modal custom + persistance en DB (`ConfirmedAssociationModel`)
- Mise à jour automatique des cartes lors des ré-associations (via `visibilitychange`)
- Comparaison avec `original_title` pour réduire les faux positifs (films étrangers)
- Extraction titre série depuis le dossier parent (évite faux positifs épisodes)

## Task Commits

| Task | Commit | Type | Description |
|------|--------|------|-------------|
| Task 1-2: Service + page web | `b62a61c` | feat | Service, routes, templates, modèle, tests |
| Task 3: Checkpoint | - | verify | Vérification visuelle approuvée |

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/services/association_checker.py` | Created | Service de détection avec heuristiques |
| `src/web/routes/quality.py` | Created | Routes SSE + confirmation + cache |
| `src/web/templates/quality/suspicious.html` | Created | Page principale avec SSE et modal |
| `src/web/templates/quality/_suspicious_list.html` | Created | Fragment résultats avec cartes |
| `tests/unit/test_association_checker.py` | Created | 9 tests unitaires |
| `src/infrastructure/persistence/models.py` | Modified | Ajout ConfirmedAssociationModel |
| `src/web/app.py` | Modified | Montage quality_router |
| `src/web/templates/base.html` | Modified | Lien "Qualité" dans la nav |
| `src/web/static/css/style.css` | Modified | Styles cartes suspectes, modal, badges |
| `src/web/routes/library.py` | Modified | Auto-confirmation lors des ré-associations |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| SSE au lieu de synchrone | Scan de ~5000 fichiers trop lent pour requête bloquante | UX fluide avec barre de progression |
| Cache fichier vs mémoire | Cache mémoire perdu à chaque `--reload` en dev | Persistance 24h, suppression ciblée possible |
| Durée en % vs absolu | 15min d'écart sur un film de 2h = 12% (normal), sur un film de 30min = 50% (suspect) | Moins de faux positifs |
| original_title | Films étrangers : "Autant en emporte le vent" vs "Gone with the Wind" | Réduction massive des faux positifs |
| Titre série depuis dossier | Fichiers épisodes nommés par titre d'épisode, pas de série | Élimination faux positifs séries |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Scope additions | 5 | Améliorations essentielles demandées par l'utilisateur |
| Deferred | 1 | Skill gap /frontend-design |

**Total impact:** Scope étendu au-delà du plan initial mais toutes les additions étaient des corrections de faux positifs ou des améliorations UX demandées par l'utilisateur.

### Scope Additions

1. **Cache fichier persistant** — Non prévu dans le plan (scope limits disait "pas de cache persistant") mais nécessaire pour l'usage réel (5000 fichiers = scan lent)
2. **Confirmation manuelle** — Prévue pour Phase 11 mais ajoutée ici car indispensable pour le workflow
3. **Comparaison original_title** — Découverte lors des tests utilisateur (faux positifs films étrangers)
4. **Extraction titre série depuis dossier** — Découverte lors des tests (faux positifs épisodes)
5. **Durée en pourcentage** — Alignement avec le CLI existant

### Skill Audit

| Expected | Invoked | Notes |
|----------|---------|-------|
| /frontend-design | ○ | Non invoqué — templates créés directement avec le thème existant |

### Deferred Items

- Enrichissement mediainfo batch : 443 films avec file_path mais sans résolution/codecs (import historique sans extraction)

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| HTMX ne détecte pas les boutons injectés via SSE | Ajout `htmx.process(results)` après innerHTML |
| `confirm()` natif ne respecte pas le thème | Modal custom `.confirm-overlay` |
| Cache mémoire perdu à chaque `--reload` | Migration vers cache fichier `~/.cineorg/` |
| Genres avec accents non matchés | Helper `_genre_json_escaped()` + correspondance insensible accents |

## Next Phase Readiness

**Ready:**
- Le mécanisme de détection et confirmation est en place
- Le cache persistant peut servir de base pour le tableau de bord
- `ConfirmedAssociationModel` permet de tracker les confirmations

**Concerns:**
- 443 films sans métadonnées techniques (enrichissement mediainfo batch à planifier)
- `library.py` grossit (~600 lignes) — extraction module envisageable

**Blockers:**
- None

---
*Phase: 10-detection-automatique-erreurs, Plan: 01*
*Completed: 2026-02-25*
