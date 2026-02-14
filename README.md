# CineOrg

Application de gestion de vidéothèque personnelle. Scanne les téléchargements, identifie les contenus via TMDB/TVDB, renomme et organise les fichiers selon un format standardisé, et crée des symlinks pour le mediacenter.

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
- [Notes et évaluations](#notes-et-évaluations)
  - [Notes TMDB](#notes-tmdb)
  - [Notes IMDb](#notes-imdb)
- [Commandes](#commandes)
  - [Nettoyage et réorganisation](#nettoyage-et-réorganisation)
  - [Regroupement par préfixe de titre](#regroupement-par-préfixe-de-titre)
  - [Réparation des symlinks cassés](#réparation-des-symlinks-cassés)
  - [Consolidation des fichiers externes](#consolidation-des-fichiers-externes)
- [Format de nommage](#format-de-nommage)
- [Stack technique](#stack-technique)

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
         Scanner (chemin, taille, nom)
              ↓
         Parser (guessit + mediainfo)
         (titre, année, épisode, codecs, langues)
              ↓
         Matcher (recherche TMDB/TVDB, scoring)
              ↓
         Validation
              ├─ Score ≥ 85% + candidat unique → AUTO-VALIDATION
              ├─ Score ≥ 95% + plusieurs candidats → AUTO-VALIDATION (haute confiance)
              └─ Sinon → STAGING (validation manuelle requise)
              ↓
         Transfert
              ├─ Vérification conflits (hash SHA-256)
              ├─ Déplacement atomique → storage/
              └─ Création symlink → video/
              ↓
         Bibliothèque organisée
```

### Zone de staging

La zone de staging est un **espace temporaire** pour les fichiers nécessitant une validation utilisateur.

#### Quand un fichier va en staging

- Score de correspondance < 85%
- Plusieurs candidats avec scores similaires (< 95% pour le meilleur)
- Aucun candidat trouvé
- Conflit détecté avec contenu existant

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
| 1 candidat, score ≥ 85% | Auto-validation |
| Plusieurs candidats, meilleur score ≥ 95% | Auto-validation (haute confiance) |
| Sinon | Validation manuelle requise |

#### Formule de scoring

**Films :**
```
Avec durée disponible :
  Score = 50% × titre + 25% × année + 25% × durée

Sans durée (fallback) :
  Score = 67% × titre + 33% × année

Où :
- titre : similarité token_sort_ratio (indépendant de l'ordre des mots)
- année : 100% si ±1 an, puis -25% par année d'écart
- durée : 100% si ±10%, puis -50% par tranche de 10%
```

**Séries :**
```
Score = 100% × titre (similarité uniquement)
```

#### Matching bilingue

Pour les films, le système compare le titre recherché avec **le titre localisé ET le titre original**, gardant le meilleur score. Cela gère les cas comme :
- Recherche "Kill Bill" → Candidat "Kill Bill Vol. 1" (japonais: "キル・ビル")

### Détection des doublons

#### Types de conflits

| Type | Description | Action |
|------|-------------|--------|
| `DUPLICATE` | Même fichier (hash identique) | Skip automatique |
| `NAME_COLLISION` | Même chemin, contenu différent | Demande utilisateur |
| `SIMILAR_CONTENT` | Titre similaire, peut-être même média | Comparaison affichée |

#### Détection de contenu similaire

Le système détecte les cas subtils :
- "Station Eleven" vs "Station Eleven (2021)"
- "Matrix" vs "The Matrix (1999)"
- Même série avec/sans année dans le nom

Lors d'une détection, un tableau comparatif est affiché :

```
⚠ Contenu similaire détecté

L'existant n'a pas d'année, le nouveau a (2021)

Comparaison           Existant              Nouveau
─────────────────────────────────────────────────────
Fichiers              3                     1
Taille totale         12.5 Go               4.2 Go
Résolution            1080p                 2160p
Codec vidéo           H.264                 HEVC
Codec audio           DTS                   DTS-HD MA

Options:
  [1] Garder l'ancien (nouveau → staging)
  [2] Garder le nouveau (ancien → staging)
  [3] Garder les deux (sous-dossier créé)
  [s] Passer
```

## Notes et évaluations

CineOrg peut enrichir votre vidéothèque avec les notes et évaluations des films et séries depuis deux sources complémentaires.

### Notes TMDB

Les notes TMDB (`vote_average` et `vote_count`) sont automatiquement récupérées lors de la validation d'un film via l'API TMDB. Ces informations sont stockées en base de données pour chaque film.

Pour enrichir les films existants qui n'ont pas encore leurs notes :

```bash
# Enrichir les 100 premiers films sans notes
uv run cineorg enrich-ratings

# Enrichir un nombre spécifique de films
uv run cineorg enrich-ratings --limit 500
```

**Note** : Cette commande utilise l'API TMDB et respecte le rate limiting (0.25s entre chaque appel).

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

#### Synchroniser avec les films

Une fois les notes IMDb importées, vous pouvez les associer aux films de votre vidéothèque :

```bash
# Synchroniser les films ayant un imdb_id mais pas de note IMDb
uv run cineorg imdb sync

# Limiter le nombre de films à synchroniser
uv run cineorg imdb sync --limit 50
```

**Prérequis** : Les films doivent avoir un `imdb_id` en base. Cet ID est récupéré via l'endpoint `/movie/{id}/external_ids` de TMDB lors de l'enrichissement.

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

### Enrichir les métadonnées

Après un import, enrichir les fichiers avec les métadonnées API :

```bash
# Enrichir les candidats API (recherche TMDB/TVDB)
uv run cineorg enrich

# Enrichir les notes TMDB des films existants
uv run cineorg enrich-ratings --limit 100
```

### Gestion des notes IMDb

```bash
# Télécharger et importer les notes IMDb
uv run cineorg imdb import

# Synchroniser les notes avec les films en base
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

Le projet suit une **architecture hexagonale** avec séparation domaine / adaptateurs / services :

```
src/
├── core/                    # Domaine métier (entités, ports, value objects)
├── adapters/                # Adaptateurs (CLI, API, parsing, persistance)
│   ├── api/                 #   Clients TMDB et TVDB avec cache et retry
│   ├── cli/                 #   Interface Typer
│   │   ├── commands/        #     1 fichier par commande CLI
│   │   ├── validation/      #     Validation interactive (candidats, boucle, batch)
│   │   └── repair/          #     Réparation interactive des symlinks
│   ├── imdb/                #   Import datasets IMDb
│   └── parsing/             #   guessit + mediainfo
├── services/                # Logique métier
│   ├── workflow/            #   Pipeline scan → match → transfer (mixin pattern)
│   ├── repair/              #   Réparation symlinks (index, analyse, similarité)
│   ├── cleanup/             #   Nettoyage video/ (analyse, correction, subdivision)
│   └── ...                  #   matcher, organizer, renamer, transferer, etc.
├── infrastructure/          # Persistance (SQLite, repositories, hash)
└── utils/                   # Constantes et helpers
```

Chaque package volumineux est découpé en modules cohérents avec un `__init__.py` qui réexporte les symboles publics pour préserver la compatibilité des imports.

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
