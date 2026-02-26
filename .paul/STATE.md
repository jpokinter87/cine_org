# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-26)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** Awaiting next milestone

## Current Position

Milestone: Awaiting next milestone
Phase: None active
Plan: None
Status: Milestone v1.5 Polish & Corrections UX complete — ready for next
Last activity: 2026-02-26 — Milestone completed

Progress:
- v1.5: [██████████] 100% ✓

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
- Profils lecteur JSON plutôt que .env (basculement rapide entre machines)
- NullPool pour SQLite — supprime le QueuePool qui s'épuisait avec providers.Factory
- Cascade inverse séries : renvoyer un épisode renvoie tous les épisodes du même candidat
- Dialogues custom overlay au lieu de confirm() natif — cohérence charte graphique
- Version footer dynamique via tomllib dans deps.py

### Deferred Issues
- 1260 films sans file_path (noms trop différents pour match exact)
- 367 épisodes sans titre (262 non trouvés TVDB + 105 sans tvdb_id)
- Symlinks épisodes ne reflètent pas les nouveaux titres
- Suppression depuis la bibliothèque : sélection de films/séries pour suppression (symlinks + stockage physique), cascade série complète si série sélectionnée
- Test lecteur distant sur machine Windows (stand-by)

### Blockers/Concerns
None.

### Git State
Last commit: 08a07c1 feat(19-config-accordeon): sections pliables + version dynamique footer — phase complete
Branch: master

## Session Continuity

Last session: 2026-02-26
Stopped at: Milestone v1.5 complete
Next action: /paul:discuss-milestone or /paul:milestone
Resume file: .paul/MILESTONES.md

---
*STATE.md — Updated after every significant action*
