# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-28)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** Awaiting next milestone

## Current Position

Milestone: Awaiting next milestone
Phase: None active
Plan: None
Status: Milestone v1.6 Gestion & Qualité de Données complete — ready for next
Last activity: 2026-02-28 — Milestone v1.6 completed and archived

Progress:
- v1.6: [██████████] 100% ✓

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
- Suppression : corbeille provisoire réversible, suppression physique uniquement au vidage définitif
- Suppression restreinte à la machine maître (localhost only — bouton masqué + 403)
- sessionStorage pour persistance état sélection entre pages
- Seuil fuzzy 0.85 validé pour link-movies et enrich-tvdb-ids
- Index mémoire par année pour matching batch (pas de requête DB par symlink)
- Recherche TVDB multi-titre : FR→original→racine (tiret) + nettoyage année
- Partial Jinja2 _play_btn.html : template réutilisable pour bouton play + popover profil
- Jinja2 global get_player_profiles : accès profils dans tous les templates sans modifier les routes
- Popover épisodes vers le bas : overflow:hidden du conteneur saison empêche le popover vers le haut

### Deferred Issues
- Symlinks épisodes ne reflètent pas les nouveaux titres
- Test lecteur distant sur machine Windows (stand-by)
- ~10-12 films récupérables via normalisation de ponctuation (`:·?` → `-...`)
- 197 films sans fichier physique correspondant — irrésoluble par matching
- Outil pour lister facilement les épisodes/séries avec données manquantes (correction manuelle)
- 285 épisodes sans titre (limites TVDB : séries anciennes, numérotation spéciale)
- 5 séries sans tvdb_id (Dahmer="Monstre" sur TVDB, Ed Gein/Playgame/Suspect pas sur TVDB, Punisher=homonyme)
- Lecteur distant : aucun message d'erreur si le profil est mal configuré (lecture s'arrête après 1s sans feedback)
- Recherche symlinks : algorithme ne retrouve pas les symlinks existants quand l'arborescence video/ a divergé de storage/ (ex: Wadjda, subdivision/année différentes)
- Test suppression depuis machine distante (vérifier bouton masqué + routes bloquées)
- Test lectures simultanées sur profils différents (ordi Windows indisponible)

### Blockers/Concerns
None.

### Git State
Last commit: e2018b2 feat(23-lectures-simultanees): popover sélecteur profil + lectures parallèles
Branch: master
Uncommitted: milestone completion files (pending commit)

## Session Continuity

Last session: 2026-02-28
Stopped at: Milestone v1.6 complete
Next action: /paul:discuss-milestone or /paul:milestone
Resume file: .paul/MILESTONES.md

---
*STATE.md — Updated after every significant action*
