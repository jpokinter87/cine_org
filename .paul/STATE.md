# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-04-04)

**Core value:** Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements
**Current focus:** v2.0 Production & Maintenance Complète

## Current Position

Milestone: v2.1 Lecteurs Externes & Intégrations
Phase: 43 of 4 (Correctifs Bibliothèque) — ✅ Complete
Plan: 43-01 ✓ livré & commité (952f95c), 43-02 ✓ livré (à commiter)
Status: Phase 43 complète — mode symlinks mergé (PR #1 squash 8e7ec1c) + mode raw livré + apply prod terminé sur /media/wd10-1 (12/12 MIGRATE OK). Deux fils en attente : (A) correctif réassociation livré & commité 856c0e7 ; (B) migration NAS — buckets wd10-1 à traiter puis PR, puis phase 41 Jellyfin. Reste à traiter sur wd10-1 : 117 NEEDS_VALIDATION, 17 unrated, 11 already_in_library, 6 low_rated.
Last activity: 2026-05-15 — Analyse trou de notes (28/6739 items réellement sans note) + 4 commandes d'enrichissement (14 imdb_ids, 53 notes IMDb films, 117 séries enrichies). Correctif réassociation TMDB commité (856c0e7) : bouton « Rafraîchir les données » sur la carte association actuelle + backfill imdb_rating/imdb_votes dans les handlers apply (helper _lookup_imdb_rating). 5 tests TDD (la réassociation n'en avait aucun). 1393 tests verts. Migration NAS intouchée — next-actions du 2026-05-10 toujours valides.

Progress:
- v2.1: [████████░░] 75% (3/4 phases complètes — Phases 40, 42, 43 ✓)
- Phase 40: [██████████] 100% (Lecteur DuneHD)
- Phase 42: [██████████] 100% (overrides épisodes + métadonnées)
- Phase 43: [██████████] 100% (recherche accents + UX champs texte)
- Phase 41: [░░░░░░░░░░] 0% (Intégration Jellyfin, à planifier)

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Plan 43-02 clos — phase 43 complète]
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
- Notes séries TV : pont TVDB → TMDB (vote_average + vote_count) → cache IMDb (imdb_rating + imdb_votes). TVDB n'expose pas de note exploitable.
- pick_best_tv_match strict avec année : refus explicite si year fournie sans candidat année-aligné, empêche les associations catastrophiques (Shameless UK vs US, Flashback 2011 vs 2025)
- Garde-fou anti-homonymes via comptes d'épisodes par saison : SeriesEnricherService écarte les candidats TMDB dont les saisons n'ont pas assez d'épisodes pour couvrir la DB (TMDBClient.get_tv_seasons_episode_counts)
- enrich-series lit aussi le cache IMDb local : évite un imdb sync séparé pour les séries
- imdb sync --target movies|series|all : commande unifiée, helper _sync_imdb_for_model factorisé
- Migration NAS — item_id = xxh3_64(symlink_path) : empreinte stable pour reprise par state store
- Migration NAS — state_store sqlite3 stdlib (pas SQLModel) : journal opérationnel local au package, supprimable post-migration
- Migration NAS — threshold inclusif (value >= threshold → MIGRATE)
- Migration NAS — RsyncRunner Protocol injectable, default subprocess (rsync -a --partial --inplace --bwlimit=NM)
- Migration NAS — swap symlink atomique via os.symlink(tmp) + os.replace(tmp, symlink) (atomique sur même fs)
- Migration NAS — reprise auto : si destination existe avec hash xxh3_64 match, finalize sans rsync (couvre crashes mid-flight)
- Migration NAS — helpers build_plan/run_apply/run_status séparés des commandes Typer pour testabilité (FakeRsync + session in-memory)
- Migration NAS — sentinel _UNSET dans tests pour distinguer "non fourni" vs explicitement None
- Migration NAS — pas de --remove-source-files dans rsync : source intacte, swap symlink seul réordonnance ; suppression effective hors périmètre executor
- Migration NAS — garde-fou anti-écrasement raw_finalizer : si Movie.file_path en DB pointe vers un fichier existant, lever FileExistsError → FAILED_OTHER (filet runtime contre multi-parts ou doublons non détectés en amont)
- Migration NAS — détection collision tmdb intra-plan : N items raw-film MIGRATE avec même tmdb_id → bascule en NEEDS_VALIDATION + tag `collision_tmdb:{id}`. Évite l'écrasement multi-parts dès le plan time
- Migration NAS — rsync sans `-a` (juste `--partial --inplace --info=progress2 --timeout=300`) : la préservation owner/group/perms sur NFS échoue (rc=23 même contenu OK), pas pertinent pour notre cas (NAS gère ses propres perms)
- Migration NAS — stratégie retry simplifiée : 3 essais identiques avec pause 30s entre (au lieu de cascade dégressive 0→50→25→10→5 MB/s). Les échecs observés sont transitoires (timeout NFS, fsync long), pas des saturations de débit
- Migration NAS — wrapper progress UI : utilise `dest.stat().st_size` (taille réelle persistée via --inplace) au lieu du compteur volatile de `--info=progress2` qui repart à 0 à chaque retry
- Migration NAS — UX apply en français : 5 phases canoniques (préparation → copie → vérification → finalisation → commit), phase courante en rouge gras dans une ligne dédiée Rich
- Réassociation TMDB — bouton « Rafraîchir les données » sur la carte « Association actuelle » : relance l'apply sur le même tmdb_id. Avant, aucun moyen de relancer une association correcte mais incomplète sans choisir volontairement une fausse association
- Réassociation TMDB — handlers apply (films + séries) backfillent imdb_rating/imdb_votes via helper _lookup_imdb_rating (cache IMDb local), même pont TMDB→IMDb que batch_builder/series_enricher. Note héritée purgée si le nouvel imdb_id est hors cache

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
- 14 séries homonymes sans tmdb_id (enrich-series → NOT_FOUND, matcher strict refuse de deviner) : Fiasco (2024), L'Espion aux deux visages (2016), Les Détectoristes (2014, ×2 — aussi un doublon DB), Monster (2017), Platonic (2023), Poldark (2015), Prey (2014), Racines (2016), Reykjavik 112 (2025), Sirens (2025), Stonehouse (2023), Surface (2025), The Sticky (2024), Yellowstone (2018) → réassociation manuelle via le bouton « Corriger » de chaque fiche
- 13 items réellement sans note (9 films + 4 séries) : making-ofs, Macbeth 2016 (opéra), STEINS;GATE #23 (special), documentaires, sorties 2025 — TMDB à 0 vote + absents du cache IMDb local. Irréductible sauf `imdb import` (rafraîchit le dataset) ou attente que TMDB/IMDb les notent
- Garde-fou anti-homonymes pas encore appliqué côté matching initial du workflow (matching_step.py). Cas plus rare car validation manuelle filtre déjà, mais à envisager si récurrent.
- Service systemd : sudo demande mot de passe lors de deploy.sh — configurer NOPASSWD pour `systemctl restart cineorg` afin que le déploiement aille au bout sans intervention
- Vérifier sur disque s'il reste un dossier `Flashback` sans année dans video/ et storage/ après les consolidations (devrait avoir été nettoyé par le script)
- Migration NAS — commande `cleanup-buckets` à créer pour traiter les buckets non-MIGRATE post-apply : (a) `already_in_library` → `rm` source après confirmation, (b) `needs_validation` → `mv` vers downloads + suggestion `process`, (c) `low_rated`/`unrated` → triage interactif. Évite de tout faire à la main fichier par fichier.
- Migration NAS — mount NFS `/media/NAS64` est en mode `sync` : chaque write attend confirmation NAS, ralentit les transferts. Envisager remount `async` côté hôte pour les futures migrations massives.
- Migration NAS — perte définitive : La Flor partie 3 source + version mono-fichier originale (id 5818) écrasées par partie 1 avant garde-fou. 3/4 du film récupérables via parties 1, 2, 4 (parties 2+4 transférées manuellement par user vers /media/NAS64/temp). Ne pas chercher à les remettre en bibliothèque (incomplet sans partie 3).
- 117 NEEDS_VALIDATION + 17 unrated + 11 already_in_library + 6 low_rated restants sur /media/wd10-1 après apply. À traiter via futur cleanup-buckets ou manuellement.

### Blockers/Concerns
None.

### Git State
Branche courante : feat/migrate-nas-raw-mode (~29 commits en avance sur master, dont **4 non poussés** sur origin)
Last commit: 856c0e7 fix(reassociate): bouton Rafraîchir + backfill note IMDb sur apply
Stack récente (du plus récent au plus ancien) :
  - 856c0e7 fix(reassociate): bouton Rafraîchir + backfill note IMDb sur apply [non pushé — cette session]
  - f1095a4 docs(paul): handoff fin de session + maj STATE [non pushé]
  - e4dc1e1 refactor(migration): rsync simplifié + UX apply en français [non pushé]
  - 8610943 fix(migration): garde-fous anti-écrasement (raw_finalizer + collision tmdb) [non pushé]
  - c8c14af feat(migration): flag --fast
  - e6bdbdd feat(migration): sous-barre Rich par fichier
  - c256bbc fix(migration): parser progress2 locale fr
  - f67f1c8 fix(migration): défaut hardcodé bwlimit shadow
  - 57dc98b fix(migration): rsync stderr→stdout
  - fe32f48 fix(migration): --outbuf=L (retiré ensuite côté logique)
  - c5656b4 fix(migration): retire bwlimit défaut
  - 6079991 fix(migration): events hashing
  - aac51ad fix(migration): rsync streaming + escape balises
  - 1d3f2c6 feat(migration): barre Rich apply
  - e18cfcf Revert "fix routage path"
  - 01922d7 feat(migration): légende buckets
  - 97a4f54 fix(migration): routage path (revert)
  - 2457e73 fix(series-repo): get_by_tmdb_id
  - 6838e56 feat(migration): fallback titre tronqué
  - 903bfbe feat(migration): bucket ALREADY_IN_LIBRARY
  - ecb1011 feat(migration): tie-break année
  - 872d84c feat(migration): filtrage catégories scanner
  - 0807658 feat(migration): barre Rich plan
  - 1ecb307 feat(migration): mode raw — CLI + wiring + README (étape 5/5)
  - 6c48c4f wip(migration): finalize complet (étape 4b3)
  - 5659f66 wip(migration): finalize séries (étape 4b2)
  - 6231d99 wip(migration): finalize films (étape 4b1)
  - 62ebd6a wip(migration): transfer_executor + Protocol (étape 4a)
  - 3718b36 wip(migration): plan_builder mode raw (étape 3)
  - ca53203 wip(migration): MigrationMatcher (étape 2)
  - 17d23ae wip(migration): dataclasses (étape 1)
Stack master :
  - 8e7ec1c refonte(migration): package migration NAS + commande migrate-nas (PR #1 squash, 2026-05-10)
  - 93e2839 garde-fou anti-homonymes
  - 8ced32b scripts consolidation Flashback + Shameless
  - b540279 fix pick_best_tv_match strict
  - 40e32e9 feat notes séries TV
PR mergée : #1 (mode symlinks pur) via squash le 2026-05-10
Feature branches active : feat/migrate-nas-raw-mode (à merger une fois apply prod validé)
Service systemd : tourne encore sur les commits d'avant le déploiement 2026-05-08 (restart cineorg en attente, sudo password requis)

## Session Continuity

Last session: 2026-05-15 (analyse trou de notes + enrichissement + correctif réassociation)
Stopped at: Correctif réassociation TMDB livré, testé et commité (856c0e7) sur feat/migrate-nas-raw-mode. Migration NAS intouchée — toujours en pause depuis le 2026-05-10. Deux fils indépendants en attente.
Next action:
  **Fil A — réassociation (quasi clos)** : optionnellement push + test manuel du bouton « Rafraîchir » sur la fiche Detectorists.
  **Fil B — migration NAS (prioritaire, en attente depuis le 2026-05-10)** :
  1. `git push origin feat/migrate-nas-raw-mode` (pousse les 4 commits non poussés)
  2. Traiter les buckets sur /media/wd10-1 :
     - already_in_library.csv (11 items, ~28 GB) → supprimer sources
     - needs_validation.csv (117 items) → mv vers downloads + cineorg process
     - low_rated.csv (6) + unrated.csv (17) → triage manuel
  3. Optionnel : créer `cineorg migrate-nas cleanup-buckets`
  4. /media/wd10-1 vidé → ouvrir PR feat/migrate-nas-raw-mode vers master
  5. PR mergée → `/paul:plan` pour phase 41 Jellyfin (clôt v2.1)
Resume file: .paul/HANDOFF-2026-05-15.md
Resume context:
- Trou de notes analysé : 28/6739 items réellement sans note (~0,4 %), cluster en page 1 (imports récents). Entrée déjà couverte par batch_builder.
- Enrichissement lancé sur cineorg.db : enrich-imdb-ids (14 imdb_ids), imdb sync --target all (53 notes IMDb films), enrich-series (117 séries). Bucket « zéro note » 28 → 27.
- Correctif réassociation 856c0e7 : la réassociation séries existait déjà ; 2 bugs corrigés — bouton « Rafraîchir les données » sur la carte association actuelle + backfill imdb_rating/imdb_votes dans les handlers apply (helper _lookup_imdb_rating). 5 tests TDD, 1393 verts.
- Reste 27 items sans note : 14 séries homonymes (réassociation manuelle) + 13 réellement non notés (irréductible).
- Migration NAS : aucune action cette session. État inchangé depuis HANDOFF-2026-05-10-soir.md (12/12 MIGRATE OK, 4 Flor en failed_other, buckets wd10-1 à traiter).
Git strategy: feat/migrate-nas-raw-mode — 4 commits non poussés (dont 856c0e7 réassociation, sur la même branche par choix utilisateur). Push puis PR vers master une fois /media/wd10-1 traité.

---
*STATE.md — Updated after every significant action*
