---
phase: 43-correctifs-bibliotheque
plan: 02
subsystem: ui
tags: [ux, search, htmx, debounce, clear-button, focus, accessibility]

requires:
  - phase: 24-filtres-bibliotheque
    provides: pattern lib-filters avec HTMX + form externe au target
  - phase: 42-02
    provides: overlay d'édition métadonnées (input URL)

provides:
  - Script JS réutilisable `static/js/input_clear.js` attachant un bouton ✕ à tout input[data-clearable]
  - Support des parents déjà positionnés (ex : .lib-search-wrap) sans wrap imbriqué
  - Résilience navigation historique : htmx:historyRestore + pageshow (bfcache)
  - Debounce recherche bibliothèque passé de 700ms à 1000ms
  - hx-preserve sur le champ q pour conserver le focus lors du swap
  - Classes CSS .input-clearable-wrap / .input-clearable-host / .input-clear-btn

affects:
  - Futures surfaces UX pouvant bénéficier de data-clearable (profils lecteur, config paths, tous les inputs texte du site)

tech-stack:
  added: []
  patterns:
    - "Attribut data-clearable + JS global auto-attach via DOMContentLoaded + htmx:afterSwap + htmx:historyRestore + pageshow(persisted)"
    - "Protection anti-doublon container-level (pas seulement input-level)"

key-files:
  created:
    - src/web/static/js/input_clear.js
  modified:
    - src/web/templates/base.html (include input_clear.js avec defer)
    - src/web/templates/library/_filters.html (data-clearable + hx-preserve + debounce 1000ms + autocomplete=off + id)
    - src/web/templates/library/_edit_metadata.html (data-clearable sur input URL)
    - src/web/static/css/style.css (~50 lignes .input-clearable-*)

key-decisions:
  - "Bouton injecté par JS plutôt que rendu Jinja : 1 seul endroit à maintenir, applicable partout avec data-clearable"
  - "hx-preserve='true' sur l'input de recherche : garantit que HTMX ne le remplace jamais lors du swap, focus préservé"
  - "autocomplete='off' : évite les suggestions navigateur qui masquent les filtres"
  - "Debounce 1000ms : sweet spot empirique entre réactivité et tolérance aux fautes"
  - "Listeners multiples (htmx:afterSwap + htmx:historyRestore + pageshow) : robustesse face aux différents modes de restauration de page"
  - "Protection anti-doublon au niveau container (querySelector :scope) : dédup robuste même si le bouton était dans le cache HTMX"

patterns-established:
  - "window.InputClear API publique : InputClear.attach(input) / InputClear.scan(root) pour usages custom"
  - "data-clearable comme contrat standard : aucun wiring par template requis"

duration: ~50min
started: 2026-04-14T23:40:00Z
completed: 2026-04-14T24:30:00Z
---

# Phase 43 Plan 02 : Ergonomie champs texte (bouton ✕ + debounce recherche) — Summary

**Script JS réutilisable input_clear.js qui attache automatiquement un bouton ✕ à tout input[data-clearable] (avec résilience navigation historique), appliqué à la recherche bibliothèque (debounce porté à 1000ms + hx-preserve pour le focus) et à l'input URL de l'overlay d'édition métadonnées.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~50 min (incl. correctifs post-test visuel) |
| Started | 2026-04-14 23:40 |
| Completed | 2026-04-14 24:30 |
| Tasks | 3 auto |
| Files modified | 4 + 1 créé |
| Tests | 1204/1204 globaux verts (pas de nouveau test automatisé pour ce plan UI) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Bouton ✕ réutilisable via data-clearable | ✓ | Scans auto DOMContentLoaded + htmx:afterSwap + htmx:historyRestore + pageshow |
| AC-2: Recherche biblio : ✕ + debounce 1000ms + focus préservé | ◐ | Debounce 1000ms ✓, hx-preserve ✓, bouton visible ✓. **Décalage visuel du hover rose non résolu — deferred (voir plus bas)** |
| AC-3: Overlay édition : ✕ sur input URL | ✓ | data-clearable ajouté |
| AC-4: Aucune régression sur autres inputs | ✓ | 1204/1204 tests verts, aucun input sans data-clearable n'est impacté |

## Accomplishments

- **Pattern data-clearable extensible** : toute nouvelle surface peut bénéficier du bouton ✕ en ajoutant un simple attribut HTML, sans toucher au JS.
- **Focus de recherche préservé** : la frappe rapide sur /library/ n'est plus coupée par le swap HTMX grâce à hx-preserve="true".
- **Robustesse historique** : la navigation back/forward du navigateur ne « perd » plus le bouton ✕, grâce aux listeners htmx:historyRestore et pageshow.
- **Anti-doublon container-level** : au rescan, si un bouton existe déjà dans le conteneur de l'input, on ne duplique pas — résilience aux passes multiples.

## Task Commits

| Task | Commit | Type | Description |
|------|--------|------|-------------|
| T1: Script JS + CSS réutilisables | (à commiter) | feat | input_clear.js + include base.html + CSS dédié |
| T2: Recherche bibliothèque | (à commiter) | feat | data-clearable + hx-preserve + debounce 1000ms + autocomplete=off |
| T3: Overlay édition URL | (à commiter) | feat | data-clearable sur input poster_url |

**À commiter** : un seul commit groupé `feat(phase-43-02): bouton ✕ réutilisable sur inputs + debounce recherche 1000ms`.

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/static/js/input_clear.js` | Created | Module IIFE autonome : scan + attach + protection doublon + 4 events de rescan |
| `src/web/templates/base.html` | Modified | `<script src="/static/js/input_clear.js" defer>` |
| `src/web/templates/library/_filters.html` | Modified | `data-clearable` + `hx-preserve="true"` + `id` + `autocomplete="off"` + `delay:1000ms` |
| `src/web/templates/library/_edit_metadata.html` | Modified | `data-clearable` sur `<input type="url">` |
| `src/web/static/css/style.css` | Modified | `.input-clearable-wrap` / `.input-clearable-host` / `.input-clear-btn` + hover (simplifié sans bordure pour éviter décalage) |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Attribut `data-clearable` | Simple à appliquer, pas besoin de modifier le template par feature | Extensible à toutes les surfaces futures |
| JS global plutôt que macro Jinja | Rendu JS = rendu dynamique, gère les nouveaux inputs via HTMX sans modifier le routeur | 1 source de vérité |
| 4 listeners rescan (DOMContentLoaded, htmx:afterSwap, htmx:historyRestore, pageshow) | Couvre tous les cas de restauration DOM : initial, swap HTMX, back/forward, bfcache | Résilience maximale |
| hx-preserve sur le champ de recherche | Garantit conservation de l'élément DOM lors du swap → focus préservé sans hack | Pattern clair et maintenable |
| Bordure retirée au hover (cause du décalage perçu) | `border: 1px solid` au hover ajoute 2px au layout box-sizing content-box, décale visuellement la pastille | Hover purement color + background |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed (post-test visuel) | 2 | Itération sur le hover CSS + listeners historique |
| Scope additions | 0 | — |
| Deferred | 1 | Décalage visuel résiduel du hover rose (voir ci-dessous) |

### Auto-fixed (post-test visuel)

**1. Croix ne s'affichait pas après retour depuis une fiche**
- **Found during:** Test UI utilisateur
- **Cause:** HTMX restaure le HTML depuis son cache sans re-exécuter le JS qui injecte le bouton
- **Fix:** Ajout des listeners `htmx:historyRestore` et `pageshow` (event.persisted)
- **Additionnel:** Protection anti-doublon container-level (querySelector :scope) pour tolérer les cas où le bouton est dans le cache

**2. Décalage visuel de la pastille rose au hover**
- **Found during:** Test UI utilisateur (capture d'écran : pastille rose apparaît décalée par rapport à la croix)
- **Hypothèse initiale:** `border: 1px solid transparent` → `border-color` au hover ajoute 2px dans box-sizing content-box
- **Fix appliqué:** Retrait complet de la bordure du bouton + box-sizing: border-box explicite + line-height: 1 + SVG display: block
- **Statut:** Partiellement amélioré — décalage résiduel signalé par l'utilisateur après fix CSS

### Deferred Items

**Décalage visuel résiduel du hover rose** (signalé après fixes CSS) :
- Après retrait de la bordure + box-sizing + line-height, le décalage persiste côté utilisateur
- Hypothèses restantes à investiguer dans un plan dédié ou en session interactive :
  1. Cache navigateur CSS non purgé (test Ctrl+F5 à proposer en premier)
  2. Injection double du bouton non couverte par l'anti-doublon actuel (bouton créé avant le fix, déjà dans le DOM quand le hover est testé)
  3. Conflit avec d'autres règles CSS spécifiques à `.lib-search-wrap` (ex. flex-align, gap)
  4. SVG interne avec transform interne ou viewBox mal calibré
- **Action recommandée** : test Ctrl+F5 d'abord ; si persistance, ouvrir un plan 43-03 ou issue dédiée avec DevTools inspector pour mesurer les offsets exactes
- **Pas de test automatisé** : c'est du pixel-perfect visuel, difficile à automatiser sans snapshot testing

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| `hx-preserve` nécessite un `id` unique sur l'input | Ajout de `id="lib-search-input"` |
| Cohabitation du bouton ✕ avec l'icône loupe dans `.lib-search-wrap` | Détection du parent déjà positionné → pas de wrap imbriqué, injection directe du bouton |
| Script `defer` vs `document.readyState` | Handler avec `document.readyState === 'loading'` puis sinon scan immédiat → fonctionne dans les 2 cas |

## Next Phase Readiness

**Ready:**
- Phase 43 complète à 2 plans — milestone v2.1 désormais 75% (3/4 phases)
- **Dernière phase restante** : **41 Intégration Jellyfin** (montage volumes Docker)
- Pattern `data-clearable` disponible pour tout futur input texte

**Concerns:**
- Décalage visuel résiduel du hover ✕ à investiguer en session interactive (non bloquant, purement UX)
- Surveiller les comportements de swap HTMX sur les futures pages : la combinaison hx-preserve + data-clearable est une bonne recette, à documenter si réutilisée

**Blockers:** None

**Commit à créer :** `feat(phase-43-02): bouton ✕ réutilisable sur inputs + debounce recherche 1000ms + hx-preserve focus`

---
*Phase: 43-correctifs-bibliotheque, Plan: 02*
*Completed: 2026-04-14*
