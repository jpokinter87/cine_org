# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-26)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.5 Polish & Corrections UX — Complete

## Current Position

Milestone: v1.5 Polish & Corrections UX
Phase: 19 of 19 — Config Accordéon — Complete
Plan: 19-01 complete
Status: Phase complete, milestone complete
Last activity: 2026-02-26 — Plan 19-01 UNIFY

Progress:
- v1.5: [██████████] 100% (3/3 phases)
- Phase 19: [██████████] 100%

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop closed]
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
- Version footer lue dynamiquement depuis pyproject.toml via tomllib dans deps.py

### Deferred Issues
- 1260 films sans file_path (noms trop différents pour match exact)
- 367 épisodes sans titre (262 non trouvés TVDB + 105 sans tvdb_id)
- Symlinks épisodes ne reflètent pas les nouveaux titres
- Test lecteur distant sur machine Windows (stand-by)

### Blockers/Concerns
None.

### Git State
Last commit: adc7b95 feat(18-reassociation-transfert): ré-association transfert + validation — phase complete
Branch: master

## Session Continuity

Last session: 2026-02-26
Stopped at: Phase 19 complete, milestone v1.5 complete
Next action: Archive milestone v1.5, plan next milestone with /paul:discuss-milestone
Resume file: .paul/phases/19-config-accordeon/19-01-SUMMARY.md

---
*STATE.md — Updated after every significant action*
