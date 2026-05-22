# Association et réassociation

Ce document détaille le fonctionnement de l'association d'un fichier vidéo à une fiche TMDB (films) ou TVDB (séries) : pipeline complet, scoring, validation auto vs manuelle, détection de doublons, enrichissement, et réassociation depuis la fiche détaillée.

## Table des matières

- [Vue d'ensemble](#vue-densemble)
- [Pipeline d'association](#pipeline-dassociation)
  - [1. Scan des téléchargements](#1-scan-des-téléchargements)
  - [2. Extraction des métadonnées](#2-extraction-des-métadonnées)
  - [3. Construction des candidats](#3-construction-des-candidats)
  - [4. Recherche API](#4-recherche-api)
  - [5. Scoring](#5-scoring)
- [Validation auto vs manuelle](#validation-auto-vs-manuelle)
- [Détection de doublons pré-transfert](#détection-de-doublons-pré-transfert)
- [Enrichissement post-validation](#enrichissement-post-validation)
- [Réassociation depuis la fiche détaillée](#réassociation-depuis-la-fiche-détaillée)
- [Cas limites](#cas-limites)

## Vue d'ensemble

Le pipeline d'association transforme un fichier vidéo brut en entrée DB enrichie (film ou épisode) avec une confiance quantifiée. Il compose :

1. **Parsing** (guessit + pymediainfo) — extraction des indices présents dans le nom et le contenu du fichier.
2. **Recherche API** (TMDB pour les films, TVDB pour les séries) — récupération des candidats.
3. **Scoring** — quantification de la ressemblance (titre, année, durée).
4. **Validation** — automatique si score ≥ 85 % et résultat unique, sinon interactive (CLI ou web).
5. **Enrichissement** — collections TMDB, notes, IMDb IDs, credits, etc. (services séparés).

La **réassociation** reprend le même scoring mais à la demande depuis la fiche détaillée web, avec en plus la recherche par ID externe et un fallback métadonnées techniques depuis le symlink.

## Pipeline d'association

### 1. Scan des téléchargements

**Fichiers** : `src/services/scanner.py`, `src/services/workflow/scan_step.py`.

Le scanner parcourt `downloads_dir/Films` et `downloads_dir/Séries` et applique ces filtres :

- **Extensions vidéo** : `VIDEO_EXTENSIONS` = `.mkv`, `.mp4`, `.avi`, `.mov`, `.wmv`, `.flv`, `.webm`, `.m4v`.
- **Patterns ignorés** : `IGNORED_PATTERNS` = `sample`, `trailer`, `preview`, `extras`, `bonus` (case-insensitive).
- **Taille minimale** : `min_file_size_mb` (défaut 100 Mo).
- **Symlinks** : ignorés (`is_symlink()`).
- **Hardlinks déjà seedés** : `st_nlink > 1` → skip (voir [docs/hardlinks.md](hardlinks.md)).

Les fichiers sous le seuil de taille sont regroupés par titre pour affichage de confirmation (évite d'ignorer silencieusement un épisode anormalement petit).

### 2. Extraction des métadonnées

**Guessit** (`src/adapters/parsing/guessit_parser.py`) extrait depuis le **nom de fichier** :

| Champ | Exemple | Normalisation |
|-------|---------|---------------|
| `title` | "Blade Runner 2049" | Ligatures Œ/Æ gérées |
| `year` | 2017 | — |
| `season`, `episode` | 2, 5 | `is not None` (pas truthiness) pour gérer E00 |
| `resolution` | "1080p" | — |
| `video_codec` | "H.264" | Mappage vers x264/x265/AV1/VP9 |
| `audio_codec` | "DTS-HD" | AC3/AAC/DTS/DTS-HD/TrueHD/FLAC/MP3 |
| `language` | "FR" | `mul` → `Multi`, alpha2 majuscules |
| `subtitle_language` | "FR" | Utilisé pour détecter VOSTFR |

**Pymediainfo** (`src/adapters/parsing/mediainfo_extractor.py`) extrait depuis le **contenu** du fichier :

- Largeur/hauteur en pixels → `Resolution` (SD reconnu comme valide).
- Codecs normalisés (x264/x265, AV1, VP9, MPEG-4/XviD/DivX).
- Langues audio multiples (liste ISO 639-1 unique, avec noms français).
- Durée en secondes (conversion `duration_ms / 1000` critique — pymediainfo retourne des ms).

Le combo guessit + pymediainfo couvre les cas où le nom est pauvre (guessit fallback) et où le fichier est mal encodé.

### 3. Construction des candidats

**Fichier** : `src/services/workflow/pending_factory.py`.

Pour chaque `VideoFile`, le factory :

1. Détermine le type (film vs série) selon la présence de `season`/`episode`.
2. Consulte un **cache mémoire série** : `dict[(titre_lower, année), candidats]`. Si hit → réutilise les candidats (évite recherche API + scoring redondants pour les épisodes multiples de la même série dans un batch).
3. Sinon, lance la recherche API.
4. Score et retient le top 5.
5. Sérialise dans `PendingValidationModel.candidates_json`.

### 4. Recherche API

**TMDB** (`src/adapters/api/tmdb_client.py`) — films :

- Requête simple `search/movie?query=…`.
- Puis requête avec année `search/movie?query={titre}&year={année}` pour capturer les films peu populaires.
- Détails top 10 via `get_details()` pour récupérer la durée TMDB (nécessaire pour le scoring film complet).
- Détection automatique de la clé API : v3 (32 hex) vs v4 (long JWT).

**TVDB** (`src/adapters/api/tvdb_client.py`) — séries :

- Recherche **multi-titre** : titre FR → titre original → racine (avant tiret) + nettoyage année.
- Token JWT auto-refresh 1 jour avant expiration (valide ~6 jours).
- **Cache bulk par saison** : 1 requête FR + EN, résultat éclaté en cache individuel par épisode + marker `bulk_cached` pour éviter les re-requêtes.

**Cache disque commun** (`src/adapters/api/cache.py`) :

- Clés typées : `tmdb:search:{query}:{year}`, `tvdb:episodes:{series}:{season}`, etc.
- TTL : 24 h pour les recherches, 7 j pour les détails.
- Paramètre `skip_cache` sur `get_details()` pour invalidation granulaire (utilisé par la réassociation).

**Retry** (`src/adapters/api/retry.py`) : backoff exponentiel + jitter sur HTTP 429 (rate limiting).

### 5. Scoring

**Fichier** : `src/services/matcher.py`.

#### Films

Deux formules selon la disponibilité de la durée locale (extraite par mediainfo) :

**Avec durée** :

```
score = 50 % × similarité_titre
      + 25 % × match_année
      + 25 % × match_durée
```

- **Similarité titre** : `token_sort_ratio` (rapidfuzz) après normalisation des accents (`É→E`, `À→A`), ligatures (`Œ→OE`, `Æ→AE`), et équivalences slash/tiret. **Bilingue** : on prend `max(score_titre_fr, score_titre_original)`.
- **Match année** : 1.0 si exact, 0.5 si écart 1 an, 0 au-delà.
- **Match durée** : 1.0 si écart ≤ 10 %, 0.5 si ≤ 20 %, 0 au-delà.

**Sans durée** (rare) :

```
score = 67 % × similarité_titre + 33 % × match_année
```

**Seuil auto-validation** : `match_score_threshold = 85` (configurable).

#### Séries

```
score = 100 % × similarité_titre
```

Pas de critère année ni durée (peu fiable pour les séries). Le matching série utilise en plus un **filtrage par nombre d'épisodes** : `filter_by_episode_count()` élimine les candidats dont `max_episodes_in_season < episode_demandé`.

## Validation auto vs manuelle

**Fichiers** :
- `src/services/workflow/matching_step.py` (décision auto)
- `src/services/validation.py` (service batch)
- `src/adapters/cli/validation/interactive_loop.py` (CLI)
- `src/web/routes/validation.py` + `src/web/templates/validation/` (web)

**Auto-validation** — conditions cumulatives :

- Score ≥ 85 %.
- Candidat unique au-dessus du seuil (pas d'ambiguïté).

→ `ValidationService.process_auto_validation(pending)` applique la validation avec `auto_validated=True`.

**Validation manuelle** :

- **CLI** : `interactive_loop.validation_loop()` — pagination des candidats (top 5), fetch des détails enrichis à la demande, sélection par numéro, saisie de titre alternatif, recherche par ID externe.
- **Web** : liste dans `/validation/`, action HTMX `POST /validation/{id}/validate`.

**Saisie d'ID externe** (CLI et web) :

- Pattern IMDb : `^tt\d{7,8}$`.
- Pattern TMDB/TVDB : numérique.
- Détermination du type film vs série :
  - Priorité à la source (TVDB → série, TMDB → film sauf si `is_tv=True`).
  - Fallback : pattern `SxxExx` dans le nom de fichier.

**Bouton "Visionner"** dans la vue détail de validation (`src/web/templates/validation/detail.html`) — lance mpv côté serveur, polling `/play-status/{pid}` pour retour UI.

## Détection de doublons pré-transfert

**Fichier** : `src/services/duplicate_detector.py`.

Avant le transfert, le système détecte si le fichier à importer **duplique une entrée existante** (même film ou même épisode) en bibliothèque. L'utilisateur doit choisir avant de lancer le transfert (dialogue overlay dans le résumé batch).

**Détection** :

- Titre normalisé (articles ignorés : Le/La/The/A, accents retirés, ponctuation).
- Année exacte.
- Pour les séries : titre + année, puis `season`/`episode` s'ils existent déjà en DB.

**Cascade série** : `_get_local_series_counts()` regroupe par `(titre, année)`. Si plusieurs épisodes du même candidat sont en doublon, l'utilisateur choisit une fois et la décision s'applique à tout le groupe. Les saisons partielles sont respectées (seuls les épisodes déjà existants sont marqués doublons).

**Scoring qualité** (`src/services/quality_scorer.py`) — pour aider la décision :

| Critère | Poids |
|---------|------:|
| Résolution | 25 % |
| Codec vidéo | 20 % |
| Bitrate vidéo (normalisé par codec) | 25 % |
| Codec audio | 15 % |
| Bitrate audio | 15 % |

**Normalisation bitrate par codec** (efficacité) :

| Codec | Multiplicateur |
|-------|---------------:|
| AV1 | ×3.0 |
| HEVC / x265 | ×2.0 |
| VP9 | ×1.8 |
| H.264 / x264 | ×1.0 |

→ Comparaison équitable entre un x264 1080p 8 Mbps et un HEVC 1080p 4 Mbps.

**Décisions possibles** (par fichier) :

- `keep_new` — remplacer l'existant.
- `keep_old` — skip le nouveau (reste en `downloads/`).
- `sandbox` — déplacer le nouveau en `.sandbox/` pour décision ultérieure.

Le bouton de transfert est **grisé** tant que tous les doublons ne sont pas tranchés.

## Enrichissement post-validation

Services distincts (batch indépendants, rate-limités) :

| Service | Fichier | Rôle |
|---------|---------|------|
| Collections TMDB | `src/services/enricher.py` | Détection appartenance collection (Marvel, Pixar, etc.) — sentinel `collection_id=0` pour "vérifié, pas de collection" |
| Notes TMDB | `src/services/ratings_enricher.py` | `vote_average`, `vote_count` |
| IMDb IDs | `src/services/imdb_id_enricher.py` | `/movie/{id}/external_ids` → `tt…` |
| Séries TMDB | `src/services/series_enricher.py` | Poster/notes/genres/créateurs/acteurs |
| Credits | `src/services/credits_analyzer.py` | Casting, réalisateurs |
| Import IMDb dataset | `src/adapters/imdb/` | Cache local via TSV publics |

**Rate limiting** : 0.25 s entre appels TMDB (4 req/s), 0.3 s pour les séries TMDB. Cache mémoire par `(titre, année)` pour éviter les recherches redondantes.

## Réassociation depuis la fiche détaillée

**Fichier** : `src/web/routes/library/reassociate.py` (overlay) + templates `src/web/templates/library/_reassociate_overlay.html` et `_reassociate_results.html`.

Cas d'usage : la fiche détaillée affiche une mauvaise association (mauvais film/série, mauvais épisode, homonyme, etc.) — l'utilisateur lance une **réassociation** depuis la fiche, qui rejoue le pipeline de manière ciblée.

### Endpoints

| Endpoint | Usage |
|----------|-------|
| `GET /movies/{id}/reassociate` | Overlay initial (avec durée locale via `_get_file_duration()` pour le scoring) |
| `GET /movies/{id}/reassociate/search?q=…` | Recherche par titre + année — scoring enrichi top candidats |
| `GET /movies/{id}/reassociate/search-by-id?id=…` | Recherche par ID externe (TMDB, TVDB, IMDb `tt…`) |
| `POST /movies/{id}/reassociate` | Validation de la nouvelle association |

Les mêmes endpoints existent pour `/series/{id}` et `/episodes/{id}`.

### Rafraîchir une association correcte

La carte « Association actuelle » des résultats expose un bouton **Rafraîchir les données** : il rejoue `POST .../reassociate` sur le `tmdb_id` **inchangé**. Sans ce bouton, relancer l'enrichissement d'une fiche correctement associée mais incomplète (ex. importée avant l'enrichissement des notes) imposait de choisir volontairement une fausse association puis de revenir.

Le handler `apply` (films comme séries) backfille `imdb_rating`/`imdb_votes` depuis le cache IMDb local via `_lookup_imdb_rating()` — même pont TMDB→IMDb que `batch_builder` et `series_enricher`. Si le nouvel `imdb_id` est absent du cache, l'ancienne note (héritée d'une association précédente) est purgée.

### Fallback métadonnées techniques depuis le symlink

Quand le fichier source original a été supprimé de `storage/`, les métadonnées techniques (résolution, codecs, langue) ne sont plus extractibles via pymediainfo. Le système applique alors un fallback :

1. Parser guessit sur le nom du **symlink** (standardisé, souvent plus riche que le nom source brut).
2. Si le symlink pointe encore vers un fichier accessible → mediainfo direct.
3. Fusion des sources, on conserve le parsing qui remplit le plus de champs non nuls.

Utile pour la correction en masse quand le fichier a été déplacé hors de la supervision de CineOrg.

### Renommage automatique du symlink

`_rename_symlink_if_needed()` : si le titre ou l'année changent suite à la réassociation, le symlink est renommé pour rester cohérent avec la nouvelle fiche :

```
ancien : /video/Films/Drame/B/Blade Runer (2017) FR x264 1080p.mkv
nouveau : /video/Films/Science-Fiction/B/Blade Runner 2049 (2017) FR x264 1080p.mkv
```

Le suffixe technique (codec, langue, résolution) est extrait par regex puis reconstruit après `{sanitize_title} ({year})`.

### Vérification de cohérence

**`src/services/association_checker.py`** offre des vérifications globales (invoquables depuis les commandes CLI de maintenance) pour détecter les associations suspectes : films sans durée, séries sans TVDB ID, incohérences de métadonnées.

## Cas limites

- **Extraction fichier source supprimé** — fallback sur nom de symlink (voir ci-dessus).
- **Cascade série sans candidats** — fallback par titre guessit (`_is_range_dir()` garde-fou pour exclure les noms composés type "Extra-Lucide" des plages alphabétiques).
- **Épisode 0 (E00)** — tests `is not None` au lieu de truthiness pour `season`/`episode`.
- **VOSTFR conditionnel** — `subtitle_language == FR` ET `audio_language != FR/Multi` → suffixe `VOSTFR` ajouté au nom de fichier.
- **`mul` → `Multi`** — normalisation guessit (pas `MUL`).
- **Distinction film vs série TV TMDB** — flag `is_tv` sur `MediaDetails`, source `tmdb_tv` propagée dans `SearchResult` → validation → `batch_builder`. `_get_details_from_source` et `_enrich_movie_metadata` appellent `get_tv_details()` / `get_tv_external_ids()` quand `source == "tmdb_tv"`.
- **Filet doublons post-batch** — détection/correction en fin de pipeline (pas en amont) pour attraper les cas non détectés par le matching initial.

---

Pour les autres sous-systèmes, voir :
- [docs/architecture.md](architecture.md) — architecture générale.
- [docs/hardlinks.md](hardlinks.md) — seeding via hardlinks.
