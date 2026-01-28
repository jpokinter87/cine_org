# CineOrg

Application de gestion de vidéothèque personnelle. Scanne les téléchargements, identifie les contenus via TMDB/TVDB, renomme et organise les fichiers selon un format standardisé, et crée des symlinks pour le mediacenter.

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
| `CINEORG_LOG_LEVEL` | `INFO` | Niveau de log (DEBUG, INFO, WARNING, ERROR) |

### Structure des répertoires

#### Répertoire de téléchargements (source)

```
~/telechargements/
├── Films/
│   ├── Inception.2010.1080p.BluRay.x264.mkv
│   └── The.Matrix.1999.2160p.UHD.mkv
└── Series/
    ├── Breaking.Bad.S01E01.720p.mkv
    └── Game.of.Thrones.S08E06.1080p.mkv
```

#### Répertoire de stockage (destination physique)

```
~/Videos/stockage/
├── Films/
│   ├── Science-Fiction/
│   │   ├── I/
│   │   │   └── Inception (2010) French DTS-HD MA 5.1 H.265 2160p.mkv
│   │   └── M/
│   │       └── Matrix (The) (1999) French DTS 5.1 H.264 1080p.mkv
│   └── Action/
│       └── ...
└── Series/
    ├── B/
    │   └── Breaking Bad (2008)/
    │       └── Saison 01/
    │           └── Breaking Bad (2008) - S01E01 - Pilot - French AAC 2.0 H.264 720p.mkv
    └── G/
        └── Game of Thrones (2011)/
            └── Saison 08/
                └── ...
```

#### Répertoire vidéo (symlinks)

```
~/Videos/video/
├── Films/
│   └── ... (symlinks vers stockage/Films/)
└── Series/
    └── ... (symlinks vers stockage/Series/)
```

## Commandes

### Afficher la configuration

```bash
uv run cineorg info
```

### Workflow principal : traiter les nouveaux téléchargements

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

Le workflow `process` :
1. Scanne le répertoire de téléchargements
2. Extrait les métadonnées (titre, année, codec, résolution...)
3. Recherche les correspondances sur TMDB/TVDB
4. Valide automatiquement les matchs avec score ≥ 85%
5. Affiche les fichiers en attente de validation manuelle

### Voir les fichiers en attente

```bash
uv run cineorg pending
```

### Validation manuelle

```bash
# Validation interactive (un par un)
uv run cineorg validate manual

# Valider un fichier spécifique par son ID
uv run cineorg validate file <ID>

# Auto-valider tous les fichiers avec score ≥ 85%
uv run cineorg validate auto

# Afficher et exécuter le batch de transferts
uv run cineorg validate batch
```

Lors de la validation manuelle, vous pouvez :
- Sélectionner un candidat proposé
- Rechercher manuellement par titre
- Entrer un ID IMDB/TMDB/TVDB directement
- Passer le fichier pour plus tard
- Marquer comme "traitement manuel" (déplacé dans un dossier spécial)

### Importer une vidéothèque existante

Si vous avez déjà une vidéothèque organisée :

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
uv run cineorg enrich
```

### Maintenance

```bash
# Vérifier l'intégrité de la vidéothèque
uv run cineorg check

# Vérifier avec validation des hash (plus lent)
uv run cineorg check --verify-hash

# Rapport au format JSON
uv run cineorg check --json

# Réparer les symlinks cassés
uv run cineorg repair-links
```

## Workflow typique

### 1. Première utilisation

```bash
# 1. Configurer l'environnement
nano .env  # Éditer avec vos chemins et clés API

# 2. Vérifier la configuration
uv run cineorg info

# 3. Importer une vidéothèque existante (si applicable)
uv run cineorg import --dry-run  # Vérifier d'abord
uv run cineorg import

# 4. Enrichir avec les métadonnées API
uv run cineorg enrich
```

### 2. Usage quotidien

```bash
# Traiter les nouveaux téléchargements
uv run cineorg process

# Si des fichiers sont en attente de validation
uv run cineorg pending
uv run cineorg validate manual

# Transférer les fichiers validés
uv run cineorg validate batch
```

### 3. Maintenance périodique

```bash
# Vérifier l'intégrité
uv run cineorg check

# Réparer les symlinks si nécessaire
uv run cineorg repair-links
```

## Format de nommage

### Films

```
Titre (Année) Langue Codec-Audio Canaux Codec-Video Résolution.ext
```

Exemples :
- `Inception (2010) French DTS-HD MA 5.1 H.265 2160p.mkv`
- `Matrix (The) (1999) English DTS 5.1 H.264 1080p.mkv`
- `Amélie (2001) French AAC 2.0 H.264 720p.mp4`

### Séries

```
Titre (Année) - SxxExx - Titre Episode - Langue Codec-Audio Canaux Codec-Video Résolution.ext
```

Exemples :
- `Breaking Bad (2008) - S01E01 - Pilot - English AAC 2.0 H.264 720p.mkv`
- `Game of Thrones (2011) - S08E06 - The Iron Throne - French DTS 5.1 H.265 1080p.mkv`

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
4. Copier la clé "API Key (v3 auth)"

### TVDB (séries)

1. Créer un compte sur [thetvdb.com](https://thetvdb.com/)
2. Aller dans [API Information](https://thetvdb.com/api-information)
3. Créer un projet et récupérer l'API Key

## Options globales

```bash
# Mode verbeux (plus de détails)
uv run cineorg -v process
uv run cineorg -vv process  # Encore plus verbeux
uv run cineorg -vvv process # Maximum de détails

# Mode silencieux (erreurs uniquement)
uv run cineorg -q process
```

## Stack technique

- **Python 3.11+**
- **Typer + Rich** - Interface CLI interactive
- **SQLModel** - ORM (SQLite)
- **guessit** - Parsing des noms de fichiers
- **pymediainfo** - Extraction métadonnées techniques
- **httpx** - Client HTTP async pour les APIs
- **diskcache** - Cache des résultats API
- **tenacity** - Retry avec backoff exponentiel
- **rapidfuzz** - Scoring de similarité des titres

## Dépannage

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

### Base de données corrompue

```bash
# Sauvegarder et recréer
mv cineorg.db cineorg.db.backup
uv run cineorg import  # Réimporter la vidéothèque
```

## Licence

MIT
