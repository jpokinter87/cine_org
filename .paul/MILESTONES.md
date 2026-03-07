# Milestones

Completed milestone log for this project.

| Milestone | Completed | Duration | Stats |
|-----------|-----------|----------|-------|
| v1.0 Interface Web | 2026-02-23 | ~3 days | 5 phases, 8 plans |
| v1.1 Enrichissement Données | 2026-02-24 | ~1 day | 3 phases, 3 plans |
| v1.2 Gestion Associations | 2026-02-25 | ~2 days | 4 phases, 4 plans |
| v1.3 Qualité & Fluidité | 2026-02-25 | ~1 day | 3 phases, 5 plans |
| v1.4 Expérience Utilisateur | 2026-02-26 | ~1 day | 2 phases, 4 plans |
| v1.5 Polish & Corrections UX | 2026-02-26 | ~1 day | 3 phases, 4 plans |
| v1.6 Gestion & Qualité de Données | 2026-02-28 | ~2 days | 4 phases, 5 plans |
| v1.7 Fiabilité & Ergonomie Bibliothèque | 2026-02-28 | ~1 day | 2 phases, 2 plans |
| v1.8 Robustesse Workflow & Corrections UX | 2026-03-01 | ~1 day | 3 phases, 3 plans |
| v1.9 Normalisation & Intégration Jellyfin | 2026-03-07 | ~7 days | 5 phases, 7 plans |

---

## ✅ v1.9 Normalisation & Intégration Jellyfin

**Completed:** 2026-03-07
**Duration:** ~7 days (2026-03-01 → 2026-03-07)

### Stats

| Metric | Value |
|--------|-------|
| Phases | 5 complete + 1 abandoned (29, 30, 31, 33, 34) |
| Plans | 7 |
| Files created | 13 |
| Files modified | 36 |

### Key Accomplishments

- Filet de sécurité films multi-parties : détection et correction automatique des doublons de nommage
- Normalisation répertoires séries : Séries→Series, Séries TV→TV, routage documentaires, migration complète (code + DB + fichiers)
- Commande fix-series-symlinks : mediainfo + guessit + enrichissement TVDB en un seul pass
- DuplicateDetector : scoring qualité multi-critères (résolution, codecs, bitrate normalisé par efficacité codec)
- Résolution doublons pré-transfert : dialog comparatif dans le résumé batch, cascade série, sandbox
- Page web /duplicates : comparaison qualité, whitelist, suppression corbeille
- Badges qualité sur posters grille : résolution (4K doré/1080p vert/720p bleu/SD gris), codec, langue
- Commande check-duplicates CLI : détection par tmdb_id, scoring, whitelist JSON
- Phase 32 NFO abandonnée : Jellyfin scrape TMDB seul, sidecar NFO sans bénéfice

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Filet doublons post-batch | Plus robuste qu'une extraction en amont |
| Répertoires sans accents (Series/TV) | Compatibilité cross-platform Jellyfin |
| mediainfo primaire, guessit fallback | Pipeline identique au workflow normal |
| SD reconnu comme résolution valide | Fichiers legacy, évite ~666 faux positifs |
| Normalisation ligatures Œ/Æ | Comparaison TVDB vs filename |
| Scoring qualité codec-normalized | AV1 ×3.0, HEVC ×2.0, VP9 ×1.8 pour bitrate équitable |
| Résolution dans résumé batch (pas SSE) | Meilleure UX, pas d'interruption mid-transfert |
| Phase 32 NFO abandonnée | Jellyfin scrape TMDB seul, sidecar inutile |

---

## ✅ v1.8 Robustesse Workflow & Corrections UX

**Completed:** 2026-03-01
**Duration:** ~1 day (2026-02-28 → 2026-03-01)

### Stats

| Metric | Value |
|--------|-------|
| Phases | 3 (26, 27, 28) |
| Plans | 3 |
| Files created | 4 |
| Files modified | 31 |

### Key Accomplishments

- Popover lecteur avec placement dynamique JS (dessous/dessus) — corrige le bug des épisodes en bas de liste
- Bouton réinitialisation workflow web avec dialogue de confirmation overlay
- Logs serveur uvicorn horodatés via loguru (format unifié avec le reste de l'application)
- Cache TVDB bulk par saison (1 requête API au lieu de N par épisode)
- Compteurs workflow web cohérents avec l'état réel en DB
- Parsing et renommage VOSTFR (subtitle_language dans ParsedFilename)
- 583 collections/sagas TMDB identifiées (939 films dans des sagas)
- Page web /library/collections avec recherche HTMX et tri
- Badge collection sur cartes films et lien saga sur fiches détail
- Pattern skip_cache sur TMDBClient.get_details() pour invalidation cache granulaire
- 914 tests, couverture tvdb_client 91%, guessit_parser 97%

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| overflow:hidden retiré de .lib-season-group | Cause racine du popover tronqué par le conteneur |
| log_config dict pour uvicorn | log_config=None supprime tout logging |
| Bulk fetch FR+EN séparé TVDB | Fallback titre EN quand FR vide |
| scanned basé sur created_video_file_ids | Reflète la réalité DB, pas le scan brut |
| VOSTFR exclu si audio Multi | Pas de redondance dans le nom de fichier |
| skip_cache param vs cache clear | Granulaire, ne détruit pas le cache existant |
| collection_id=0 sentinel | Évite re-vérification des films sans saga |
| Nav Collections = lien standard | Cohérence avec les autres onglets navbar |

---

## ✅ v1.7 Fiabilité & Ergonomie Bibliothèque

**Completed:** 2026-02-28
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 2 (24, 25) |
| Plans | 2 |
| Files created | 1 |
| Files modified | 6 |

### Key Accomplishments

- Filtres bibliothèque réorganisés en 2 lignes (recherche/filtres + tri/checkboxes/technique/suppression)
- Flèches tri intégrées (hidden input + boutons ↑↓ + dispatchEvent HTMX)
- Panneau technique dépliable (collapsed class + max-height transition, auto-open si filtre actif)
- Commande CLI reconcile avec 3 phases de réconciliation DB↔storage↔symlinks
- Index rapide dictionnaires O(1) pour matching symlinks (remplace rglob linéaire)
- Phase 0 DB↔storage : réconciliation file_path NULL avant réparation symlinks

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Layout filtres 2 lignes | Meilleure lisibilité que tout-en-un |
| Index rapide dict O(1) | Performance pour 54K+ fichiers |
| Phase 0 DB↔storage avant symlinks | Résout file_path NULL avant de chercher les symlinks cassés |
| db_session optionnel dans RepairService | Compatibilité tests sans accès DB |

---

## ✅ v1.6 Gestion & Qualité de Données

**Completed:** 2026-02-28
**Duration:** ~2 days (2026-02-27 → 2026-02-28)

### Stats

| Metric | Value |
|--------|-------|
| Phases | 4 (20, 21, 22, 23) |
| Plans | 5 |
| Files created | 6 |
| Files modified | 26 |

### Key Accomplishments

- 1040 films liés à leurs fichiers via matching fuzzy progressif 4 stratégies (seuil 0.85)
- Suppression batch depuis la bibliothèque avec corbeille provisoire réversible et sécurité localhost
- 13 séries enrichies tvdb_id via recherche multi-titre TVDB (FR→original→racine)
- 98 épisodes enrichis avec titres manquants via TVDB
- Sélecteur de profil lecteur popover + lectures parallèles multi-profils
- Cartouches accueil cliquables, genres normalisés FR, tri "récemment ajouté"
- Filtres enrichis : langue, sans fichier, sans poster
- Template partiel réutilisable `_play_btn.html` (élimine la duplication bouton play)
- Persistance sélection via sessionStorage entre pages

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Normalisation genres à l'affichage uniquement | Préservation intégrité DB |
| Seuil fuzzy 0.85 pour link-movies et enrich-tvdb-ids | Sweet spot évitant les faux positifs |
| Index mémoire par année pour matching batch | Performance O(1) vs N requêtes DB |
| Corbeille provisoire avant suppression physique | Filet de sécurité réversible |
| Suppression restreinte localhost | Sécurité — machine maître uniquement |
| sessionStorage pour état sélection | Persiste entre pages sans polluer localStorage |
| Partial Jinja2 pour bouton play | Séparation template/logique, réutilisable |
| Popover épisodes vers le bas | Contournement overflow:hidden du conteneur saison |

---

## v1.5 Polish & Corrections UX

**Completed:** 2026-02-26
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 3 (17, 18, 19) |
| Plans | 4 |
| Files modified | ~21 |

### Key Accomplishments

- Bouton Visionner sur page Surprends-moi (films et séries, premier épisode S01E01)
- Bouton "Renvoyer en validation" par fichier sur page transfert avec cascade inverse séries
- Section "Auto-validés" sur page validation avec bouton Revalider et cascade série
- Fix NullPool pour SQLite (résout QueuePool exhaustion avec providers.Factory)
- Dialogues custom overlay pour toutes les confirmations destructives (remplacement confirm() natif)
- Page config avec sections pliables (accordéon) et animation CSS fluide
- Version footer dynamique lue depuis pyproject.toml via tomllib

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Route series/play → premier épisode S01E01 | Plus propre que passer episode_id au template |
| NullPool pour SQLite | Résout définitivement le QueuePool exhaustion avec providers.Factory |
| Cascade inverse séries (send-back + reset) | Miroir de l'auto-validation cascade existante |
| Dialogues custom overlay partout | Cohérence charte graphique, remplacement confirm() natif |
| Version footer via tomllib dans deps.py | Centralisé avec les templates Jinja2 |

---

## v1.4 Expérience Utilisateur

**Completed:** 2026-02-26
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 2 (15, 16) |
| Plans | 4 |

### Key Accomplishments

- Tag "déjà vu" et note étoiles (1-5) sur fiches films et séries
- Page "Surprends-moi" avec suggestion aléatoire et filtres (genre, durée, note, type)
- Navigation historique des suggestions (avant/arrière)
- Bouton accueil avec animation glow ambrée
- Lecteur vidéo configurable (mpv/vlc, local/remote, SSH)
- Profils lecteur nommés avec CRUD et sélection rapide (JSON)
- Mapping de chemins cross-platform (Linux→Linux, Linux→Windows)
- Migration transparente des paramètres .env vers profils JSON

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Suggestion random parmi éligibles | Simple et efficace, pas de ML |
| Profils lecteur JSON plutôt que .env | Basculement rapide entre machines sans redémarrer |
| SSH BatchMode=yes + ConnectTimeout=5 | Évite les blocages interactifs |
| Path mapping par préfixe | Cross-platform Linux→Linux et Linux→Windows |

---

## v1.0 Interface Web

**Completed:** 2026-02-23
**Duration:** ~3 days

### Stats

| Metric | Value |
|--------|-------|
| Phases | 5 |
| Plans | 8 |

### Key Accomplishments

- Foundation web : FastAPI app, layout Jinja2 thème sombre, HTMX, page d'accueil stats
- Validation visuelle : liste pending, détail candidats enrichis, actions HTMX
- Orchestration workflow : scan, matching, auto-validation avec SSE temps réel
- Transfert et résolution de conflits via le web
- Navigation bibliothèque films/séries avec filtres, fiches détaillées
- Page configuration (répertoires, clés API, seuils)
- Maintenance : diagnostics intégrité et cleanup avec SSE temps réel

---

## v1.1 Enrichissement Données

**Completed:** 2026-02-24
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 3 |
| Plans | 3 |

### Key Accomplishments

- Ratings films enrichis à 100% (IMDb via TMDB, progress bar Rich)
- Séries enrichies : tmdb_id 99.7%, imdb_id 98.3%
- Fiches web enrichies : liens IMDb/TMDB, crédits cliquables, filtre par personne

---

## v1.2 Gestion Associations

**Completed:** 2026-02-25
**Duration:** ~2 days (2026-02-24 → 2026-02-25)

### Stats

| Metric | Value |
|--------|-------|
| Phases | 4 (9, 9b, 10, 11) |
| Plans | 4 |
| Files created | ~10 |
| Files modified | ~25 |

### Key Accomplishments

- Correction manuelle d'associations TMDB : overlay de recherche avec indicateurs de confiance durée/saisons, dialog de confirmation custom
- Filtres avancés bibliothèque : résolution (4K/1080p/720p/SD), codec vidéo/audio, recherche étendue synopsis
- Cartouches techniques cliquables sur fiches détaillées + badges Multi langues
- Navigation prev/next entre fiches avec prefetch et flèches clavier
- Propagation complète des métadonnées techniques dans le pipeline workflow
- Détection automatique d'associations suspectes : AssociationChecker avec heuristiques titre/année/durée, scan SSE temps réel, cache 24h
- Confirmation manuelle des associations avec persistance en DB
- Dashboard qualité : métriques de couverture enrichissement, résumé suspects, historique corrections
- Enrichissement 923 séries avec tvdb_id via TMDB API + purge 29 séries documentaires

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Durée fichier via mediainfo (pas la DB) | La durée DB peut correspondre à une mauvaise association TMDB |
| SSE + cache fichier 24h pour scan qualité | 5000+ fichiers trop lent pour requête bloquante, cache survit aux --reload |
| Comparaison original_title | Réduit les faux positifs pour les films étrangers |
| data-* attributes au lieu de onclick | Les apostrophes dans les titres cassaient le JS |
| Durée en pourcentage (30%/15%) | Évite les faux positifs selon la durée du film |
| Séries documentaires exclues | Identification trop difficile, hors périmètre |

---

## v1.3 Qualité & Fluidité

**Completed:** 2026-02-25
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 3 (12, 13, 14) |
| Plans | 5 |
| Files created | ~7 |
| Files modified | ~20 |

### Key Accomplishments

- Tri bibliothèque normalisé : accents, ligatures (œ/æ), articles, caractères invisibles
- Recherche unicode-aware avec variantes de ligatures
- Enrichissement batch : link-movies (file_path), enrich-tech (métadonnées techniques), enrich-episode-titles (titres épisodes TVDB)
- Code matching partagé CLI/web via pending_factory.py (factory functions standalone)
- Package library/ découpé en 6 modules spécialisés (1250 lignes → 6 fichiers)
- Boutons d'accès rapide guidant workflow → validation → transfert
- Cohérence visuelle boutons page d'accueil

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Ligatures par expansion explicite (œ→oe) | Plus simple et fiable que table Unicode |
| Recherche SQL via OR sur variantes | Contourne limitation SQLite LIKE unicode |
| Factory standalone pour code partagé | Plus simple qu'une classe abstraite, deps explicites |
| Package library/ avec sous-routers | Découpage fichier monolithique en modules cohérents |
| Boutons accès rapide plutôt que redirections auto | Respect du rythme utilisateur |

---

*Last updated: 2026-02-26*
