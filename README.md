# CineOrg

Application de gestion de vidéothèque personnelle. Scanne les téléchargements, identifie les contenus via TMDB/TVDB, renomme et organise les fichiers selon un format standardisé, et crée des symlinks pour le mediacenter.

> 📖 **Documentation détaillée** dans [`docs/`](docs/) :
> - [docs/architecture.md](docs/architecture.md) — Architecture hexagonale, DI, persistance, pipeline
> - [docs/association.md](docs/association.md) — Pipeline d'association et de réassociation TMDB/TVDB
> - [docs/hardlinks.md](docs/hardlinks.md) — Seeding via hardlinks et purge

## Table des matières

- [Installation](#installation)
- [Configuration](#configuration)
- [Architecture](#architecture)
  - [Modèle de stockage dual](#modèle-de-stockage-dual)
  - [Organisation des films](#organisation-des-films)
  - [Organisation des séries](#organisation-des-séries)
  - [Subdivision alphabétique](#subdivision-alphabétique)
- [Workflow de traitement](#workflow-de-traitement)
  - [Zone de staging](#zone-de-staging)
  - [Validation automatique et manuelle](#validation-automatique-et-manuelle)
  - [Détection des doublons](#détection-des-doublons)
  - [Hardlinks et seeding](#hardlinks-et-seeding)
  - [Sandbox des orphelins](#sandbox-des-orphelins)
- [Peupler la base de données séries](#peupler-la-base-de-données-séries)
- [Notes et évaluations](#notes-et-évaluations)
  - [Notes TMDB](#notes-tmdb)
  - [Notes IMDb](#notes-imdb)
- [Commandes](#commandes)
  - [Enrichissement](#enrichissement)
  - [Nettoyage et réorganisation](#nettoyage-et-réorganisation)
  - [Regroupement par préfixe de titre](#regroupement-par-préfixe-de-titre)
  - [Réparation des symlinks cassés](#réparation-des-symlinks-cassés)
  - [Ré-association des fiches sans fichier](#ré-association-des-fiches-sans-fichier)
  - [Consolidation des fichiers externes](#consolidation-des-fichiers-externes)
  - [Migration depuis anciens NAS](#migration-depuis-anciens-nas)
  - [Purge des hardlinks](#purge-des-hardlinks)
  - [Films multi-parties](#films-multi-parties)
  - [Surveillance de complétude des séries](#surveillance-de-complétude-des-séries)
- [Intégration Jellyfin](#intégration-jellyfin)
  - [Synchronisation Jellyfin](#synchronisation-jellyfin)
  - [Brancher Jellyfin](#brancher-jellyfin)
- [Format de nommage](#format-de-nommage)
- [Interface web](#interface-web)
  - [Lancement du serveur](#lancement-du-serveur)
  - [Tableau de bord](#tableau-de-bord)
  - [Bibliothèque](#bibliothèque)
  - [Filtres et recherche](#filtres-et-recherche)
  - [Fiches détaillées](#fiches-détaillées)
  - [Correction des associations TMDB](#correction-des-associations-tmdb)
  - [Lecteur vidéo intégré](#lecteur-vidéo-intégré)
  - [Traitement et validation](#traitement-et-validation)
  - [Transfert](#transfert)
  - [Qualité et doublons](#qualité-et-doublons)
  - [Corbeille](#corbeille)
  - [Fusion de fiches séries dupliquées](#fusion-de-fiches-séries-dupliquées)
  - [Maintenance](#maintenance)
  - [Configuration](#configuration-web)
- [Stack technique](#stack-technique)
- [Versioning & releases](#versioning--releases)

## Installation

```bash
# Cloner le projet
git clone <repo-url>
cd cine_org

# Installer avec uv
uv sync

# Vérifier l'installation
uv run cineorg --help
```

## Configuration

### Variables d'environnement

CineOrg se configure via des variables d'environnement préfixées par `CINEORG_`. Vous pouvez les définir dans un fichier `.env` à la racine du projet.

```bash
# Créer le fichier .env
cat > .env << 'EOF'
# === RÉPERTOIRES ===
# Répertoire des téléchargements (avec sous-dossiers Films/ et Series/)
CINEORG_DOWNLOADS_DIR=~/telechargements

# Répertoire de stockage physique des fichiers
CINEORG_STORAGE_DIR=~/Videos/stockage

# Répertoire des symlinks pour le mediacenter
CINEORG_VIDEO_DIR=~/Videos/video

# === BASE DE DONNÉES ===
CINEORG_DATABASE_URL=sqlite:///cineorg.db

# === CLÉS API (optionnelles mais recommandées) ===
# TMDB : https://www.themoviedb.org/settings/api
CINEORG_TMDB_API_KEY=votre_cle_tmdb

# TVDB : https://thetvdb.com/api-information
CINEORG_TVDB_API_KEY=votre_cle_tvdb

# === TRAITEMENT ===
# Taille minimum des fichiers en MB (ignore les petits fichiers)
CINEORG_MIN_FILE_SIZE_MB=100

# Seuil de score pour validation automatique (0-100)
CINEORG_MATCH_SCORE_THRESHOLD=85

# Nombre max de fichiers par sous-répertoire avant subdivision
CINEORG_MAX_FILES_PER_SUBDIR=50

# === LOGGING ===
CINEORG_LOG_LEVEL=INFO
CINEORG_LOG_FILE=logs/cineorg.log
EOF
```

### Paramètres disponibles

| Variable | Défaut | Description |
|----------|--------|-------------|
| `CINEORG_DOWNLOADS_DIR` | `~/Downloads` | Répertoire de téléchargements à scanner |
| `CINEORG_STORAGE_DIR` | `~/Videos/storage` | Stockage physique des fichiers organisés |
| `CINEORG_VIDEO_DIR` | `~/Videos/video` | Symlinks pour le mediacenter |
| `CINEORG_DATABASE_URL` | `sqlite:///cineorg.db` | URL de la base de données |
| `CINEORG_TMDB_API_KEY` | (vide) | Clé API TMDB pour les films |
| `CINEORG_TVDB_API_KEY` | (vide) | Clé API TVDB pour les séries |
| `CINEORG_MIN_FILE_SIZE_MB` | `100` | Taille minimum en MB |
| `CINEORG_MATCH_SCORE_THRESHOLD` | `85` | Seuil de validation auto (%) |
| `CINEORG_MAX_FILES_PER_SUBDIR` | `50` | Max fichiers par sous-dossier |
| `CINEORG_HARDLINK_RETENTION_DAYS` | `60` | TTL des hardlinks de seeding (jours) |
| `CINEORG_SANDBOX_DIR` | `{storage}/.sandbox` | Sandbox orphelins (même volume que storage) |
| `CINEORG_JELLYFIN_DIR` | `/media/Serveur/JellyfinLib` | Répertoire de l'arbre Jellyfin (symlinks + NFO) |
| `CINEORG_LOG_LEVEL` | `INFO` | Niveau de log (DEBUG, INFO, WARNING, ERROR) |

## Architecture

### Modèle de stockage dual

CineOrg utilise un modèle de **stockage dual** séparant les fichiers physiques des symlinks :

```
~/Videos/
├── storage/          # Fichiers physiques (ne bougent jamais)
│   ├── Films/
│   │   └── Genre/Subdivision/fichier.mkv
│   └── Séries/
│       └── Type/Subdivision/Titre (Année)/Saison XX/fichier.mkv
│
└── video/            # Symlinks (réorganisés librement)
    ├── Films/        # Miroir de storage/Films/
    └── Séries/       # Miroir de storage/Séries/
```

**Principe clé :** Le répertoire `video/` (symlinks) **dicte la structure visible** par le mediacenter. Lors des réorganisations (subdivision de répertoires trop peuplés), seuls les symlinks sont déplacés — les fichiers physiques restent en place dans `storage/`.

**Avantages :**
- Performances : pas de déplacement de gros fichiers lors des réorganisations
- Sécurité : les fichiers originaux ne sont jamais touchés après le premier transfert
- Flexibilité : structure du mediacenter modifiable sans impact sur le stockage

### Organisation des films

#### Structure : Films/Genre/[Subdivision]/

```
video/Films/
├── Animation/
│   ├── A-F/
│   │   ├── Akira (1988) FR DTS HEVC 1080p.mkv → ../../storage/...
│   │   └── ...
│   └── G-Z/
├── Science-Fiction/
│   ├── A-I/
│   │   ├── Avatar (2009) FR DTS-HD MA HEVC 2160p.mkv
│   │   └── Inception (2010) FR DTS H264 1080p.mkv
│   └── J-Z/
│       └── Matrix (1999) EN DTS H264 1080p.mkv
├── Action & Aventure/
│   └── ...
└── Drame/
    └── ...
```

#### Hiérarchie des genres

Quand un film appartient à plusieurs genres, le **premier genre correspondant dans la hiérarchie** est sélectionné :

1. Animation
2. Science-Fiction
3. Fantastique
4. Horreur
5. Action
6. Aventure
7. Comédie
8. Drame
9. Thriller
10. Crime
11. Guerre
12. Western
13. Romance
14. Musical
15. Documentaire
16. Famille
17. Histoire
18. Mystère
19. Téléfilm

Exemple : Un film "Action/Science-Fiction" sera classé dans **Science-Fiction** (priorité 2 > priorité 5).

#### Mapping des genres API

Les genres TMDB sont mappés vers des noms de dossiers français :

| Genre API | Dossier |
|-----------|---------|
| `action`, `aventure` | Action & Aventure |
| `science-fiction` | SF |
| `crime` | Policier |
| `animation` | Animation |

### Organisation des séries

#### Structure : Séries/{Type}/[Subdivision]/Titre (Année)/Saison XX/

```
video/Séries/
├── Séries TV/                    # Séries classiques
│   ├── A-M/
│   │   ├── Breaking Bad (2008)/
│   │   │   ├── Saison 01/
│   │   │   │   ├── Breaking Bad (2008) - S01E01 - Pilot - EN AAC H264 720p.mkv
│   │   │   │   └── ...
│   │   │   └── Saison 02/
│   │   └── Game of Thrones (2011)/
│   │       └── ...
│   └── N-Z/
│       └── ...
│
├── Animation/                    # Animation occidentale (Cartoon Network, etc.)
│   ├── A-F/
│   │   └── Avatar, le dernier maître de l'air (2005)/
│   └── ...
│
└── Mangas/                       # Anime japonais
    ├── A-H/
    │   ├── Attack on Titan (2013)/
    │   └── Death Note (2006)/
    └── I-Z/
        └── Naruto (2002)/
```

#### Classification par type

La classification se base sur les genres retournés par l'API TVDB :

| Genre TVDB | Type |
|------------|------|
| `anime` | **Mangas** (animation japonaise) |
| `animation` (sans `anime`) | **Animation** (occidentale) |
| Autres | **Séries TV** |

### Subdivision alphabétique

#### Tri alphabétique multilingue

Les articles sont **retirés du début des titres** pour le tri :

| Langue | Articles ignorés |
|--------|------------------|
| Français | le, la, les, l', un, une, des, de, du, au, aux |
| Anglais | the, a, an |
| Allemand | der, die, das, ein, eine |
| Espagnol | el, los, las |

Exemples :
- "The Matrix" → classé sous **M** (pas T)
- "L'Odyssée" → classé sous **O** (pas L)
- "Les Misérables" → classé sous **M**
- "De parfaites demoiselles" → classé sous **P** (pas D)
- "Du plomb dans la tête" → classé sous **P** (pas D)
- "Au service de la France" → classé sous **S** (pas A)

#### Création des subdivisions

Quand un répertoire dépasse `max_files_per_subdir` (50 par défaut), il est subdivisé :

| Contenu | Subdivision |
|---------|-------------|
| Peu de fichiers | Lettres simples : `A`, `B`, `C` |
| Plus de fichiers | Plages : `A-F`, `G-M`, `N-Z` |
| Beaucoup de fichiers | Préfixes : `Ba-Bi`, `Me-My`, `Sh-Sy` |

L'algorithme de subdivision :
- **Équilibre les groupes** : répartition homogène (pas de groupe résiduel de 9 items)
- **Couvre la plage parente** : un sous-répertoire `S-Z` produit des plages `Sa-Te` / `Ti-Zz`
- **Exclut les items hors plage** : un film mal classé (ex: Jadotville dans S-Z) est signalé séparément
- **Pas de chevauchement** : les coupures se font aux frontières de clés alphabétiques
- **Normalise les accents** : "Éternel" est trié entre D et F (pas après Z)
- **Format cohérent** : toujours `Start-End` (jamais une borne unique)

Caractère spécial `#` : pour les titres commençant par des chiffres ou symboles.

#### Sous-répertoires de préfixe de titre

En complément des plages alphabétiques, CineOrg reconnaît les **sous-répertoires de regroupement par préfixe de titre**. Quand plusieurs films partagent le même premier mot (après suppression de l'article), ils peuvent être regroupés dans un sous-répertoire portant ce préfixe.

```
video/Films/Drame/A-Ami/
├── American/                      # Préfixe de titre
│   ├── American Beauty (1999) MULTi HEVC 1080p.mkv
│   ├── American History X (1998) MULTi HEVC 1080p.mkv
│   └── American Son (2019) MULTi x264 1080p.mkv
├── Amant/                         # Regroupe L'Amant, Les Amants, etc.
│   ├── L'Amant (1992) FR HEVC 1080p.mkv
│   └── Les Amants (1958) FR HEVC 1080p.mkv
└── Amadeus (1984) MULTi HEVC 1080p.mkv
```

La navigation récursive reconnaît automatiquement ces répertoires : un nouveau film "American Gangster" sera correctement dirigé vers `A-Ami/American/`.

La commande `regroup` (voir ci-dessous) permet de détecter les préfixes récurrents et de créer ces regroupements automatiquement.

## Workflow de traitement

### Flux de données

```
Téléchargements/
    Films/ ou Series/
         └── [fichiers vidéo]
              ↓
         Scanner (taille, extensions, patterns ignorés, st_nlink > 1)
              ↓
         Parser (guessit + mediainfo)
         (titre, année, épisode, codecs, langues, durée)
              ↓
         Matcher (recherche TMDB/TVDB, cache série, scoring)
              ↓
         Validation
              ├─ Score ≥ 85% ET candidat unique → AUTO-VALIDATION
              └─ Sinon → STAGING (validation manuelle requise)
              ↓
         Détection doublons pré-transfert (résolution dialog)
              ↓
         Transfert atomique
              ├─ Déplacement → storage/
              ├─ Création symlink → video/
              └─ Hardlink seeding downloads/ ↔ storage/ (non bloquant cross-device)
              ↓
         Enrichissement (collections, notes, IMDb IDs, credits…)
              ↓
         Bibliothèque organisée
```

> 📖 Détail complet du pipeline : [docs/association.md](docs/association.md).

### Zone de staging

La zone de staging est un **espace temporaire** pour les fichiers nécessitant une validation utilisateur.

#### Quand un fichier va en staging

- Score de correspondance < 85 %.
- Plusieurs candidats au-dessus du seuil (ambiguïté à trancher manuellement).
- Aucun candidat trouvé.

#### Commandes staging

```bash
# Voir les fichiers en attente
uv run cineorg pending

# Valider manuellement
uv run cineorg validate manual
```

### Validation automatique et manuelle

#### Seuils d'auto-validation

| Condition | Action |
|-----------|--------|
| Score ≥ 85 % **ET** candidat unique | Auto-validation |
| Plusieurs candidats au-dessus du seuil | Validation manuelle (ambiguïté) |
| Aucun candidat / score < 85 % | Validation manuelle |

#### Formule de scoring

**Films :**
```
Avec durée disponible :
  Score = 50% × titre + 25% × année + 25% × durée

Sans durée (fallback) :
  Score = 67% × titre + 33% × année

Où :
- titre : token_sort_ratio avec normalisation accents/ligatures, bilingue (localisé ET original)
- année : 1.0 si exact, 0.5 si ±1 an, 0 au-delà
- durée : 1.0 si ±10%, 0.5 si ±20%, 0 au-delà
```

**Séries :**
```
Score = 100% × titre (avec filtrage par nombre d'épisodes compatible)
```

#### Matching bilingue

Pour les films, le système compare le titre recherché avec **le titre localisé ET le titre original**, gardant le meilleur score. Cela gère les cas comme :
- Recherche "Kill Bill" → Candidat "Kill Bill Vol. 1" (japonais : "キル・ビル")

### Détection des doublons

La détection des doublons est effectuée **avant** le transfert. Un dialogue overlay dans le résumé batch propose une décision pour chaque conflit, avec cascade par série.

**Critères de détection** :

- Titre normalisé (articles Le/La/The/A ignorés, accents retirés, ponctuation).
- Année exacte.
- Pour les séries : saison + épisode déjà présents en DB (les saisons partielles sont respectées).

**Cascade série** : si plusieurs épisodes d'une même série (titre + année) sont en doublon, la décision prise sur un épisode s'applique automatiquement à tout le groupe.

**Scoring qualité** (pour aider la décision keep-new / keep-old) :

| Critère | Poids |
|---------|------:|
| Résolution | 25 % |
| Codec vidéo | 20 % |
| Bitrate vidéo (normalisé par codec) | 25 % |
| Codec audio | 15 % |
| Bitrate audio | 15 % |

Normalisation bitrate par codec : AV1 × 3.0, HEVC × 2.0, VP9 × 1.8, x264 × 1.0 — comparaison équitable entre un x264 8 Mbps et un HEVC 4 Mbps.

**Décisions disponibles** :

- `keep_new` — remplacer l'existant par le nouveau fichier.
- `keep_old` — skip le nouveau (reste en `downloads/`).
- `keep_old + corbeille` — skip le nouveau **et** déplacer la source dans `.trash/` (évite qu'elle soit re-détectée à chaque workflow ; le dossier parent vidé est nettoyé).
- `sandbox` — déplacer le nouveau dans `.sandbox/` pour décision ultérieure.

Le bouton de transfert reste **grisé** tant que tous les conflits ne sont pas tranchés.

### Hardlinks et seeding

Pour préserver le seeding BitTorrent après transfert, CineOrg crée un **hardlink** dans `downloads/` pointant vers le nouveau fichier dans `storage/`. Le client torrent voit toujours le fichier à son chemin d'origine, sans doubler l'occupation disque.

- **TTL configurable** via `CINEORG_HARDLINK_RETENTION_DAYS` (défaut : 60 jours).
- **Cross-device** géré : si `downloads/` et `storage/` sont sur des volumes différents, la création échoue silencieusement sans interrompre le transfert.
- **Purge quotidienne** via un timer systemd (fichiers dans `deploy/`).
- **Re-scan évité** : le scanner ignore les fichiers avec `st_nlink > 1`.

> 📖 Installation du timer et détails : [docs/hardlinks.md](docs/hardlinks.md).

### Sandbox des orphelins

Les **orphelins** (fichiers physiques sans symlink les référençant) peuvent être déplacés vers un répertoire `.sandbox/` (sur le même volume que `storage/` pour éviter les copies réseau) avant suppression ou réinjection :

- Détection via comparaison storage ↔ symlinks.
- Déplacement non destructif (l'arborescence d'origine est préservée dans la sandbox).
- Réinjection possible via le workflow (scan → match → transfer) pour les fichiers valables.

## Notes et évaluations

CineOrg peut enrichir votre vidéothèque avec les notes et évaluations des films et séries depuis deux sources complémentaires.

### Notes TMDB

Les notes TMDB (`vote_average` et `vote_count`) sont automatiquement récupérées :
- **pour les films** : lors de la validation, via l'API TMDB ;
- **pour les séries** : lors du transfert d'un nouvel épisode (pont TVDB → TMDB par recherche titre+année) puis également lors de la commande `enrich-series` pour les séries déjà présentes en base.

Pour enrichir les films existants qui n'ont pas encore leurs notes :

```bash
# Enrichir les 100 premiers films sans notes
uv run cineorg enrich-ratings

# Enrichir un nombre spécifique de films
uv run cineorg enrich-ratings --limit 500
```

Pour enrichir les séries existantes (poster + notes TMDB + IMDb + créateurs + casting) :

```bash
# Enrichir les séries dont le poster, vote_average ou director est manquant
uv run cineorg enrich-series

# Forcer le re-enrichissement de toutes les séries
uv run cineorg enrich-series --force --limit 200
```

`enrich-series` lit aussi le cache IMDb local (s'il a été importé via `imdb import`) pour peupler `imdb_rating` et `imdb_votes` directement après avoir récupéré l'`imdb_id` via TMDB — pas besoin de relancer `imdb sync` derrière.

**Note** : Ces commandes utilisent l'API TMDB et respectent le rate limiting (0.25 s entre chaque appel pour les films, 0.3 s pour les séries).

### Notes IMDb

CineOrg peut également importer les notes IMDb depuis les [datasets publics IMDb](https://www.imdb.com/interfaces/). Ces datasets contiennent les notes de millions de titres et sont mis à jour quotidiennement.

#### Importer les notes IMDb

```bash
# Télécharger et importer le dataset title.ratings (~6 Mo compressé)
uv run cineorg imdb import

# Forcer le re-téléchargement même si le fichier est récent
uv run cineorg imdb import --force
```

Le fichier est téléchargé dans `.cache/imdb/` et importé dans la table `imdb_ratings` de la base de données locale. L'import ne sera refait que si le fichier a plus de 7 jours.

#### Synchroniser avec les films et les séries

Une fois les notes IMDb importées, vous pouvez les associer aux films **et aux séries** de votre vidéothèque :

```bash
# Synchroniser films + séries ayant un imdb_id mais pas de note IMDb (défaut)
uv run cineorg imdb sync

# Limiter le nombre d'entrées à synchroniser (par cible)
uv run cineorg imdb sync --limit 50

# Cibler uniquement les films
uv run cineorg imdb sync --target movies

# Cibler uniquement les séries
uv run cineorg imdb sync --target series
```

**Prérequis** : Les entrées doivent avoir un `imdb_id` en base. Pour les films, il est récupéré via `/movie/{id}/external_ids` de TMDB lors de l'enrichissement. Pour les séries, il est récupéré soit lors du transfert d'un nouvel épisode (workflow), soit via `enrich-series` (qui lit aussi le cache IMDb dans la foulée).

#### Statistiques du cache IMDb

```bash
# Afficher le nombre d'enregistrements et la date de dernière mise à jour
uv run cineorg imdb stats
```

**Avantages de l'approche IMDb :**
- **Aucun appel API** : Les notes sont stockées localement
- **Très rapide** : Lookup instantané par ID
- **Complet** : Le dataset contient ~1.3 million de titres avec notes

## Commandes

### Afficher la configuration

```bash
uv run cineorg info
```

### Traiter les nouveaux téléchargements

```bash
# Scanner et traiter tous les fichiers
uv run cineorg process

# Traiter uniquement les films
uv run cineorg process --filter movies

# Traiter uniquement les séries
uv run cineorg process --filter series

# Mode simulation (sans modification)
uv run cineorg process --dry-run
```

### Gestion des validations

```bash
# Voir les fichiers en attente
uv run cineorg pending

# Validation interactive (un par un)
uv run cineorg validate manual

# Valider un fichier spécifique par son ID
uv run cineorg validate file <ID>

# Auto-valider tous les fichiers éligibles
uv run cineorg validate auto

# Afficher et exécuter le batch de transferts
uv run cineorg validate batch
```

Lors de la validation manuelle, vous pouvez :
- Sélectionner un candidat proposé (avec synopsis, réalisateur, acteurs)
- Rechercher manuellement par titre
- Entrer un ID IMDB/TMDB/TVDB directement
- Passer le fichier pour plus tard
- Marquer comme "corbeille"

### Importer une vidéothèque existante

```bash
# Importer depuis le répertoire configuré
uv run cineorg import

# Importer depuis un répertoire spécifique
uv run cineorg import /chemin/vers/videotheque

# Mode simulation
uv run cineorg import --dry-run
```

### Peupler la base de données séries

La commande `populate-series` scanne les symlinks dans `video/Séries/` pour créer les entrées séries et épisodes en base de données. Les cibles des symlinks sont résolues pour stocker le chemin physique (`file_path`) de chaque épisode.

```bash
# Simulation (affiche ce qui serait créé sans modifier la base)
uv run cineorg populate-series --dry-run

# Peupler depuis le video_dir configuré
uv run cineorg populate-series

# Peupler depuis un répertoire spécifique
uv run cineorg populate-series /chemin/vers/video

# Limiter à 50 séries (utile pour tester)
uv run cineorg populate-series --limit 50
```

**Fonctionnement :**

1. **Découverte** : Parcourt récursivement `video/Séries/` (toutes catégories : Séries TV, Animation, Mangas, etc.) et détecte les dossiers contenant un sous-dossier `Saison XX`.

2. **Parsing** : Extrait le titre et l'année depuis le nom du dossier série (ex: `Breaking Bad (2008)` → titre "Breaking Bad", année 2008). Les dossiers sans année sont acceptés.

3. **Épisodes** : Pour chaque fichier vidéo dans les `Saison XX/`, parse le pattern `SxxExx` et le titre d'épisode (format CineOrg : `Titre - S01E01 - Titre Episode - MULTi ...`).

4. **Déduplication** : Vérifie l'existence en base par titre+année (séries) et series_id+saison+épisode (épisodes) avant insertion.

**Note** : Cette commande ne fait aucun appel API. L'enrichissement TVDB pourra être fait séparément, comme `enrich-ratings` pour les films.

### Enrichissement

Après un import, enrichir les fichiers avec les métadonnées API. Chaque commande est indépendante et peut être relancée sans effet de bord :

```bash
# Recherche TMDB/TVDB pour associer les films/séries sans ID API
uv run cineorg enrich

# Notes TMDB (vote_average, vote_count)
uv run cineorg enrich-ratings --limit 100

# IMDb IDs (via /movie/{id}/external_ids TMDB)
uv run cineorg enrich-imdb-ids

# Collections TMDB (saga, franchise)
uv run cineorg enrich-collections

# Credits des films (réalisateur, casting)
uv run cineorg enrich-movies-credits

# Enrichissement complet des séries (poster, genres, créateurs, casting)
uv run cineorg enrich-series

# TVDB IDs pour les séries déjà en DB
uv run cineorg enrich-tvdb-ids

# Titres des épisodes via TVDB
uv run cineorg enrich-episode-titles

# Métadonnées techniques (résolution, codecs, langues) via mediainfo
uv run cineorg enrich-tech
```

Toutes les commandes acceptent `--limit N` pour limiter le nombre d'éléments traités (utile pour respecter les quotas API ou tester). Le rate limiting TMDB est de 0.25 s entre appels (4 req/s), et 0.3 s pour les séries TMDB.

### Gestion des notes IMDb

```bash
# Télécharger et importer les notes IMDb
uv run cineorg imdb import

# Synchroniser les notes avec les films et les séries en base
uv run cineorg imdb sync

# Afficher les statistiques du cache IMDb
uv run cineorg imdb stats
```

Voir la section [Notes IMDb](#notes-imdb) pour plus de détails.

### Maintenance

```bash
# Vérifier l'intégrité de la vidéothèque
uv run cineorg check

# Vérifier avec validation des hash (plus lent)
uv run cineorg check --verify-hash

# Rapport au format JSON
uv run cineorg check --json
```

### Nettoyage et réorganisation

La commande `cleanup` détecte et corrige tous les problèmes structurels du répertoire `video/` en une seule passe : symlinks cassés, symlinks mal placés (mauvais genre/subdivision), répertoires surchargés non subdivisés, et répertoires vides résiduels.

**Scope :** Seuls les symlinks dans `video/` sont affectés — les fichiers physiques dans `storage/` ne sont jamais touchés.

```bash
# Analyser sans modifier (rapport uniquement)
uv run cineorg cleanup

# Analyser un répertoire spécifique
uv run cineorg cleanup /chemin/vers/video

# Exécuter les corrections
uv run cineorg cleanup --fix

# Exécuter sans réparer les symlinks cassés
uv run cineorg cleanup --fix --skip-repair

# Exécuter sans subdiviser les répertoires surchargés
uv run cineorg cleanup --fix --skip-subdivide

# Ajuster le score minimum pour l'auto-réparation (défaut: 90%)
uv run cineorg cleanup --fix --min-score 85
```

**Étapes du nettoyage :**

1. **Symlinks cassés** : Détection via l'index de fichiers et réparation automatique si un candidat est trouvé avec un score suffisant (≥ 90% par défaut).

2. **Symlinks mal placés** : Pour chaque symlink valide, le chemin attendu est recalculé à partir des métadonnées en base (genre du film, type de série). Si le symlink est dans le mauvais répertoire, il est déplacé et la base de données est mise à jour.

3. **Répertoires surchargés** : Les répertoires contenant plus de 50 symlinks sont automatiquement subdivisés en plages alphabétiques (ex: `Aa-Am`, `An-Az`). Les articles (Le, La, The...) sont ignorés pour le tri.

4. **Répertoires vides** : Suppression bottom-up des répertoires vides laissés après les déplacements.

**Exemple de rapport :**

```
        Rapport de nettoyage
┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━┓
┃ Catégorie              ┃ Nombre ┃ Détails       ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━┩
│ Symlinks cassés        │      3 │ 2 réparables  │
│ Symlinks mal placés    │      5 │               │
│ Répertoires surchargés │      1 │ Action (67)   │
│ Répertoires vides      │      8 │               │
└────────────────────────┴────────┴───────────────┘

Pour corriger : cineorg cleanup --fix
```

### Regroupement par préfixe de titre

La commande `regroup` analyse les répertoires de symlinks pour détecter les fichiers partageant un préfixe de titre récurrent, puis les regroupe dans des sous-répertoires dédiés.

```bash
# Analyser les préfixes récurrents (mode dry-run avec arborescence projetée)
uv run cineorg regroup

# Analyser un répertoire spécifique
uv run cineorg regroup /chemin/vers/video

# Ajuster le seuil minimum de fichiers par groupe (défaut: 3)
uv run cineorg regroup --min-count 4

# Exécuter les regroupements (crée les sous-répertoires et déplace les fichiers)
uv run cineorg regroup --fix

# Spécifier le répertoire storage correspondant
uv run cineorg regroup --fix --storage-dir /chemin/vers/storage
```

**Fonctionnement :**

1. **Scan récursif** : Parcourt tous les répertoires contenant des fichiers médias.

2. **Extraction des préfixes** : Pour chaque fichier, le titre est extrait (avant l'année entre parenthèses), l'article est retiré, et le premier mot est utilisé comme clé de regroupement.

3. **Fusion des variantes** : Les clés partageant un préfixe commun de 4+ caractères sont fusionnées sous le préfixe le plus court. Par exemple : "Amant", "Amants", "Amante" → regroupés sous "Amant".

4. **Filtrage** : Seuls les groupes atteignant le seuil minimum (3 fichiers par défaut) sont proposés. Les fichiers déjà dans un sous-répertoire de préfixe sont ignorés.

**Exemple de sortie (mode analyse) :**

```
Modifications projetees dans Films/Drame/A-Ami/ :
  Films/Drame/A-Ami/
  ├── American/ (nouveau)
  │   ├── American Beauty (1999) MULTi HEVC 1080p.mkv <- deplace
  │   ├── American History X (1998) MULTi HEVC 1080p.mkv <- deplace
  │   ├── American Son (2019) MULTi x264 1080p.mkv <- deplace
  │   └── American Translation (2011) FR HEVC 1080p.mkv <- deplace
  └── Amant/ (nouveau)
      ├── L'Amant (1992) FR HEVC 1080p.mkv <- deplace
      ├── L'Amante (2020) FR HEVC 1080p.mkv <- deplace
      └── Les Amants (1958) FR HEVC 1080p.mkv <- deplace

Total: 2 groupe(s), 7 fichier(s) a deplacer

Pour executer : cineorg regroup --fix
```

**Scope :** En mode `--fix`, les fichiers sont déplacés dans `video/` (symlinks) **et** dans `storage/` (fichiers physiques). Les symlinks sont recréés pour pointer vers le nouvel emplacement dans storage.

### Réparation des symlinks cassés

La commande `repair-links` détecte les symlinks cassés dans `video/` et recherche automatiquement les fichiers correspondants dans `storage/` grâce à une recherche floue intelligente.

```bash
# Scanner tout video/ en mode interactif
uv run cineorg repair-links

# Scanner un répertoire spécifique
uv run cineorg repair-links /chemin/vers/Films/Drame

# Mode automatique : répare si score >= 90%
uv run cineorg repair-links --auto

# Mode simulation (sans modification)
uv run cineorg repair-links --auto --dry-run

# Ajuster le score minimum de recherche (défaut: 50%)
uv run cineorg repair-links --min-score 60
```

**Fonctionnement :**

1. **Indexation** : Au premier lancement, un index des fichiers vidéo est construit et mis en cache (`~/.cineorg/file_index.json`). Le cache est valide 24h.

2. **Recherche progressive** : Pour chaque symlink cassé, la recherche se fait d'abord dans le même genre, puis le même type (Films/Séries), puis toute la base.

3. **Scoring** : La similarité est calculée en comparant les titres (extraction du titre et de l'année, suppression des infos techniques).

4. **Affichage** :
   - `✓` vert : symlink réparé avec succès
   - `✗` rouge : aucun candidat trouvé
   - `~` jaune : candidat trouvé mais score insuffisant

**Mode interactif** : Sans `--auto`, chaque symlink est présenté avec ses candidats et vous pouvez choisir l'action (réparer, supprimer, ignorer).

### Ré-association des fiches sans fichier

`repair-links` part des symlinks cassés ; `relink-movies` part de l'autre bout : les **fiches films en base sans `file_path`/`symlink_path`** (import d'une vidéothèque, matching incomplet) dont le fichier existe pourtant sur le disque. Ces fiches apparaissent dans le filtre web « Sans fichier ». La commande retrouve le fichier et renseigne la base.

```bash
# Simulation (lecture seule, par défaut)
uv run cineorg relink-movies

# Appliquer les liens sûrs
uv run cineorg relink-movies --execute

# Ajuster le seuil canonique d'auto-liaison (défaut : 85)
uv run cineorg relink-movies --execute --min-score 90

# Liens sûrs PUIS revue interactive des cas litigieux (implique l'exécution)
uv run cineorg relink-movies --suggest
```

**Fonctionnement :**

1. **Tier 1 — `video/`** : si un symlink formaté existe déjà pour le titre + année, il est réutilisé tel quel (`file_path` = sa cible, `symlink_path` = le symlink).

2. **Tier 2 — `storage/`** : sinon, recherche floue du fichier physique en utilisant le **titre localisé, le titre original et les titres alternatifs (AKA)** récupérés via TMDB (utile pour les films rangés sous leur titre international, ex. « Ukryta gra » → « The Coldest Game »). Chaque candidat est scoré avec la formule canonique du workflow `process` (**titre 50 % + année 25 % + durée 25 %**) et n'est lié qu'au-dessus du seuil (85 par défaut). Un symlink au nom canonique est alors créé à la bonne destination ; le fichier physique brut n'est pas renommé (voir `rename-canonical` pour cela).

   Le **garde-fou durée** écarte automatiquement les featurettes (« making-of » bien plus court que le film) et les mauvais films de même année.

3. **Coquilles vides** : les fiches dont aucun fichier n'est trouvé restent intactes (supprimables via le bouton « fiche fantôme » de l'interface web).

**Mode `--suggest`** : après application des liens sûrs (non proposés), chaque fiche restante est présentée en interactif avec les candidats de la bande litigieuse (score 60-85). Pour chaque fiche :

- `<n>` — lier au candidat numéro *n* ;
- `v<n>` — **visionner** le candidat *n* via mpv (lecteur configuré) pour vérifier à l'écran ;
- `t` — saisir un **titre manuel** : relance la recherche storage **sans garde-fou** (classée par similarité de titre), pour les fichiers au nom corrompu (ex. un recut « Inversion intégrale » d'année différente) ;
- `Entrée` — passer ; `q` — quitter.

> ⚠️ `--suggest` implique l'exécution : les liens sûrs **et** les choix manuels sont écrits en base.

### Consolidation des fichiers externes

Si certains symlinks dans `storage/` pointent vers des volumes externes (NAS secondaire, disque USB), la commande `consolidate` permet de rapatrier ces fichiers dans le stockage principal.

```bash
# Lister les symlinks vers des volumes externes
uv run cineorg consolidate

# Scanner un répertoire spécifique
uv run cineorg consolidate /chemin/vers/storage/Films

# Rapatrier les fichiers accessibles
uv run cineorg consolidate --execute

# Mode simulation
uv run cineorg consolidate --execute --dry-run
```

**Cas d'usage** : Vous avez déplacé des fichiers sur un NAS externe pour libérer de l'espace. Plus tard, vous voulez les récupérer sur le stockage principal.

### Renommage canonique

La commande `rename-canonical` renomme les fichiers physiques et les symlinks selon le titre canonique stocké en base. Utile après l'import d'une vidéothèque existante ou quand des fichiers ont gardé leur nom de release scene malgré une association TMDB correcte.

```bash
# Dry-run sur un film précis
uv run cineorg rename-canonical --movie-id 84

# Dry-run depuis un cache de scan d'associations suspectes (page /quality/suspicious)
uv run cineorg rename-canonical --from-cache logs/quality_scan_cache.json --limit 50

# Exécution réelle
uv run cineorg rename-canonical --from-cache logs/quality_scan_cache.json --execute --limit 50
```

**Fonctionnement** :

1. Charge chaque `MovieModel` cible et son fichier physique.
2. Extrait les métadonnées techniques via mediainfo.
3. Génère le nom cible via `RenamerService` (format standardisé).
4. Compare avec le nom actuel — skip si identique.
5. Vérifie l'absence de conflit à la destination.
6. En mode `--execute` : `os.rename()` dans `storage/`, recrée le symlink `video/`, met à jour `file_path`/`symlink_path` en DB.

**Préservation du seeding** : `os.rename()` conserve l'inode, donc les hardlinks dans `downloads/` (voir section [Hardlinks et seeding](#hardlinks-et-seeding)) restent valides et le client torrent continue de servir le fichier.

**Sortie** : table Rich listant pour chaque film son statut (`renamed` / `already_canonical` / `conflict` / `file_missing` / `error`) avec le nom actuel et le nom cible.

### Migration depuis anciens NAS

La sous-commande `migrate-nas` migre des fichiers vidéo depuis d'anciens volumes (vieux NAS, disques USB) vers le nouveau NAS, en filtrant par note minimale combinée IMDb / TMDB / personnelle. Elle préserve la source (pas de `--remove-source-files`), vérifie l'intégrité xxh3_64 source/destination après chaque copie, et swappe atomiquement les symlinks vers la nouvelle destination.

**Trois étapes séparées** :

```bash
# 1. Construire le plan (lecture seule)
uv run cineorg migrate-nas plan \
    --source /mnt/old_nas/Vidéos \
    --output ./migration/plan.json \
    --csv-dir ./migration/review \
    --threshold 6.0

# 2. Exécuter les transferts (reprenable)
uv run cineorg migrate-nas apply ./migration/plan.json

# 3. Suivre l'avancement
uv run cineorg migrate-nas status ./migration/plan.json
```

**Phase plan** : parcourt l'arborescence source (symlinks ou fichiers physiques), parse chaque nom de fichier via guessit, recherche l'œuvre en base CineOrg et calcule sa note retenue selon `max(imdb_rating, vote_average, personal_rating × 2)`. Chaque fichier est classé dans un *bucket* :

| Bucket | Sens |
|---|---|
| `MIGRATE` | Note ≥ seuil et destination calculable — sera transféré. |
| `LOW_RATED` | Note < seuil — ignoré (à revoir manuellement). |
| `UNRATED` | Œuvre absente de la base ou aucune note — ignoré. |
| `BROKEN` | Symlink brisé même après recherche dans `--alt-root`. |
| `ALREADY_ON_DESTINATION` | Cible déjà sur le nouveau NAS — rien à faire. |
| `NOT_SYMLINK` | Fichier physique trouvé dans la source — signalé. |

Le plan est écrit en JSON (versionné, désérialisable) et accompagné de trois CSV de revue (`low_rated.csv` / `unrated.csv` / `broken.csv`) listant `symlink_path`, note, source de la note, et titre matché.

**Phase apply** : pour chaque item `MIGRATE` non encore `COMMITTED` dans le state store, lance `rsync -a --partial --inplace --bwlimit=NM` avec retry sur paliers de bande passante (par défaut **25 → 20 → 15 → 10 → 5 MB/s**). Vérifie ensuite le hash xxh3_64 source/destination ; en cas de mismatch, la destination est supprimée et la source reste intacte. Si OK, le symlink est swappé via `os.symlink` + `os.replace` (atomique sur même filesystem) et l'item est marqué `COMMITTED`.

Le state store est un journal SQLite local (par défaut `<plan>.json.state.sqlite`) qui suit chaque item via les statuts `PENDING` → `COPYING` → `COPIED` → `VERIFIED` → `COMMITTED` (ou `FAILED_COPY` / `FAILED_VERIFY` / `FAILED_OTHER`). Une exécution interrompue peut être relancée : seuls les items non `COMMITTED` sont retraités, et les items dont la destination existe déjà avec le bon hash sont finalisés sans re-rsync.

**Options principales** :

- `--source PATH` : racine de scan (anciens NAS montés en lecture).
- `--output PATH` : chemin du plan JSON.
- `--csv-dir PATH` : répertoire des CSV de revue (omis = pas de CSV).
- `--alt-root PATH` (multi) : racines alternatives où retrouver les cibles brisées (utile quand un fichier physique a été déplacé sur un autre disque).
- `--threshold FLOAT` : note minimale (échelle 0-10), défaut `6.0`.
- `--state-store PATH` (apply / status) : journal SQLite custom.

**Sécurité** : `apply` n'efface jamais la source. Le réordonnancement se fait uniquement par swap des symlinks. La suppression effective de la source relève d'une étape ultérieure (post-validation), hors du périmètre de cette commande.

### Purge des hardlinks

La commande `purge-hardlinks` supprime les hardlinks de seeding expirés (TTL `CINEORG_HARDLINK_RETENTION_DAYS`, défaut 60 jours). Elle est généralement déclenchée automatiquement par un timer systemd, mais peut être lancée manuellement :

```bash
# Purger les hardlinks expirés
uv run cineorg purge-hardlinks

# Simulation (aucune modification)
uv run cineorg purge-hardlinks --dry-run

# Forcer la purge de tous les hardlinks (ignore expires_at)
uv run cineorg purge-hardlinks --force
```

Les fichiers physiques dans `storage/` ne sont **jamais** touchés. Seul le hardlink dans `downloads/` est supprimé, et les dossiers parents vides sont nettoyés ascendant jusqu'à `downloads_dir`.

**Installation du timer systemd** (purge quotidienne automatique) :

```bash
sudo cp deploy/cineorg-purge.service /etc/systemd/system/
sudo cp deploy/cineorg-purge.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cineorg-purge.timer
```

> 📖 Détails et diagnostic : [docs/hardlinks.md](docs/hardlinks.md).

### Films multi-parties

Certains films rares sont distribués en plusieurs parties indépendantes (ex. : *Nos meilleures années*, *Docteur Mabuse le joueur*). CineOrg les gère comme une **fiche unique** : lors du transfert, la Partie 1 reste attachée à la fiche film principale tandis que les parties suivantes (Partie 2, Partie 3…) sont enregistrées dans la table `movie_parts`, liées à la même fiche par leur `movie_id`.

**Dans l'interface web**, la fiche film affiche un bloc **Parties** listant chaque partie avec son nom de fichier et un bouton de lecture individuel. Le bouton **Visionner** en tête de fiche lance toujours la Partie 1.

**Au transfert**, la détection est automatique : si plusieurs fichiers d'un même lot partagent un titre identique et portent un suffixe `Partie N`, la plus petite partie devient le fichier principal et les autres sont annotées `movie_part_number` dans le batch avant d'être enregistrées comme `MoviePart`.

**Rattacher des parties déjà transférées** (films traités avant l'activation de cette fonctionnalité) :

```bash
# Rapport : liste les symlinks « Partie N » (N >= 2) sans entrée en base
uv run python -m src.main link-movie-parts

# Écriture : crée les lignes MoviePart manquantes
uv run python -m src.main link-movie-parts --apply
```

La commande `link-movie-parts` parcourt la zone `video/` à la recherche de symlinks contenant `Partie N` (N ≥ 2), retrouve le film propriétaire via son symlink de Partie 1, et crée les enregistrements `MoviePart` manquants. **Le storage n'est jamais modifié.** La commande est idempotente : une partie déjà enregistrée est ignorée.

### Surveillance de complétude des séries

**Objectif** : détecter les séries **incomplètes** — celles dont il manque des épisodes ou des saisons déjà diffusés, suite à un téléchargement raté/interrompu ou à la perte d'un fichier. La vérification compare la liste des épisodes attendus (déjà diffusés) à ceux réellement présents en vidéothèque.

**Critère d'incomplétude** : une série est considérée incomplète s'il lui manque **au moins un épisode dont la date de diffusion est déjà passée**. Le statut « en cours / terminée » renvoyé par TMDB n'est **pas** utilisé (jugé peu fiable). Sont exclus du décompte :

- la **saison 0** (spéciaux, hors-séries) ;
- les épisodes numérotés `SxxE00` (pilotes, récaps) ;
- les épisodes **hors-canon** (marqués `is_extra`) ;
- les épisodes **non encore diffusés** (date de diffusion future ou absente).

**Source des données** : **TVDB uniquement** en V1. Les séries sans `tvdb_id` ne sont pas évaluées et reçoivent le statut **« non vérifiable »**.

**Usage CLI :**

```bash
# Vérifier la complétude de toutes les séries
uv run python -m src.main check-completeness

# Vérifier une seule série par son ID
uv run python -m src.main check-completeness --series-id <ID>
```

**Usage web** — un bouton **« Vérifier la complétude »** est disponible sur la page **Maintenance**. Il lance une vérification par lots de toutes les séries avec une barre de progression en temps réel (SSE). Le récapitulatif final propose un lien direct vers les séries incomplètes dans la bibliothèque.

**Recalcul automatique après transfert** : la complétude des séries est **recalculée automatiquement en fin de transfert**. Compléter une série incomplète (télécharger ses épisodes manquants et les transférer) met le verdict à jour sans action manuelle. La commande `check-completeness` et la maintenance web restent disponibles pour un recalcul global.

**Filtre & badge dans la bibliothèque** :

- deux cases indépendantes affinent la grille :
  - **« Épisodes manquants »** (`missing_episodes=1`) — séries dont au moins une saison détenue a des trous (épisodes déjà diffusés absents) ;
  - **« Saisons manquantes »** (`missing_seasons=1`) — séries dont au moins une saison entière est absente.

  Cocher les deux affiche l'**union** de toutes les séries incomplètes (c'est la cible du lien « Voir les séries incomplètes » du récapitulatif de maintenance). La complétude est calculée via la commande `check-completeness` ou le bouton **« Vérifier la complétude »** de la page Maintenance (confrontation aux épisodes TVDB déjà diffusés).
- un **badge ambre « Incomplet »** apparaît sur les cartes et la fiche des séries concernées ;
- la **fiche série** détaille les saisons et épisodes manquants (numéro, titre, date de diffusion).

**Limite connue (V1)** : seules les séries disposant d'un `tvdb_id` sont évaluées. Un repli sur TMDB est prévu ultérieurement pour couvrir les séries sans identifiant TVDB.

## Intégration Jellyfin

CineOrg peut générer un arbre de symlinks dédié à Jellyfin, accompagné de fichiers de métadonnées NFO, pour que le mediacenter identifie chaque film et chaque série de façon fiable sans requête réseau.

### Synchronisation Jellyfin

La commande `jellyfin-sync` génère un **arbre de symlinks dédié** ainsi que des fichiers **NFO** (métadonnées XML) à partir de la base CineOrg. Jellyfin lit les IDs TMDB/TVDB/IMDb directement dans les NFO — sans deviner, sans série zappée.

**Répertoire cible** : variable d'environnement `CINEORG_JELLYFIN_DIR` (défaut : `/media/Serveur/JellyfinLib`).

```bash
# Générer l'arbre Jellyfin complet (films + séries)
uv run cineorg jellyfin-sync

# Simuler sans écrire aucun fichier
uv run cineorg jellyfin-sync --dry-run

# Films uniquement
uv run cineorg jellyfin-sync --movies-only

# Séries uniquement
uv run cineorg jellyfin-sync --series-only

# Supprimer de l'arbre Jellyfin les entrées absentes de la base
uv run cineorg jellyfin-sync --prune
```

**Options :**

| Option | Description |
|--------|-------------|
| `--movies-only` | Traite uniquement les films |
| `--series-only` | Traite uniquement les séries |
| `--dry-run` | Simule sans modifier ni créer aucun fichier |
| `--prune` | Supprime de l'arbre Jellyfin les entrées absentes de la base CineOrg |

**Exemple de sortie (dry-run) :**

```
Films liés : 5853 / Séries liées : 1022 (épisodes : 20572) / Ignorés : 39
```

**Structure générée :**

```
JellyfinLib/
├── Films/
│   └── Inception (2010)/
│       ├── Inception (2010).mkv        → symlink vers storage/
│       └── movie.nfo                   # IDs TMDB/IMDb + métadonnées complètes
│
└── Series/
    └── Breaking Bad (2008)/
        ├── tvshow.nfo                  # métadonnées série + IDs
        └── Saison 01/
            ├── Breaking Bad (2008) S01E01.mkv   → symlink vers storage/
            └── Breaking Bad (2008) S01E01.nfo   # métadonnées épisode
```

La structure est **à plat** : un dossier par film (indépendant de la classification genre/subdivision de `video/`), une arborescence `Saison NN/` par série. Les films multi-parties utilisent le suffixe `- cd2`, `- cd3`, etc.

**Contenu des NFO :** titre, année, synopsis, genres, durée, notes TMDB et IMDb, note personnelle, réalisateur(s), casting, affiche, collection/saga. Les corrections manuelles CineOrg (`*_override`) priment sur les valeurs API.

**Chaîne de repli pour les sources :**
1. `realpath(symlink_path)` — cible résolue du symlink `video/`
2. `file_path` — chemin physique direct issu de la base
3. Entrée ignorée et listée dans le rapport (sans interruption de la commande)

La commande est **idempotente** : elle peut être relancée à tout moment pour intégrer le nouveau contenu ou recréer des fichiers manquants.

**Périmètre :** films et séries gérés par CineOrg uniquement (documentaires, musiques et autres types non inclus).

### Brancher Jellyfin

**1. Lancer le conteneur Docker :**

```bash
docker run -d \
  --name jellyfin \
  --restart=unless-stopped \
  -p 8096:8096 \
  -v /home/jp/jellyfin/config:/config \
  -v /home/jp/jellyfin/cache:/cache \
  -v /media/Serveur/JellyfinLib:/media/Serveur/JellyfinLib:ro \
  -v /media/NAS64:/media/NAS64:ro \
  -v /media/Serveur:/media/Serveur:ro \
  jellyfin/jellyfin
```

Les montages `/media/NAS64` et `/media/Serveur` en lecture seule permettent à Jellyfin de résoudre les symlinks de `JellyfinLib/` vers les fichiers physiques stockés sur ces volumes.

**2. Configurer les bibliothèques (interface web `http://<serveur>:8096`) :**

| Bibliothèque | Type Jellyfin | Répertoire |
|---|---|---|
| Films | *Films* | `/media/Serveur/JellyfinLib/Films` |
| Séries | *Séries/Émissions* | `/media/Serveur/JellyfinLib/Series` |

> Le dossier généré s'appelle `Series` (sans accent, par cohérence avec le stockage CineOrg) ; le nom d'affichage de la bibliothèque dans Jellyfin peut rester « Séries ».

**3. Activer la lecture des NFO locaux :**

Dans les paramètres de chaque bibliothèque Jellyfin, activer **« Lecture des fichiers de métadonnées locaux NFO »** comme source prioritaire, et régler la langue des métadonnées sur **fr**.

Avec les NFO actifs, Jellyfin n'interroge pas les serveurs distants pour identifier les contenus : les IDs TMDB/TVDB/IMDb inscrits dans les fichiers garantissent une identification fiable, même pour les titres ambigus ou les séries peu connues.

**4. Accès distant via Tailscale (regarder hors du réseau local) :**

Pour regarder la bibliothèque depuis un téléphone en 4G/5G ou sur un autre Wi-Fi, on relie le serveur et les appareils nomades par un **tailnet privé** [Tailscale](https://tailscale.com/). Le trafic passe par un tunnel WireGuard chiffré : **rien n'est exposé sur Internet** et le conteneur Docker reste inchangé (Jellyfin écoute déjà sur `0.0.0.0:8096`).

1. **Créer un compte** sur [login.tailscale.com/start](https://login.tailscale.com/start) (offre *Personal* gratuite ; connexion via Google/GitHub/…). **Retenir le fournisseur d'identité choisi** : tous les appareils doivent utiliser le *même* compte pour former un seul tailnet.

2. **Connecter le serveur** (Ubuntu) — installer le paquet si besoin, puis l'authentifier :
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh   # si Tailscale n'est pas déjà installé
   sudo tailscale up --hostname=cineorg-server
   ```
   Ouvrir l'URL d'authentification affichée dans un navigateur connecté au même compte. Le serveur obtient alors une IP stable `100.x.x.x` (ex. `100.75.129.69`) et, si MagicDNS est actif, un nom lisible `cineorg-server`.

3. **Connecter chaque appareil nomade** — installer l'appli Tailscale (Play Store / App Store), se connecter au **même compte**, vérifier que l'appareil voit le serveur dans la liste.

4. **Pointer Jellyfin sur l'adresse du tailnet** — dans l'appli Jellyfin du téléphone, ajouter le serveur via son IP tailnet `http://100.x.x.x:8096` (ou son nom `http://cineorg-server:8096`). L'ancienne adresse locale `http://192.168.1.15:8096` ne fonctionne **que** sur le réseau domestique.

5. **Vérifier hors réseau local** — couper le Wi-Fi du téléphone (passer en données mobiles), s'assurer que l'interrupteur Tailscale est **actif**, puis lancer une lecture. Si elle démarre, l'accès distant est opérationnel.

> **Confort (optionnel)** : ajouter le sous-réseau Tailscale `100.64.0.0/10` aux « réseaux locaux » de Jellyfin (Tableau de bord → Réseau) pour que ces clients soient traités comme du LAN (lecture directe, moins de transcodage inutile).

### Partage SyncPlay (Partager / Départager)

Depuis une fiche film ou série de la bibliothèque web, le bouton **« Partager »** expose *temporairement* ce seul titre à un ami distant pour une séance de visionnage synchronisé ([SyncPlay](https://jellyfin.org/docs/general/server/syncplay/)). Le film (fichier unique) ou la série (intégrale, toutes saisons) est publié dans une bibliothèque Jellyfin éphémère, et le **[Tailscale Funnel](https://tailscale.com/kb/1223/funnel)** ouvre une URL *publique* le temps de la séance — l'ami n'a donc **pas** besoin d'installer Tailscale (contrairement à l'accès distant ci-dessus, qui reste réservé au propriétaire).

Au clic sur « Partager », le titre est publié puis **CineOrg attend que Jellyfin l'ait indexé** avant de valider : le bouton affiche une **bordure animée** (« en cours de préparation ») pendant le scan Jellyfin (~45 s), puis se transforme en **« Départager »** une fois le contenu réellement visible pour l'ami. Cette attente garantit que l'ami ne tombe pas sur une bibliothèque vide. Si Jellyfin n'indexe rien dans le délai imparti, un message d'erreur invite à réessayer (aucun faux « partage » n'est enregistré).

> ℹ️ Le scan est déclenché via `POST /Library/Refresh` (scan des médiathèques). Le refresh ciblé `POST /Items/{id}/Refresh` ne ré-énumère **pas** le dossier et laissait donc la bibliothèque de partage vide — c'est pourquoi le scan global est utilisé.

Le bouton **« Départager »** (sur la fiche ou via le bandeau rouge « Partage en cours » présent en haut de toutes les pages) referme le partage : la bibliothèque éphémère est vidée, le contenu dé-indexé côté Jellyfin et le Funnel coupé. Le bandeau apparaît/disparaît **immédiatement** (évènement HTMX `shareChanged`, sans attendre le rafraîchissement périodique). Le démontage est aussi **automatique** — après **30 min sans lecture** ou au bout d'un **plafond de 6 h**. Un seul titre peut être partagé à la fois (partager un nouveau titre propose de remplacer le partage courant).

**Prérequis (à faire une fois) :**

1. **Deux bibliothèques Jellyfin dédiées**, restreintes au compte de l'ami, NFO activés, « Actualiser depuis Internet = Jamais » :

   | Bibliothèque | Type Jellyfin | Répertoire |
   |---|---|---|
   | Partage Films | *Films* | `/media/Serveur/JellyfinLib/Partage/Films` |
   | Partage Séries | *Séries/Émissions* | `/media/Serveur/JellyfinLib/Partage/Series` |

2. **Un compte invité** (ex. `Alex`) : non-administrateur, accès limité à ces deux bibliothèques uniquement, **SyncPlay activé**.
3. **Une clé API Jellyfin** (Tableau de bord → Avancé → Clés API), renseignée dans le fichier `.env` du projet :

   ```bash
   CINEORG_JELLYFIN_URL=http://localhost:8096          # URL du serveur Jellyfin (défaut)
   CINEORG_JELLYFIN_API_KEY=<clé_générée>              # active la fonctionnalité de partage
   CINEORG_JELLYFIN_PARTAGE_DIR=/media/Serveur/JellyfinLib/Partage   # dossier des biblio éphémères (défaut)
   ```

4. **Opérateur Tailscale + Funnel** : le service web tourne sous l'utilisateur déclaré opérateur Tailscale (pas de `sudo`), avec le Funnel autorisé sur le tailnet (Admin console → Access controls → `nodeAttrs`/`funnel`).

**Côté ami :** lui communiquer l'URL publique du Funnel (ex. `https://cineorg-server.tail592482.ts.net`) et les identifiants du compte invité. Client recommandé : **Jellyfin Media Player** (Windows) ou l'appli Jellyfin, en rejoignant le groupe SyncPlay une fois connecté.

## Format de nommage

### Films

```
Titre (Année) Langue Codec-Audio Codec-Video Résolution.ext
```

Exemples :
- `Inception (2010) FR DTS-HD MA HEVC 2160p.mkv`
- `Matrix (1999) EN DTS H264 1080p.mkv`
- `Amélie (2001) FR AAC H264 720p.mp4`

### Séries

```
Titre (Année) - SxxExx - Titre Episode - Langue Codec-Audio Codec-Video Résolution.ext
```

Exemples :
- `Breaking Bad (2008) - S01E01 - Pilot - EN AAC H264 720p.mkv`
- `Game of Thrones (2011) - S08E06 - The Iron Throne - FR DTS HEVC 1080p.mkv`

## Extensions supportées

`.mkv`, `.mp4`, `.avi`, `.mov`, `.wmv`, `.flv`, `.webm`, `.m4v`, `.mpg`, `.mpeg`, `.ts`, `.vob`

## Fichiers ignorés

Les fichiers contenant ces termes sont automatiquement ignorés :
- `sample`, `trailer`, `preview`, `extras`
- `behind the scenes`, `deleted scenes`, `featurette`
- `interview`, `bonus`

## Obtenir les clés API

### TMDB (films)

1. Créer un compte sur [themoviedb.org](https://www.themoviedb.org/)
2. Aller dans Paramètres → API
3. Demander une clé API (usage personnel)
4. Copier la clé "API Key (v3 auth)" ou le "Read Access Token (v4)"

### TVDB (séries)

1. Créer un compte sur [thetvdb.com](https://thetvdb.com/)
2. Aller dans [API Information](https://thetvdb.com/api-information)
3. Créer un projet et récupérer l'API Key

## Options globales

```bash
# Mode verbeux (plus de détails)
uv run cineorg -v process
uv run cineorg -vv process  # Encore plus verbeux

# Mode silencieux (erreurs uniquement)
uv run cineorg -q process
```

## Interface web

CineOrg dispose d'une interface web complète (FastAPI + Jinja2 + HTMX) permettant de parcourir la vidéothèque, filtrer et rechercher des contenus, consulter les fiches détaillées, lancer le traitement des nouveaux fichiers et effectuer la maintenance.

La barre de navigation donne accès à toutes les sections : **Accueil**, **Traitement**, **Validation**, **Transfert**, **Bibliothèque**, **Maintenance** et **Configuration**.

### Lancement du serveur

```bash
# Lancement standard (accessible depuis le réseau local sur le port 8000)
uv run cineorg serve

# Options disponibles
uv run cineorg serve --port 9000       # Port personnalisé
uv run cineorg serve --reload          # Rechargement automatique (développement)
uv run cineorg serve --host 127.0.0.1  # Restreindre à la machine locale
```

L'interface est accessible à `http://localhost:8000` (ou `http://<IP-du-serveur>:8000` depuis un autre poste du réseau local).

### Tableau de bord

> ![Tableau de bord](docs/screenshots/dashboard.png)

La page d'accueil (`/`) affiche un tableau de bord avec les statistiques de la vidéothèque :

- Nombre de **films** en base
- Nombre de **séries** et d'**épisodes**
- Nombre de fichiers **en attente de validation**

### Bibliothèque

> ![Bibliothèque — grille de jaquettes](docs/screenshots/library-grid.png)

La page `/library` affiche l'ensemble des films et séries sous forme de grille de jaquettes avec pagination (48 éléments par page). Chaque carte affiche :

- La **jaquette** TMDB (ou un placeholder si absente)
- Le **titre** et l'**année**
- Un badge **Film** ou **Série**
- La **note IMDb** si disponible

Un clic sur une carte ouvre la fiche détaillée du contenu.

### Filtres et recherche

> ![Filtres actifs avec cartouches](docs/screenshots/library-filters.png)

La barre de filtres en haut de la bibliothèque permet de combiner librement plusieurs critères. Tous les filtres sont interactifs via HTMX : la grille se met à jour sans rechargement de page.

| Filtre | Description |
|--------|-------------|
| **Recherche** | Par titre (défaut) ou titre + synopsis (mode « Titre + Synopsis ») |
| **Type** | Tous, Films, Séries |
| **Genre** | Filtrer par genre (Action, Drame, Science-Fiction…) |
| **Année** | Filtrer par année de sortie |
| **Résolution** | 4K, 1080p, 720p, SD |
| **Codec vidéo** | x264, x265, XviD… |
| **Codec audio** | AAC, AC3, DTS, DTS-HD… |
| **Tri** | Par titre, année, note, résolution, codec vidéo ou audio |
| **Ordre** | Croissant ou décroissant |

**Cartouches déselectionnables** — Chaque filtre actif s'affiche sous forme de cartouche avec un bouton × pour le retirer. Cela permet de visualiser et gérer facilement les critères en cours.

> ![Cartouches filtre personne](docs/screenshots/library-filter-tags.png)

**Filtrage par clic** — Depuis les fiches détaillées, un clic sur un badge technique (résolution, codec), un genre, un réalisateur ou un acteur filtre automatiquement la bibliothèque sur ce critère. Les réalisateurs et acteurs sont distingués par des icônes différentes (mégaphone pour le réalisateur, buste pour l'acteur).

**Recherche étendue** — Le mode « Titre + Synopsis » permet de chercher des mots-clés dans le synopsis des films (ex : chercher « espace » trouve les films de science-fiction même si le mot n'est pas dans le titre).

### Fiches détaillées

> ![Fiche détaillée film](docs/screenshots/movie-detail.png)

Chaque film dispose d'une fiche complète affichant :

- **Jaquette** zoomable — clic pour agrandir en plein écran (lightbox)
- **Notes** — badges colorés IMDb (jaune) et TMDB (vert/orange/rouge selon le score)
- **Liens externes** — accès direct vers les fiches IMDb et TMDB
- **Genres** — sous forme de tags cliquables
- **Badges techniques** — résolution (bleu), codec vidéo et audio (violet), langues (vert). Chaque badge est cliquable pour filtrer toute la bibliothèque sur ce critère
- **Crédits** — réalisateur et acteurs sous forme de liens. Un clic affiche tous les films de cette personne dans la bibliothèque
- **Synopsis** complet
- **Bouton Visionner** — placé sous la jaquette, mis en valeur en vert ; lance la lecture via mpv (ou le profil de lecteur choisi)
- **Menu « Modifier la fiche »** — sous la jaquette, un menu déroulant discret regroupe les actions rares **Corriger** (ré-association TMDB, voir section dédiée) et **Éditer** (affiche, synopsis, casting). Masquées par défaut, elles ne peuvent être déclenchées par erreur. Pour les fiches fantômes (sans fichier), ce menu propose aussi **Supprimer la fiche**.
- **Informations fichier** — panneau dépliable avec chemin storage, chemin symlink, codec, résolution, taille du fichier et IDs externes (TMDB, IMDb)

> ![Fiche détaillée série](docs/screenshots/series-detail.png)

Pour les **séries**, le menu **« Modifier la fiche »** (Corriger / Éditer) figure également sous la jaquette ; il n'y a pas de bouton Visionner global, la lecture se faisant épisode par épisode. La fiche affiche en plus :

- Le nombre de **saisons** et d'**épisodes**
- Les **badges techniques agrégés** à partir de l'ensemble des épisodes (valeurs distinctes)
- La **liste des saisons** sous forme de panneaux dépliables, chaque épisode ayant :
  - Son numéro (E01, E02…) et son titre
  - Un bouton **lecture** (triangle play) pour lancer l'épisode dans mpv
  - Un bouton **fichier** pour afficher le chemin du fichier

### Correction des associations TMDB

> ![Overlay de ré-association](docs/screenshots/reassociate.png)

Lorsqu'un film ou une série est mal identifié par TMDB, le bouton **Corriger** ouvre un overlay de ré-association :

1. **Recherche** — Saisir le titre correct dans le champ de recherche
2. **Résultats** — Les candidats TMDB s'affichent avec :
   - Jaquette miniature
   - Titre et année
   - Score de correspondance (badge vert/orange/rouge)
   - Popularité TMDB
   - Synopsis abrégé
3. **Sélection** — Cliquer sur « Associer » pour remplacer l'association TMDB
4. Les métadonnées (titre, synopsis, genres, notes, jaquette) sont automatiquement mises à jour

Pour une **série**, la correction entraîne en plus trois mises à jour automatiques :

- **Complétude recalculée** — l'ancien verdict portait sur la mauvaise fiche. Le `tvdb_id` est
  re-résolu depuis l'IMDb ID de la nouvelle fiche, puis les épisodes détenus sont confrontés aux
  épisodes réellement diffusés. Sans `tvdb_id` retrouvé, la série redevient « non vérifiable »
  plutôt que de conserver un « incomplet » périmé.
- **Titres d'épisodes rafraîchis** — TMDB est la source primaire ; quand il ne renvoie qu'un
  gabarit numéroté (« Épisode 7 », fréquent en fr-FR), TVDB prend le relais car il possède
  souvent les titres français.
- **Fichiers et symlinks réalignés** — le dossier de série (`storage/` et `video/`), les fichiers
  physiques et les symlinks sont renommés d'après le nouveau titre/année et les nouveaux titres
  d'épisodes. Opération best-effort : un incident disque est journalisé sans annuler la correction,
  déjà enregistrée. Si le dossier canonique existe déjà, les fichiers sont renommés sur place sans
  déplacement de dossier.

#### Suppression d'une fiche fantôme (doublon)

Une **fiche fantôme** est une fiche sans aucun fichier rattaché (série dont aucun épisode n'a de fichier, ou film sans fichier). Elle résulte typiquement d'un mauvais matching laissé en place après une re-analyse (ex. une série associée à tort à un mauvais résultat, puis re-validée vers la bonne fiche, l'ancienne fiche restant orpheline).

Dans ce cas seulement, un bouton **Supprimer la fiche** apparaît sur le détail. Il supprime la fiche (et ses épisodes pour une série) vers la corbeille — les fichiers physiques (`storage/`) éventuels ne sont jamais touchés. Le bouton n'apparaît **pas** sur une fiche porteuse de fichiers, et le serveur refuse la suppression dans ce cas (garde-fou).

> Pour prévenir ce type de doublon, les séries documentaires sont désormais exclues des candidats lors du matching (le dossier de téléchargement `Séries` n'en contient jamais), et la déduplication des séries se fait aussi par `tmdb_id` (et plus seulement `tvdb_id`).

### Lecteur vidéo intégré

Le bouton **Visionner** (films) ou le bouton **play** (épisodes) lance la lecture du fichier via le lecteur configuré. Un indicateur de statut s'affiche pendant la lecture.

#### Visionner en un clic (identité par navigateur)

Chaque navigateur mémorise « qui regarde » via le sélecteur **« Vous regardez sur »**
de l'en-tête (stockage local, propre à chaque appareil — aucun réglage côté serveur,
donc plusieurs personnes peuvent regarder en même temps sans interférence).

- **Clic sur « Visionner »** : lance la vidéo directement sur votre profil, en un seul clic.
- **Chevron ▾** : choix ponctuel d'un autre lecteur ou envoi vers le mediacenter **DuneHD**,
  sans changer votre identité.

DuneHD n'apparaît pas dans le sélecteur d'identité (il *envoie* au mediacenter plutôt que
de « regarder ») : il reste accessible uniquement via le menu ▾.

**Trois modes de lecture** sont disponibles via les profils lecteur (`/config` > Lecteur) :

| Mode | Target | Description |
|------|--------|-------------|
| **Local** | `local` | Lance le lecteur directement sur la machine serveur |
| **SSH Linux** | `remote` | Lance le lecteur sur une machine Linux distante via SSH (ex: `env DISPLAY=:0 mpv`) |
| **SSH Windows** | `remote` | Envoie le chemin à un watcher sur une machine Windows via SCP |

#### Configuration d'un poste Windows distant

Pour lancer des films/séries sur un PC Windows depuis CineOrg (serveur Linux), plusieurs étapes sont nécessaires :

**1. Installer OpenSSH Server sur Windows**

```
Paramètres > Applications > Fonctionnalités facultatives > Ajouter une fonctionnalité > OpenSSH Server
```

Puis dans PowerShell (admin) :

```powershell
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
```

**2. Configurer l'authentification par clé SSH**

Sur le serveur Linux, copier la clé publique. Pour un compte administrateur Windows, la clé doit être dans `C:\ProgramData\ssh\administrators_authorized_keys` (et non `~/.ssh/authorized_keys`) :

```bash
# Depuis Linux, afficher la clé publique
cat ~/.ssh/id_ed25519.pub
```

Sur Windows (PowerShell admin), créer le fichier et fixer les permissions :

```powershell
# Coller la clé publique dans le fichier
Set-Content -Path "C:\ProgramData\ssh\administrators_authorized_keys" -Value "ssh-ed25519 AAAA... user@host"

# Fixer les permissions (obligatoire)
icacls "C:\ProgramData\ssh\administrators_authorized_keys" /inheritance:r /grant "SYSTEM:F" /grant "Administrators:F"
```

Vérifier la connexion depuis Linux :

```bash
ssh Utilisateur@192.168.1.XX "echo OK"
```

**3. Installer mpv sur Windows**

Télécharger mpv depuis https://mpv.io/installation/ et extraire dans `C:\Apps\mpv\`.

Ajouter `C:\Apps\mpv` au PATH Windows (Paramètres > Variables d'environnement).

**4. Accès au NAS via chemin UNC**

Les lecteurs réseau mappés (ex: `N:`) ne sont pas visibles dans les sessions SSH. Il faut utiliser un chemin UNC avec authentification guest :

```powershell
net use \\192.168.1.XX\partage "" /user:guest
```

**5. Installer le watcher mpv**

Le fichier `mpv_watcher.ps1` (inclus dans le dépôt) surveille un fichier queue et lance mpv dans la session interactive du bureau. SSH ne peut pas lancer directement une application GUI sur le bureau Windows.

Copier le fichier sur Windows :

```bash
scp mpv_watcher.ps1 Utilisateur@192.168.1.XX:C:/Apps/mpv_watcher.ps1
```

Configurer le démarrage automatique (PowerShell sur Windows) :

```powershell
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\mpv_watcher.lnk")
$Shortcut.TargetPath = "powershell.exe"
$Shortcut.Arguments = "-ExecutionPolicy Bypass -WindowStyle Hidden -File C:\Apps\mpv_watcher.ps1"
$Shortcut.Save()
```

Le watcher se lancera automatiquement à chaque connexion de l'utilisateur.

**6. Configurer le profil dans CineOrg**

Dans la page Configuration (`/config` > Lecteur), créer un profil avec :

| Paramètre | Valeur |
|-----------|--------|
| Commande | `mpv` |
| Cible | `remote` |
| Hôte SSH | `192.168.1.XX` (IP du PC Windows) |
| Utilisateur SSH | Nom d'utilisateur Windows |
| Préfixe local | Chemin côté serveur (ex: `/media/NAS64`) |
| Préfixe distant | Chemin UNC (ex: `\\192.168.1.XX\partage`) |

> **Fonctionnement** : CineOrg envoie le chemin du fichier via SCP (pour préserver l'encodage UTF-8 des caractères accentués) dans `C:\Apps\mpv_queue.txt`. Le watcher détecte le fichier et lance mpv dans la session de bureau.

### Traitement et validation

> ![Page de traitement](docs/screenshots/workflow.png)

La page **Traitement** (`/workflow`) permet de lancer le pipeline de traitement des nouveaux fichiers directement depuis le navigateur :

1. **Scan** des répertoires de téléchargement
2. **Identification** via TMDB/TVDB avec scoring de correspondance
3. **Validation automatique** pour les résultats à haute confiance (score >= 85%)

La progression s'affiche en temps réel via SSE (Server-Sent Events).

> ![Page de validation](docs/screenshots/validation.png)

La page **Validation** (`/validation`) liste les fichiers en attente de validation manuelle. Pour chaque fichier :

- Affichage du nom original et des candidats TMDB/TVDB proposés
- Possibilité de **valider** un candidat, de le **rejeter** ou de **rechercher** manuellement un titre alternatif
- Recherche par titre ou par ID TMDB/TVDB direct

### Transfert

> ![Page de transfert](docs/screenshots/transfer.png)

La page **Transfert** (`/transfer`) gère le déplacement des fichiers validés vers le stockage organisé :

- Renommage selon le format standardisé.
- Création de la structure de répertoires (genre/lettre/subdivision pour les films, lettre/titre/saison pour les séries).
- Création des symlinks dans `video/`.
- Création des hardlinks de seeding dans `downloads/`.
- Gestion des **conflits** (doublons détectés) via dialogue overlay avec cascade série et aide à la décision par scoring qualité.

La progression s'affiche en temps réel via SSE (préparation du batch et exécution du transfert).

### Qualité et doublons

- **Page Qualité** (`/quality`) — classe les films et épisodes selon le score qualité (résolution + codecs + bitrates). Permet d'identifier les candidats à l'upgrade (versions HD ou HDR disponibles).
- **Page Doublons** (`/duplicates`) — liste les doublons de la base (même film référencé deux fois) et les doublons physiques détectés via hash SHA-256.

### Corbeille

La **corbeille** (`/library/trash`) est une poubelle réversible : les fichiers supprimés depuis la bibliothèque y sont envoyés avec leurs métadonnées sérialisées. Possibilité de restaurer ou de vider définitivement.

La suppression est restreinte à **localhost** — le bouton est masqué depuis une machine distante, et la route DELETE retourne 403. Évite les suppressions accidentelles depuis un client non supervisé.

### Fusion de fiches séries dupliquées

Après le téléchargement de nouveaux épisodes, il arrive que ceux-ci soient rattachés à une **fiche distincte** au lieu de la fiche existante (ex. « Doctor Who » et « Doctor Who (2005) » coexistent en base). La fusion permet de réunifier les deux fiches en une seule sans toucher aux fichiers physiques.

> Cette opération est restreinte à **localhost** (même restriction que la suppression).

#### Utilisation

1. Ouvrir la **Bibliothèque** (`/library/`), filtrer sur « Séries » et rechercher le titre concerné.
2. Cliquer sur le bouton **Suppression** pour passer en mode sélection.
3. Cocher **exactement deux** fiches de type Série (le bouton **Fusionner** n'apparaît que pour cette combinaison ; il reste masqué pour les films ou si le nombre de sélections est différent de 2).
4. Cliquer sur **Fusionner** dans la barre flottante.
5. Un overlay s'ouvre avec les deux fiches côte à côte. Un bouton radio **Conserver celle-ci** permet de choisir quelle fiche est conservée (la plus ancienne est pré-sélectionnée). Un aperçu calculé affiche :
   - le nombre d'épisodes qui seront rattachés à la fiche conservée ;
   - les champs de métadonnées récupérés depuis la fiche absorbée (ex. `tvdb_id` manquant) ;
   - les éventuels conflits d'épisodes (même saison + même numéro dans les deux fiches) ;
   - un avertissement si les deux fiches ont des `tmdb_id` ou des années différents (risque de fusionner deux séries distinctes).
   
   Modifier la sélection radio recalcule l'aperçu dans l'autre sens.
6. Cliquer sur **Fusionner ▶** pour exécuter. La page redirige vers la fiche unifiée.

#### Ce que fait la fusion

- Les épisodes de la fiche absorbée sont **rattachés à la fiche conservée**.
- Les **conflits** (même épisode présent des deux côtés) sont résolus automatiquement en conservant la version de meilleure qualité (score qualité : résolution, codec vidéo/audio, bitrate). Le fichier physique de la version écartée est conservé ; seul son symlink et sa ligne en base sont supprimés.
- Les métadonnées manquantes sur la fiche conservée (ex. `tvdb_id` nul) sont complétées par celles de la fiche absorbée.
- Les **symlinks** dans `video/` sont régénérés sous le dossier canonique de la fiche conservée (`Titre (Année)/Saison XX/…`).
- La fiche absorbée est envoyée en **corbeille** pour traçabilité.
- Les fichiers physiques dans `storage/` ne sont **jamais déplacés ni renommés**.

### Maintenance

> ![Page de maintenance](docs/screenshots/maintenance.png)

La page **Maintenance** (`/maintenance`) fournit des diagnostics en lecture seule :

- **Vérification d'intégrité** — Détecte les symlinks cassés, les fichiers storage orphelins, les entrées DB sans fichier correspondant
- **Analyse de nettoyage** — Détecte les symlinks cassés dans `video/`, les répertoires vides, les symlinks mal placés (mauvais genre, mauvaise subdivision), les problèmes de case
- **Vérifier la complétude** — Lance une vérification par lots de la [complétude des séries](#surveillance-de-complétude-des-séries) : détecte les séries auxquelles il manque des épisodes ou des saisons déjà diffusés. Le récapitulatif propose un lien vers les séries incomplètes dans la bibliothèque

Chaque diagnostic s'exécute avec une barre de progression en temps réel (SSE) et affiche un rapport détaillé avec compteurs. Les actions correctives restent disponibles via le CLI (`uv run cineorg cleanup --fix`).

### Configuration web

> ![Page de configuration](docs/screenshots/config.png)

La page **Configuration** (`/config`) permet de visualiser et modifier les paramètres de l'application :

| Section | Paramètres |
|---------|-----------|
| **Répertoires** | Téléchargements, Stockage, Vidéo |
| **Base de données** | URL SQLite (lecture seule) |
| **Clés API** | TMDB, TVDB (masquées) |
| **Traitement** | Taille minimale fichier, seuil de score, max fichiers par sous-dossier |
| **Logging** | Niveau de log, fichier de log, rotation |

Les modifications sont enregistrées dans le fichier `.env` et prises en compte au redémarrage du serveur.

## Stack technique

- **Python 3.11+**
- **Typer + Rich** - Interface CLI interactive avec panneaux colorés
- **SQLModel** - ORM (SQLite)
- **dependency-injector** - Injection de dépendances
- **guessit** - Parsing des noms de fichiers
- **pymediainfo** - Extraction métadonnées techniques (codecs, résolution, durée)
- **httpx** - Client HTTP async pour les APIs
- **diskcache** - Cache persistant des résultats API
- **tenacity** - Retry avec backoff exponentiel
- **rapidfuzz** - Scoring de similarité des titres

## Architecture du code

Le projet suit une **architecture hexagonale** (ports & adapters) :

```
src/
├── core/                    # Domaine métier (entities, ports, value_objects)
├── adapters/                # Adaptateurs (api, cli, parsing, imdb, file_system)
├── services/                # Logique métier (workflow, repair, cleanup, matcher, …)
├── infrastructure/          # Persistance (SQLModel, repositories, hash)
├── web/                     # FastAPI + Jinja2 + HTMX
└── utils/                   # Constantes et helpers
```

Câblage centralisé dans `src/container.py` via `dependency-injector` (Singleton pour les composants stateless, Factory pour les sessions/services stateful). Persistance SQLite avec `NullPool` (évite l'épuisement des connexions avec les Factory).

> 📖 Architecture détaillée (couches, DI, persistance, pipeline, CLI, web, décisions structurantes) : [docs/architecture.md](docs/architecture.md).

## Versioning & releases

La version du projet est stockée dans `pyproject.toml` (`[project].version`) — **source
unique de vérité**. Le footer web et la commande `cineorg version` l'affichent
dynamiquement (helper `src/version.py`).

### Règles SemVer (basées sur les commits conventionnels)

| Type de commit | Effet sur la version | Exemple |
|---|---|---|
| `feat:` | **MINOR** | 2.0.0 → 2.1.0 |
| `fix:` | **PATCH** | 2.0.0 → 2.0.1 |
| `feat!:` ou bloc `BREAKING CHANGE:` | **MAJOR** | 2.0.0 → 3.0.0 |
| `docs:`, `chore:`, `refactor:`, `test:`, `style:` | aucun bump | — |

### Publier une nouvelle version

```bash
uv run cz bump          # calcule le numéro depuis les commits, met à jour
                        # pyproject.toml + CHANGELOG.md, commit et crée le tag
git push --follow-tags  # publie le commit de version et le tag
```

`uv run cz bump --dry-run` permet de prévisualiser le numéro sans rien modifier.

## Dépannage

### Warning "Ignoring unsupported Python request"

Si vous voyez ce warning au lancement :
```
warning: Ignoring unsupported Python request `system` in version file
```

Le fichier `.python-version` contient une valeur non supportée par `uv`. Remplacez `system` par la version Python réelle :

```bash
echo "3.13" > .python-version
```

### "No module named..."

```bash
uv sync  # Réinstaller les dépendances
```

### Les fichiers ne sont pas détectés

- Vérifier que `CINEORG_DOWNLOADS_DIR` pointe vers le bon répertoire
- Vérifier que les sous-dossiers `Films/` et `Series/` existent
- Vérifier que les fichiers font plus de 100 MB (ou ajuster `CINEORG_MIN_FILE_SIZE_MB`)

### Pas de résultats API

- Vérifier que les clés API sont définies dans `.env`
- Tester avec `uv run cineorg info` (affiche si les APIs sont activées)

### Aucun candidat pour les séries

L'API TheTVDB v3 a retiré son endpoint de recherche par nom (`/search/series?name=` → 404). La recherche de séries passe désormais par TMDB (`search_tv`), puis résout le `tvdb_id` via les identifiants externes TMDB pour conserver l'accès TVDB par ID (titres d'épisodes, complétude). Une série présente sur TMDB mais absente de TVDB n'est pas proposée automatiquement (validation manuelle par ID possible).

### Symlinks cassés après déplacement

```bash
# Nettoyage complet (symlinks cassés + mal placés + répertoires vides)
uv run cineorg cleanup --fix

# Ou réparation ciblée des symlinks uniquement
uv run cineorg repair-links --auto

# Forcer la reconstruction de l'index de recherche
rm ~/.cineorg/file_index.json
uv run cineorg repair-links --auto
```

### Nouveaux épisodes d'une série sur une fiche distincte

Après un téléchargement, les épisodes apparaissent dans la bibliothèque sous une deuxième fiche (ex. « Doctor Who » et « Doctor Who (2005) ») au lieu d'être rattachés à la fiche existante. Cela se produit quand le matching TMDB/TVDB a créé une nouvelle entrée légèrement différente.

→ Utiliser la **fusion de fiches séries** depuis la bibliothèque web (voir [Fusion de fiches séries dupliquées](#fusion-de-fiches-séries-dupliquées)).

### Mes séries apparaissent toutes « non vérifiables »

La [surveillance de complétude](#surveillance-de-complétude-des-séries) ne s'appuie que sur TVDB en V1. Si toutes les séries ressortent « non vérifiables », la cause probable est l'absence de `tvdb_id` sur les fiches, ou une clé API TVDB non configurée.

```bash
# Renseigner les tvdb_id manquants
uv run cineorg enrich-tvdb-ids

# Puis relancer la vérification
uv run python -m src.main check-completeness
```

Vérifier aussi que la clé `CINEORG_TVDB_API_KEY` est bien définie dans `.env` (`uv run cineorg info` indique si l'API TVDB est activée).

### Un contenu n'apparaît pas dans Jellyfin

- Relancer `jellyfin-sync` : la commande est idempotente et rattrape tout nouveau contenu en base.
  ```bash
  uv run cineorg jellyfin-sync
  ```
- Utiliser `--dry-run` pour diagnostiquer les ignorés (entrées sans fichier source résolvable).
- Vérifier que les montages Docker (`/media/NAS64`, `/media/Serveur`) sont accessibles depuis le conteneur et que les symlinks de `JellyfinLib/` se résolvent bien vers les fichiers physiques.
- Si le contenu est présent dans `JellyfinLib/` mais absent de l'interface Jellyfin, forcer un scan de la bibliothèque concernée depuis `http://<serveur>:8096` (Tableau de bord → bibliothèque → scanner).
- Vérifier que la variable `CINEORG_JELLYFIN_DIR` pointe vers le bon répertoire (`uv run cineorg info`).

### Jellyfin inaccessible à distance (4G / autre réseau)

- Vérifier que l'interrupteur **Tailscale est actif** sur le téléphone (sans tunnel, pas d'accès hors LAN).
- L'appli Jellyfin doit pointer sur l'**adresse du tailnet** (`http://100.x.x.x:8096` ou `http://cineorg-server:8096`), **pas** sur l'ancienne adresse locale `192.168.1.15:8096` (qui ne marche que sur le réseau domestique).
- Confirmer côté serveur que les deux machines sont sous le **même compte** et que Jellyfin répond sur l'IP tailnet :
  ```bash
  tailscale status
  curl -s -o /dev/null -w "%{http_code}\n" http://<IP-tailnet-serveur>:8096/System/Info/Public
  ```
  Un `200` confirme que Jellyfin est joignable via le tailnet.

### Le partage (« Partager ») ne s'expose pas

Si le bouton « Partager » échoue ou si l'ami n'atteint pas l'URL publique :

- **Clé API manquante** : vérifier que `CINEORG_JELLYFIN_API_KEY` est bien défini dans `.env` (sans cette clé, le partage est désactivé). Tester la clé : `curl -s -o /dev/null -w "%{http_code}\n" -H "X-Emby-Token: <clé>" http://localhost:8096/System/Info` doit renvoyer `200`.
- **Funnel indisponible** : le service doit tourner sous l'utilisateur opérateur Tailscale. Vérifier l'état du Funnel : `tailscale funnel status`. Si la commande échoue, contrôler l'autorisation Funnel dans la console d'administration Tailscale.
- **L'ami ne voit rien** : s'assurer que le compte invité a bien accès aux bibliothèques *Partage Films* / *Partage Séries* (et à elles seules), et que la séance n'a pas été démontée automatiquement (30 min sans lecture / plafond 6 h) — dans ce cas, relancer « Partager ». Depuis la correction de l'indexation, « Partager » attend que le contenu soit réellement indexé avant de basculer sur « Départager » ; si le bouton reste en attente puis affiche une erreur, c'est que le scan Jellyfin n'a pas abouti dans le délai — vérifier que le scan des médiathèques n'est pas déjà en cours/bloqué (Jellyfin → Tableau de bord → Tâches planifiées → *Analyser la médiathèque*).

### Base de données corrompue

```bash
# Sauvegarder et recréer
mv cineorg.db cineorg.db.backup
uv run cineorg import  # Réimporter la vidéothèque
```

### Fichier classé dans le mauvais genre

Le genre est déterminé par la **hiérarchie de priorité**. Si un film "Action/Drame" est dans "Action" au lieu de "Drame", c'est le comportement attendu (Action a une priorité plus élevée).

Si les genres ont été corrigés en base mais que le symlink est resté dans l'ancien répertoire :

```bash
# Détecter et corriger les symlinks mal placés
uv run cineorg cleanup --fix
```

## Licence

MIT
