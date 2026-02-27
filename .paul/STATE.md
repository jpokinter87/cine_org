# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-26)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.6 Gestion & Qualité de Données

## Current Position

Milestone: v1.6 Gestion & Qualité de Données
Phase: 21 of 4 (Résolution Données Manquantes)
Plan: Not started
Status: Phase 20 complete, ready to plan Phase 21
Last activity: 2026-02-27 — Phase 20 complete

Progress:
- v1.6: [██░░░░░░░░] 25%
- Phase 20: [██████████] 100% ✓

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop complete — Phase 20 done, ready for Phase 21]
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
- Suppression : corbeille provisoire réversible, suppression physique uniquement au vidage définitif

### Deferred Issues
- Symlinks épisodes ne reflètent pas les nouveaux titres
- Test lecteur distant sur machine Windows (stand-by)

### Blockers/Concerns
None.

### Git State
Last commit: c963ed9 chore: retirer player_profiles.json du dépôt (données personnelles)
Branch: master

## Session Continuity

Last session: 2026-02-27
Stopped at: Phase 20 complete, transition done
Next action: /paul:plan for Phase 21
Resume file: .paul/phases/20-navigation-affichage/20-01-SUMMARY.md

---
*STATE.md — Updated after every significant action*
