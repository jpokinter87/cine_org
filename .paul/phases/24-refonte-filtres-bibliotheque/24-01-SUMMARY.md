---
phase: 24-refonte-filtres-bibliotheque
plan: 01
subsystem: ui
tags: [jinja2, css, htmx, filters, layout]

requires: []
provides:
  - Filtres bibliothèque réorganisés en 2 lignes + panneau dépliable
  - Flèches tri intégrées au cartouche (remplace select asc/desc)
  - Bouton suppression intégré dans la barre de filtres
affects: []

tech-stack:
  added: []
  patterns:
    - "Layout filtres 2 lignes : main (recherche/filtres) + secondary (tri/checkboxes/tech/suppression)"
    - "Panneau dépliable via collapsed class + max-height transition"
    - "Flèches tri : hidden input + button toggle + dispatchEvent pour HTMX"

key-files:
  modified:
    - src/web/templates/library/_filters.html
    - src/web/templates/library/index.html
    - src/web/static/css/style.css

key-decisions:
  - "Layout 2 lignes au lieu de tout-en-un : meilleure lisibilité"
  - "Bouton suppression déplacé de index.html vers _filters.html (ligne 2)"
  - "Checkboxes compacts (.lib-filter-checkbox-sm) pour la ligne secondaire"
  - "Bouton suppression rouge sombre discret (.delete-mode-btn-subtle)"

patterns-established:
  - "Toggle technique via data-target + getElementById (bouton séparé du panneau)"

duration: 35min
completed: 2026-02-28T14:15:00Z
---

# Phase 24 Plan 01: Refonte UX Filtres Bibliothèque Summary

**Filtres bibliothèque réorganisés en 2 lignes compactes avec flèches tri, section technique dépliable, et bouton suppression intégré.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~35min |
| Completed | 2026-02-28 |
| Tasks | 2 complétés (1 auto + 1 checkpoint) |
| Files modified | 3 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Groupement logique des filtres | Pass | 2 lignes + panneau dépliable |
| AC-2: Flèches de tri intégrées au cartouche | Pass | Hidden input + boutons ↑↓ avec classe active ambrée |
| AC-3: Section technique dépliable | Pass | Auto-open si filtre actif, badge compteur, animation CSS |
| AC-4: Conservation des fonctionnalités existantes | Pass | Tous les query params inchangés, tags filtres actifs OK |
| AC-5: Cohérence thème sombre | Pass | Variables CSS existantes, palette ambrée + rose |

## Accomplishments

- Réorganisation des 14 contrôles en 2 lignes + panneau dépliable (au lieu d'une seule ligne débordante)
- Remplacement du select Croissant/Décroissant par flèches ↑↓ intégrées au cartouche tri
- Bouton suppression intégré dans la barre de filtres (rouge sombre discret)
- Checkboxes compacts sur la ligne secondaire
- Skill audit: /frontend-design invoqué ✓

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/templates/library/_filters.html` | Modified | Restructuré en 2 lignes + panneau technique dépliable + bouton suppression |
| `src/web/templates/library/index.html` | Modified | Supprimé le div bouton suppression (déplacé dans _filters.html) |
| `src/web/static/css/style.css` | Modified | Nouveau layout (lib-filters-main, lib-filters-secondary, lib-sort-group, lib-filters-tech, checkbox-sm, delete-mode-btn-subtle) |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| 2 lignes séparées au lieu de flex-wrap unique | L'utilisateur trouvait le layout trop haut — les 2 lignes donnent un meilleur contrôle | Structure claire et prévisible |
| Bouton suppression déplacé dans _filters.html | L'utilisateur voulait le bouton sur la 2e ligne avec les checkboxes | Plus compact, moins de lignes |
| Label raccourci "Suppression" au lieu de "Sélectionner pour suppression" | Gain de place sur la ligne | Label identique dans le bouton |
| Style rouge sombre discret pour suppression | Différencie visuellement des filtres sans être intrusif | opacity 0.7 par défaut |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Scope additions | 1 | Bouton suppression déplacé (demande utilisateur) |
| Itérations layout | 2 | Passage flex-wrap unique → 2 lignes séparées |

**Total impact:** Ajustements UX demandés par l'utilisateur pendant le checkpoint — résultat final plus compact et mieux structuré que le plan initial.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Toggle technique cassé après séparation bouton/panneau | Ajout data-target + getElementById au lieu de closest() |

## Next Phase Readiness

**Ready:**
- Phase 24 complète — filtres bibliothèque réorganisés
- Phase 25 (Réconciliation Symlinks/Storage) peut commencer

**Concerns:**
- Aucun

**Blockers:**
- None

---
*Phase: 24-refonte-filtres-bibliotheque, Plan: 01*
*Completed: 2026-02-28*
