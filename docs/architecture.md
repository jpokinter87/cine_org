# Architecture CineOrg

Ce document décrit l'architecture interne de CineOrg : organisation du code, couches, injection de dépendances, modèle de stockage, persistance, pipeline workflow, CLI, interface web, et décisions structurantes.

## Table des matières

- [Vue d'ensemble](#vue-densemble)
- [Organisation du code](#organisation-du-code)
  - [Core (domaine métier)](#core-domaine-métier)
  - [Adapters (ports externes)](#adapters-ports-externes)
  - [Services (logique applicative)](#services-logique-applicative)
  - [Infrastructure (persistance)](#infrastructure-persistance)
- [Injection de dépendances](#injection-de-dépendances)
- [Configuration](#configuration)
- [Modèle de stockage dual](#modèle-de-stockage-dual)
- [Persistance](#persistance)
- [Pipeline workflow](#pipeline-workflow)
- [CLI](#cli)
- [Interface web](#interface-web)
- [Décisions structurantes](#décisions-structurantes)

## Vue d'ensemble

CineOrg suit une **architecture hexagonale** (ports & adapters) :

- **Core** : entités métier et ports (interfaces) purs, sans dépendance externe.
- **Adapters** : implémentations concrètes (TMDB, TVDB, guessit, pymediainfo, filesystem).
- **Services** : orchestration métier qui compose core + adapters.
- **Infrastructure** : persistance SQLite via SQLModel.

Le câblage est centralisé dans un **container d'injection de dépendances** (`dependency-injector`). Trois interfaces cohabitent : **CLI** (Typer), **Web** (FastAPI + Jinja2 + HTMX), et des **timers systemd** pour les tâches périodiques.

## Organisation du code

```
src/
├── main.py                     # Point d'entrée CLI (Typer)
├── config.py                   # Settings Pydantic (variables CINEORG_*)
├── container.py                # Injection de dépendances
├── core/                       # Domaine métier pur
│   ├── entities/               #   Entités (VideoFile, PendingValidation, …)
│   ├── ports/                  #   Interfaces (repositories, API clients, parser)
│   └── value_objects/          #   Objets valeur (ParsedInfo, MediaInfo, Resolution, …)
├── adapters/                   # Adaptateurs (implémentations de ports)
│   ├── api/                    #   TMDBClient, TVDBClient, APICache, retry
│   ├── parsing/                #   GuessitFilenameParser, MediaInfoExtractor
│   ├── file_system.py          #   FileSystemAdapter (SymlinkManager inclus)
│   ├── cli/                    #   Commandes Typer et validation interactive
│   └── imdb/                   #   Import datasets IMDb (TSV)
├── services/                   # Services métier
│   ├── workflow/               #   Pipeline scan → match → transfer
│   ├── repair/                 #   Réparation des symlinks cassés
│   ├── cleanup/                #   Nettoyage et réorganisation
│   ├── matcher.py              #   Scoring association
│   ├── organizer.py            #   Calcul des chemins destination
│   ├── renamer.py              #   Génération des noms standardisés
│   ├── transferer.py           #   Déplacement + symlinks + hardlinks seeding
│   ├── hardlink_service.py     #   Gestion hardlinks seeding (purge)
│   ├── duplicate_detector.py   #   Détection doublons pré-transfert
│   ├── quality_scorer.py       #   Score qualité film/épisode
│   ├── enricher.py             #   Enrichissement collections TMDB
│   ├── series_enricher.py      #   Enrichissement séries TMDB/TVDB
│   ├── ratings_enricher.py     #   Notes TMDB/IMDb
│   ├── imdb_id_enricher.py     #   Association IMDb IDs
│   ├── credits_analyzer.py     #   Analyse casting/réalisation
│   ├── association_checker.py  #   Vérification cohérence associations
│   ├── sandbox_service.py      #   Sandbox pour orphelins
│   ├── validation.py           #   Gestion validations batch
│   ├── importer.py             #   Import vidéothèque existante
│   └── integrity.py            #   Vérification d'intégrité
├── infrastructure/
│   └── persistence/            # SQLite + SQLModel
│       ├── database.py         #   init_db, get_session, NullPool
│       ├── models.py           #   9 modèles SQLModel
│       ├── hash_service.py     #   SHA-256
│       └── repositories/       #   Implémentations SQLModel des ports
├── web/
│   ├── app.py                  #   FastAPI, lifespan, mounts
│   ├── deps.py                 #   Dépendances FastAPI + Jinja2 globals
│   ├── routes/                 #   Routes groupées par domaine
│   ├── templates/              #   Jinja2 (partials réutilisables)
│   └── static/                 #   CSS, JS, favicon
└── utils/
    ├── constants.py            # VIDEO_EXTENSIONS, IGNORED_PATTERNS, GENRE_HIERARCHY…
    └── helpers.py              # Utilitaires transverses
```

### Core (domaine métier)

Code pur, sans import externe (hors stdlib).

**Entités** (`src/core/entities/`) : dataclasses représentant les concepts métier.

- `VideoFile` : fichier vidéo scanné (path, hash, métadonnées techniques).
- `PendingValidation` : validation en attente (liste de candidats, flag auto_validated).

**Ports** (`src/core/ports/`) : interfaces (Protocol) que les adapters doivent implémenter.

- `repositories.py` : `IMovieRepository`, `ISeriesRepository`, `IEpisodeRepository`, `IVideoFileRepository`, `ITrashRepository`.
- `api_clients.py` : `IMediaAPIClient` — contrat commun TMDB/TVDB, retourne `SearchResult` + `MediaDetails`/`EpisodeDetails`.
- `parser.py` : `IFilenameParser`, `IMediaInfoExtractor`.
- `file_system.py` : `IFileSystem`, `ISymlinkManager`.

**Value objects** (`src/core/value_objects/`) : dataclasses `frozen=True`.

- `ParsedFilename`, `MediaType` (film vs série).
- `Resolution`, `VideoCodec`, `AudioCodec`, `MediaInfo`.

### Adapters (ports externes)

Implémentations concrètes des ports.

- **`api/tmdb_client.py`** — `TMDBClient` : films, collections, détails, external_ids. Détection automatique clé v3 (32 hex) vs v4 (JWT).
- **`api/tvdb_client.py`** — `TVDBClient` : séries, épisodes, cache bulk par saison (1 requête FR+EN, cache individuel par épisode + marker bulk). Token JWT auto-refresh.
- **`api/cache.py`** — `APICache` : persistance disque des réponses (TTL recherches 24 h, détails 7 j). Paramètre `skip_cache` pour invalidation granulaire.
- **`api/retry.py`** — backoff exponentiel avec jitter sur HTTP 429.
- **`parsing/guessit_parser.py`** — `GuessitFilenameParser` : titre, année, saison/épisode, codecs, résolution, langue (normalisation `mul` → `Multi`).
- **`parsing/mediainfo_extractor.py`** — `MediaInfoExtractor` : extraction technique via pymediainfo (largeur/hauteur, codecs x264/x265, audio AC3/AAC/DTS-HD/TrueHD/FLAC/MP3, langues ISO 639-1, durée en secondes).
- **`file_system.py`** — `FileSystemAdapter` : opérations fichiers et symlinks (absolus).

### Services (logique applicative)

Orchestrent les adapters et appliquent les règles métier. Exemples clés :

- **`workflow/`** : pipeline principal (voir [Pipeline workflow](#pipeline-workflow)).
- **`matcher.py`** : scoring films (50 % titre + 25 % année + 25 % durée) et séries (100 % titre) — seuil auto 85 %.
- **`organizer.py`** : calcul destination selon structure existante (descend l'arborescence, ne la reconstruit pas). Gère subdivisions alphabétiques, priorité genre (GENRE_HIERARCHY : Animation > Science-Fiction > Fantastique > …), articles ignorés (Le/La/The/A), sous-routage Animation Enfant/Adultes.
- **`renamer.py`** : génération noms standardisés + `sanitize_for_filesystem` (remplace `:`, `?`, etc. par `-` ou `...`).
- **`transferer.py`** : déplacement atomique, création symlinks absolus, création hardlinks seeding (voir [docs/hardlinks.md](hardlinks.md)).
- **`repair/repair_service.py`** : réparation symlinks cassés via indexation `storage/` + fuzzy matching (seuil 0.85).
- **`cleanup/cleanup_service.py`** : analyse/nettoyage structure (subdivisions, symlinks cassés, orphelins). Les opérations de subdivision affectent **uniquement** les symlinks `video/`, jamais les fichiers physiques `storage/`.

### Infrastructure (persistance)

- **`database.py`** : initialisation SQLModel avec **`NullPool`** (pas `QueuePool` — évite l'épuisement des connexions avec `providers.Factory`).
- **`models.py`** : 9 modèles SQLModel (voir [Persistance](#persistance)).
- **`hash_service.py`** : `compute_file_hash()` en SHA-256 pour déduplication.
- **`repositories/`** : implémentations SQLModel des ports. Méthodes dédiées : `get_by_tmdb_id`, `search_by_title`, `list_without_ratings`, `get_by_hash`, `update_symlink_path`, etc.

## Injection de dépendances

`src/container.py` — container `dependency-injector`.

**Singletons** (instanciés une seule fois) :
- `Config`, `FileSystemAdapter`, `APICache`.
- Parseurs : `GuessitFilenameParser`, `MediaInfoExtractor`.
- Clients API : `TMDBClient`, `TVDBClient`.
- Services stateless : `MatcherService`, `OrganizerService`, `RenamerService`, `QualityScorerService`.

**Factory** (nouvelle instance à chaque appel) :
- **Session DB** : `session = providers.Factory(lambda: next(get_session()))` — session fraîche par appel, évite la corruption transactionnelle.
- Tous les repositories (dépendent de la session).
- Services avec état : `ScannerService`, `ValidationService`, `ImporterService`, `EnricherService`, `IntegrityChecker`, `RepairService`, `CleanupService`, `SandboxService`, `HardlinkService`, `TransfererService`, `WorkflowService`.

**Resource** :
- `database = providers.Resource(init_db)` — initialisation unique, cleanup automatique à l'arrêt.

Les clés API (`tmdb_api_key`, `tvdb_api_key`) sont **optionnelles** : les clients sont créés avec `config.provided.tmdb_api_key`, et `ValidationService` gère gracieusement l'absence.

## Configuration

`src/config.py` — Pydantic `BaseSettings`. Variables d'environnement préfixées `CINEORG_` (ou fichier `.env`).

Principales clés :

| Clé | Défaut | Rôle |
|-----|--------|------|
| `downloads_dir` | — | Téléchargements (avec sous-dossiers `Films/`, `Series/`) |
| `storage_dir` | — | Stockage physique |
| `video_dir` | — | Symlinks pour le mediacenter |
| `sandbox_dir` | `{storage}/.sandbox` | Sandbox orphelins (même volume) |
| `database_url` | `sqlite:///cineorg.db` | URL DB |
| `tmdb_api_key` | `None` | Clé TMDB (v3 ou v4) |
| `tvdb_api_key` | `None` | Clé TVDB |
| `min_file_size_mb` | `100` | Taille minimale considérée |
| `max_files_per_subdir` | `50` | Déclenche subdivision alphabétique |
| `match_score_threshold` | `85` | Seuil auto-validation |
| `hardlink_retention_days` | `30` | TTL hardlinks seeding |
| `log_level` | `INFO` | Niveau loguru |

Les chemins passent par `@field_validator` avec `expanduser()` (support `~`).

## Modèle de stockage dual

CineOrg maintient **deux arborescences parallèles** :

```
storage/  ← fichiers physiques (source de vérité)
├── Films/{Genre}/{Lettre}/{Subdivision}/...
└── Séries/{Lettre}/{Subdivision}/{Titre (Année)}/Saison XX/...

video/    ← symlinks absolus pointant vers storage/
├── Films/{Genre}/{Lettre}/{Subdivision}/...
└── Séries/{Lettre}/{Subdivision}/{Titre (Année)}/Saison XX/...
```

**Pourquoi** : permet de réorganiser l'arborescence (subdivisions, fusion de genres, regroupement alphabétique) en manipulant uniquement les symlinks, sans déplacer les fichiers physiques. Le media center lit `video/`, les scripts système lisent `storage/`.

**Implémentation** :
- `organizer.py` parcourt l'existant et décide de la destination.
- `transferer.py` crée les symlinks absolus `os.symlink(storage, video)`.
- `_resolve_storage_path()` suit les symlinks `video/` pour retrouver le vrai chemin storage (évite les erreurs de casse).
- `cleanup_service.py` déplace uniquement les symlinks lors des subdivisions.

## Persistance

SQLite via SQLModel, 9 tables.

| Modèle | Rôle | Index clés |
|--------|------|------------|
| `MovieModel` | Films TMDB | `tmdb_id`, `title`, `file_path`, `symlink_path`, `file_hash`, `imdb_id`, `collection_id` |
| `SeriesModel` | Séries TVDB/TMDB | `tvdb_id`, `title` |
| `EpisodeModel` | Épisodes (FK `series_id`) | composite `(series_id, season, episode)` |
| `VideoFileModel` | Fichiers scannés | `path`, `symlink_path`, `file_hash` |
| `PendingValidationModel` | Validations en attente | FK `video_file_id`, `candidates_json` (top 5), `auto_validated` |
| `IMDbRatingModel` | Cache dataset IMDb | PK `tconst`, `average_rating`, `num_votes` |
| `TrashModel` | Corbeille réversible | `entity_type`, `original_id`, `metadata_json` |
| `ConfirmedAssociationModel` | Associations validées manuellement | `entity_type`, `entity_id` |
| `HardlinkModel` | Registre hardlinks seeding | `download_path`, `storage_path`, `expires_at` |

Les hashs SHA-256 permettent la déduplication. Les `candidates_json` sérialisent les top 5 candidats API pour affichage sans nouvel appel.

## Pipeline workflow

`src/services/workflow/workflow_service.py` — `WorkflowService` orchestre les étapes via mixins (`ScanStepMixin`, `MatchingStepMixin`, `TransferStepMixin`).

Séquence :

1. **Cleanup orphans** — supprime symlinks cassés, fichiers orphelins (→ sandbox optionnel).
2. **Scan downloads** (`scan_step.py`) — parcourt `downloads/Films` et `downloads/Series`, filtre extensions, patterns ignorés (sample/trailer/preview), taille minimale, et **`st_nlink > 1`** (skip hardlinks déjà seedés).
3. **Matching** (`matching_step.py`) — `pending_factory` construit les candidats via TMDB/TVDB (cache mémoire série par `(titre, année)`), `matcher.py` score.
4. **Auto-validation** — score ≥ 85 % AND résultat unique → `auto_validated=True`, sinon crée une `PendingValidationModel`.
5. **Validation manuelle** — boucle interactive (CLI ou web).
6. **Transfer** (`transfer_step.py`) — renomme, déplace atomiquement, crée symlinks `video/`, crée hardlink seeding dans `downloads/`, insère `HardlinkModel`.
7. **Summary** — rapport final (fichiers transférés, erreurs, compteurs DB).

Dataclasses échangées (`workflow/dataclasses.py`) :
- `WorkflowConfig` — filtre type, dry-run, chemins.
- `WorkflowState` — résultats scan, pending, `created_video_file_ids` (source de vérité pour les compteurs), compteurs par étape.
- `WorkflowResult` — succès, état final, erreurs.

Voir [docs/association.md](association.md) pour le détail matching/validation et [docs/hardlinks.md](hardlinks.md) pour les hardlinks seeding.

## CLI

`src/main.py` — `app = typer.Typer()` avec callback global `--verbose/-v`, `--quiet/-q`. Container DI instancié au démarrage.

Commandes dans `src/adapters/cli/commands/` (un fichier par domaine) :

| Domaine | Commandes |
|---------|-----------|
| Workflow | `process`, `pending` |
| Validation | `validate auto`, `validate manual`, `validate batch`, `validate file` |
| Enrichissement | `enrich`, `enrich-ratings`, `enrich-imdb-ids`, `enrich-series`, `enrich-tvdb-ids`, `enrich-collections`, `enrich-movies-credits`, `enrich-episode-titles`, `enrich-tech` |
| Import | `import`, `populate-movies`, `populate-series` |
| IMDb | `imdb import`, `imdb sync`, `imdb stats` |
| Réparation | `repair-links`, `fix-symlinks`, `fix-bad-links`, `fix-series-symlinks` |
| Maintenance | `cleanup`, `consolidate`, `check`, `regroup`, `migrate-series`, `reconcile`, `check-duplicates`, `clean-titles` |
| Hardlinks | `purge-hardlinks` (appelé par le timer systemd) |

**Pattern** : fonction Typer synchrone → `asyncio.run(_async_impl(...))` pour les services asynchrones. Rich pour l'affichage (Progress, Status, Table, Panel). Loguru désactivé pendant les widgets Rich (`loguru_logger.disable("src")`).

## Interface web

`src/web/app.py` — FastAPI avec lifespan context (init container, cleanup à l'arrêt). Mount `/static/`.

Routes par domaine (`src/web/routes/`) :

| Module | Rôle |
|--------|------|
| `home.py` | Dashboard |
| `library/browse.py` | Bibliothèque (films + séries, filtres, tri) |
| `library/detail.py` | Fiche détaillée |
| `library/collections.py` | Collections TMDB |
| `library/reassociate.py` | Réassociation (recherche nouvelle, ID externe) |
| `library/player.py` | Lecteur intégré (mpv subprocess) |
| `library/trash.py` | Corbeille |
| `library/delete.py` | Suppression (localhost only — 403 distant) |
| `library/suggest.py` | Suggestions qualité |
| `workflow.py` | Pipeline scan → match (SSE progression) |
| `validation.py` | Validation interactive (HTMX) |
| `transfer.py` | Résumé batch, résolution doublons, transfert (SSE) |
| `quality.py` | Analyse qualité technique |
| `duplicates.py` | Doublons DB / physiques |
| `maintenance.py` | Cleanup, repair, purge corbeille |
| `config.py` | Configuration (paths, API keys, seuils) |

**Dépendances** (`deps.py`) :
- `Jinja2Templates` depuis `src/web/templates/`.
- Version applicative chargée dynamiquement (`tomllib` sur `pyproject.toml`) → variable `{{ app_version }}` globale.
- `get_player_profiles()` global Jinja2 — accès aux profils lecteur depuis tous les templates.

**Stack UI** :
- Jinja2 avec partials réutilisables (ex. `_play_btn.html`, `_reassociate_overlay.html`).
- HTMX (`hx-get`, `hx-post`, `hx-swap`) pour interactivité sans SPA.
- **SSE** (Server-Sent Events) pour progression asynchrone : workflow, transfert préparation, transfert exécution.
- CSS custom (Instrument Serif + DM Sans, thème sombre).
- Popover dynamique flip position (absolute + `getBoundingClientRect()`).
- Dialogues custom overlay (pas `confirm()` natif).
- `sessionStorage` pour persistance sélection entre pages.
- `htmx.process()` obligatoire après injection `innerHTML` pour activer les attributs `hx-*` dynamiques.

## Décisions structurantes

Extraites de l'historique (`.paul/STATE.md`, `CLAUDE.md`) :

- **NullPool SQLite** au lieu de `QueuePool` — évite l'épuisement des connexions avec les `providers.Factory` qui créent une session par appel.
- **Cache mémoire série** par `(titre_lower, année)` dans `pending_factory.py` — évite les recherches API TVDB et scoring redondants sur un batch multi-épisodes.
- **Cache TVDB bulk par saison** — 1 requête FR+EN, cache individuel par épisode avec marker bulk (perf).
- **Index mémoire par année** pour le matching batch — remplace les requêtes DB par symlink (O(1) au lieu de O(n)).
- **Hardlinks seeding** non bloquants cross-device — `os.link()` en fallback, l'échec n'interrompt pas le transfert.
- **Normalisation ligatures** (Œ/Æ) et slash/tiret pour comparaison de titres robuste.
- **Cascade série** : renvoyer un épisode renvoie tous les épisodes du même candidat (titre + année).
- **Sandbox sur le même volume** (`.sandbox` sous `storage/`) — évite les copies réseau pour les orphelins.
- **Suppression restreinte à localhost** — bouton masqué côté distant, 403 sur la route DELETE (sécurité usage personnel).
- **Flag `is_tv`** + source `tmdb_tv` pour distinguer film vs série TMDB dans tout le pipeline.
- **Corbeille réversible** — suppression physique uniquement au vidage définitif.
- **Réécriture du titre série via `sanitize_for_filesystem`** côté dossier (pas seulement côté fichier) — évite les caractères `:` et `?` incompatibles avec certains media centers.

---

Pour le détail des sous-systèmes :
- [docs/association.md](association.md) — association et réassociation TMDB/TVDB.
- [docs/hardlinks.md](hardlinks.md) — seeding via hardlinks.
