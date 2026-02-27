# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-26)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.6 Gestion & Qualité de Données

## Current Position

Milestone: v1.6 Gestion & Qualité de Données
Phase: 21 of 4 (Résolution Données Manquantes) — In Progress
Plan: 21-01 complete, 21-02 to create (épisodes sans titres)
Status: Ready for next PLAN
Last activity: 2026-02-27 — Plan 21-01 unified (1040 films liés, 82.5%)

Progress:
- v1.6: [███░░░░░░░] 30%
- Phase 21: [█████░░░░░] 50% (plan 01/02)

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop complete — ready for next PLAN]
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
- Seuil fuzzy 0.85 validé pour link-movies (bon ratio vrais/faux positifs)
- Index mémoire par année pour matching batch (pas de requête DB par symlink)

### Deferred Issues
- Symlinks épisodes ne reflètent pas les nouveaux titres
- Test lecteur distant sur machine Windows (stand-by)
- ~10-12 films récupérables via normalisation de ponctuation (`:·?` → `-...`) — candidat plan 21-03 optionnel
- 197 films sans fichier physique correspondant — irrésoluble par matching

### Blockers/Concerns
None.

### Git State
Last commit: 5478a47 feat(20-navigation-affichage): cartouches cliquables, genres normalisés, tri récemment ajouté
Branch: master
Uncommitted: src/adapters/cli/commands/import_commands.py (link-movies amélioré)

## Session Continuity

Last session: 2026-02-27
Stopped at: Plan 21-01 unified
Next action: Commit changes, then run /paul:plan for plan 21-02 (épisodes sans titres, séries sans tvdb_id)
Resume file: .paul/phases/21-donnees-manquantes/21-01-SUMMARY.md

---
*STATE.md — Updated after every significant action*
