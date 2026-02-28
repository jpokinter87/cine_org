# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-28)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v1.8 Robustesse Workflow & Corrections UX

## Current Position

Milestone: v1.8 Robustesse Workflow & Corrections UX
Phase: 28 of 3 (Films Spéciaux) — Not started
Plan: Not started
Status: Ready to plan
Last activity: 2026-02-28 — Phase 27 complete, transitioned to Phase 28

Progress:
- v1.8: [██████░░░░] 67%
- Phase 28: [░░░░░░░░░░] 0%

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Phase 27 loop complete — ready for next PLAN]
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
- Popover dynamique dessous/dessus : position absolute + getBoundingClientRect() flip
- overflow:hidden retiré de .lib-season-group — cause racine popover tronqué
- Uvicorn logging via loguru : log_config dict avec _LoguruInterceptHandler
- Filtres bibliothèque 2 lignes : ligne 1 recherche/filtres, ligne 2 tri/checkboxes/techniques/suppression
- Flèches tri ↑↓ au lieu de select asc/desc : hidden input + dispatchEvent HTMX
- Section technique dépliable : collapsed class + max-height transition, auto-open si filtre actif
- Bouton suppression intégré dans barre filtres (rouge sombre discret)
- Index rapide dict O(1) pour matching symlinks (remplace rglob linéaire)
- Phase 0 DB↔storage : réconcilier file_path NULL avant réparation symlinks
- db_session optionnel dans RepairService pour compatibilité tests
- Cache TVDB bulk par saison : 1 requête FR+EN, cache individuel par épisode + marker bulk
- Compteurs workflow = réalité DB : scanned basé sur created_video_file_ids
- VOSTFR conditionnel : subtitle_language FR + audio non-FR/non-Multi → suffixe VOSTFR
- "mul" normalisé en "Multi" (pas "MUL") dans le parsing guessit

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
- Vérification tooltips workflow click-to-toggle (pas de fichiers à traiter pour tester)

### Planned for v1.8
- ~~Phase 26 : Corrections UX mineures~~ ✓ (2026-02-28)
- ~~Phase 27 : Performance & Robustesse Matching~~ ✓ (2026-02-28)
- Phase 28 : Films spéciaux (multi-parties, sagas)

### Blockers/Concerns
None.

### Git State
Last commit: (pending — phase 27 commit)
Branch: master
Tag: v1.6.0 (v1.7.0 à tagger via /paul:complete-milestone)

## Session Continuity

Last session: 2026-02-28
Stopped at: Phase 27 complete, ready to plan Phase 28
Next action: /paul:plan for Phase 28
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
