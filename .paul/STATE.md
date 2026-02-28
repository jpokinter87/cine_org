# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-28)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.7 Fiabilité & Ergonomie Bibliothèque

## Current Position

Milestone: v1.7 Fiabilité & Ergonomie Bibliothèque
Phase: 25 of 2 (Réconciliation Symlinks/Storage)
Plan: Not started
Status: Ready to plan
Last activity: 2026-02-28 — Phase 24 complete, transitioned to Phase 25

Progress:
- v1.7: [█████░░░░░] 50%
- Phase 24: [██████████] 100% ✓
- Phase 25: [░░░░░░░░░░] 0%

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ○        ○        ○     [Ready for Phase 25 PLAN]
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
- Filtres bibliothèque 2 lignes : ligne 1 recherche/filtres, ligne 2 tri/checkboxes/techniques/suppression
- Flèches tri ↑↓ au lieu de select asc/desc : hidden input + dispatchEvent HTMX
- Section technique dépliable : collapsed class + max-height transition, auto-open si filtre actif
- Bouton suppression intégré dans barre filtres (rouge sombre discret)

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
- Logging serveur (uv run cineorg serve) : horodatage manquant dans les logs

### Planned for v1.8 (Robustesse Workflow)
- Performance matching séries : cache résultat TVDB par série (The Bear, The Boys bloquent le traitement)
- Fix discordance compteurs workflow (barre 291/344 vs résultats 332+12+1=345)
- Gestion VOSTFR : films étrangers affichés avec langue du film au lieu de VOSTFR
- Films multi-parties : détection et préservation part1/part2 dans le renommage
- Sagas de films : regroupement symlinks Die Hard, James Bond, etc. dans répertoire saga

### Blockers/Concerns
None.

### Git State
Last commit: 82be854 chore: milestone v1.6 complete — archive and version bump
Branch: master
Tag: v1.6.0
Uncommitted: milestone v1.7 creation

## Session Continuity

Last session: 2026-02-28
Stopped at: Phase 24 complete, ready to plan Phase 25
Next action: /paul:plan for Phase 25
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
