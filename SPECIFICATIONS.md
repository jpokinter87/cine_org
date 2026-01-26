# CineOrg - Spécifications Techniques Complètes

> Document de référence pour le développement de l'application de gestion de vidéothèque personnelle.
> Version : 1.3 | Date : 2026-01-26

---

## Table des Matières

1. [Présentation du Projet](#1-présentation-du-projet)
2. [Stack Technique](#2-stack-technique)
3. [Architecture des Répertoires](#3-architecture-des-répertoires)
4. [Workflow de Traitement](#4-workflow-de-traitement)
5. [Système de Scoring](#5-système-de-scoring)
6. [Conventions de Nommage](#6-conventions-de-nommage)
7. [Organisation Alphabétique](#7-organisation-alphabétique)
8. [Hiérarchie des Genres](#8-hiérarchie-des-genres)
9. [Gestion des Langues](#9-gestion-des-langues)
10. [Base de Données](#10-base-de-données)
11. [APIs Externes](#11-apis-externes)
12. [Interface Web](#12-interface-web)
13. [Interface CLI](#13-interface-cli)
14. [Gestion des Erreurs](#14-gestion-des-erreurs)
15. [Cas Particuliers](#15-cas-particuliers)
16. [Évolutions Futures](#16-évolutions-futures)
17. [Structure du Code](#17-structure-du-code)
18. [Constantes et Configuration](#18-constantes-et-configuration)
19. [Gestion de l'Existant](#19-gestion-de-lexistant)

---

## 1. Présentation du Projet

### 1.1 Objectif

CineOrg est une application de gestion de vidéothèque personnelle permettant de :
- Scanner un répertoire de téléchargements contenant des fichiers vidéo
- Extraire les métadonnées via `guessit` et `mediainfo`
- Valider et enrichir les informations via les APIs TMDB (films) et TVDB (séries)
- Renommer les fichiers selon un format standardisé
- Organiser les fichiers dans une arborescence structurée par genre (films) ou alphabétique (séries)
- Créer des liens symboliques pour le mediacenter

### 1.2 Principes de Développement

- **TDD** (Test-Driven Development) - Les tests sont écrits AVANT le code
- **Couverture maximale** - Objectif ≥ 90% de couverture de code
- **DRY** (Don't Repeat Yourself)
- **SOLID** (Single Responsibility, Open/Closed, Liskov Substitution, Interface Segregation, Dependency Inversion)
- **Structure modulaire** avec séparation claire des responsabilités

### 1.3 Stratégie de Tests (TDD)

#### Cycle TDD

```
1. RED    → Écrire un test qui échoue
2. GREEN  → Écrire le minimum de code pour faire passer le test
3. REFACTOR → Améliorer le code en gardant les tests verts
```

#### Types de Tests

| Type | Objectif | Outils |
|------|----------|--------|
| **Unitaires** | Tester chaque fonction/classe isolément | pytest, unittest.mock |
| **Intégration** | Tester l'interaction entre modules | pytest, fixtures |
| **API** | Tester les endpoints FastAPI | pytest, httpx, TestClient |
| **E2E** | Tester le workflow complet | pytest |

#### Couverture Minimale par Module

| Module | Couverture Min | Priorité |
|--------|----------------|----------|
| `core/parser.py` | 95% | Critique |
| `core/matcher.py` | 95% | Critique |
| `core/organizer.py` | 90% | Haute |
| `core/renamer.py` | 95% | Critique |
| `core/importer.py` | 90% | Haute |
| `core/repair.py` | 90% | Haute |
| `api/tmdb.py` | 85% | Moyenne |
| `api/tvdb.py` | 85% | Moyenne |
| `db/repository.py` | 90% | Haute |
| `web/routes/*` | 80% | Moyenne |
| `cli/commands.py` | 80% | Moyenne |

#### Structure des Tests

```
tests/
├── conftest.py              # Fixtures globales
├── fixtures/                # Données de test
│   ├── sample_files/        # Fichiers vidéo factices
│   ├── api_responses/       # Réponses API mockées (JSON)
│   └── databases/           # BDD de test pré-remplies
├── unit/                    # Tests unitaires
│   ├── test_parser.py
│   ├── test_matcher.py
│   ├── test_renamer.py
│   ├── test_organizer.py
│   ├── test_importer.py
│   └── ...
├── integration/             # Tests d'intégration
│   ├── test_import_workflow.py
│   ├── test_process_workflow.py
│   └── test_repair_workflow.py
├── api/                     # Tests des endpoints
│   ├── test_dashboard.py
│   ├── test_validation.py
│   └── test_processing.py
└── e2e/                     # Tests end-to-end
    ├── test_full_import.py
    └── test_full_process.py
```

#### Fixtures Essentielles

```python
# conftest.py
import pytest
from pathlib import Path
from sqlmodel import SQLModel, create_engine, Session

@pytest.fixture
def temp_video_dir(tmp_path):
    """Crée une structure de répertoires vidéo temporaire."""
    video_dir = tmp_path / "video"
    (video_dir / "Films" / "Action" / "A").mkdir(parents=True)
    (video_dir / "Séries" / "A").mkdir(parents=True)
    return video_dir

@pytest.fixture
def temp_storage_dir(tmp_path):
    """Crée un répertoire de stockage temporaire."""
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    return storage_dir

@pytest.fixture
def test_db():
    """Crée une base de données en mémoire pour les tests."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

@pytest.fixture
def mock_tmdb_response():
    """Charge une réponse TMDB mockée."""
    return {
        "results": [{
            "id": 27205,
            "title": "Inception",
            "release_date": "2010-07-16",
            "runtime": 148,
            "genres": [{"id": 28, "name": "Action"}]
        }]
    }
```

#### Commandes de Test

```bash
# Lancer tous les tests
pytest

# Avec couverture
pytest --cov=src --cov-report=html --cov-report=term-missing

# Tests unitaires uniquement
pytest tests/unit/

# Tests d'un module spécifique
pytest tests/unit/test_parser.py -v

# Tests avec marqueur spécifique
pytest -m "slow"  # Tests lents
pytest -m "api"   # Tests API

# Vérifier la couverture minimale (échoue si < 90%)
pytest --cov=src --cov-fail-under=90
```

#### Règles TDD pour ce Projet

1. **Aucune fonctionnalité sans test** - Chaque nouvelle fonction doit avoir ses tests écrits en premier
2. **Tests de régression** - Chaque bug corrigé doit avoir un test qui le reproduit
3. **Mocking des APIs** - Jamais d'appels réels aux APIs TMDB/TVDB dans les tests
4. **Isolation** - Chaque test doit être indépendant et pouvoir s'exécuter seul
5. **Nommage explicite** - `test_parser_extracts_year_from_standard_format()`
6. **CI obligatoire** - Les tests doivent passer avant tout merge

---

## 2. Stack Technique

| Composant | Technologie | Justification |
|-----------|-------------|---------------|
| Langage | Python 3.11+ | Écosystème riche, guessit natif |
| Framework Web | FastAPI | Moderne, performant, async |
| Templates | Jinja2 + HTMX | Interactivité sans complexité JS |
| CLI | Typer | Type hints, même auteur FastAPI |
| ORM | SQLModel | Fusion SQLAlchemy + Pydantic |
| Base de données | SQLite | Simple, pas de serveur |
| Configuration | Pydantic Settings | Validation, typage fort |
| Parsing vidéo | guessit | Standard de l'industrie |
| Métadonnées | pymediainfo | Wrapper mediainfo |
| HTTP Client | httpx | Async, moderne |

### 2.1 Dépendances Principales

```
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
jinja2>=3.1.0
python-multipart>=0.0.6
typer[all]>=0.9.0
sqlmodel>=0.0.14
pydantic-settings>=2.1.0
guessit>=3.8.0
pymediainfo>=6.1.0
httpx>=0.26.0
aiofiles>=23.2.0
```

### 2.2 Dépendances de Développement et Tests

```
pytest>=8.0.0
pytest-cov>=4.1.0
pytest-asyncio>=0.23.0
pytest-mock>=3.12.0
respx>=0.20.0              # Mock HTTP pour httpx
factory-boy>=3.3.0         # Factories pour données de test
faker>=22.0.0              # Génération de données aléatoires
ruff>=0.1.0                # Linter rapide
mypy>=1.8.0                # Typage statique
pre-commit>=3.6.0          # Hooks pre-commit
```

---

## 3. Architecture des Répertoires

### 3.1 Répertoires de l'Application

| Répertoire | Rôle | Configurable |
|------------|------|--------------|
| `téléchargements/` | Fichiers bruts à traiter | Oui |
| `téléchargements/Films/` | Sous-répertoire films | Structure fixe |
| `téléchargements/Séries/` | Sous-répertoire séries | Structure fixe |
| `stockage/` | Fichiers physiques organisés | Oui |
| `vidéo/` | Liens symboliques uniquement | Oui |
| `traitement_manuel/` | Fichiers non résolus | Oui |
| `corbeille/` | Avant suppression définitive | Oui |

### 3.2 Structure du Stockage - Films

```
stockage/
└── Films/
    └── {Genre}/
        └── {Lettre}/
            └── {Sous-division}/    # Si > 50 fichiers
                └── {Fichier}.{ext}
```

**Exemple :**
```
stockage/Films/Science-Fiction/A/Aa-Am/Alien (1979) FR DTS x264 1080p.mkv
stockage/Films/Science-Fiction/A/An-Az/Avatar (2009) MULTi TrueHD x265 2160p.mkv
```

### 3.3 Structure du Stockage - Séries

```
stockage/
└── Séries/
    └── {Lettre}/
        └── {Sous-division}/        # Si > 50 dossiers
            └── {Titre} ({Année})/
                └── Saison {XX}/
                    └── {Fichier}.{ext}
```

**Exemple :**
```
stockage/Séries/A/Aa-Am/Altered Carbon (2018)/Saison 01/Altered Carbon (2018) - S01E01 - Out of the Past - EN AAC x264 1080p.mkv
```

### 3.4 Structure du Répertoire Vidéo (Symlinks)

Miroir exact de la structure de stockage, contenant uniquement des liens symboliques pointant vers les fichiers physiques du stockage.

---

## 4. Workflow de Traitement

### 4.1 Flux Principal

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. SCAN                                                                 │
│    - Parcours récursif de téléchargements/Films/ et téléchargements/Séries/│
│    - Filtrage : extensions vidéo (.mkv, .mp4, .avi, etc.)              │
│    - Filtrage : taille > 100 Mo (exclusion samples)                    │
│    - Exclusion : fichiers sample*, .nfo, .txt, images                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 2. PARSING                                                              │
│    - Extraction métadonnées via guessit (titre, année, saison, épisode)│
│    - Extraction infos techniques via mediainfo (codec, durée, langue)  │
│    - Détection type : film ou série (guessit + vérification répertoire)│
│    - Correction silencieuse si fichier mal placé                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 3. RECHERCHE API                                                        │
│    - Films : recherche TMDB par titre + année                          │
│    - Séries : recherche TVDB par titre                                 │
│    - Gestion rate limiting                                             │
│    - File d'attente si API indisponible                                │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 4. SCORING ET MATCHING                                                  │
│    - Calcul score de concordance pour chaque candidat                  │
│    - Si score ≥ 85% ET résultat unique → validation automatique        │
│    - Sinon → file d'attente validation manuelle                        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
        ┌───────────────────┐           ┌───────────────────┐
        │ VALIDATION AUTO   │           │ VALIDATION MANUELLE│
        │                   │           │                   │
        │ Score ≥ 85%       │           │ Interface web     │
        │ Résultat unique   │           │ Affichage 5 par 5 │
        │                   │           │ Poster + infos    │
        │                   │           │ Bande-annonce     │
        │                   │           │ Lecture fichier   │
        │                   │           │ Recherche manuelle│
        └───────────────────┘           └───────────────────┘
                    │                               │
                    └───────────────┬───────────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 5. VALIDATION FINALE                                                    │
│    - Présentation de TOUS les fichiers à traiter                       │
│    - Destination prévue pour chaque fichier                            │
│    - Possibilité de modifier titre/année/genre                         │
│    - Possibilité d'exclure des fichiers                                │
│    - Validation par l'utilisateur avant transfert                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 6. TRANSFERT                                                            │
│    - Vérification doublons (validation humaine si doublon détecté)     │
│    - Renommage selon format standardisé                                │
│    - Déplacement vers stockage (création sous-répertoires si besoin)   │
│    - Création lien symbolique dans vidéo                               │
│    - Enregistrement en base SQLite                                     │
│    - Suppression fichier source (ou répertoire source si vide)         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Mode d'Exécution

- **Exécution manuelle** uniquement (pas de daemon/watchdog)
- Via interface web ou CLI
- La validation se fait en parallèle/après coup (ne bloque pas le scan des autres fichiers)

---

## 5. Système de Scoring

### 5.1 Critères de Concordance (Films)

| Critère | Poids | Calcul |
|---------|-------|--------|
| Similarité titre | 50% | Algorithme de distance (Levenshtein, fuzzy matching) |
| Concordance année | 25% | 100% si exact, 75% si ±1 an, 25% si ±2 ans, 0% au-delà |
| Concordance durée | 25% | 100% si écart ≤ 5min, 50% si ≤ 10min, 0% au-delà |

### 5.2 Critères de Concordance (Séries)

| Critère | Poids | Calcul |
|---------|-------|--------|
| Similarité titre série | 100% | Algorithme de distance |

> Note : Pas de validation de durée pour les séries (durées variables par épisode).

### 5.3 Seuil de Validation Automatique

- **Score minimum** : 85%
- **Condition supplémentaire** : Résultat unique
- Si plusieurs résultats avec score ≥ 85% → validation manuelle

### 5.4 Formule de Calcul

```python
def calculate_score(guessit_data, api_result, mediainfo_data):
    title_score = fuzzy_match(guessit_data.title, api_result.title)

    year_diff = abs(guessit_data.year - api_result.year)
    if year_diff == 0:
        year_score = 1.0
    elif year_diff == 1:
        year_score = 0.75
    elif year_diff == 2:
        year_score = 0.25
    else:
        year_score = 0.0

    duration_diff = abs(mediainfo_data.duration - api_result.runtime)
    if duration_diff <= 5:
        duration_score = 1.0
    elif duration_diff <= 10:
        duration_score = 0.5
    else:
        duration_score = 0.0

    return (title_score * 0.50) + (year_score * 0.25) + (duration_score * 0.25)
```

---

## 6. Conventions de Nommage

### 6.1 Format Films

```
{Titre} ({Année}) {Langue} {CodecAudio} {CodecVideo} {Résolution}.{extension}
```

**Exemples :**
```
Inception (2010) MULTi DTS x265 1080p.mkv
Alien (1979) FR AC3 x264 720p.mkv
Avatar (2009) VOSTFR TrueHD x265 2160p.mkv
```

### 6.2 Format Séries

```
{Titre} ({Année}) - {SaisonEpisode} - {TitreEpisode} - {Langue} {CodecAudio} {CodecVideo} {Résolution}.{extension}
```

**Exemples :**
```
Breaking Bad (2008) - S01E01 - Pilot - VOSTFR AAC x264 720p.mkv
Altered Carbon (2018) - S01E01 - Out of the Past - EN AAC x264 1080p.mkv
Game of Thrones (2011) - S01E01E02 - Winter Is Coming - MULTi DTS x265 1080p.mkv
```

> Note : Si le titre de l'épisode n'est pas trouvé dans TVDB, il est omis.

### 6.3 Format Saison/Épisode

| Format | Exemple |
|--------|---------|
| Standard | S01E01 |
| Épisode double | S01E01E02 |
| Saison à 2 chiffres | S01, S12 |
| Épisode à 2 chiffres | E01, E99 |

### 6.4 Nettoyage des Titres

- Suppression caractères interdits : `/ \ : * ? " < > |`
- Remplacement par espace ou suppression
- Conservation des accents et caractères Unicode valides

---

## 7. Organisation Alphabétique

> **Note** : L'organisation alphabétique et la subdivision dynamique ne concernent **QUE le répertoire des symlinks** (`vidéo/`). Le répertoire de stockage (`stockage/`) conserve une structure figée et n'est jamais réorganisé.

### 7.1 Articles Ignorés pour le Tri

| Langue | Articles |
|--------|----------|
| Français | le, la, les, l', un, une, du, des, de la, au, aux |
| Anglais | the, a, an |
| Allemand | der, die, das, ein, eine |
| Espagnol | el, la, los, las, un, una |

**Exemples :**
```
"L'Arnacoeur" → classé sous "A" (Arnacoeur)
"The Matrix" → classé sous "M" (Matrix)
"Les Misérables" → classé sous "M" (Misérables)
```

### 7.2 Gestion des Accents

Les accents sont ignorés pour le classement alphabétique :
```
"Été meurtrier" → classé sous "E"
"Ça" → classé sous "C"
```

### 7.3 Subdivision Dynamique

- **Seuil** : 50 fichiers maximum par sous-répertoire
- **Déclenchement** : Création automatique de subdivisions quand le seuil est atteint
- **Format** : `{Première lettre}{première sous-lettre}-{Première lettre}{dernière sous-lettre}`
- **Exemple** : `A/Aa-Am/`, `A/An-Az/`

### 7.4 Algorithme de Subdivision

```python
def get_subdivision(title: str, existing_files: list) -> str:
    """Détermine le sous-répertoire approprié."""
    sort_key = get_sort_key(title)  # Supprime articles, normalise accents
    first_letter = sort_key[0].upper()

    # Compte les fichiers par première lettre
    if count_files_in_letter(first_letter) <= MAX_FILES_PER_SUBDIR:
        return first_letter

    # Subdivision nécessaire
    second_letter = sort_key[1].lower() if len(sort_key) > 1 else 'a'
    return find_or_create_subdivision(first_letter, second_letter)
```

---

## 8. Hiérarchie des Genres

### 8.1 Films - Ordre de Priorité

| Priorité | Genre | Notes |
|----------|-------|-------|
| 1 | Animation | Inclut anime |
| 2 | Science-Fiction | |
| 3 | Fantastique | Fantasy |
| 4 | Western | |
| 5 | Policier | |
| 6 | Thriller | |
| 7 | Guerre / Espionnage | |
| 8 | Action & Aventure | |
| 9 | Comédie dramatique | Si API renvoie Comédie + Drame |
| 10 | Comédie | |
| 11 | Drame | |
| 12 | Horreur | |

### 8.2 Règle de Sélection

1. Récupérer tous les genres de l'API
2. Cas spécial : si "Comédie" ET "Drame" → "Comédie dramatique"
3. Sinon : premier genre trouvé dans la hiérarchie

### 8.3 Séries

**Pas de classement par genre pour les séries** - uniquement classement alphabétique.

### 8.4 Mapping TMDB

```python
TMDB_GENRE_MAPPING = {
    16: "Animation",
    878: "Science-Fiction",
    14: "Fantastique",
    37: "Western",
    80: "Policier",
    53: "Thriller",
    10752: "Guerre",
    28: "Action",
    12: "Aventure",
    35: "Comédie",
    18: "Drame",
    27: "Horreur",
    10759: "Action & Aventure",  # TV
    10765: "Science-Fiction",    # TV (Sci-Fi & Fantasy)
}
```

---

## 9. Gestion des Langues

### 9.1 Codes Langue

Format : **ISO 639-1** (2 lettres majuscules)

| Code | Langue |
|------|--------|
| FR | Français |
| EN | Anglais |
| DE | Allemand |
| ES | Espagnol |
| IT | Italien |
| JA | Japonais |
| KO | Coréen |
| ZH | Chinois |

### 9.2 Cas Spéciaux

| Code | Signification | Détection |
|------|---------------|-----------|
| MULTi | Plusieurs pistes audio | mediainfo détecte > 1 piste audio |
| VOSTFR | VO + sous-titres français | Audio non-FR + sous-titres FR intégrés |

### 9.3 Logique de Détection

```python
def detect_language_code(mediainfo_data) -> str:
    audio_tracks = mediainfo_data.audio_tracks
    subtitle_tracks = mediainfo_data.subtitle_tracks

    # Plusieurs pistes audio
    if len(audio_tracks) > 1:
        return "MULTi"

    # VO + sous-titres français
    main_audio_lang = audio_tracks[0].language
    has_french_subs = any(s.language == "fr" for s in subtitle_tracks)

    if main_audio_lang != "fr" and has_french_subs:
        return "VOSTFR"

    # Langue unique
    return main_audio_lang.upper()
```

---

## 10. Base de Données

### 10.1 Schéma SQLite

```sql
-- Table des films
CREATE TABLE films (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tmdb_id INTEGER UNIQUE,
    imdb_id TEXT,
    title TEXT NOT NULL,
    original_title TEXT,
    year INTEGER,
    genre TEXT NOT NULL,
    synopsis TEXT,
    duration_minutes INTEGER,
    rating REAL,
    poster_url TEXT,
    trailer_url TEXT,

    -- Chemins fichiers
    file_path TEXT NOT NULL,
    symlink_path TEXT NOT NULL,
    original_filename TEXT,
    formatted_filename TEXT NOT NULL,

    -- Infos techniques
    codec_video TEXT,
    codec_audio TEXT,
    resolution TEXT,
    language TEXT,
    file_size_mb INTEGER,
    file_duration_minutes INTEGER,

    -- Métadonnées système
    match_score REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table des séries
CREATE TABLE series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tvdb_id INTEGER UNIQUE,
    imdb_id TEXT,
    title TEXT NOT NULL,
    original_title TEXT,
    year INTEGER,
    synopsis TEXT,
    poster_url TEXT,
    status TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table des épisodes
CREATE TABLE episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id INTEGER NOT NULL,
    tvdb_episode_id INTEGER,
    season_number INTEGER NOT NULL,
    episode_number INTEGER NOT NULL,
    episode_number_end INTEGER,  -- Pour épisodes doubles
    title TEXT,

    -- Chemins fichiers
    file_path TEXT NOT NULL,
    symlink_path TEXT NOT NULL,
    original_filename TEXT,
    formatted_filename TEXT NOT NULL,

    -- Infos techniques
    codec_video TEXT,
    codec_audio TEXT,
    resolution TEXT,
    language TEXT,
    file_size_mb INTEGER,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (series_id) REFERENCES series(id) ON DELETE CASCADE
);

-- File d'attente de validation
CREATE TABLE pending_validation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_type TEXT NOT NULL CHECK (media_type IN ('film', 'serie')),
    original_path TEXT NOT NULL,
    guessit_data TEXT,      -- JSON
    mediainfo_data TEXT,    -- JSON
    api_candidates TEXT,    -- JSON avec scores
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'validated', 'rejected', 'manual')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Corbeille
CREATE TABLE trash (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_path TEXT NOT NULL,
    trash_path TEXT NOT NULL,
    media_type TEXT,
    reason TEXT,
    metadata TEXT,  -- JSON sauvegarde des infos
    deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Collections (pour évolution future)
CREATE TABLE collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tmdb_collection_id INTEGER UNIQUE,
    name TEXT NOT NULL,
    poster_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE film_collections (
    film_id INTEGER NOT NULL,
    collection_id INTEGER NOT NULL,
    position INTEGER,
    PRIMARY KEY (film_id, collection_id),
    FOREIGN KEY (film_id) REFERENCES films(id) ON DELETE CASCADE,
    FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
);

-- Index pour performances
CREATE INDEX idx_films_tmdb ON films(tmdb_id);
CREATE INDEX idx_films_genre ON films(genre);
CREATE INDEX idx_films_year ON films(year);
CREATE INDEX idx_films_title ON films(title);
CREATE INDEX idx_series_tvdb ON series(tvdb_id);
CREATE INDEX idx_series_title ON series(title);
CREATE INDEX idx_episodes_series ON episodes(series_id);
CREATE INDEX idx_episodes_season ON episodes(series_id, season_number);
CREATE INDEX idx_pending_status ON pending_validation(status);
CREATE INDEX idx_trash_date ON trash(deleted_at);
```

---

## 11. APIs Externes

### 11.1 TMDB (The Movie Database)

**Usage** : Films uniquement

| Endpoint | Usage |
|----------|-------|
| `/search/movie` | Recherche par titre |
| `/movie/{id}` | Détails du film |
| `/movie/{id}/videos` | Bandes-annonces |

**Rate Limiting** : ~40 requêtes/10 secondes

### 11.2 TVDB (The TV Database)

**Usage** : Séries uniquement

| Endpoint | Usage |
|----------|-------|
| `/search` | Recherche par titre |
| `/series/{id}` | Détails de la série |
| `/series/{id}/episodes` | Liste des épisodes |

**Rate Limiting** : Authentification requise, limites variables

### 11.3 Gestion des Erreurs API

| Situation | Action |
|-----------|--------|
| Rate limit atteint | Pause + retry avec backoff exponentiel |
| API indisponible | File d'attente, notification utilisateur |
| Indisponibilité persistante | Message d'erreur, arrêt du programme |
| Aucun résultat | Fichier → traitement_manuel/ avec symlink créé |

### 11.4 Cache Local

- Mise en cache des résultats de recherche (24h)
- Mise en cache des détails de films/séries (7 jours)
- Stockage en base SQLite ou fichiers JSON

---

## 12. Interface Web

### 12.1 Stack Frontend

- **FastAPI** : Backend API
- **Jinja2** : Templates HTML
- **HTMX** : Interactivité sans JavaScript complexe
- **CSS** : Style simple (Pico CSS ou similaire)

### 12.2 Pages Principales

| Route | Description |
|-------|-------------|
| `/` | Tableau de bord |
| `/process` | Lancement du traitement |
| `/validation` | File d'attente validation manuelle |
| `/validation/{id}` | Validation d'un fichier spécifique |
| `/review` | Validation finale avant transfert |
| `/config` | Configuration des chemins et paramètres |
| `/stats` | Statistiques de la vidéothèque |

### 12.3 Tableau de Bord

- Nombre total de films / séries
- Répartition par genre
- Derniers ajouts
- Fichiers en attente de validation
- Fichiers en traitement manuel

### 12.4 Page de Validation Manuelle

- Affichage des candidats 5 par 5
- Pour chaque candidat :
  - Poster (image)
  - Titre + année
  - Synopsis
  - Durée
  - Note TMDB/TVDB
  - Genres
  - Lien bande-annonce YouTube
- Bouton "Lancer le fichier vidéo" (lecteur système par défaut)
- Bouton "Recherche manuelle" :
  - Champ recherche libre par titre
  - Champ saisie ID IMDB (dernier recours)
- Boutons : Valider / Rejeter / Passer

### 12.5 Page de Validation Finale

- Liste de tous les fichiers traités dans le batch
- Pour chaque fichier :
  - Nom original
  - Nom formaté proposé
  - Destination prévue (chemin complet)
  - Checkbox pour inclure/exclure
  - Bouton édition rapide (titre, année, genre)
- Bouton "Valider et transférer"
- Bouton "Annuler"

### 12.6 Persistance de Session

Si l'utilisateur ferme l'interface sans valider :
- État sauvegardé en base (table pending_validation)
- Reprise possible au prochain lancement

---

## 13. Interface CLI

### 13.1 Framework

**Typer** - CLI moderne basé sur les type hints Python

### 13.2 Commandes

```bash
# Lancer le traitement complet
cineorg process [--auto] [--dry-run]

# Lancer uniquement le scan (sans transfert)
cineorg scan

# Afficher les fichiers en attente de validation
cineorg pending

# Valider un fichier spécifique
cineorg validate <id>

# Afficher les statistiques
cineorg stats

# Lancer le serveur web
cineorg serve [--host HOST] [--port PORT]

# Vérifier la configuration
cineorg config show

# Modifier la configuration
cineorg config set <key> <value>

# Réparer les liens symboliques cassés
cineorg repair-links

# Vider la corbeille
cineorg empty-trash [--older-than DAYS]

# Importer la vidéothèque existante dans la base de données
cineorg import [--dry-run]

# Enrichir les métadonnées via API (avec rate limiting)
cineorg enrich [--batch-size 50] [--delay 2] [--continue] [--type films|series]

# Gérer les symlinks cassés
cineorg repair-links --analyze      # Analyser et afficher le rapport
cineorg repair-links --fix          # Réparer automatiquement les réparables
cineorg repair-links --list-manual  # Lister ceux nécessitant intervention
cineorg repair-links --clean        # Supprimer les irréparables (avec confirmation)

# Analyser et réorganiser les répertoires (subdivision)
cineorg reorganize [--dry-run] [--report-only]

# Vérifier l'intégrité de la vidéothèque
cineorg check [--fix]

# Afficher les rapports de réorganisation
cineorg reports [--last N]
```

### 13.3 Options Globales

```bash
--verbose, -v    # Mode verbeux
--config FILE    # Fichier de configuration alternatif
--dry-run        # Simulation sans modification
```

---

## 14. Gestion des Erreurs

### 14.1 Niveaux de Log

| Niveau | Usage |
|--------|-------|
| DEBUG | Développement uniquement |
| INFO | Actions principales (fichier traité, transfert effectué) |
| WARNING | Situations anormales non bloquantes |
| ERROR | Erreurs récupérables |
| CRITICAL | Erreurs fatales, arrêt du programme |

### 14.2 Fichier de Log

- Emplacement : `logs/cineorg.log`
- Rotation : quotidienne ou par taille (10 Mo)
- Rétention : 30 jours

### 14.3 Cas d'Erreur

| Erreur | Action |
|--------|--------|
| Fichier corrompu / illisible | → traitement_manuel/ |
| guessit échoue à parser | → traitement_manuel/ |
| API indisponible | File d'attente + notification |
| Aucune correspondance API | → traitement_manuel/ (symlink créé) |
| Doublon détecté | Validation humaine obligatoire |
| Espace disque insuffisant | Erreur critique, arrêt |
| Erreur écriture fichier | Erreur critique, arrêt |

### 14.4 Notifications

| Événement | Canal |
|-----------|-------|
| Fichier nécessite validation | Interface web ou CLI |
| Erreur critique | Message + arrêt programme |
| Traitement terminé | Résumé (X auto, Y manuels, Z erreurs) |

---

## 15. Cas Particuliers

### 15.1 Doublons

**Détection** :
- Même TMDB ID / TVDB ID
- Ou même titre + année + type

**Action** :
1. Notification utilisateur
2. Choix : garder ancien / garder nouveau / garder les deux
3. Fichier non retenu → corbeille/

### 15.2 Épisodes Doubles

- Format détecté : `S01E01E02`, `S01E01-E02`
- Nommage conservé : `S01E01E02`
- Titre : celui du premier épisode (ou combinaison si disponible)

### 15.3 Saisons Complètes

- Traitement par lot
- Une seule validation pour la série
- Récupération automatique de tous les titres d'épisodes
- Si titre épisode manquant → omis du nom de fichier

### 15.4 Fichiers dans Sous-Répertoires

```
Téléchargements/Films/
    Inception.2010.1080p.BluRay/
        Inception.2010.1080p.BluRay.mkv  ← Traité
        Sample.mkv                        ← Ignoré (sample)
        Inception.nfo                     ← Ignoré
```

- Scan récursif
- Seul le fichier vidéo principal (> 100 Mo, pas "sample") est traité
- Répertoire source supprimé si vide après traitement

### 15.5 Fichier Mal Placé

- Série dans `Films/` ou film dans `Séries/`
- Détection via guessit
- Correction silencieuse et automatique

### 15.6 Réparation des Liens Symboliques

- Vérification périodique ou à la demande
- Si fichier source déplacé/renommé → mise à jour du symlink
- Si fichier source supprimé → notification + symlink cassé signalé

---

## 16. Évolutions Futures

### 16.1 Prévues dans l'Architecture

| Fonctionnalité | Préparation |
|----------------|-------------|
| Intégration anime (AniDB/MAL) | Interface `MediaAPIClient` extensible |
| Collections (sagas, univers) | Tables `collections` et `film_collections` |

### 16.2 Non Prévues

- Recherche/filtrage dans l'interface web
- Génération de fichiers poster.jpg/fanart.jpg

---

## 17. Structure du Code

### 17.1 Arborescence

```
cine_org/
├── config/
│   └── config.json
├── src/
│   ├── __init__.py
│   ├── main.py                  # Point d'entrée CLI
│   │
│   ├── core/                    # Logique métier
│   │   ├── __init__.py
│   │   ├── scanner.py           # Scan répertoire téléchargements
│   │   ├── parser.py            # Extraction métadonnées
│   │   ├── matcher.py           # Scoring et correspondance
│   │   ├── renamer.py           # Génération noms formatés
│   │   ├── organizer.py         # Gestion arborescence
│   │   ├── transferer.py        # Déplacement + symlinks
│   │   ├── duplicate_checker.py # Détection doublons
│   │   └── orchestrator.py      # Coordination workflow
│   │
│   ├── api/                     # Clients API externes
│   │   ├── __init__.py
│   │   ├── base.py              # Interface abstraite
│   │   ├── tmdb.py              # Client TMDB
│   │   ├── tvdb.py              # Client TVDB
│   │   └── anidb.py             # Client AniDB (futur)
│   │
│   ├── db/                      # Couche données
│   │   ├── __init__.py
│   │   ├── database.py          # Connexion SQLite
│   │   ├── models.py            # Modèles SQLModel
│   │   └── repository.py        # Accès données
│   │
│   ├── web/                     # Interface web
│   │   ├── __init__.py
│   │   ├── app.py               # Application FastAPI
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── dashboard.py
│   │   │   ├── validation.py
│   │   │   ├── processing.py
│   │   │   └── config.py
│   │   ├── templates/           # Templates Jinja2
│   │   │   ├── base.html
│   │   │   ├── dashboard.html
│   │   │   ├── validation.html
│   │   │   └── ...
│   │   └── static/
│   │       ├── css/
│   │       └── js/
│   │
│   ├── cli/                     # Interface CLI
│   │   ├── __init__.py
│   │   └── commands.py          # Commandes Typer
│   │
│   └── utils/                   # Utilitaires
│       ├── __init__.py
│       ├── logger.py
│       ├── constants.py
│       └── helpers.py
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Fixtures pytest
│   ├── test_scanner.py
│   ├── test_parser.py
│   ├── test_matcher.py
│   ├── test_organizer.py
│   └── ...
│
├── logs/
├── requirements.txt
├── pyproject.toml
└── README.md
```

### 17.2 Principes SOLID Appliqués

| Principe | Application |
|----------|-------------|
| **S**ingle Responsibility | Chaque module a une responsabilité unique |
| **O**pen/Closed | `MediaAPIClient` extensible pour nouveaux providers |
| **L**iskov Substitution | Tous les clients API interchangeables |
| **I**nterface Segregation | Interfaces minimales et ciblées |
| **D**ependency Inversion | Injection de dépendances, pas de couplage fort |

---

## 18. Constantes et Configuration

### 18.1 Fichier config.json

```json
{
  "paths": {
    "downloads": "/path/to/downloads",
    "storage": "/path/to/storage",
    "video": "/path/to/video",
    "manual": "/path/to/manual",
    "trash": "/path/to/trash"
  },
  "api": {
    "tmdb_api_key": "your_tmdb_api_key",
    "tvdb_api_key": "your_tvdb_api_key"
  },
  "processing": {
    "min_file_size_mb": 100,
    "max_files_per_subdir": 50,
    "match_score_threshold": 85,
    "auto_process": false
  },
  "logging": {
    "level": "INFO",
    "file": "logs/cineorg.log"
  }
}
```

### 18.2 Constantes (constants.py)

```python
# Extensions vidéo supportées
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"}

# Patterns à ignorer
IGNORED_PATTERNS = ["sample", "trailer", "preview", "extras", "bonus"]
IGNORED_EXTENSIONS = {".nfo", ".txt", ".jpg", ".png", ".srt", ".sub", ".idx"}

# Hiérarchie des genres
GENRE_HIERARCHY = [
    "Animation",
    "Science-Fiction",
    "Fantastique",
    "Western",
    "Policier",
    "Thriller",
    "Guerre",
    "Espionnage",
    "Action",
    "Aventure",
    "Comédie",
    "Drame",
    "Horreur",
]

# Articles ignorés pour le tri
IGNORED_ARTICLES = {
    "fr": ["le", "la", "les", "l'", "un", "une", "du", "des", "de la", "au", "aux"],
    "en": ["the", "a", "an"],
    "de": ["der", "die", "das", "ein", "eine"],
    "es": ["el", "la", "los", "las", "un", "una"],
}

# Mapping genres TMDB
TMDB_GENRE_MAPPING = {
    16: "Animation",
    878: "Science-Fiction",
    14: "Fantastique",
    37: "Western",
    80: "Policier",
    53: "Thriller",
    10752: "Guerre",
    28: "Action",
    12: "Aventure",
    35: "Comédie",
    18: "Drame",
    27: "Horreur",
}

# Codecs normalisés
AUDIO_CODECS = {
    "aac": "AAC",
    "ac3": "AC3",
    "ac-3": "AC3",
    "dts": "DTS",
    "dts-hd": "DTS-HD",
    "truehd": "TrueHD",
    "flac": "FLAC",
    "mp3": "MP3",
}

VIDEO_CODECS = {
    "h264": "x264",
    "avc": "x264",
    "x264": "x264",
    "h265": "x265",
    "hevc": "x265",
    "x265": "x265",
    "av1": "AV1",
    "vp9": "VP9",
}

# Poids pour le scoring
SCORE_WEIGHTS = {
    "title_similarity": 0.50,
    "year_match": 0.25,
    "duration_match": 0.25,
}
```

---

## 19. Gestion de l'Existant

### 19.1 Contexte

Le programme doit s'adapter à une vidéothèque existante :
- **Structure existante** : respecte déjà le format décrit (Films/Genre/Lettre/... et Séries/Lettre/...)
- **Symlinks** : déjà nommés selon le format standardisé
- **Fichiers cibles (stockage)** : noms potentiellement non standardisés (historique)
- **Base de données** : inexistante, import nécessaire

### 19.2 Principe Fondamental

> **IMPORTANT** : Les opérations de réorganisation (subdivision, déplacement) ne concernent **QUE le répertoire des symlinks** (`vidéo/`). Le répertoire de stockage (`stockage/`) n'est **JAMAIS** modifié par ces opérations.

Cela simplifie les opérations :
- Déplacement de liens symboliques (quelques octets) vs fichiers volumineux
- Pas de risque de corruption des fichiers sources
- Rapidité d'exécution

### 19.3 Import de l'Existant

L'import est une **opération unique** pour créer la base de données initiale à partir de la vidéothèque existante.

#### Commande

```bash
cineorg import [--dry-run]
```

| Option | Description |
|--------|-------------|
| `--dry-run` | Simulation sans modification de la base |

> **Note** : L'enrichissement via API est une opération **séparée** (voir section 19.3.4) pour éviter de surcharger les APIs lors de l'import initial.

#### 19.3.1 Processus d'Import

```
PHASE 1 : SCAN ET IMPORT
─────────────────────────
1. SCAN DU RÉPERTOIRE VIDÉO (symlinks)
   - Parcours récursif de vidéo/Films/ et vidéo/Séries/
   - Identification de tous les symlinks existants

2. POUR CHAQUE SYMLINK
   a. Vérifier si la cible existe
   b. Si OUI :
      - Parser le nom du symlink (format standardisé) → titre, année, langue, codec, résolution
      - Suivre le symlink vers le fichier cible
      - Extraire infos techniques via mediainfo (durée, taille, pistes audio/sous-titres)
      - Déterminer le type (film/série) selon l'emplacement
      - Enregistrer en base de données
   c. Si NON :
      - Enregistrer dans la table broken_symlinks
      - NE PAS supprimer (approche prudente)

PHASE 2 : TENTATIVE DE RÉPARATION AUTOMATIQUE
─────────────────────────────────────────────
3. POUR CHAQUE SYMLINK CASSÉ
   a. Extraire le nom du fichier attendu depuis le chemin cible
   b. Rechercher ce nom dans le répertoire stockage/ (récursivement)
   c. Si trouvé :
      - Marquer comme "repairable" dans broken_symlinks
      - Stocker le nouveau chemin trouvé (found_target)
   d. Si non trouvé :
      - Marquer comme "manual" (intervention humaine requise)

PHASE 3 : RAPPORT
─────────────────
4. GÉNÉRATION DU RAPPORT D'IMPORT
   - Nombre de films importés avec succès
   - Nombre de séries/épisodes importés
   - Nombre de symlinks cassés :
     - Réparables automatiquement
     - Nécessitant intervention manuelle
   - Fichiers non parsables (noms non conformes)
```

#### 19.3.2 Table des Symlinks Cassés

```sql
CREATE TABLE broken_symlinks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symlink_path TEXT NOT NULL,           -- Chemin du symlink cassé
    expected_target TEXT NOT NULL,        -- Chemin cible original (inexistant)
    expected_filename TEXT NOT NULL,      -- Nom du fichier attendu
    found_target TEXT,                    -- Chemin trouvé (si recherche OK)
    status TEXT DEFAULT 'broken'          -- broken, repairable, repaired, manual
        CHECK (status IN ('broken', 'repairable', 'repaired', 'manual')),
    error_message TEXT,                   -- Message d'erreur détaillé
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP                 -- Date de résolution
);

CREATE INDEX idx_broken_status ON broken_symlinks(status);
```

#### 19.3.3 Réparation des Symlinks Cassés

Après l'import, les symlinks cassés peuvent être traités avec des commandes dédiées :

```bash
# Analyser les symlinks cassés (affiche le rapport)
cineorg repair-links --analyze

# Réparer automatiquement ceux qui ont été trouvés
cineorg repair-links --fix

# Lister ceux qui nécessitent intervention manuelle
cineorg repair-links --list-manual

# Supprimer les symlinks irréparables (après confirmation interactive)
cineorg repair-links --clean
```

**Workflow de réparation :**

```
1. cineorg repair-links --analyze
   → Affiche :
     - X symlinks réparables automatiquement
     - Y symlinks nécessitant intervention manuelle
     - Détails pour chaque symlink cassé

2. cineorg repair-links --fix
   → Pour chaque symlink "repairable" :
     - Met à jour le symlink pour pointer vers found_target
     - Met à jour le statut → "repaired"
     - Importe le fichier en base de données
   → Rapport des réparations effectuées

3. (Optionnel) Intervention manuelle
   → L'utilisateur localise/restaure les fichiers manquants
   → Relance cineorg repair-links --analyze

4. cineorg repair-links --clean
   → Liste les symlinks toujours en statut "manual"
   → Demande confirmation pour chaque suppression
   → Supprime et enregistre dans la corbeille
```

**Recherche des fichiers perdus :**
- Recherche **uniquement** dans le répertoire `stockage/`
- Recherche récursive par nom de fichier exact
- Pas de recherche approximative (trop risqué)

#### 19.3.4 Enrichissement API (Séparé)

L'enrichissement via les APIs TMDB/TVDB est une opération **distincte** de l'import pour :
- Éviter de surcharger les APIs avec des milliers de requêtes
- Permettre la reprise en cas d'interruption
- Contrôler finement le rate limiting

```bash
# Enrichir les entrées sans ID API (avec rate limiting)
cineorg enrich [--batch-size 50] [--delay 2] [--continue]

# Enrichir uniquement les films
cineorg enrich --type films

# Enrichir uniquement les séries
cineorg enrich --type series
```

| Option | Description | Défaut |
|--------|-------------|--------|
| `--batch-size` | Nombre de requêtes avant pause | 50 |
| `--delay` | Pause en secondes entre les batchs | 2 |
| `--continue` | Reprendre là où on s'est arrêté | - |
| `--type` | Filtrer par type (films/series) | tous |

**Processus d'enrichissement :**

```
1. Sélectionner les entrées sans tmdb_id/tvdb_id
2. Pour chaque entrée (par batch) :
   a. Recherche API par titre + année
   b. Si correspondance unique avec score ≥ 85% → enrichissement auto
   c. Sinon → marquer pour validation manuelle
   d. Pause entre les batchs (rate limiting)
3. Possibilité d'interrompre et reprendre (--continue)
4. Rapport final :
   - X enrichis automatiquement
   - Y en attente de validation manuelle
   - Z erreurs API
```

**Stockage de la progression :**

```sql
-- Ajout d'une colonne pour suivre l'enrichissement
ALTER TABLE films ADD COLUMN enrichment_status TEXT DEFAULT 'pending'
    CHECK (enrichment_status IN ('pending', 'enriched', 'manual', 'error'));

ALTER TABLE series ADD COLUMN enrichment_status TEXT DEFAULT 'pending'
    CHECK (enrichment_status IN ('pending', 'enriched', 'manual', 'error'));
```

#### 19.3.5 Gestion des Noms Non Conformes

Si le nom du symlink ne peut pas être parsé :
1. Tentative de parsing via guessit sur le nom du fichier cible
2. Si succès → import avec les données extraites
3. Si échec → ajout à une table `unparseable_files` pour traitement manuel
4. Log détaillé pour analyse

```sql
CREATE TABLE unparseable_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symlink_path TEXT NOT NULL,
    target_path TEXT,
    symlink_name TEXT NOT NULL,
    target_name TEXT,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 19.4 Réorganisation et Subdivision

#### Principe

La subdivision intervient dans deux cas :
1. **Automatiquement** : lors du placement d'un nouveau symlink, si le répertoire cible dépasse 50 éléments
2. **À la demande** : via la commande `cineorg reorganize`

#### Commande Dédiée

```bash
cineorg reorganize [--dry-run] [--report-only]
```

| Option | Description |
|--------|-------------|
| `--dry-run` | Simulation sans modification |
| `--report-only` | Affiche uniquement les répertoires à subdiviser |

#### Algorithme de Subdivision Automatique

```python
def place_symlink(symlink_name: str, target_dir: Path) -> Path:
    """
    Place un symlink dans le bon répertoire, avec subdivision si nécessaire.
    Opère UNIQUEMENT sur le répertoire vidéo (symlinks).
    """
    # Compter les éléments actuels dans le répertoire cible
    current_count = count_items(target_dir)

    if current_count < MAX_FILES_PER_SUBDIR:
        # Pas de subdivision nécessaire
        return target_dir / symlink_name

    # Subdivision nécessaire
    sort_key = get_sort_key(symlink_name)  # Normalise le titre
    first_letter = sort_key[0].upper()
    second_letter = sort_key[1].lower() if len(sort_key) > 1 else 'a'

    # Trouver ou créer la subdivision appropriée
    subdivision = find_or_create_subdivision(target_dir, first_letter, second_letter)

    # Si c'est une nouvelle subdivision, redistribuer les symlinks existants
    if is_new_subdivision(subdivision):
        redistribute_symlinks(target_dir, first_letter)
        update_database_paths()
        generate_subdivision_report()

    return subdivision / symlink_name
```

#### Processus de Redistribution

Quand une subdivision est créée (ex: `A/` → `A/Aa-Am/` + `A/An-Az/`) :

```
1. ANALYSE
   - Lister tous les symlinks dans le répertoire parent (A/)
   - Calculer la clé de tri pour chaque symlink
   - Déterminer la subdivision cible pour chacun

2. CRÉATION DES SUBDIVISIONS
   - Créer les sous-répertoires nécessaires (Aa-Am/, An-Az/)
   - Les limites sont calculées pour équilibrer la distribution

3. DÉPLACEMENT DES SYMLINKS
   - Déplacer chaque symlink vers sa subdivision
   - Les symlinks restent valides (chemins relatifs vers stockage inchangés)

4. MISE À JOUR BASE DE DONNÉES
   - Mettre à jour symlink_path pour chaque entrée concernée

5. GÉNÉRATION DU RAPPORT
   - Liste des symlinks déplacés
   - Anciennes et nouvelles destinations
   - Timestamp de l'opération
```

#### Calcul des Limites de Subdivision

```python
def calculate_subdivision_ranges(items: list[str], max_per_subdir: int) -> list[tuple]:
    """
    Calcule les plages de subdivision optimales.
    Ex: ['Aa-Al', 'Am-Az'] pour répartir équitablement.
    """
    # Trier par clé de tri (sans articles, accents normalisés)
    sorted_items = sorted(items, key=get_sort_key)

    # Diviser en groupes de taille max_per_subdir
    subdivisions = []
    for i in range(0, len(sorted_items), max_per_subdir):
        group = sorted_items[i:i + max_per_subdir]
        first_key = get_sort_key(group[0])[:2]
        last_key = get_sort_key(group[-1])[:2]
        subdivisions.append((first_key, last_key))

    return subdivisions
```

### 19.5 Rapports de Réorganisation

#### Format du Rapport

```
================================================================================
RAPPORT DE RÉORGANISATION - 2026-01-26 14:32:15
================================================================================

RÉPERTOIRE CONCERNÉ : vidéo/Films/Science-Fiction/A/

RAISON : Dépassement du seuil (52 fichiers, max: 50)

SUBDIVISIONS CRÉÉES :
  - Aa-Al/ (26 fichiers)
  - Am-Az/ (26 fichiers)

SYMLINKS DÉPLACÉS :
  [1/52] Alien (1979) FR DTS x264 1080p.mkv
         A/ → Aa-Al/
  [2/52] Aliens (1986) MULTi AC3 x264 720p.mkv
         A/ → Aa-Al/
  ...
  [27/52] Avatar (2009) MULTi TrueHD x265 2160p.mkv
          A/ → Am-Az/
  ...

BASE DE DONNÉES : 52 entrées mises à jour

DURÉE : 0.8 secondes

================================================================================
```

#### Stockage des Rapports

- Emplacement : `logs/reorganization/`
- Format : `reorganization_YYYYMMDD_HHMMSS.txt`
- Rétention : 90 jours

### 19.6 Commandes CLI Additionnelles

```bash
# Importer la vidéothèque existante (opération unique)
cineorg import [--dry-run]

# Enrichir via API (après import, avec rate limiting)
cineorg enrich [--batch-size 50] [--delay 2] [--continue] [--type films|series]

# Gérer les symlinks cassés
cineorg repair-links --analyze       # Analyser et afficher le rapport
cineorg repair-links --fix           # Réparer automatiquement
cineorg repair-links --list-manual   # Lister ceux nécessitant intervention
cineorg repair-links --clean         # Supprimer les irréparables (confirmation)

# Analyser et réorganiser les répertoires
cineorg reorganize [--dry-run] [--report-only]

# Vérifier l'intégrité de la vidéothèque
cineorg check [--fix]
  # Vérifie : symlinks cassés, cohérence BDD, répertoires > 50 fichiers

# Afficher les rapports
cineorg reports [--last N] [--type import|reorganization|repair]
```

### 19.7 Workflow Intégré

Lors d'un traitement standard (`cineorg process`), la subdivision est intégrée :

```
1. Scan des téléchargements
2. Parsing et matching API
3. Validation (auto ou manuelle)
4. Pour chaque fichier validé :
   a. Transfert vers stockage (création du fichier)
   b. Détermination du répertoire symlink cible
   c. Vérification du seuil de 50 fichiers
   d. Si dépassement → subdivision automatique (silencieuse)
   e. Création du symlink
   f. Enregistrement en BDD
5. Rapport final (inclut les subdivisions effectuées)
```

### 19.8 Structure du Module

```
src/core/
├── importer.py           # Import de l'existant
│   ├── scan_existing()
│   ├── parse_symlink_name()
│   ├── import_valid_symlinks()
│   ├── collect_broken_symlinks()
│   └── save_to_database()
├── enricher.py           # Enrichissement API (séparé)
│   ├── enrich_films()
│   ├── enrich_series()
│   ├── batch_process()
│   └── save_progress()
├── repair.py             # Réparation des symlinks cassés
│   ├── analyze_broken()
│   ├── search_in_storage()
│   ├── fix_repairable()
│   └── clean_irrecoverable()
├── reorganizer.py        # Logique de subdivision
│   ├── check_threshold()
│   ├── calculate_subdivisions()
│   ├── redistribute_symlinks()
│   └── generate_report()
└── integrity.py          # Vérifications d'intégrité
    ├── check_broken_symlinks()
    ├── check_database_consistency()
    └── check_directory_thresholds()
```

---

## Annexe : Commandes de Développement

```bash
# Installation des dépendances
pip install -r requirements.txt

# Lancer les tests
pytest

# Lancer le serveur de développement
uvicorn src.web.app:app --reload

# Lancer le CLI
python -m src.main --help

# Créer la base de données
python -m src.db.database init
```

---

*Document généré le 2026-01-26 - CineOrg v1.0*
