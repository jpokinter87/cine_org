---
phase: 15-que-regarder-ce-soir
plan: 02
subsystem: ui, routing
tags: [suggestion, random, filters, htmx, css-animation, fastapi]

requires:
  - phase: 15-que-regarder-ce-soir
    provides: colonnes watched et personal_rating sur MovieModel et SeriesModel
provides:
  - Page "Surprends-moi" avec suggestion aléatoire filtrée
  - Bouton accueil avec animation glow ambrée
  - Footer version corrigée v1.4
affects: [16-lecteur-distant]

tech-stack:
  added: []
  patterns: [auto-submit filtres onchange, animation CSS one-shot via JS class toggle, grid 4 colonnes actions alignées sur stats]

key-files:
  created:
    - src/web/routes/library/suggest.py
    - src/web/templates/library/suggest.html
  modified:
    - src/web/routes/library/__init__.py
    - src/web/templates/home.html
    - src/web/templates/base.html
    - src/web/static/css/style.css

key-decisions:
  - "Paramètres max_duration et min_rating en str avec parsing manuel (évite erreur FastAPI sur chaîne vide)"
  - "Auto-submit filtres via onchange natif (pas HTMX, rechargement complet OK pour cette page)"
  - "Animation glow récurrente à chaque mouvement souris avec cooldown 3s (class toggle JS)"
  - "Grid 4 colonnes pour actions-row aligné sur stats-grid"

patterns-established:
  - "Filtre auto-submit via onchange=this.form.submit() pour formulaires GET simples"
  - "Animation attention via mousemove + class toggle + setTimeout cleanup"

duration: ~40min
completed: 2026-02-26
---

# Phase 15 Plan 02: Page "Surprends-moi" — Summary

**Page suggestion aléatoire avec filtres genre/durée/note, auto-submit, bouton accueil animé et footer v1.4**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~40min |
| Completed | 2026-02-26 |
| Tasks | 3 auto + 1 checkpoint (3 cycles corrections) |
| Files created | 2 |
| Files modified | 4 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Algorithme de suggestion | Pass | Random parmi non-vus + re-watch si note >= 4 |
| AC-2: Filtres optionnels | Pass | Genre, durée, type + note minimale (ajout) |
| AC-3: Page suggestion avec résultat | Pass | Jaquette, infos, boutons "Autre" et "Voir la fiche" |
| AC-4: Bouton accueil et navigation | Pass | 4ème bouton avec animation glow ambrée |
| AC-5: Version footer corrigée | Pass | "CineOrg v1.4" |

## Accomplishments

- Page `/library/suggest` avec algorithme de suggestion aléatoire (non-vus + re-watch si note >= 4)
- Filtres auto-submit : genre, durée max, note minimale (6+/7+/8+), type (films/séries/tous)
- Bouton "Surprends-moi" sur la page d'accueil avec animation glow ambrée récurrente au mousemove
- Actions-row en grid 4 colonnes aligné sur les 4 cartouches stats
- Footer corrigé de v0.1.0 à v1.4
- 875 tests, 0 régressions

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/routes/library/suggest.py` | Created | Route GET /library/suggest avec algorithme et filtres |
| `src/web/templates/library/suggest.html` | Created | Template page suggestion avec filtres auto-submit |
| `src/web/routes/library/__init__.py` | Modified | Import suggest.router avant detail.router |
| `src/web/templates/home.html` | Modified | 4ème bouton "Surprends-moi" + script animation glow |
| `src/web/templates/base.html` | Modified | Footer v0.1.0 → v1.4 |
| `src/web/static/css/style.css` | Modified | Styles suggest-*, action-surprise, animation surpriseReveal, grid actions-row |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| max_duration/min_rating en str + parsing manuel | FastAPI rejette `""` pour Optional[int] | Robuste face aux formulaires HTML |
| Auto-submit filtres via onchange | Demande utilisateur — pas intuitif de devoir cliquer "Lancer" | UX fluide, bouton Lancer reste en fallback |
| Filtre note minimale ajouté | Demande utilisateur — permet de ne voir que les bien notés | Filtrage côté Python post-requête (simple) |
| Animation glow récurrente au mousemove | Demande utilisateur — attire l'attention sur le bouton | Cooldown 3s via setTimeout, pas fatigant |
| Grid 4 colonnes pour actions-row | Alignement visuel avec les 4 cartouches stats | Responsive 2 colonnes tablette, 1 mobile |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Scope additions | 3 | Améliorations UX demandées par l'utilisateur |
| Auto-fixed | 1 | Parsing params vides |

**Total impact:** Extensions demandées par l'utilisateur, améliorent significativement l'UX.

### Scope Additions

**1. Filtre note minimale**
- **Demandé par:** Utilisateur pendant checkpoint
- **Impact:** Paramètre `min_rating` ajouté à la route, select dans le template
- **Justification:** Permet de ne suggérer que des films bien notés

**2. Auto-submit filtres**
- **Demandé par:** Utilisateur pendant checkpoint
- **Impact:** `onchange="this.form.submit()"` sur tous les selects
- **Justification:** Changer un filtre sans cliquer "Lancer" n'était pas intuitif

**3. Animation glow récurrente + grid 4 colonnes**
- **Demandé par:** Utilisateur après approbation initiale
- **Impact:** CSS animation, JS mousemove listener, grid layout
- **Justification:** Alignement visuel stats/boutons + signal d'attention sur "Surprends-moi"

### Auto-fixed Issues

**1. Parsing params vides (max_duration)**
- **Found during:** Checkpoint — "Autre suggestion" crashait
- **Issue:** FastAPI rejetait `""` pour `Optional[int]`
- **Fix:** Changé en `Optional[str]` avec parsing manuel `int()`
- **Files:** suggest.py

## Skill Audit

Skill audit: All required skills invoked ✓
- /frontend-design : invoqué pour le design de la page suggestion et l'animation glow

## Next Phase Readiness

**Ready:**
- Phase 15 complète — watched, rating, suggestion en place
- Bouton "Surprends-moi" accessible depuis l'accueil
- Phase 16 (Lecteur Distant) peut être lancée

**Concerns:**
- Aucune

**Blockers:**
- None

---
*Phase: 15-que-regarder-ce-soir, Plan: 02*
*Completed: 2026-02-26*
