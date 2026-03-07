# CineOrg

## What This Is

Application Python de gestion de vidéothèque personnelle. Scanne les téléchargements, identifie et formate les films et séries via guessit et les bases TMDB/TVDB, organise les fichiers en une zone de stockage physique et une zone de lecture (symlinks) pour médiacenter. L'organisation en sous-répertoires est alphabétique avec subdivision par plages pour maintenir moins de 50 fichiers par répertoire. Le CLI est fonctionnel ; la prochaine étape est l'interface graphique web.

## Core Value

Organiser et renommer automatiquement une vidéothèque personnelle à partir des téléchargements, sans effort manuel.

## Current State

| Attribute | Value |
|-----------|-------|
| Version | 1.9.0 (Normalisation & Intégration Jellyfin) |
| Status | Stable — v1.9 complete |
| Last Updated | 2026-03-07 |

## Requirements

### Validated (Shipped)

- [x] Scan des téléchargements et parsing via guessit/mediainfo
- [x] Matching TMDB (films) et TVDB (séries) avec scoring
- [x] Renommage standardisé des fichiers
- [x] Organisation en storage/ (physique) et video/ (symlinks)
- [x] Subdivision alphabétique automatique (max 50 fichiers/répertoire)
- [x] Validation automatique et manuelle des candidats
- [x] Réparation de symlinks cassés
- [x] Cleanup et consolidation de la vidéothèque
- [x] Import/enrichissement de vidéothèques existantes
- [x] CLI complet via Typer
- [x] Interface web graphique (FastAPI + Jinja2 + HTMX)
  - Foundation web : FastAPI app, layout Jinja2, HTMX, page d'accueil stats — Phase 1
  - Validation visuelle : liste pending, détail candidats enrichis, actions HTMX — Phase 2
  - Orchestration workflow : scan → matching → auto-validation avec SSE temps réel — Phase 3
  - Transfert et résolution de conflits via le web — Phase 4
  - Navigation bibliothèque films/séries avec filtres et détail — Phase 5
  - Page configuration (répertoires, clés API, seuils) — Phase 5
  - Maintenance : diagnostics intégrité et cleanup avec SSE temps réel — Phase 5
- [x] Enrichissement données (v1.1)
  - Ratings films enrichis à 100% (progress bar Rich) — Phase 6
  - Séries enrichies : tmdb_id 99.7%, imdb_id 98.3% — Phase 7
  - Fiches web enrichies : liens IMDb/TMDB, crédits cliquables, filtre par personne — Phase 8
- [x] Gestion des associations TMDB (v1.2)
  - Correction manuelle d'associations depuis la fiche web (overlay recherche TMDB) — Phase 9
  - Métadonnées techniques, filtres avancés, navigation inter-fiches, pipeline enrichi — Phase 9b
  - Détection automatique d'associations suspectes (heuristiques + SSE + cache 24h) — Phase 10
  - Tableau de bord qualité (couverture enrichissement, résumé suspects, historique corrections) — Phase 11
- [x] Dette technique données (v1.3)
  - Tri et recherche bibliothèque normalisés (accents, ligatures, articles) — Phase 12
  - Enrichissement batch données (file_path, métadonnées techniques, titres épisodes) — Phase 12
- [x] Refactoring code (v1.3)
  - Code matching partagé CLI/web via pending_factory.py — Phase 13
  - Package library/ découpé en 6 modules (1250→6 fichiers) — Phase 13
- [x] Workflow fluide (v1.3)
  - Boutons d'accès rapide guidant workflow → validation → transfert — Phase 14
  - Cohérence visuelle boutons page d'accueil — Phase 14
- [x] Que regarder ce soir (v1.4)
  - Tag "déjà vu" et note étoiles sur fiches films et séries — Phase 15
  - Page "Surprends-moi" avec suggestion aléatoire et filtres (genre, durée, note, type) — Phase 15
  - Bouton accueil avec animation glow ambrée — Phase 15
- [x] Lecteur distant (v1.4)
  - Lecteur vidéo configurable : programme (mpv/vlc), cible (local/remote), SSH — Phase 16
  - Profils lecteur nommés avec CRUD et sélection rapide — Phase 16
  - Mapping de chemins cross-platform (Linux→Linux, Linux→Windows) — Phase 16
  - Migration transparente des anciens paramètres .env vers profils JSON — Phase 16
- [x] Visionner Surprends-moi (v1.5)
  - Bouton Visionner sur page Surprends-moi (films et séries) — Phase 17
  - Route series/play → premier épisode (S01E01) avec fichier — Phase 17

- [x] Ré-association transfert (v1.5)
  - Bouton "Renvoyer en validation" par fichier sur page transfert + cascade inverse séries — Phase 18
  - Section "Auto-validés" sur page validation avec bouton "Revalider" + cascade série — Phase 18
  - Fix NullPool pour SQLite (QueuePool exhaustion) — Phase 18
  - Dialogues custom overlay pour toutes les confirmations destructives — Phase 18

- [x] Config accordéon (v1.5)
  - Sections config pliables/dépliables avec animation — Phase 19
  - Version footer dynamique lue depuis pyproject.toml — Phase 19
- [x] Gestion & Qualité de Données (v1.6)
  - Cartouches accueil cliquables, genres normalisés FR, tri récemment ajouté — Phase 20
  - Résolution données manquantes (1040 films liés, 13 séries tvdb_id, 98 épisodes titrés) — Phase 21
  - Suppression depuis la bibliothèque avec corbeille réversible et sécurité localhost — Phase 22
  - Lectures simultanées : popover sélecteur de profil, lectures parallèles multi-profils — Phase 23

### Active (In Progress)

(none — v1.9 phases complete)

### Validated (Recently Shipped)

- [x] Overlays qualité sur posters web (v1.9)
  - Badges résolution (4K/1080p/720p/SD), codec vidéo, langue (Multi/FR/VO) sur posters grille — Phase 33
- [x] Détection doublons au transfert (v1.9)
  - DuplicateDetector avec scoring qualité multi-critères (résolution, codecs, bitrate normalisé) — Phase 34
  - Résolution pré-transfert dans le résumé batch web (dialog comparatif, cascade série) — Phase 34
  - Sandbox des anciennes versions via résolution symlinks (video→storage) — Phase 34
- [x] Détection de doublons (v1.9)
  - CLI check-duplicates : détection par tmdb_id, scoring qualité, whitelist JSON — Phase 31 plan 01
  - Vue web /duplicates : comparaison qualité, visionner, réassocier, suppression corbeille, distinction doublon DB — Phase 31 plan 02
- [x] Normalisation répertoires séries (v1.9)
  - Migration Séries→Series, fix-series-symlinks, normalisation complète — Phase 30
- [x] Films multi-parties (v1.9)
  - Filet de sécurité doublons : détection post-batch + correction automatique "Partie N" — Phase 29
- [x] Robustesse Workflow & Corrections UX (v1.8)
  - [x] Corrections UX mineures (popover dynamique, profil Migré, reset workflow, logs serveur) — Phase 26
  - [x] Performance & Robustesse Matching (cache TVDB bulk, compteurs workflow, VOSTFR) — Phase 27
  - [x] Collections TMDB (583 sagas, page web, badges, commande CLI enrich-collections) — Phase 28
- [x] Fiabilité & Ergonomie Bibliothèque (v1.7)
  - [x] Refonte UX filtres bibliothèque (2 lignes compactes, flèches tri, section technique dépliable) — Phase 24
  - [x] Réconciliation symlinks/storage (commande reconcile 3 phases, index rapide, titres TVDB) — Phase 25

### Out of Scope

- Streaming vidéo — CineOrg organise les fichiers, ne les lit pas
- Multi-utilisateur — usage personnel uniquement

## Target Users

**Primary:** Utilisateur unique gérant sa vidéothèque personnelle
- Télécharge régulièrement des films et séries
- Utilise un médiacenter (Plex, Jellyfin, Kodi)
- Veut une organisation propre et automatique

## Context

**Technical Context:**
- CLI existant complet et fonctionnel (Typer)
- Architecture hexagonale avec DI (dependency-injector)
- Stack : Python 3.11+, FastAPI, Jinja2+HTMX, SQLModel/SQLite, guessit, pymediainfo, httpx
- APIs externes : TMDB (films), TVDB (séries)

## Constraints

### Technical Constraints
- Python 3.11+
- SQLite (pas de serveur DB)
- APIs TMDB/TVDB avec rate limiting
- Symlinks uniquement dans video/ (jamais déplacer les fichiers storage/)
- Le CLI doit rester pleinement fonctionnel — l'interface web est un complément, pas un remplacement
- L'utilisateur doit pouvoir choisir entre CLI et web pour toutes les opérations

### Business Constraints
- Usage personnel uniquement
- Pas de stockage cloud

## Key Decisions

| Decision | Rationale | Date | Status |
|----------|-----------|------|--------|
| Architecture hexagonale | Séparation claire domaine/infra | - | Active |
| Symlinks pour video/ | Ne jamais déplacer les fichiers physiques lors de réorganisations | - | Active |
| HTMX pour le web | Interactivité sans SPA complexe, cohérent avec Jinja2 | 2026-02-23 | Active |
| Web = complément du CLI | L'utilisateur choisit son interface ; le CLI ne doit jamais régresser | 2026-02-23 | Active |
| Lifespan DI pattern | Container initialisé via asynccontextmanager dans FastAPI | 2026-02-23 | Active |
| deps.py pour partage | Templates Jinja2 dans module séparé pour éviter imports circulaires | 2026-02-23 | Active |
| CSS custom thème sombre | Instrument Serif + DM Sans, pas de framework CSS lourd | 2026-02-23 | Active |
| Fragments HTMX + HX-Redirect | Actions POST retournent des fragments HTML, redirect via header | 2026-02-23 | Active |
| Dialogue custom pour actions destructives | Overlay CSS avec explication plutôt que confirm() natif | 2026-02-23 | Active |
| Distinction doublon DB vs fichiers distincts | Suppression conditionnelle selon que les copies partagent le même file_path | 2026-03-01 | Active |
| Durée fichier via mediainfo + résolution symlink | La durée DB peut correspondre à une mauvaise association TMDB | 2026-02-24 | Active |
| Indicateurs confiance associations | Durée (films) et saisons/épisodes (séries) pour guider la correction | 2026-02-24 | Active |
| SSE pour progression workflow | EventSource + StreamingResponse, état partagé via WorkflowProgress | 2026-02-23 | Active |
| Cascade auto-validation séries | Valider 1 épisode auto-valide les autres de la même série (même candidat TVDB) | 2026-02-23 | Active |
| SSE maintenance multi-phases | Progression par phase pour analyses longues (intégrité 3, cleanup 6) | 2026-02-23 | Active |
| Scope Films+Séries maintenance | Limiter les analyses aux sous-dossiers pertinents | 2026-02-23 | Active |
| Durée fichier via mediainfo | La durée DB vient de TMDB et peut être erronée | 2026-02-24 | Active |
| SSE + cache fichier 24h | Scan qualité ~5000 fichiers trop lent en synchrone | 2026-02-25 | Active |
| Comparaison original_title TMDB | Réduit les faux positifs pour les films étrangers | 2026-02-25 | Active |
| data-* attributes au lieu de onclick | Apostrophes dans les titres cassaient le JS inline | 2026-02-25 | Active |
| Factory standalone pour code partagé CLI/web | Plus simple qu'une classe abstraite, deps passées explicitement | 2026-02-25 | Active |
| Package library/ avec sous-routers | Découpage fichier 1250 lignes en modules cohérents | 2026-02-25 | Active |
| Boutons accès rapide plutôt que redirections auto | Respect du rythme utilisateur, pas de timer ni countdown | 2026-02-25 | Active |
| Profils lecteur JSON plutôt que .env | Basculement rapide entre machines sans redémarrer | 2026-02-26 | Active |
| SSH BatchMode=yes + ConnectTimeout=5 | Évite les blocages interactifs, erreurs rapides | 2026-02-26 | Active |
| NullPool pour SQLite | Résout le QueuePool exhaustion avec providers.Factory | 2026-02-26 | Active |
| Cascade inverse séries (send-back/reset) | Renvoyer un épisode renvoie toute la série | 2026-02-26 | Active |
| Version footer dynamique via tomllib | Centralisé dans deps.py avec les templates Jinja2 | 2026-02-26 | Active |
| Matching progressif link-movies | Normalisé→substring→contains→fuzzy (seuil 0.85) | 2026-02-27 | Active |
| Recherche TVDB multi-titre | FR→original→racine (tiret) + nettoyage année | 2026-02-27 | Active |
| Suppression : corbeille provisoire réversible | Suppression physique uniquement au vidage définitif | 2026-02-27 | Active |
| Suppression restreinte localhost | Bouton masqué + routes 403 pour clients distants | 2026-02-27 | Active |
| sessionStorage pour état UI sélection | Persistance entre pages sans polluer localStorage | 2026-02-27 | Active |
| Partial Jinja2 _play_btn.html | Template réutilisable pour bouton play + popover profil | 2026-02-28 | Active |
| Jinja2 global get_player_profiles | Accès profils dans tous les templates sans modifier les routes | 2026-02-28 | Active |
| Popover dynamique dessous/dessus | position: absolute + getBoundingClientRect() flip, overflow:hidden retiré | 2026-02-28 | Active |
| Uvicorn logging via loguru | log_config dict routant uvicorn loggers vers _LoguruInterceptHandler | 2026-02-28 | Active |
| Filtres bibliothèque 2 lignes | Ligne 1 recherche/filtres, ligne 2 tri/checkboxes/techniques/suppression | 2026-02-28 | Active |
| Flèches tri au lieu de select asc/desc | Hidden input + boutons ↑↓ + dispatchEvent pour HTMX | 2026-02-28 | Active |
| Section technique dépliable filtres | collapsed class + max-height transition, auto-open si filtre actif | 2026-02-28 | Active |
| Index rapide dict O(1) pour matching symlinks | Remplace rglob linéaire pour 54K+ fichiers | 2026-02-28 | Active |
| Phase 0 DB↔storage avant réparation symlinks | Résout file_path NULL avant de chercher les symlinks cassés | 2026-02-28 | Active |
| db_session optionnel dans RepairService | Compatibilité tests sans accès DB | 2026-02-28 | Active |
| Cache TVDB bulk par saison | 1 requête FR+EN par saison, cache individuel par épisode + marker bulk | 2026-02-28 | Active |
| Compteurs workflow = réalité DB | scanned basé sur created_video_file_ids, pas scan_results | 2026-02-28 | Active |
| VOSTFR conditionnel dans renommage | subtitle_language FR + audio non-FR/non-Multi → suffixe VOSTFR | 2026-02-28 | Active |
| "mul" normalisé en "Multi" | Guessit alpha2 "mul" → "Multi" au lieu de "MUL" | 2026-02-28 | Active |
| skip_cache sur TMDBClient.get_details() | Invalidation cache granulaire sans détruire le cache global | 2026-03-01 | Active |
| collection_id=0 sentinel | Films sans collection marqués pour éviter re-vérification | 2026-03-01 | Active |
| Filet doublons post-batch | Détection/correction doublons en fin de pipeline au lieu d'extraction en amont | 2026-03-01 | Active |

## Success Metrics

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Couverture tests | 90%+ | ~90% | On track |
| CLI fonctionnel | Toutes commandes | Complet | Achieved |
| Interface web | Workflow complet | Complet (5 phases) | Achieved |

## Tech Stack

| Layer | Technology | Notes |
|-------|------------|-------|
| Framework | FastAPI | Web API |
| Frontend | Jinja2 + HTMX | Templates + interactivité |
| CLI | Typer | Interface ligne de commande |
| Database | SQLModel (SQLite) | ORM |
| Parsing | guessit + pymediainfo | Extraction métadonnées |
| API clients | httpx (async) | TMDB, TVDB |
| DI | dependency-injector | Container IoC |

---
*PROJECT.md — Updated when requirements or context change*
*Last updated: 2026-03-07 after Phase 33 Overlays Qualité Web UI*
