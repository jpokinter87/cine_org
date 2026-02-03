# TODO - Fonctionnalités futures

## v2.0 - Interface Web

### Interface Web FastAPI
- **Priorité** : Haute
- **Statut** : À faire
- **Description** : Commande `serve` pour lancer l'interface web avec FastAPI + Jinja2 + HTMX

### Dashboard statistiques vidéothèque
- **Priorité** : Haute
- **Statut** : À faire
- **Description** : Vue d'ensemble de la vidéothèque (nombre de films/séries, répartition par genre, espace disque, etc.)

### Validation manuelle avec posters et bandes-annonces
- **Priorité** : Haute
- **Statut** : À faire
- **Description** : Affichage des posters TMDB/TVDB et liens vers les bandes-annonces YouTube pour faciliter l'identification

### Page de validation finale visuelle
- **Priorité** : Moyenne
- **Statut** : À faire
- **Description** : Confirmation visuelle avec aperçu des fichiers et destinations avant transfert batch

---

## Enrichissement des données

### 📊 Ajout des notes TMDB dans la base de données

**Statut** : À IMPLÉMENTER
**Priorité** : Moyenne
**Complexité** : Faible
**Dépendances** : Aucune (API TMDB retourne déjà ces données)

#### Description

Ajouter les notes et nombre de votes TMDB aux entités `Movie` et `Series` pour permettre des recherches avancées basées sur la popularité et la qualité des contenus.

#### Cas d'usage

Recherches avancées sur la vidéothèque :
- "Films de SF des années 90 avec une note > 8.0"
- "Films cultes (>10000 votes) peu connus (<7.0)"
- "Meilleurs films d'action toutes époques (>8.0)"
- Trier la vidéothèque par note décroissante
- Filtrer les films "sûrs" pour une soirée (>7.5)

#### Modifications nécessaires

##### 1. Modèles de données (`src/core/entities/media.py`)

```python
@dataclass
class Movie:
    # ... champs existants ...
    vote_average: Optional[float] = None  # Note moyenne /10 (ex: 8.4)
    vote_count: Optional[int] = None      # Nombre de votes (ex: 32000)

@dataclass
class Series:
    # ... champs existants ...
    vote_average: Optional[float] = None
    vote_count: Optional[int] = None
```

##### 2. Interface API (`src/core/ports/api_clients.py`)

```python
@dataclass
class MediaDetails:
    # ... champs existants ...
    vote_average: Optional[float] = None
    vote_count: Optional[int] = None
```

##### 3. Client TMDB (`src/adapters/api/tmdb_client.py`)

Extraire `vote_average` et `vote_count` des réponses API :
```python
# Dans get_details()
vote_average = data.get("vote_average")
vote_count = data.get("vote_count")
```

##### 4. Migration de base de données

Ajouter les colonnes dans les tables `movies` et `series` :
```sql
ALTER TABLE movies ADD COLUMN vote_average REAL;
ALTER TABLE movies ADD COLUMN vote_count INTEGER;
ALTER TABLE series ADD COLUMN vote_average REAL;
ALTER TABLE series ADD COLUMN vote_count INTEGER;
```

##### 5. Tests

- Mettre à jour les fixtures (`tests/fixtures/tmdb_responses.py`)
- Ajouter tests unitaires pour vérifier l'extraction des notes
- Tester la migration de base de données

#### Notes techniques

- TMDB fournit `vote_average` (0-10) et `vote_count` pour tous les films/séries
- TVDB ne semble pas fournir de note utilisateur (juste rating de classification d'âge)
- Les notes existantes ne seront pas rétroactivement mises à jour → nécessite un ré-enrichissement ou une commande dédiée

#### Implémentation future

Une fois les notes en base, possibilité d'ajouter :
- Une commande CLI de recherche avancée
- Des filtres dans l'interface web (future)
- Un système de recommandation basé sur les notes

---

### ⭐ Intégration des datasets publics IMDb

**Statut** : À IMPLÉMENTER
**Priorité** : Moyenne-Haute
**Complexité** : Moyenne
**Dépendances** : Aucune (datasets gratuits et publics)

#### Description

Intégrer les datasets publics IMDb (mis à jour quotidiennement) pour enrichir la base de données avec les notes IMDb, considérées comme les plus fiables et complètes du marché (9+ millions de titres notés).

**Approche recommandée : Hybride TMDB/TVDB + Datasets IMDb locaux**

#### Avantages de l'approche hybride

- ✅ **Notes IMDb plus fiables** que TMDB (référence industrie)
- ✅ **Gratuit et légal** pour usage non-commercial
- ✅ **Données locales** = rapide, pas de rate limiting API
- ✅ **Coverage énorme** : 9+ millions de titres avec notes
- ✅ **Mise à jour quotidienne** des datasets par IMDb
- ✅ **Pas d'API payante** : simple téléchargement TSV

#### Datasets IMDb disponibles

**Source** : https://datasets.imdbws.com/ (mis à jour quotidiennement)

Fichiers pertinents :
- **`title.ratings.tsv.gz`** (~20MB) : Notes et votes
  - `tconst` (ID IMDb, ex: tt0111161)
  - `averageRating` (float 0-10)
  - `numVotes` (int)

- **`title.basics.tsv.gz`** (~200MB) : Infos de base
  - `tconst`, `titleType`, `primaryTitle`, `originalTitle`
  - `startYear`, `runtimeMinutes`, `genres`

- **`title.akas.tsv.gz`** : Titres alternatifs par région
- **`title.crew.tsv.gz`** : Réalisateurs et scénaristes
- **`title.principals.tsv.gz`** : Acteurs principaux

#### Architecture proposée

##### 1. Modèles de données étendus

```python
@dataclass
class Movie:
    # ... champs existants ...
    imdb_id: Optional[str] = None           # tt1234567
    imdb_rating: Optional[float] = None     # Note IMDb (0-10)
    imdb_votes: Optional[int] = None        # Nombre de votes IMDb
    tmdb_rating: Optional[float] = None     # Note TMDB (pour comparaison)
    tmdb_votes: Optional[int] = None
```

##### 2. Base de données locale IMDb

Créer une table SQLite dédiée pour les données IMDb :

```sql
CREATE TABLE imdb_ratings (
    tconst TEXT PRIMARY KEY,        -- tt0111161
    average_rating REAL,            -- 9.2
    num_votes INTEGER,              -- 2800000
    last_updated DATE
);

CREATE INDEX idx_imdb_rating ON imdb_ratings(average_rating);
CREATE INDEX idx_imdb_votes ON imdb_ratings(num_votes);
```

##### 3. Service d'import des datasets

Nouveau service : `src/services/imdb_dataset_importer.py`

```python
class IMDbDatasetImporter:
    """Importe les datasets publics IMDb dans la base locale."""

    async def download_dataset(self, dataset_name: str) -> Path:
        """Télécharge un dataset depuis datasets.imdbws.com"""

    async def import_ratings(self, file_path: Path) -> int:
        """Parse et importe title.ratings.tsv.gz"""

    async def sync_with_movies(self) -> int:
        """Join avec la table movies via imdb_id"""
```

##### 4. Workflow d'enrichissement

```
1. Validation TMDB/TVDB (workflow actuel)
   └─> Récupère tmdb_id, titre, année, etc.

2. Récupération IMDb ID via TMDB
   └─> GET /movie/{tmdb_id}/external_ids
   └─> Extrait imdb_id (ex: tt0111161)

3. Lookup local dans imdb_ratings
   └─> SELECT average_rating, num_votes FROM imdb_ratings WHERE tconst = ?

4. Enrichissement Movie avec notes IMDb + TMDB
   └─> Stocke les deux sources pour comparaison
```

#### Commandes CLI à ajouter

```bash
# Import initial des datasets IMDb
python -m src.main imdb import --dataset ratings --force

# Mise à jour quotidienne/hebdomadaire
python -m src.main imdb sync

# Ré-enrichir les films existants avec IMDb
python -m src.main imdb enrich-existing

# Statistiques sur la couverture
python -m src.main imdb stats
```

#### Modifications nécessaires

##### 1. Extension du client TMDB

```python
# src/adapters/api/tmdb_client.py
async def get_external_ids(self, tmdb_id: int) -> dict[str, str]:
    """Récupère les IDs externes (IMDb, Facebook, etc.)"""
    url = f"{self._base_url}/movie/{tmdb_id}/external_ids"
    response = await self._client.get(url, params={"api_key": self._api_key})
    return response.json()
```

##### 2. Service de parsing TSV

```python
# src/adapters/imdb/tsv_parser.py
import gzip
from pathlib import Path

class TSVParser:
    """Parse les fichiers TSV gzippés IMDb."""

    def parse_ratings(self, file_path: Path) -> Generator[dict, None, None]:
        """Yield {tconst, averageRating, numVotes} pour chaque ligne."""
        with gzip.open(file_path, 'rt', encoding='utf-8') as f:
            headers = next(f).strip().split('\t')
            for line in f:
                values = line.strip().split('\t')
                yield dict(zip(headers, values))
```

##### 3. Migration de base de données

```sql
-- Ajout colonnes IMDb dans movies et series
ALTER TABLE movies ADD COLUMN imdb_id TEXT;
ALTER TABLE movies ADD COLUMN imdb_rating REAL;
ALTER TABLE movies ADD COLUMN imdb_votes INTEGER;

ALTER TABLE series ADD COLUMN imdb_id TEXT;
ALTER TABLE series ADD COLUMN imdb_rating REAL;
ALTER TABLE series ADD COLUMN imdb_votes INTEGER;

-- Table locale pour cache IMDb
CREATE TABLE imdb_ratings (
    tconst TEXT PRIMARY KEY,
    average_rating REAL,
    num_votes INTEGER,
    last_updated DATE DEFAULT CURRENT_DATE
);

-- Index pour recherches rapides
CREATE INDEX idx_movies_imdb_id ON movies(imdb_id);
CREATE INDEX idx_series_imdb_id ON series(imdb_id);
CREATE INDEX idx_imdb_rating_desc ON imdb_ratings(average_rating DESC);
```

##### 4. Tests

- Parser TSV avec données de test
- Import dans base SQLite de test
- Vérifier le join avec movies via imdb_id
- Tester le téléchargement avec mock httpx

#### Cas d'usage enrichis

Avec IMDb + TMDB combinés :

```python
# Recherche avancée
"Films SF années 90, IMDb > 8.0, > 100K votes"
"Films sous-estimés : IMDb > 7.5 mais TMDB < 7.0"
"Blockbusters populaires : IMDb votes > 500K"
"Consensus critique : IMDb et TMDB > 8.0"
```

#### Points d'attention

- **Taille des datasets** : ~200MB gzippé, ~1GB décompressé pour title.basics
- **Temps d'import initial** : ~2-5 minutes pour ratings, ~10-15 min pour basics
- **Mise à jour** : Automatiser avec cron hebdomadaire ou mensuel
- **Stockage** : Prévoir ~500MB pour la base SQLite locale
- **Mapping TMDB→IMDb** : Appel API supplémentaire lors de la validation
- **Coverage** : Tous les films n'ont pas forcément de note IMDb

#### Implémentation par phases

**Phase 1** : Import manuel et lookup basique
- Download + parse title.ratings.tsv.gz
- Table imdb_ratings en SQLite
- Commande `imdb import`

**Phase 2** : Intégration dans validation
- Récupération external_ids depuis TMDB
- Lookup automatique dans imdb_ratings
- Stockage imdb_id + rating dans movies

**Phase 3** : Automatisation et maintenance
- Commande `imdb sync` (update incrémental)
- Cron quotidien/hebdomadaire
- Ré-enrichissement batch des films existants

**Phase 4** : Recherche avancée
- Filtres combinés IMDb + TMDB
- Interface CLI de recherche
- Statistiques et recommandations

#### Ressources

- [IMDb Non-Commercial Datasets](https://developer.imdb.com/non-commercial-datasets/)
- [Structure des datasets](https://www.imdb.com/interfaces/)
- [TMDB External IDs endpoint](https://developer.themoviedb.org/reference/find-by-id)
- [Exemples d'usage](https://the-examples-book.com/projects/data-sets/movies_and_tv)

---

## Améliorations CLI

### Mode dry-run / preview
- **Priorité** : Moyenne
- **Statut** : À faire
- **Description** : Option `--dry-run` pour simuler les opérations sans modification réelle des fichiers

### Commande `stats`
- **Priorité** : Moyenne
- **Statut** : À faire
- **Description** : Statistiques de la vidéothèque (total films/séries, par genre, par année, espace utilisé)

### Commande `reorganize`
- **Priorité** : Basse
- **Statut** : À faire
- **Description** : Réorganisation de la structure existante et subdivision des répertoires volumineux

### Détection doublons avant transfert
- **Priorité** : Moyenne
- **Statut** : À faire
- **Description** : Vérification des doublons potentiels (même film, qualité différente) avant le transfert

### Subdivision dynamique des répertoires
- **Priorité** : Basse
- **Statut** : À faire
- **Description** : Subdivision automatique des répertoires contenant >50 fichiers (ex: A1/, A2/)

### Collections et sagas
- **Priorité** : Basse
- **Statut** : À faire
- **Description** : Regroupement des franchises (trilogies, sagas) via les collections TMDB

---

## Implémenté

### ✅ Analyse IA du générique pour validation automatique

**Statut** : IMPLÉMENTÉ
**Priorité** : Moyenne
**Complexité** : Élevée
**Dépendances** : ffmpeg, EasyOCR (ou Claude Vision API en option)

#### Description

Lors de la validation manuelle, quand plusieurs candidats ont des scores similaires (ex: deux films "Cold War" avec 100% chacun), utiliser l'IA pour analyser le générique de fin du fichier vidéo et déterminer automatiquement le bon candidat.

#### Workflow

1. Nouvelle option `a` (analyze) dans la boucle de validation
2. Extraction des frames du générique via ffmpeg :
   ```bash
   ffmpeg -sseof -120 -i fichier.mkv -vf "fps=1/10" -q:v 2 frame_%03d.jpg
   ```
3. OCR avec EasyOCR pour extraire le texte (réalisateur, acteurs)
4. Comparaison du texte extrait avec les métadonnées TMDB des candidats
5. Calcul d'un score de confiance et proposition du meilleur match

#### Exemple d'utilisation

```
Fichier: Cold.War.2018.1080p.mkv

Candidat 1: Guerre froide (2017) - Réal: J. Wilder Konschak
Candidat 2: Cold War (2018) - Réal: Paweł Pawlikowski

Choix: a
[Extraction du générique...]
[Analyse IA...]
Texte détecté: "Directed by Paweł Pawlikowski", "Joanna Kulig", "Tomasz Kot"
→ Correspondance: Candidat 2 (confiance: 95%)
Valider automatiquement ? [O/n]
```

---

## Hors périmètre

Les fonctionnalités suivantes sont explicitement exclues du projet :

- **Intégration AniDB/MAL** — architecture prête mais pas implémenté pour l'instant
- **Recherche/filtrage dans l'interface** — non prévu dans les specs
- **Génération poster.jpg/fanart.jpg** — explicitement exclu
- **Multi-utilisateurs** — usage personnel uniquement
- **Streaming intégré** — délégué à Plex/Jellyfin
- **Daemon/watchdog** — exécution manuelle uniquement
