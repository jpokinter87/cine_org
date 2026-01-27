# Phase 4: Persistance - Research

**Researched:** 2026-01-27
**Domain:** SQLModel ORM avec SQLite pour persistance de videotheque
**Confidence:** HIGH

## Summary

Cette phase implemente la couche de persistance pour la videotheque CineOrg utilisant SQLModel avec SQLite. L'architecture existante definit deja les entites de domaine (Movie, Series, Episode, VideoFile, PendingValidation) et les interfaces de repositories dans `src/core/ports/repositories.py`. La recherche confirme que SQLModel 0.0.24+ est le choix optimal pour ce projet, offrant une integration native avec Pydantic et SQLAlchemy.

Les decisions cles du CONTEXT.md sont validees par la recherche :
- **XXHash pour le hashing** : Confirme comme algorithme non-cryptographique ideal pour la detection de doublons (10x plus rapide que MD5/SHA)
- **Hash par echantillons** : Pattern standard pour les gros fichiers video (premiers + derniers Mo + taille)
- **Index sur tmdb_id, tvdb_id, title** : Critique pour les >10000 entrees attendues

L'architecture hexagonale existante (ports/adapters) s'integre parfaitement : les modeles SQLModel seront des adapters implementant les interfaces de repository deja definies.

**Primary recommendation:** Utiliser SQLModel.metadata.create_all() pour le developpement initial, puis migrer vers Alembic quand le schema se stabilise. Stocker les candidats API en JSON serialise dans pending_validation pour eviter une table de liaison complexe.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLModel | >=0.0.24 | ORM unifiant Pydantic + SQLAlchemy | Integration native FastAPI, un seul modele validation/DB |
| SQLite3 | stdlib | Base de donnees | Fichier unique, zero configuration, suffisant pour >10000 entrees |
| xxhash | >=3.6.0 | Calcul de hash rapide | 10x plus rapide que MD5, ideal pour detection doublons |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Alembic | >=1.14.0 | Migrations de schema | Production, quand le schema est stable |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| SQLite | PostgreSQL | Plus robuste mais necessite serveur externe |
| SQLModel | SQLAlchemy pur | Plus de controle mais plus verbeux |
| XXHash | MD5/SHA-256 | Cryptographique mais 10x plus lent |

**Installation:**
```bash
pip install "sqlmodel>=0.0.24" "xxhash>=3.6.0" "alembic>=1.14.0"
```

## Architecture Patterns

### Recommended Project Structure
```
src/
├── core/
│   ├── entities/           # Entites de domaine (existantes)
│   │   ├── media.py        # Movie, Series, Episode
│   │   └── video.py        # VideoFile, PendingValidation
│   └── ports/
│       └── repositories.py # Interfaces abstraites (existantes)
├── infrastructure/
│   └── persistence/        # NOUVEAU - Adapters SQLModel
│       ├── __init__.py
│       ├── database.py     # Engine, session factory
│       ├── models.py       # Modeles SQLModel (tables)
│       └── repositories/   # Implementations des ports
│           ├── __init__.py
│           ├── movie_repository.py
│           ├── series_repository.py
│           ├── episode_repository.py
│           ├── video_file_repository.py
│           └── pending_validation_repository.py
```

### Pattern 1: Separation Entites Domaine / Modeles DB
**What:** Les entites de domaine (dataclass) restent pures, les modeles SQLModel sont des adapters
**When to use:** Architecture hexagonale, separation concerns
**Example:**
```python
# Source: Architecture existante + SQLModel docs
# src/core/entities/media.py (EXISTANT - NE PAS MODIFIER)
@dataclass
class Movie:
    id: Optional[str] = None
    tmdb_id: Optional[int] = None
    title: str = ""
    # ...

# src/infrastructure/persistence/models.py (NOUVEAU)
from sqlmodel import SQLModel, Field

class MovieModel(SQLModel, table=True):
    __tablename__ = "movies"

    id: int | None = Field(default=None, primary_key=True)
    tmdb_id: int | None = Field(default=None, index=True)
    imdb_id: str | None = Field(default=None, index=True)
    title: str = Field(index=True)
    original_title: str | None = None
    year: int | None = None
    genres: str | None = None  # JSON serialise
    duration_seconds: int | None = None
    overview: str | None = None
    poster_path: str | None = None

    # Metadonnees techniques du fichier associe
    file_path: str | None = None
    file_hash: str | None = None
    codec_video: str | None = None
    codec_audio: str | None = None
    resolution: str | None = None
    languages: str | None = None  # JSON serialise
    file_size_bytes: int | None = None

    created_at: datetime | None = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None = Field(default_factory=datetime.utcnow)
```

### Pattern 2: Session Management avec Dependency Injection
**What:** Une session par operation, gestion via context manager
**When to use:** Toute interaction avec la base
**Example:**
```python
# Source: https://sqlmodel.tiangolo.com/tutorial/fastapi/session-with-dependency/
# src/infrastructure/persistence/database.py
from sqlmodel import Session, create_engine, SQLModel

sqlite_url = "sqlite:///data/cineorg.db"
engine = create_engine(
    sqlite_url,
    echo=False,
    connect_args={"check_same_thread": False}  # Requis pour SQLite + async
)

def get_session():
    """Generateur de session pour injection de dependance."""
    with Session(engine) as session:
        yield session

def create_db_and_tables():
    """Cree toutes les tables definies dans les modeles."""
    SQLModel.metadata.create_all(engine)
```

### Pattern 3: Repository Implementation
**What:** Adapter implementant l'interface de port avec SQLModel
**When to use:** Toute implementation de repository
**Example:**
```python
# src/infrastructure/persistence/repositories/movie_repository.py
from sqlmodel import Session, select
from src.core.ports.repositories import IMovieRepository
from src.core.entities.media import Movie
from src.infrastructure.persistence.models import MovieModel

class SQLModelMovieRepository(IMovieRepository):
    def __init__(self, session: Session):
        self._session = session

    def get_by_tmdb_id(self, tmdb_id: int) -> Optional[Movie]:
        statement = select(MovieModel).where(MovieModel.tmdb_id == tmdb_id)
        result = self._session.exec(statement).first()
        return self._to_entity(result) if result else None

    def save(self, movie: Movie) -> Movie:
        db_model = self._to_model(movie)
        self._session.add(db_model)
        self._session.commit()
        self._session.refresh(db_model)
        return self._to_entity(db_model)

    def _to_entity(self, model: MovieModel) -> Movie:
        """Convertit un modele DB en entite de domaine."""
        return Movie(
            id=str(model.id),
            tmdb_id=model.tmdb_id,
            title=model.title,
            # ... autres champs
        )

    def _to_model(self, entity: Movie) -> MovieModel:
        """Convertit une entite de domaine en modele DB."""
        return MovieModel(
            id=int(entity.id) if entity.id else None,
            tmdb_id=entity.tmdb_id,
            title=entity.title,
            # ... autres champs
        )
```

### Pattern 4: Hash par Echantillons pour Fichiers Video
**What:** Hash rapide en prelevant echantillons debut + fin + taille
**When to use:** Detection de doublons sur gros fichiers (>100Mo)
**Example:**
```python
# Source: https://github.com/ifduyue/python-xxhash + best practices
import xxhash
from pathlib import Path

def compute_sample_hash(file_path: Path, sample_size: int = 1024 * 1024) -> str:
    """
    Calcule un hash rapide base sur des echantillons du fichier.

    Args:
        file_path: Chemin du fichier
        sample_size: Taille des echantillons en octets (default 1Mo)

    Returns:
        Hash hexadecimal xxh3_64 combine (debut + fin + taille)
    """
    hasher = xxhash.xxh3_64()
    file_size = file_path.stat().st_size

    with open(file_path, "rb") as f:
        # Hash du debut
        hasher.update(f.read(sample_size))

        # Hash de la fin (si fichier assez grand)
        if file_size > sample_size * 2:
            f.seek(-sample_size, 2)  # 2 = SEEK_END
            hasher.update(f.read(sample_size))

        # Inclure la taille dans le hash
        hasher.update(str(file_size).encode())

    return hasher.hexdigest()
```

### Pattern 5: Stockage JSON pour Listes/Dicts
**What:** Serialisation JSON pour stocker tuples, listes, dicts dans SQLite
**When to use:** Champs comme genres, languages, candidates
**Example:**
```python
# Source: https://github.com/fastapi/sqlmodel/discussions/696
import json
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON

class PendingValidationModel(SQLModel, table=True):
    __tablename__ = "pending_validations"

    id: int | None = Field(default=None, primary_key=True)
    video_file_id: int = Field(foreign_key="video_files.id")

    # Stockage des candidats API en JSON (top 5)
    candidates_json: str | None = None  # JSON serialise

    auto_validated: bool = False
    validation_status: str = "pending"
    selected_candidate_id: str | None = None
    created_at: datetime | None = Field(default_factory=datetime.utcnow)

    @property
    def candidates(self) -> list[dict]:
        """Deserialise les candidats depuis JSON."""
        if self.candidates_json:
            return json.loads(self.candidates_json)
        return []

    @candidates.setter
    def candidates(self, value: list[dict]):
        """Serialise les candidats en JSON."""
        self.candidates_json = json.dumps(value)
```

### Anti-Patterns to Avoid
- **Melanger entites domaine et modeles DB:** Garder les @dataclass du domaine purs, sans heritage SQLModel
- **Session partagee entre requetes:** Une session par operation/requete, jamais partagee
- **Index sur toutes les colonnes:** Seulement sur les colonnes frequemment requetees (tmdb_id, tvdb_id, title, file_hash)
- **create_all() en production:** Utiliser Alembic pour les migrations en production

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Hashing de fichiers | Algorithme MD5/SHA maison | xxhash.xxh3_64 | 10x plus rapide, optimise pour gros fichiers |
| ORM mapping | Requetes SQL manuelles | SQLModel select/exec | Typage, injection SQL impossible |
| Session management | Session globale | get_session() generator | Isolation transactions, cleanup automatique |
| Index creation | SQL brut | Field(index=True) | Automatique, typage, gestion SQLModel |
| JSON serialization | Pickle | json.dumps/loads | Standard, lisible, portable |

**Key insight:** SQLModel abstrait la complexite de SQLAlchemy tout en gardant l'acces au bas niveau quand necessaire. Ne pas reimplementer ce que SQLModel gere automatiquement.

## Common Pitfalls

### Pitfall 1: Import Circulaire avec Relations
**What goes wrong:** ImportError lors de references croisees entre modeles (Team <-> Hero)
**Why it happens:** Python ne peut pas resoudre les imports circulaires au runtime
**How to avoid:**
- Utiliser des references string pour les relations: `Relationship(back_populates="heroes")`
- Utiliser TYPE_CHECKING pour les imports de typage
- Garder tous les modeles dans un seul fichier si possible
**Warning signs:** `ImportError: cannot import name 'X' from partially initialized module`

### Pitfall 2: Index Non Cree Apres Modification
**What goes wrong:** Ajouter `index=True` a un champ existant ne cree pas l'index
**Why it happens:** `create_all()` ne modifie pas les tables existantes
**How to avoid:**
- Supprimer la DB et recreer (dev)
- Utiliser Alembic pour les migrations (prod)
- Ou ajouter l'index manuellement avec SQL
**Warning signs:** Requetes lentes sur colonnes supposees indexees

### Pitfall 3: Session SQLite Multi-thread
**What goes wrong:** `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread`
**Why it happens:** SQLite par defaut interdit l'utilisation cross-thread
**How to avoid:** `connect_args={"check_same_thread": False}` dans create_engine
**Warning signs:** Erreurs intermittentes en mode async/multi-thread

### Pitfall 4: Oublier commit/refresh
**What goes wrong:** Donnees non persistees ou ID non mis a jour apres insert
**Why it happens:** SQLModel necessite commit explicite et refresh pour recuperer les valeurs generees
**How to avoid:** Toujours `session.add()` puis `session.commit()` puis `session.refresh(obj)`
**Warning signs:** `id` reste None apres save, changements perdus

### Pitfall 5: Cascade Delete Non Configure
**What goes wrong:** Erreur de cle etrangere lors de suppression parent
**Why it happens:** Par defaut, SQLModel/SQLAlchemy n'applique pas de cascade
**How to avoid:** Configurer `sa_relationship_kwargs={"cascade": "all, delete-orphan"}` ou gerer manuellement
**Warning signs:** `IntegrityError: FOREIGN KEY constraint failed`

### Pitfall 6: Soft Delete et Contraintes Uniques
**What goes wrong:** Impossible de recreer une entree avec meme valeur unique (ex: tmdb_id)
**Why it happens:** L'entree "supprimee" existe toujours physiquement
**How to avoid:** Pour la table trash, dupliquer les donnees sans contraintes uniques
**Warning signs:** `IntegrityError: UNIQUE constraint failed`

## Code Examples

### Initialisation Complete de la Base
```python
# src/infrastructure/persistence/database.py
from datetime import datetime
from pathlib import Path
from sqlmodel import SQLModel, Session, create_engine

# Configuration
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
DATABASE_URL = f"sqlite:///{DATA_DIR}/cineorg.db"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False}
)

def init_db():
    """Initialise la base de donnees et cree les tables."""
    # Importer tous les modeles pour les enregistrer dans metadata
    from src.infrastructure.persistence.models import (
        MovieModel, SeriesModel, EpisodeModel,
        VideoFileModel, PendingValidationModel, TrashModel
    )
    SQLModel.metadata.create_all(engine)

def get_session():
    """Generateur de session pour DI."""
    with Session(engine) as session:
        yield session
```

### Modele VideoFile avec Hash
```python
# src/infrastructure/persistence/models.py
from datetime import datetime
from sqlmodel import SQLModel, Field

class VideoFileModel(SQLModel, table=True):
    __tablename__ = "video_files"

    id: int | None = Field(default=None, primary_key=True)

    # Chemin complet + nom fichier (redondant mais pratique)
    path: str = Field(index=True)
    filename: str

    # Detection doublons
    file_hash: str | None = Field(default=None, index=True)
    size_bytes: int = 0

    # Metadonnees techniques (JSON serialise pour les listes)
    codec_video: str | None = None
    codec_audio: str | None = None
    resolution_width: int | None = None
    resolution_height: int | None = None
    duration_seconds: int | None = None
    languages_json: str | None = None  # ["fr", "en"]

    # Timestamps
    created_at: datetime | None = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None = Field(default_factory=datetime.utcnow)
```

### Modele Trash pour Historique Suppressions
```python
# src/infrastructure/persistence/models.py
class TrashModel(SQLModel, table=True):
    """Historique des fichiers supprimes avec metadonnees completes."""
    __tablename__ = "trash"

    id: int | None = Field(default=None, primary_key=True)

    # Type d'entite supprimee
    entity_type: str  # "movie", "series", "episode", "video_file"
    original_id: int  # ID original dans la table source

    # Metadonnees completes serialisees (permet restauration)
    metadata_json: str  # Toutes les donnees de l'entite

    # Info suppression
    deleted_at: datetime = Field(default_factory=datetime.utcnow)
    deletion_reason: str | None = None
```

### Repository avec Conversion Entite/Modele
```python
# src/infrastructure/persistence/repositories/video_file_repository.py
import json
from pathlib import Path
from typing import Optional
from sqlmodel import Session, select

from src.core.entities.video import VideoFile
from src.core.ports.repositories import IVideoFileRepository
from src.core.value_objects import MediaInfo, Resolution, VideoCodec, AudioCodec, Language
from src.infrastructure.persistence.models import VideoFileModel

class SQLModelVideoFileRepository(IVideoFileRepository):
    def __init__(self, session: Session):
        self._session = session

    def get_by_hash(self, file_hash: str) -> Optional[VideoFile]:
        """Trouve un fichier par son hash (detection doublons)."""
        statement = select(VideoFileModel).where(VideoFileModel.file_hash == file_hash)
        result = self._session.exec(statement).first()
        return self._to_entity(result) if result else None

    def get_by_path(self, path: Path) -> Optional[VideoFile]:
        statement = select(VideoFileModel).where(VideoFileModel.path == str(path))
        result = self._session.exec(statement).first()
        return self._to_entity(result) if result else None

    def save(self, video_file: VideoFile) -> VideoFile:
        db_model = self._to_model(video_file)

        # Upsert: verifier si existe deja
        if video_file.id:
            existing = self._session.get(VideoFileModel, int(video_file.id))
            if existing:
                # Mise a jour
                for key, value in db_model.model_dump(exclude={"id"}).items():
                    setattr(existing, key, value)
                existing.updated_at = datetime.utcnow()
                db_model = existing
            else:
                self._session.add(db_model)
        else:
            self._session.add(db_model)

        self._session.commit()
        self._session.refresh(db_model)
        return self._to_entity(db_model)

    def _to_entity(self, model: VideoFileModel) -> VideoFile:
        """Convertit modele DB vers entite domaine."""
        media_info = None
        if model.codec_video or model.resolution_width:
            resolution = None
            if model.resolution_width and model.resolution_height:
                resolution = Resolution(model.resolution_width, model.resolution_height)

            video_codec = VideoCodec(model.codec_video) if model.codec_video else None

            languages = []
            if model.languages_json:
                for code in json.loads(model.languages_json):
                    languages.append(Language(code=code, name=code))

            media_info = MediaInfo(
                resolution=resolution,
                video_codec=video_codec,
                audio_languages=tuple(languages),
                duration_seconds=model.duration_seconds
            )

        return VideoFile(
            id=str(model.id),
            path=Path(model.path),
            filename=model.filename,
            size_bytes=model.size_bytes,
            file_hash=model.file_hash,
            media_info=media_info,
            created_at=model.created_at,
            updated_at=model.updated_at
        )

    def _to_model(self, entity: VideoFile) -> VideoFileModel:
        """Convertit entite domaine vers modele DB."""
        languages_json = None
        resolution_width = None
        resolution_height = None
        codec_video = None
        duration_seconds = None

        if entity.media_info:
            if entity.media_info.resolution:
                resolution_width = entity.media_info.resolution.width
                resolution_height = entity.media_info.resolution.height
            if entity.media_info.video_codec:
                codec_video = entity.media_info.video_codec.name
            if entity.media_info.audio_languages:
                languages_json = json.dumps([l.code for l in entity.media_info.audio_languages])
            duration_seconds = entity.media_info.duration_seconds

        return VideoFileModel(
            id=int(entity.id) if entity.id else None,
            path=str(entity.path) if entity.path else "",
            filename=entity.filename,
            size_bytes=entity.size_bytes,
            file_hash=entity.file_hash,
            codec_video=codec_video,
            resolution_width=resolution_width,
            resolution_height=resolution_height,
            duration_seconds=duration_seconds,
            languages_json=languages_json,
            created_at=entity.created_at,
            updated_at=entity.updated_at
        )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| SQLAlchemy Core + declarations | SQLModel (unifie Pydantic) | 2022 | Un seul modele pour validation + DB |
| MD5/SHA-256 pour hash fichiers | XXHash (xxh3_64) | 2020 | 10x plus rapide, ideal big files |
| Raw SQL pour indexes | Field(index=True) | SQLModel 0.0.8 | Declaratif, type-safe |
| Modeles couples domaine/DB | Architecture hexagonale | Pattern etabli | Testabilite, maintenabilite |

**Deprecated/outdated:**
- `typing.Optional[X]` : Utiliser `X | None` (Python 3.10+)
- `sqlalchemy.Column` pour indexes simples : Utiliser `Field(index=True)`
- Session globale partagee : Une session par operation

## Open Questions

1. **Strategie de migration vers Alembic**
   - What we know: create_all() suffit pour dev, Alembic pour prod
   - What's unclear: Quand exactement basculer (schema stable?)
   - Recommendation: Commencer sans Alembic, ajouter quand les tests passent et schema valide

2. **Granularite des repositories**
   - What we know: Un repository par entite est le pattern standard
   - What's unclear: Faut-il un repository separe pour PendingValidation ou l'integrer a VideoFileRepository?
   - Recommendation: Separer (SRP), l'interface IVideoFileRepository a deja list_pending() qui peut etre deplace

3. **Index sur file_hash**
   - What we know: Utile pour detection doublons rapide
   - What's unclear: Impact performance ecriture sur >10000 fichiers
   - Recommendation: Ajouter l'index, surveiller les performances, ajuster si necessaire

## Sources

### Primary (HIGH confidence)
- [SQLModel Official Documentation](https://sqlmodel.tiangolo.com/) - Tutorial complet, relationships, indexes
- [SQLModel Create DB and Table](https://sqlmodel.tiangolo.com/tutorial/create-db-and-table/) - Engine, create_all
- [SQLModel Indexes](https://sqlmodel.tiangolo.com/tutorial/indexes/) - Field(index=True)
- [SQLModel Session with FastAPI Dependency](https://sqlmodel.tiangolo.com/tutorial/fastapi/session-with-dependency/) - get_session pattern
- [xxhash PyPI](https://pypi.org/project/xxhash/) - xxhash 3.6.0 documentation
- [python-xxhash GitHub](https://github.com/ifduyue/python-xxhash) - File hashing examples

### Secondary (MEDIUM confidence)
- [SQLModel + Alembic Tutorial](https://dev.to/mchawa/sqlmodel-alembic-tutorial-gc8) - Integration Alembic
- [Getting Started with SQLModel](https://betterstack.com/community/guides/scaling-python/sqlmodel-orm/) - Best practices
- [SQLModel Code Structure](https://sqlmodel.tiangolo.com/tutorial/code-structure/) - Circular imports solution
- [Soft Delete Pattern SQLAlchemy](https://theshubhendra.medium.com/mastering-soft-delete-advanced-sqlalchemy-techniques-4678f4738947) - Trash table alternatives

### Tertiary (LOW confidence)
- [Finding Duplicate Files with Python](https://third-bit.com/sdxpy/dup/) - Hash sampling technique
- [SQLite Performance Tuning](https://phiresky.github.io/blog/2020/sqlite-performance-tuning/) - WAL, indexes

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - SQLModel et xxhash sont documentes officiellement, versions verifiees
- Architecture: HIGH - Patterns confirmes par documentation officielle SQLModel
- Pitfalls: MEDIUM - Bases sur issues GitHub et documentation, non tous testes
- Hash sampling: MEDIUM - Pattern etabli mais implementation specifique non verifiee

**Research date:** 2026-01-27
**Valid until:** 60 days (SQLModel et SQLite sont stables)
