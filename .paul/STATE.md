# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-26)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.5 Polish & Corrections UX — Phase 18

## Current Position

Milestone: v1.5 Polish & Corrections UX
Phase: 18 of 19 — Ré-association Transfert — In Progress
Plan: 18-01 complete ✓, 18-02 ready for APPLY
Status: Plan 01 closed, proceeding to Plan 02
Last activity: 2026-02-26 — Plan 18-01 UNIFY complete

Progress:
- v1.5: [███░░░░░░░] 33% (1/3 phases)
- Phase 18: [█████░░░░░] 50% (plan 01/02)

## Loop Position

Current loop state:
```
Plan 18-01:
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Complete]

Plan 18-02:
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ○        ○     [Ready for APPLY]
```

## Accumulated Context

### Decisions
- Web = complément du CLI, jamais un remplacement
- Stack : FastAPI + Jinja2 + HTMX (pas de SPA)
- CSS custom thème sombre (Instrument Serif + DM Sans)
- Profils lecteur JSON plutôt que .env (basculement rapide entre machines)
- Route series/play cherche le premier épisode (S01E01) avec fichier
- NullPool pour SQLite — supprime le QueuePool qui s'épuisait avec providers.Factory
- Cascade inverse séries : renvoyer un épisode renvoie tous les épisodes du même candidat
- Dialogues custom overlay au lieu de confirm() natif — cohérence charte graphique

### Deferred Issues
- 1260 films sans file_path (noms trop différents pour match exact)
- 367 épisodes sans titre (262 non trouvés TVDB + 105 sans tvdb_id)
- Symlinks épisodes ne reflètent pas les nouveaux titres
- Test lecteur distant sur machine Windows (stand-by)
- Atiye / The Gift : deux tvdb_id distincts (372912/433737) — cas test Phase 18

### Blockers/Concerns
None.

### Git State
Last commit: (pending — plan 18-01 changes to commit)
Branch: master

## Session Continuity

Last session: 2026-02-26
Stopped at: Plan 18-01 UNIFY complete
Next action: Run /paul:apply for Plan 18-02
Resume file: .paul/phases/18-reassociation-transfert/18-02-PLAN.md

---
*STATE.md — Updated after every significant action*
