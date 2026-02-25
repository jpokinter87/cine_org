# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-25)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** Awaiting next milestone

## Current Position

Milestone: Awaiting next milestone
Phase: None active
Plan: None
Status: Milestone v1.3 complete — ready for next
Last activity: 2026-02-25 — Milestone v1.3 completed and archived

Progress:
- v1.3: [██████████] 100% ✓

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ○        ○        ○     [Milestone complete - ready for next]
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
- Boutons accès rapide plutôt que redirections auto (respect du rythme utilisateur)

### Deferred Issues
- 1260 films sans file_path (noms trop différents pour match exact)
- 367 épisodes sans titre (262 non trouvés TVDB + 105 sans tvdb_id)
- Symlinks épisodes ne reflètent pas les nouveaux titres
- Ré-association in extremis depuis la page transfert (cases à cocher pour renvoyer en validation)

### Blockers/Concerns
None.

### Git State
Last commit: 525dfc1
Branch: master

## Session Continuity

Last session: 2026-02-25
Stopped at: Milestone v1.3 complete and archived
Next action: /paul:discuss-milestone or /paul:milestone
Resume file: .paul/MILESTONES.md

---
*STATE.md — Updated after every significant action*
