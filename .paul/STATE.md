# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-25)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.3 Qualité & Fluidité — Phase 14 next

## Current Position

Milestone: v1.3 Qualité & Fluidité
Phase: 14 of 14 — Workflow Fluide
Plan: Not started
Status: Ready to plan
Last activity: 2026-02-25 — Phase 13 complete, transitioned to Phase 14

Progress:
- v1.3: [███████░░░] 67%
- Phase 14: [░░░░░░░░░░] 0%

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ○        ○        ○     [Ready for new PLAN]
```

## Accumulated Context

### Decisions
- Web = complément du CLI, jamais un remplacement
- Stack : FastAPI + Jinja2 + HTMX (pas de SPA)
- CSS custom thème sombre (Instrument Serif + DM Sans)
- Ligatures traitées par expansion explicite (œ→oe, æ→ae)
- Recherche SQL via OR sur variantes (contourne limitation SQLite LIKE unicode)
- Code partagé CLI/web via factory functions standalone dans src/services/workflow/
- Package library/ avec sous-routers FastAPI pour découpage routes web

### Deferred Issues
- 1260 films sans file_path (noms trop différents pour match exact)
- 367 épisodes sans titre (262 non trouvés TVDB + 105 sans tvdb_id)
- Symlinks épisodes ne reflètent pas les nouveaux titres

### Blockers/Concerns
None.

### Git State
Last commit: ad7fb9c (uncommitted changes from Phase 13)
Branch: master

## Session Continuity

Last session: 2026-02-25
Stopped at: Phase 13 complete, ready to plan Phase 14
Next action: /paul:plan for Phase 14 (Workflow Fluide)
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
