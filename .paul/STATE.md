# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-28)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.7 complete — prêt pour v1.8 Robustesse Workflow

## Current Position

Milestone: v1.7 Fiabilité & Ergonomie Bibliothèque — Complete
Phase: 25 of 2 (Réconciliation Symlinks/Storage) — Complete
Plan: 25-01 complete
Status: Milestone v1.7 complete, ready for v1.8
Last activity: 2026-02-28 — Phase 25 complete, milestone v1.7 closed

Progress:
- v1.7: [██████████] 100% ✓
- Phase 24: [██████████] 100% ✓
- Phase 25: [██████████] 100% ✓

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop complete — milestone v1.7 done]
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
- Index rapide dict O(1) pour matching symlinks (remplace rglob linéaire)
- Phase 0 DB↔storage : réconcilier file_path NULL avant réparation symlinks
- db_session optionnel dans RepairService pour compatibilité tests

### Deferred Issues
- Test lecteur distant sur machine Windows (stand-by)
- ~10-12 films récupérables via normalisation de ponctuation (`:·?` → `-...`)
- ~65 films sans fichier physique correspondant — irrésoluble par matching
- Outil pour lister facilement les épisodes/séries avec données manquantes (correction manuelle)
- 285 épisodes sans titre (limites TVDB : séries anciennes, numérotation spéciale)
- 5 séries sans tvdb_id (Dahmer="Monstre" sur TVDB, Ed Gein/Playgame/Suspect pas sur TVDB, Punisher=homonyme)
- Lecteur distant : aucun message d'erreur si le profil est mal configuré (lecture s'arrête après 1s sans feedback)
- ~100 symlinks cassés irréductibles (fichiers source supprimés du storage)
- Test suppression depuis machine distante (vérifier bouton masqué + routes bloquées)
- Test lectures simultanées sur profils différents (ordi Windows indisponible)
- Logging serveur (uv run cineorg serve) : horodatage manquant dans les logs
- Supprimer l'option "migré" de la liste des lecteurs (laisser juste Local + profils enregistrés)
- Ajouter option de réinitialisation workflow depuis l'interface web
- Popover sélection lecteur : parfois trop haut, cache les 2 premières lignes

### Planned for v1.8 (Robustesse Workflow)
- Performance matching séries : cache résultat TVDB par série (The Bear, The Boys bloquent le traitement)
- Fix discordance compteurs workflow (barre 291/344 vs résultats 332+12+1=345)
- Gestion VOSTFR : films étrangers affichés avec langue du film au lieu de VOSTFR
- Films multi-parties : détection et préservation part1/part2 dans le renommage
- Sagas de films : regroupement symlinks Die Hard, James Bond, etc. dans répertoire saga

### Blockers/Concerns
None.

### Git State
Last commit: ec07756 feat(24-refonte-filtres-bibliotheque): refonte UX filtres bibliothèque
Branch: master
Tag: v1.6.0

## Session Continuity

Last session: 2026-02-28
Stopped at: Milestone v1.7 complete
Next action: /paul:complete-milestone or /paul:discuss-milestone for v1.8
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
