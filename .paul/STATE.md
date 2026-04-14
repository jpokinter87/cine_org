# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-04-04)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v2.0 Production & Maintenance Complète

## Current Position

Milestone: v2.1 Lecteurs Externes & Intégrations
Phase: 43 of 4 (Correctifs Bibliothèque) — ✅ Complete
Plan: 43-01 ✓ livré (UNIFY clos)
Status: Phase 43 complète — à commiter puis démarrer phase 41 (Jellyfin) pour clôturer la milestone v2.1
Last activity: 2026-04-14 — UNIFY plan 43-01 : recherche accents validée, 18 tests dédiés + 1204/1204 globaux

Progress:
- v2.1: [████████░░] 75% (3/4 phases complètes — Phases 40, 42, 43 ✓)
- Phase 40: [██████████] 100% (Lecteur DuneHD)
- Phase 42: [██████████] 100% (overrides épisodes + métadonnées)
- Phase 43: [██████████] 100% (recherche insensible aux accents)
- Phase 41: [░░░░░░░░░░] 0% (Intégration Jellyfin, à planifier)

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Plan 43-01 clos — phase 43 complète]
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
- Uvicorn direct sans nginx : usage personnel réseau local, pas besoin de reverse proxy
- deploy.sh depuis le serveur : git pull + uv sync + systemctl restart
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
- Source tmdb_tv pour distinguer film/série TV TMDB dans tout le pipeline (validation + batch_builder)
- is_tv flag sur MediaDetails pour marquer les résultats TV TMDB
- Cross-genre DB-first : requête symlink_path groupée par file_path, fallback filesystem si vide
- Corbeille maintenance : routes /maintenance/trash/* avec spinner vidage + dialog confirmation
- Comédie+Drame → Comédie dramatique : règle combinatoire dans get_priority_genre(), genres protégés priment
- sandbox_dir = storage_dir/.sandbox (même volume, pas de copie réseau)
- Réinjection sandbox dans downloads/Films ou downloads/Series (détection type correcte)
- Nettoyage séquelles symlinks : matching titre+année (films), titre+SxxExx (épisodes), format scene
- _is_subdivision_path() : garde-fou critique empêchant sandbox de détruire une subdivision entière
- htmx.process() obligatoire après innerHTML sur résultats SSE (attributs hx-* non activés sinon)
- Hardlinks seeding : os.link(storage, download) dans transfer_file(), non bloquant si cross-device
- st_nlink > 1 filtre scanner downloads (stat unique combiné avec size check)
- HardlinkModel SQLite avec expires_at, purge quotidienne via timer systemd
- Nettoyage dossiers vides ascendant après purge hardlink (rmdir jusqu'à downloads_dir)
- Backend lecteur pluggable via `profile.type` (dispatcher `_launch_player`, branches mpv/dunehd isolées)
- PID synthétique ≥ 10M pour lecteurs HTTP fire-and-forget (DuneHD), distinct des vrais PIDs Linux
- ElementTree stdlib pour parser la réponse Dune (XML plat, pas de dépendance ajoutée)
- httpx `params=` au lieu de `urllib.quote()` — URL-encoding géré au transport
- `_validate_profile_form()` unifie la validation add+edit (IPv4 simple pour LAN, préfixe smb:// minimal)
- Champs hors type courant forcés à None à la persistance (évite les résidus quand on bascule mpv→dunehd)
- Tests routes config via FastAPI minimal (FastAPI() + router seul) sans lifespan Container
- AnomalyDetector refait sa propre recherche TVDB (indépendant de pending.candidates filtré)
- Seuil similarité titre 0.7 dans AnomalyDetector pour éviter faux positifs (The Big Bake vs The Big C)
- Route accept fabrique un SearchResult fallback quand la série cible est absente de pending.candidates
- Rendu anomalies en JS pur dans _progress.html (payload SSE complete étendu avec anomaly_groups)
- StaticPool + check_same_thread=False pour tests TestClient FastAPI partageant une DB SQLite in-memory

### Deferred Issues
- README.md à réécrire de fond en comble : nouvelles commandes, structure répertoires attendue, architecture, configuration
- Test lecteur distant sur machine Windows (stand-by)
- ~10-12 films récupérables via normalisation de ponctuation (`:·?` → `-...`)
- ~65 films sans fichier physique correspondant — irrésoluble par matching
- Outil pour lister facilement les épisodes/séries avec données manquantes (correction manuelle)
- 285 épisodes sans titre (limites TVDB : séries anciennes, numérotation spéciale)
- 5 séries sans tvdb_id (Dahmer="Monstre" sur TVDB, Ed Gein/Playgame/Suspect pas sur TVDB, Punisher=homonyme)
- Lecteur distant : aucun message d'erreur si le profil est mal configuré (lecture s'arrête après 1s sans feedback)
- ~58 symlinks cassés irréductibles (fichiers source supprimés du storage, après nettoyage séquelles)
- Test suppression depuis machine distante (vérifier bouton masqué + routes bloquées)
- Test lectures simultanées sur profils différents (ordi Windows indisponible)
- Vérification tooltips workflow click-to-toggle (pas de fichiers à traiter pour tester)
- 487 épisodes avec langue indétectable (fichiers anciens sans métadonnée langue)
- Quelques tvdb_id potentiellement erronés (découvert avec BSG 1978 vs 2004)
- 3 doublons DB (même file_path, 2 MovieModel) : Double mise, Compañeros, Plein la vue — purger l'entrée excédentaire
- Vérifier détection doublons avec un film (testé uniquement avec séries jusqu'ici)
- Trous dans subdivisions alphabétiques : étendre la borne la plus proche au lieu de laisser à la racine
- Vérifier si le bug subdivision a causé des dégâts dans des sessions antérieures (pré-existait depuis phase 35)
- Réassociation TMDB : les données techniques (résolution, codecs, langue) ne sont pas re-peuplées après correction — cartouches qualité absents sur jaquette et fiche détaillée. Le code ne touche pas ces champs mais ils n'étaient probablement jamais remplis pour les films importés. Enrichir depuis VideoFileModel ou mediainfo lors de la réassociation.
- "En cours de lecture" (reprise de position) : faisable pour mpv local/remote via IPC socket, partiellement faisable pour DuneHD via polling `command=status` (fragile). Candidat Phase 42 post-Jellyfin. Analyse faisabilité produite en fin de session 2026-04-14 (chat uniquement, pas de doc créé).

### Blockers/Concerns
None.

### Git State
Last commit: 63ee104 (feat(phase-42-01): socle DB overrides hors canon — SeasonOverrideModel + is_extra) — NOT pushed
À commiter : Tasks 2 + 3 du plan 42-01 (AnomalyDetector, filtres override, UI anomalies, fallback route accept) + tests + scripts + SUMMARY
Previous: c42258c (feat(ui): bulles d'aide contextuelle sur config et maintenance) — pushed
Branch: master
Feature branches merged: none

## Session Continuity

Last session: 2026-04-14 (phases 42 + 43 livrées)
Stopped at: Phase 43 complète. 42-02 commité (02e6318). 43-01 à commiter. 1204/1204 tests verts.
Next action: Commit `feat(phase-43-01): recherche bibliothèque insensible aux accents via UDF SQLite unaccent` puis `/paul:plan` pour phase 41 (Jellyfin) et clôturer la milestone v2.1
Resume file: .paul/phases/43-correctifs-bibliotheque/43-01-SUMMARY.md
Resume context:
- Milestone v2.1 : 3/4 phases complètes (40 DuneHD, 42 Overrides Manuels, 43 Correctifs Bibliothèque)
- Dernière phase restante : 41 Intégration Jellyfin (montage volumes Docker)
- 43-01 livré : UDF SQLite unaccent() + search_variants étendu + _title_search_filter avec double LIKE, 18 nouveaux tests
- Pattern établi : @event.listens_for(Engine, "connect") réutilisable pour d'autres UDF
- Toutes les deferred issues de cette session sont résolues (bug 1 via enrich-collections, bug 2 via 43-01, bug 3 n'était pas un bug)

---
*STATE.md — Updated after every significant action*
