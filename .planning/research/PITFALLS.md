# Pièges et Erreurs Courantes - CineOrg

> Document de recherche sur les erreurs courantes et pièges à éviter dans ce type de projet.
> Recherche effectuée le 2026-01-26

---

## Table des Matières

1. [Architecture et Maintenabilité](#1-architecture-et-maintenabilité)
2. [APIs TMDB et TVDB](#2-apis-tmdb-et-tvdb)
3. [Manipulation de Fichiers et Symlinks](#3-manipulation-de-fichiers-et-symlinks)
4. [Parsing avec GuessIt](#4-parsing-avec-guessit)
5. [Base de Données SQLite](#5-base-de-données-sqlite)
6. [Leçons de l'Ancienne Version](#6-leçons-de-lancienne-version)

---

## 1. Architecture et Maintenabilité

### 1.1 Anti-Pattern : God Object / Blob

**Description :** Une classe unique accumule trop de responsabilités et devient le centre du système.

**Signes avant-coureurs :**
- Une classe avec des centaines de lignes de code
- Des méthodes qui touchent à des domaines très différents (parsing, API, fichiers, BDD)
- De nombreuses autres classes dépendent de cette "super-classe"
- Difficile de tester sans mocker la moitié du système

**Stratégie de prévention :**
- Appliquer le Single Responsibility Principle (SRP) dès le départ
- Découper en modules spécialisés : `scanner`, `parser`, `matcher`, `renamer`, `transferer`
- Chaque module ne doit avoir qu'une seule raison de changer

**Phase concernée :** Architecture initiale, toutes les phases

**Sources :** [The Dark Side Of Software: Anti-Patterns](https://www.paulsblog.dev/the-dark-side-of-software-anti-patterns-and-how-to-fix-them/)

---

### 1.2 Anti-Pattern : Big Ball of Mud

**Description :** Système sans architecture claire, code chaotique sans couches ni modularité.

**Signes avant-coureurs :**
- Absence de séparation entre couches (présentation, métier, données)
- Imports circulaires fréquents
- Impossible de comprendre le flux de données
- Chaque modification casse autre chose

**Stratégie de prévention :**
- Définir une architecture en couches dès le début (hexagonale ou clean architecture)
- Respecter la règle de dépendance : les couches externes dépendent des couches internes, jamais l'inverse
- Le domaine métier ne dépend de rien d'autre que lui-même

**Phase concernée :** Architecture initiale

**Sources :** [A Deeper Look at Software Architecture Anti-Patterns](https://medium.com/@srinathperera/a-deeper-look-at-software-architecture-anti-patterns-9ace30f59354)

---

### 1.3 Anti-Pattern : Couplage CLI/Métier (Lava Flow)

**Description :** Code ancien non documenté reste dans le projet car trop risqué à supprimer. C'est exactement ce qui s'est passé avec l'ancienne version de CineOrg.

**Signes avant-coureurs :**
- Logique métier mélangée avec le code d'interface (CLI ou Web)
- Fonctions qui font à la fois du parsing, de l'affichage et de l'accès fichier
- Impossible d'ajouter une nouvelle interface sans dupliquer le code métier
- Personne ne comprend pourquoi certaines parties du code existent

**Stratégie de prévention :**
- Séparer strictement les couches : `core/` (métier), `cli/` (interface), `web/` (interface)
- Les interfaces appellent le coeur métier, jamais l'inverse
- Utiliser l'injection de dépendances pour découpler
- Le coeur métier ne doit jamais importer typer, fastapi, ou tout framework d'interface

**Phase concernée :** Architecture initiale, CLI, Web

**Application directe au projet :**
```python
# MAUVAIS - couplage CLI/métier
def process_file(filepath):
    typer.echo(f"Processing {filepath}...")  # CLI dans le métier
    result = parse_file(filepath)
    typer.echo(f"Found: {result.title}")     # CLI dans le métier
    return result

# BON - séparation nette
# core/processor.py
def process_file(filepath) -> ProcessResult:
    return ProcessResult(...)

# cli/commands.py
def process_command(filepath):
    typer.echo(f"Processing {filepath}...")
    result = process_file(filepath)
    typer.echo(f"Found: {result.title}")
```

**Sources :** [Building Maintainable Python Applications with Hexagonal Architecture](https://dev.to/hieutran25/building-maintainable-python-applications-with-hexagonal-architecture-and-domain-driven-design-chp)

---

### 1.4 Piège : Sur-ingénierie de l'Architecture

**Description :** Appliquer l'architecture hexagonale partout, même pour des opérations CRUD simples.

**Signes avant-coureurs :**
- Boilerplate excessif pour des opérations simples
- Interfaces/abstractions qui n'ont qu'une seule implémentation
- Temps de développement disproportionné par rapport à la valeur ajoutée
- Navigation difficile dans le projet (trop de couches)

**Stratégie de prévention :**
- Appliquer l'architecture hexagonale uniquement là où c'est nécessaire
- Pour les opérations CRUD simples, rester pragmatique
- Se poser la question : "Est-ce que cette abstraction sera réellement utile ?"
- Commencer simple et refactorer quand le besoin se fait sentir

**Phase concernée :** Architecture initiale

**Sources :** [Hexagonal Architecture in Python](https://blog.szymonmiks.pl/p/hexagonal-architecture-in-python/)

---

## 2. APIs TMDB et TVDB

### 2.1 TMDB : Rate Limiting

**Description :** TMDB applique des limites de requêtes par IP (~50 req/s, 20 connexions simultanées max pour les images).

**Signes avant-coureurs :**
- Erreurs HTTP 429 (Too Many Requests)
- Images qui ne chargent pas aléatoirement
- Échecs lors du traitement de gros lots de fichiers

**Stratégie de prévention :**
- Implémenter un rate limiter avec backoff exponentiel
- Diviser les requêtes en lots (batches) de 50 maximum
- Réutiliser les connexions HTTP (keep-alive)
- Mettre en cache les résultats de recherche (24h) et les détails (7 jours)
- Pour les images : utiliser `loading="lazy"` et limiter les connexions simultanées à 20

**Phase concernée :** Intégration API, Enrichissement

**Configuration recommandée :**
```python
TMDB_RATE_LIMIT = {
    "requests_per_second": 40,
    "max_simultaneous_connections": 20,
    "batch_size": 50,
    "pause_between_batches_seconds": 2,
}
```

**Sources :** [TMDB Rate Limiting Documentation](https://developer.themoviedb.org/docs/rate-limiting)

---

### 2.2 TMDB : Données Manquantes et Titres Alternatifs

**Description :** Les titres localisés ne sont pas toujours disponibles via l'API, même s'ils apparaissent sur le site web.

**Signes avant-coureurs :**
- Recherche par titre français ne trouve pas le film
- Le paramètre `language=fr-FR` ne fonctionne que pour ~50% des films
- L'endpoint `alternative_titles` ne contient pas tous les titres

**Stratégie de prévention :**
- Toujours rechercher d'abord avec le titre original
- Combiner plusieurs stratégies de recherche : titre original, titre traduit, année
- Utiliser le format complet de langue (`fr-FR` plutôt que `fr`)
- Prévoir un fallback vers la recherche manuelle si score < seuil
- Stocker à la fois `title` et `original_title` en BDD

**Phase concernée :** Matching, Enrichissement

**Workflow de recherche recommandé :**
```
1. Recherche avec titre parsé + année
2. Si pas de résultat : recherche sans année
3. Si pas de résultat : recherche avec titre normalisé (sans accents, articles)
4. Si score < 85% : validation manuelle
```

**Sources :** [TMDB Search & Query Documentation](https://developer.themoviedb.org/docs/search-and-query-for-details), [French title not found discussion](https://www.themoviedb.org/talk/63c012a923be4600b2f0cf80)

---

### 2.3 TVDB : Authentification et Instabilité

**Description :** TVDB nécessite une authentification et a connu des problèmes de stabilité et de changements d'API.

**Signes avant-coureurs :**
- Erreurs 401 Unauthorized intermittentes
- JWT qui expire sans avertissement
- Changements d'API non annoncés
- Certains pays ont des restrictions d'accès

**Stratégie de prévention :**
- Utiliser uniquement l'API key pour l'authentification (pas username/password)
- Implémenter un refresh automatique du token JWT
- Toujours envoyer les credentials dans le body, pas le header
- Utiliser TLS 1.2 minimum
- Maintenir une copie locale des données (cache ou BDD)
- Implémenter un mécanisme de retry robuste

**Phase concernée :** Intégration API, Enrichissement

**Configuration d'authentification :**
```python
# CORRECT
headers = {"Content-Type": "application/json"}
body = {"apikey": "your_api_key"}

# INCORRECT - credentials dans le header
headers = {"apikey": "your_api_key"}  # Ne fonctionnera pas
```

**Sources :** [TVDB API GitHub](https://github.com/thetvdb/v4-api), [TVDB API Known Issues](https://support.thetvdb.com/kb/faq.php?id=74)

---

### 2.4 Piège : APIs Indisponibles

**Description :** Les APIs externes peuvent être indisponibles temporairement ou définitivement.

**Signes avant-coureurs :**
- Timeouts fréquents
- Changements de structure de réponse
- Endpoints dépréciés sans préavis

**Stratégie de prévention :**
- Ne jamais bloquer le workflow complet si une API est indisponible
- Implémenter une file d'attente pour les fichiers non traités
- Sauvegarder les réponses API pour pouvoir les rejouer
- Prévoir un mode "hors-ligne" qui utilise uniquement le cache
- Abstraire les clients API derrière une interface pour faciliter le remplacement

**Phase concernée :** Intégration API

---

## 3. Manipulation de Fichiers et Symlinks

### 3.1 Symlinks sur Windows

**Description :** La création de symlinks sur Windows nécessite des privilèges spéciaux.

**Signes avant-coureurs :**
- `OSError: symbolic link privilege not held` sur Windows
- Symlinks créés sans erreur mais ne fonctionnent pas
- Comportement différent entre développement (Linux) et production (Windows)

**Stratégie de prévention :**
- Détecter le système d'exploitation et adapter le comportement
- Sur Windows : vérifier si le Developer Mode est activé ou si on a les privilèges admin
- Documenter clairement les prérequis Windows
- Prévoir un fallback (copie ou hardlink) si symlink impossible

**Phase concernée :** Transfert, Organisation

**Code de détection :**
```python
import os
import sys

def can_create_symlinks() -> bool:
    if sys.platform != "win32":
        return True

    # Tester la création d'un symlink temporaire
    try:
        test_target = Path(tempfile.gettempdir()) / "symlink_test_target"
        test_link = Path(tempfile.gettempdir()) / "symlink_test_link"
        test_target.touch()
        test_link.symlink_to(test_target)
        test_link.unlink()
        test_target.unlink()
        return True
    except OSError:
        return False
```

**Sources :** [Python os.symlink Guide](https://zetcode.com/python/os-symlink/), [Windows Symlink Permissions](https://www.scivision.dev/windows-symbolic-link-permission-enable/)

---

### 3.2 Caractères Spéciaux dans les Noms de Fichiers

**Description :** Les caractères interdits varient selon le système de fichiers et peuvent causer des erreurs silencieuses.

**Signes avant-coureurs :**
- Fichiers créés avec des noms tronqués ou modifiés
- Erreurs `OSError: Invalid argument` sur certains fichiers
- Caractères invisibles (Unicode) dans les noms de fichiers
- Comportement différent entre systèmes de fichiers (NTFS vs ext4)

**Stratégie de prévention :**
- Utiliser une bibliothèque de sanitization comme `pathvalidate`
- Normaliser les caractères Unicode en NFC avant toute opération
- Définir une liste explicite de caractères interdits pour tous les OS : `/ \ : * ? " < > |`
- Tester avec des noms de fichiers contenant des accents, emojis, caractères asiatiques

**Phase concernée :** Renommage, Transfert

**Code de sanitization :**
```python
import unicodedata
from pathvalidate import sanitize_filename

def safe_filename(name: str) -> str:
    # Normaliser les caractères Unicode
    normalized = unicodedata.normalize("NFC", name)
    # Sanitizer pour tous les OS
    return sanitize_filename(normalized, platform="universal")
```

**Sources :** [pathvalidate Documentation](https://pathvalidate.readthedocs.io/en/latest/pages/examples/sanitize.html), [Python Unicode HOWTO](https://docs.python.org/3/howto/unicode.html)

---

### 3.3 Race Conditions et Opérations Non-Atomiques

**Description :** Les opérations fichiers peuvent échouer si plusieurs processus accèdent aux mêmes ressources.

**Signes avant-coureurs :**
- Fichiers partiellement écrits après un crash
- Erreurs "File in use" intermittentes
- Corruption de données difficile à reproduire
- Problèmes qui disparaissent en mode debug (Heisenbug)

**Stratégie de prévention :**
- Utiliser le pattern "write to temp, then rename" pour les écritures atomiques
- Ne jamais faire check-then-act (TOCTOU vulnerability)
- Utiliser `atomicwrites` pour les écritures critiques
- S'assurer que source et destination sont sur le même filesystem pour les renames atomiques
- Implémenter un mécanisme de lock pour les opérations critiques

**Phase concernée :** Transfert, Base de données

**Pattern d'écriture atomique :**
```python
from pathlib import Path
import tempfile
import shutil

def atomic_move(src: Path, dst: Path) -> None:
    """Déplace un fichier de manière atomique si possible."""
    # Si même filesystem, rename est atomique
    try:
        src.rename(dst)
    except OSError:
        # Filesystem différents, fallback non-atomique
        temp_dst = dst.with_suffix(".tmp")
        shutil.copy2(src, temp_dst)
        temp_dst.rename(dst)
        src.unlink()
```

**Sources :** [python-atomicwrites Documentation](https://python-atomicwrites.readthedocs.io/), [Avoid Race Conditions](https://tldp.org/HOWTO/Secure-Programs-HOWTO/avoid-race.html)

---

### 3.4 Permissions et Propriété des Fichiers

**Description :** Les fichiers créés peuvent avoir des permissions incorrectes ou appartenir au mauvais utilisateur.

**Signes avant-coureurs :**
- Erreur `Permission denied` lors de la lecture/modification
- Fichiers inaccessibles par le media center
- Problèmes après migration entre systèmes

**Stratégie de prévention :**
- Hériter des permissions du répertoire parent
- Documenter les permissions requises
- Vérifier les permissions avant de commencer le traitement
- Prévoir un mode de vérification/réparation des permissions

**Phase concernée :** Transfert, Import

---

## 4. Parsing avec GuessIt

### 4.1 Ambiguïté Film vs Série

**Description :** GuessIt utilise la présence d'un pattern d'épisode pour distinguer séries et films. Sans pattern, c'est considéré comme un film.

**Signes avant-coureurs :**
- Films mal classés comme séries (ex: "Episode 4" dans le titre)
- Séries mal classées comme films (numérotation non standard)
- Animes avec numérotation absolue mal interprétés

**Stratégie de prévention :**
- Utiliser le contexte du répertoire source (`Films/` ou `Séries/`) comme indice primaire
- Utiliser l'option `-t TYPE` de GuessIt quand le type est connu
- Vérifier la cohérence avec l'API après le parsing
- Prévoir une correction manuelle pour les cas ambigus

**Phase concernée :** Parsing

**Cas problématiques connus :**
- "Star Wars Episode 4" - contient "Episode" mais c'est un film
- "Band of Brothers" - hardcodé comme série dans GuessIt
- Animes avec numérotation `720` sans `p` - interprété comme S07E20

**Sources :** [GuessIt GitHub Issues](https://github.com/guessit-io/guessit/issues/87), [Wrong detection movie vs episode](https://github.com/guessit-io/guessit/issues/233)

---

### 4.2 Résolutions Sans Suffixe "p"

**Description :** Les résolutions comme `720` ou `1080` sans le suffixe `p` sont parfois interprétées comme des numéros de saison/épisode.

**Signes avant-coureurs :**
- Film "1080" devient saison 10 épisode 80
- Film "720" devient saison 7 épisode 20
- Parsing incohérent selon les fichiers

**Stratégie de prévention :**
- Post-traiter les résultats GuessIt pour détecter ce pattern
- Si `season > 10` et `episode > 70`, c'est probablement une résolution
- Combiner avec mediainfo pour confirmer la résolution réelle

**Phase concernée :** Parsing

**Code de correction :**
```python
def fix_resolution_as_episode(guessit_result: dict, mediainfo_data: dict) -> dict:
    """Corrige les résolutions mal interprétées comme épisodes."""
    season = guessit_result.get("season")
    episode = guessit_result.get("episode")

    # Pattern suspect : S07E20 ou S10E80
    if season and episode:
        combined = season * 100 + episode
        if combined in [720, 1080, 2160]:
            # C'est probablement une résolution
            del guessit_result["season"]
            del guessit_result["episode"]
            guessit_result["screen_size"] = f"{combined}p"
            guessit_result["type"] = "movie"

    return guessit_result
```

**Sources :** [GuessIt Issue #693](https://github.com/guessit-io/guessit/issues/693)

---

### 4.3 Titres de Séries avec "US" ou "UK"

**Description :** Les titres se terminant par "Us" ou "Uk" sont parfois interprétés comme ayant un code pays.

**Signes avant-coureurs :**
- "Those Who Would Destroy Us" devient "Those Who Would Destroy (US)"
- Recherche API échoue à cause du titre altéré

**Stratégie de prévention :**
- Vérifier si le code pays fait vraiment partie du nom de fichier original
- Comparer avec le titre TVDB pour confirmer
- Stocker le titre original non modifié pour la recherche

**Phase concernée :** Parsing, Matching

**Sources :** [FlexGet GuessIt parsing error](https://lightrun.com/answers/flexget-flexget-guessit-series-parsing-error-when-ending-in-us-or-uk)

---

### 4.4 Parsing des Animes

**Description :** Les animes ont souvent des conventions de nommage différentes qui perturbent GuessIt.

**Signes avant-coureurs :**
- Titre de série coupé au premier tiret
- Sous-titre interprété comme titre d'épisode
- Numérotation absolue mal comprise
- Tags de groupe entre crochets mal gérés

**Stratégie de prévention :**
- Détecter les patterns anime (crochets de groupe, numérotation absolue)
- Utiliser l'option `--type episode` explicitement pour les animes
- Post-traiter pour recombiner les titres séparés par des tirets
- Prévoir une intégration AniDB/MAL pour validation (évolution future)

**Phase concernée :** Parsing

**Sources :** [GuessIt Anime Issue #628](https://github.com/guessit-io/guessit/issues/628)

---

### 4.5 Dates Ambiguës

**Description :** Les dates courtes dans les noms de fichiers peuvent être interprétées différemment.

**Signes avant-coureurs :**
- "12.05.2020" interprété différemment selon la locale
- Année extraite incorrectement

**Stratégie de prévention :**
- Utiliser les options `--date-year-first` ou `--date-day-first` selon le contexte
- Valider l'année extraite avec l'API
- Accepter une tolérance de +/- 1 an dans le scoring

**Phase concernée :** Parsing

---

## 5. Base de Données SQLite

### 5.1 Accès Concurrent

**Description :** SQLite gère mal les accès concurrent en écriture.

**Signes avant-coureurs :**
- Erreurs "database is locked"
- Transactions qui échouent aléatoirement
- Corruption de données lors d'accès multiples

**Stratégie de prévention :**
- Utiliser le mode WAL (Write-Ahead Logging) : `PRAGMA journal_mode=WAL`
- Garder les transactions d'écriture aussi courtes que possible
- Utiliser une seule connexion pour les écritures, plusieurs pour les lectures
- Pour SQLModel/SQLAlchemy : configurer correctement le pool de connexions

**Phase concernée :** Base de données

**Configuration recommandée :**
```python
from sqlmodel import create_engine

engine = create_engine(
    "sqlite:///cineorg.db",
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)

# Activer WAL mode
with engine.connect() as conn:
    conn.execute("PRAGMA journal_mode=WAL")
```

**Sources :** [Going Fast with SQLite and Python](https://charlesleifer.com/blog/going-fast-with-sqlite-and-python/)

---

### 5.2 Gestion des Connexions

**Description :** Les connexions non fermées causent des fuites mémoire et des locks persistants.

**Signes avant-coureurs :**
- Mémoire qui augmente progressivement
- "database is locked" même sans accès concurrent apparent
- Tests qui échouent aléatoirement

**Stratégie de prévention :**
- Toujours utiliser les context managers (`with Session(engine) as session:`)
- Fermer explicitement les cursors après utilisation
- Utiliser `scoped_session` pour les applications web
- Implémenter un health check de connexion

**Phase concernée :** Base de données

**Sources :** [SQLite3 Best Practices](https://climbtheladder.com/10-python-sqlite-best-practices/)

---

### 5.3 Schéma et Migrations

**Description :** Les changements de schéma peuvent corrompre les données existantes.

**Signes avant-coureurs :**
- Colonnes manquantes après mise à jour
- Données perdues après migration
- Impossible de revenir à une version précédente

**Stratégie de prévention :**
- Utiliser Alembic pour les migrations de schéma
- Toujours tester les migrations sur une copie de la BDD de production
- Sauvegarder la BDD avant chaque migration
- Prévoir des scripts de rollback
- Versionner le schéma dans la BDD

**Phase concernée :** Base de données, Maintenance

---

### 5.4 Performance avec Grandes Tables

**Description :** SQLite peut devenir lent avec des tables volumineuses sans indexation appropriée.

**Signes avant-coureurs :**
- Recherches de plus en plus lentes
- Temps de démarrage qui augmente
- Requêtes qui timeoutent

**Stratégie de prévention :**
- Créer des index sur les colonnes fréquemment utilisées dans les WHERE
- Utiliser `fetchmany()` plutôt que `fetchall()` pour les gros résultats
- Analyser les requêtes avec `EXPLAIN QUERY PLAN`
- Configurer `PRAGMA cache_size` si la RAM le permet

**Phase concernée :** Base de données

**Index recommandés (déjà dans les specs) :**
```sql
CREATE INDEX idx_films_tmdb ON films(tmdb_id);
CREATE INDEX idx_films_genre ON films(genre);
CREATE INDEX idx_films_title ON films(title);
CREATE INDEX idx_series_tvdb ON series(tvdb_id);
CREATE INDEX idx_episodes_series ON episodes(series_id);
```

**Sources :** [SQLite Appropriate Uses](https://www.sqlite.org/whentouse.html)

---

## 6. Leçons de l'Ancienne Version

### 6.1 Erreur Principale : Couplage CLI/Métier

**Ce qui s'est passé :**
- La logique métier était dispersée dans les commandes CLI
- Les fonctions de traitement contenaient des `print()` et des inputs utilisateur
- Impossible d'extraire le coeur métier pour l'utiliser dans une interface web
- Nécessité de maintenir deux codebases séparées

**Comment éviter :**
- Architecture en couches dès le premier jour
- Le coeur métier (`core/`) ne doit JAMAIS importer `typer`, `click`, `fastapi`, ou tout framework d'interface
- Toute communication avec l'utilisateur passe par des objets de retour (DTOs, exceptions typées)
- L'interface (CLI ou Web) est responsable de la présentation, pas le métier

### 6.2 Évolution Non Planifiée

**Ce qui s'est passé :**
- Ajouts successifs de fonctionnalités sans refactoring
- Code legacy incompréhensible conservé "au cas où"
- Aucune documentation d'architecture

**Comment éviter :**
- Maintenir un document PROJECT.md à jour
- Refactorer au fur et à mesure, pas "plus tard"
- Supprimer le code mort immédiatement
- Écrire les tests AVANT le code (TDD) pour forcer une bonne conception

### 6.3 Validation Manuelle Sous-Estimée

**Ce qui s'est passé :**
- La validation manuelle était un afterthought
- Interface CLI peu ergonomique pour choisir parmi plusieurs candidats
- ~10% des fichiers nécessitent une intervention humaine mais le workflow n'était pas optimisé pour ça

**Comment éviter :**
- Concevoir le workflow de validation manuelle dès le début
- L'interface de validation doit être aussi importante que le traitement automatique
- Prévoir le stockage et la reprise des validations en cours
- Afficher toutes les informations nécessaires à la décision (poster, synopsis, durée, bande-annonce)

### 6.4 Import de l'Existant Non Prévu

**Ce qui s'est passé :**
- L'application a grandi avec la vidéothèque
- Pas de mécanisme pour importer une vidéothèque existante
- Repartir de zéro était la seule option

**Comment éviter :**
- Prévoir la commande `import` dès la v1
- Séparer l'import (lecture seule) de l'enrichissement (appels API)
- Gérer les symlinks cassés avec grâce
- Permettre l'import incrémental

---

## Résumé des Priorités

### Haute Priorité (bloquant)

| Piège | Phase | Impact |
|-------|-------|--------|
| Couplage CLI/Métier | Architecture | Évolutivité impossible |
| Rate Limiting TMDB | API | Échecs de traitement |
| Symlinks Windows | Transfert | Non-fonctionnel sur Windows |
| Caractères spéciaux | Renommage | Fichiers inaccessibles |

### Moyenne Priorité (dégradation)

| Piège | Phase | Impact |
|-------|-------|--------|
| Ambiguïté Film/Série | Parsing | Mauvais classement |
| Données TMDB manquantes | Matching | Score bas, validation manuelle |
| Accès concurrent SQLite | BDD | Erreurs intermittentes |
| Race conditions fichiers | Transfert | Corruption possible |

### Basse Priorité (confort)

| Piège | Phase | Impact |
|-------|-------|--------|
| Performance BDD | BDD | Lenteur avec grosse vidéothèque |
| Parsing animes | Parsing | Cas particuliers non gérés |
| Dates ambiguës | Parsing | Année incorrecte |

---

## Checklist de Validation

Avant chaque phase majeure, vérifier :

- [ ] Le code métier n'importe pas de framework d'interface (typer, fastapi)
- [ ] Les appels API sont wrappés avec retry et rate limiting
- [ ] Les opérations fichiers utilisent le pattern atomique
- [ ] Les noms de fichiers sont sanitizés avant utilisation
- [ ] La BDD utilise le mode WAL
- [ ] Les tests couvrent les cas limites identifiés
- [ ] La validation manuelle est fonctionnelle et ergonomique

---

*Document généré le 2026-01-26 pour le projet CineOrg*
