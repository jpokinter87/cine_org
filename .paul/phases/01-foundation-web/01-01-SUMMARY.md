---
phase: 01-foundation-web
plan: 01
subsystem: web
tags: [fastapi, jinja2, htmx, uvicorn, css-custom]

requires:
  - phase: none
    provides: first web plan, no prior dependencies
provides:
  - FastAPI application with DI container integration
  - Jinja2 base layout with HTMX
  - Home page with library statistics
  - CLI serve command
affects: [02-validation-ui, 03-workflow-web, 04-transfer-web, 05-library-web]

tech-stack:
  added: [fastapi, uvicorn, jinja2]
  patterns: [lifespan-di, deps-module, lazy-import]

key-files:
  created:
    - src/web/app.py
    - src/web/deps.py
    - src/web/routes/home.py
    - src/web/templates/base.html
    - src/web/templates/home.html
    - src/web/static/css/style.css
  modified:
    - src/main.py
    - pyproject.toml
    - requirements.txt

key-decisions:
  - "Import uvicorn paresseux dans serve() pour ne pas impacter le CLI"
  - "Module deps.py séparé pour éviter import circulaire app↔routes"
  - "Dépendances ajoutées dans pyproject.toml (source de vérité pour uv)"
  - "func.count() SQL direct plutôt que chargement complet des repos"

patterns-established:
  - "Lifespan pattern: Container DI initialisé via asynccontextmanager"
  - "deps.py: dépendances partagées (templates) dans module séparé"
  - "Routes dans src/web/routes/ avec un fichier par domaine"
  - "Templates dans src/web/templates/ avec héritage base.html"
  - "CSS custom dans src/web/static/css/"

duration: ~30min
started: 2026-02-23T11:30:00Z
completed: 2026-02-23T11:55:00Z
---

# Phase 1 Plan 01: Foundation Web Summary

**Application FastAPI avec Container DI, layout Jinja2 thème cinéma sombre (Instrument Serif + DM Sans), HTMX, et page d'accueil affichant 5650 films.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~25min |
| Started | 2026-02-23 11:30 |
| Completed | 2026-02-23 11:55 |
| Tasks | 3 completed (2 auto + 1 checkpoint) |
| Files created | 8 |
| Files modified | 3 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: FastAPI démarre et répond | Pass | `serve` démarre uvicorn, GET / retourne 200 |
| AC-2: Container DI intégré | Pass | Lifespan initialise Container, sessions via get_session() |
| AC-3: Layout avec navigation et HTMX | Pass | base.html avec nav responsive, HTMX 2.0.4 via CDN |
| AC-4: Page d'accueil avec statistiques | Pass | 4 stats affichées (films, séries, épisodes, en attente) |
| AC-5: CLI préservé | Pass | 845 tests passent, toutes commandes visibles dans --help |

## Accomplishments

- Application FastAPI fonctionnelle avec Container DI via lifespan pattern
- Layout Jinja2 responsive avec thème cinéma sombre, animations d'entrée en cascade
- Page d'accueil avec 4 cartes de stats colorées et section actions rapides
- Commande CLI `serve` avec options --host, --port, --reload

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/web/__init__.py` | Created | Package web |
| `src/web/app.py` | Created | Application FastAPI, lifespan DI, static files |
| `src/web/deps.py` | Created | Templates Jinja2 partagées (évite import circulaire) |
| `src/web/routes/__init__.py` | Created | Package routes |
| `src/web/routes/home.py` | Created | GET / avec stats via func.count() |
| `src/web/templates/base.html` | Created | Layout HTML5, nav, HTMX, Google Fonts |
| `src/web/templates/home.html` | Created | Page accueil avec stats et actions rapides |
| `src/web/static/css/style.css` | Created | Thème sombre cinéma, responsive, animations |
| `src/main.py` | Modified | Ajout commande serve (import uvicorn paresseux) |
| `pyproject.toml` | Modified | Ajout dépendances fastapi, uvicorn, jinja2 |
| `requirements.txt` | Modified | Décommenté dépendances web |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| deps.py pour templates | Évite import circulaire app.py ↔ routes/home.py | Pattern à suivre pour toutes les routes futures |
| Import uvicorn paresseux | Ne pas forcer le chargement de uvicorn pour les commandes CLI | Aucun impact négatif |
| pyproject.toml comme source | uv utilise pyproject.toml, pas requirements.txt | Toutes futures dépendances dans pyproject.toml |
| func.count() SQL direct | Plus efficace que charger toutes les entités en mémoire | Pattern à réutiliser pour futures stats |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 2 | Essentiels, pas de scope creep |
| Scope additions | 1 | Fichier deps.py non prévu |
| Deferred | 0 | - |

**Total impact:** Corrections techniques nécessaires, aucun changement de scope.

### Auto-fixed Issues

**1. Import circulaire app↔routes**
- **Found during:** Task 1
- **Issue:** app.py importait home router, home.py importait templates depuis app.py
- **Fix:** Extraction des templates dans deps.py
- **Files:** src/web/deps.py (créé), src/web/app.py, src/web/routes/home.py
- **Verification:** Import fonctionne sans erreur

**2. pyproject.toml non mis à jour**
- **Found during:** Checkpoint Task 1 (user feedback)
- **Issue:** uv utilise pyproject.toml, pas requirements.txt — fastapi non installé
- **Fix:** Ajout des 3 dépendances web dans pyproject.toml + uv sync
- **Files:** pyproject.toml
- **Verification:** uv run python -m src.main serve fonctionne

## Skill Audit

| Expected | Invoked | Notes |
|----------|---------|-------|
| /frontend-design | ✓ | Utilisé pour Task 2 (layout + CSS) |

All required skills invoked.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| pyenv intercepte `python` dans le shell | Utiliser `.venv/bin/python` ou `uv run python` |
| Port 8000 occupé après test | kill -9 du processus orphelin |

## Next Phase Readiness

**Ready:**
- FastAPI app fonctionnelle avec Container DI
- Layout Jinja2 extensible (base.html + blocs)
- Pattern routes établi (routes/{domain}.py)
- HTMX chargé et prêt pour interactivité
- CSS design system avec variables (couleurs, radius, fonts)

**Concerns:**
- Aucun

**Blockers:**
- None

---
*Phase: 01-foundation-web, Plan: 01*
*Completed: 2026-02-23*
