# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-03-04)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v2.0 Production & Maintenance Complète

## Current Position

Milestone: v2.0 Production & Maintenance Complète
Phase: 37 of 5 (Optimisations & Sandbox) — In Progress
Plan: 37-01 complet, 37-02 en attente
Status: Plan 37-01 UNIFY terminé, prêt pour plan 37-02
Last activity: 2026-03-20 — Plan 37-01 complété (cross-genre DB + corbeille + Comédie dramatique)

Progress:
- v2.0: [█████░░░░░] 40% (2/5 phases)
- Phase 37: [█████░░░░░] 50% (1/2 plans)

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop 37-01 complete — ready for next PLAN]
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
- skip_cache param sur TMDBClient.get_details() pour invalidation granulaire du cache
- sentinel collection_id=0 pour "vérifié, pas de collection"
- Filet doublons post-batch : détection/correction en fin de pipeline au lieu d'extraction en amont
- Phase 32 NFO abandonnée : Jellyfin scrape TMDB tout seul, les sidecar NFO/poster/fanart quadruplent les fichiers par répertoire pour un bénéfice marginal
- mediainfo primaire, guessit fallback langue : pipeline identique au workflow normal
- Normalisation ligatures Œ/Æ et slash/tiret pour comparaison de titres
- SD reconnu comme résolution valide, MPEG-4/XviD/DivX comme codecs valides
- Réutiliser le pipeline workflow existant plutôt que réinventer (règle CLAUDE.md)
- Distinction doublon DB (même file_path) vs fichiers physiques distincts — suppression conditionnelle
- overflow:hidden retiré de .dup-group (même pattern que .lib-season-group)
- Popover lecteur : vérification débordement horizontal (popover-right) ajoutée globalement
- innerHTML n'exécute pas les scripts : replaceChild pour évaluer les scripts injectés dynamiquement
- Cascade série validation : fallback par titre guessit quand candidats vides
- _is_range_dir() garde-fou pour _title_matches_range : noms composés (Extra-Lucide) exclus
- Épisode 0 (E00) : `is not None` au lieu de truthiness pour season/episode
- Barre progression workflow : 0-100% par phase, animation indéterminée pour le scan
- Résolution doublons pré-transfert : dialog dans le résumé batch, cascade série par title+year
- Scoring qualité : resolution 25%, video codec 20%, audio codec 15%, video bitrate 25%, audio bitrate 15%
- Codec efficiency normalization : AV1 ×3.0, HEVC ×2.0, VP9 ×1.8, x264 ×1.0 pour bitrate équitable
- pymediainfo fallback codecs : extraction video/audio codec quand filename ne les contient pas
- _is_content_dir() : empêche organizer de descendre dans les répertoires séries (Saison XX = contenu)
- Bouton transfert grisé tant que doublons non résolus
- keep_old = skip le nouveau (reste dans temp), ne touche pas l'existant
- _resolve_storage_path : suit les symlinks video pour trouver le vrai chemin storage (évite erreurs de casse)
- Loguru dans transfer.py au lieu de logging standard (messages visibles)
- Orphelins par symlinks : fichier orphelin = pas ciblé par un symlink (remplace comparaison DB)
- Cache analyse _analysis_cache module-level pour partage analyse → fix
- Réconciliation DB dry-run avant apply pour actions sur fichiers réels
- Sandbox des orphelins différé à une phase dédiée (périmètre trop large)
- Source tmdb_tv pour distinguer film/série TV TMDB dans tout le pipeline (validation + batch_builder)
- is_tv flag sur MediaDetails pour marquer les résultats TV TMDB
- Cross-genre DB-first : requête symlink_path groupée par file_path, fallback filesystem si vide
- Corbeille maintenance : routes /maintenance/trash/* avec spinner vidage + dialog confirmation
- Comédie+Drame → Comédie dramatique : règle combinatoire dans get_priority_genre(), genres protégés priment

### Deferred Issues
- README.md à réécrire de fond en comble : nouvelles commandes, structure répertoires attendue, architecture, configuration
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
- Skill gap /frontend-design : invoquer systématiquement pour les phases UI
- 487 épisodes avec langue indétectable (fichiers anciens sans métadonnée langue)
- Quelques tvdb_id potentiellement erronés (découvert avec BSG 1978 vs 2004)
- 3 doublons DB (même file_path, 2 MovieModel) : Double mise, Compañeros, Plein la vue — purger l'entrée excédentaire
- Doublons physiques + symlinks orphelins cross-genre : des films existent en double dans storage (même taille, noms différents) avec des symlinks dans plusieurs genres
- Sandbox management complet : sandboxer orphelins vers .sandbox/orphans/, interface gestion (liste/suppression/réinjection workflow)
- Vérifier détection doublons avec un film (testé uniquement avec séries jusqu'ici)
- Trous dans subdivisions alphabétiques : étendre la borne la plus proche au lieu de laisser à la racine

### Blockers/Concerns
None.

### Git State
Last commit: dd5997a (fix(config): rechargement à chaud après modification de la configuration)
Branch: master

## Session Continuity

Last session: 2026-03-20
Stopped at: Plan 37-01 complet (UNIFY)
Next action: /paul:apply .paul/phases/37-optimisations-sandbox/37-02-PLAN.md
Resume file: .paul/phases/37-optimisations-sandbox/37-01-SUMMARY.md
Resume context:
- Plan 37-01 : Complet (cross-genre DB + corbeille maintenance + Comédie dramatique)
- Plan 37-02 : Sandbox orphelins complet avec UI (checkpoint visual, wave 2, prêt)

---
*STATE.md — Updated after every significant action*
