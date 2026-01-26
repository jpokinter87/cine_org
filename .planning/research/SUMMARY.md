# Research Summary - CineOrg

**Project:** CineOrg
**Domain:** Media Library Management System
**Researched:** 2026-01-26
**Confidence:** HIGH

## Executive Summary

CineOrg est un système de gestion de vidéothèque Python qui combine une CLI (Typer) et une API Web (FastAPI) pour organiser des films et séries. La recherche démontre que l'architecture hexagonale (Ports & Adapters) est le pattern optimal pour ce type d'application, permettant de partager le coeur métier entre les deux interfaces sans couplage. Le stack recommandé est moderne et mature : FastAPI + Typer pour les interfaces, SQLModel pour la persistance, RapidFuzz pour le matching de titres, et httpx avec aiolimiter pour les appels API TMDB/TVDB.

Le principal risque identifié est le couplage CLI/métier, erreur commise dans la version précédente qui a rendu l'évolution impossible. Pour l'éviter, la séparation stricte des couches est critique : le domaine métier ne doit jamais importer de framework d'interface. Les autres risques majeurs incluent le rate limiting des APIs externes (40 requêtes/seconde max pour TMDB), la gestion des symlinks sur Windows, et l'ambiguïté dans le parsing des noms de fichiers (notamment la distinction film vs série).

La validation manuelle est un composant essentiel : environ 10% des fichiers nécessitent une intervention humaine. L'interface de validation doit être conçue dès le début avec affichage de posters, synopsis, et possibilité de recherche manuelle. L'import d'une vidéothèque existante est également une fonctionnalité critique qui doit être prévue dans la roadmap initiale, pas en afterthought.

## Key Findings

### Recommended Stack

L'architecture hexagonale est le pattern fondamental qui permet de séparer complètement les interfaces (CLI, Web) du coeur métier. Le domaine métier reste en Python pur sans dépendances externes, les services implémentent la logique d'orchestration, et les adapters (CLI/Web) consomment ces services via injection de dépendances. Cette séparation garantit la testabilité, la réutilisabilité du code, et l'évolutivité du système.

**Core technologies:**

- **FastAPI (>=0.115.0)**: API Web avec type hints natifs et async — framework moderne aligné avec le reste du stack
- **Typer (>=0.15.0)**: CLI avec type hints et interface intuitive — construit sur Click mais avec meilleure ergonomie
- **SQLModel (>=0.0.24)**: ORM avec intégration Pydantic — un seul modèle pour DB et validation, excellente intégration FastAPI
- **RapidFuzz (>=3.10.0)**: Fuzzy matching ultra-rapide (C++, MIT) — 10-100x plus rapide que fuzzywuzzy, token_set_ratio parfait pour les titres de films
- **httpx (>=0.28.0)**: Client HTTP async moderne — remplace requests, supporte async/await nativement
- **aiolimiter (>=1.2.0)**: Rate limiting async avec leaky bucket — critique pour respecter les limites TMDB (40 req/s)
- **tenacity (>=9.0.0)**: Retry avec backoff exponentiel — gère les échecs API avec grâce
- **guessit (>=3.8.0)**: Parsing de noms de fichiers — standard de l'industrie, reconnait titres/années/saisons/épisodes
- **pymediainfo (>=6.1.0)**: Extraction métadonnées techniques — codec, résolution, langues audio

### Expected Features

La recherche a identifié une distinction claire entre table stakes (fonctionnalités attendues par défaut) et différenciateurs (valeur ajoutée).

**Must have (table stakes):**

- Parsing automatique des noms de fichiers — extraction titre, année, saison, épisode via guessit
- Matching API TMDB/TVDB avec scoring — recherche automatique avec seuil de confiance (85%)
- Validation manuelle pour cas ambigus — interface pour résoudre les correspondances multiples ou scores faibles
- Renommage selon conventions Plex/Jellyfin — formats standard type "Titre (Année)/Titre (Année).ext"
- Organisation par genre (films) et alphabétique (séries) — arborescence Genre/Lettre pour films, Lettre/Titre pour séries
- Création de symlinks — séparation stockage brut (immutable) et présentation vidéothèque
- Gestion de la quarantaine — fichiers non résolus vers traitement_manuel/ pour traitement différé
- Rate limiting API avec retry — backoff exponentiel et respect des limites TMDB/TVDB

**Should have (competitive):**

- Preview avant renommage (dry-run) — aperçu complet des changements avant application
- Detection de doublons — par hash ou ID API pour éviter les redondances
- Affichage poster et bande-annonce — aide visuelle pour validation manuelle
- Subdivision dynamique — split automatique si > 50 fichiers dans un répertoire
- Import de vidéothèque existante — scan + parsing + import BDD avec enrichissement différé
- Detection et réparation symlinks cassés — vérification périodique et recherche automatique de fichiers déplacés
- Historique de renommage — rollback possible vers noms originaux

**Defer (v2+):**

- Collections/Sagas — regroupement de franchises (Star Wars, MCU, etc.)
- Support des éditions multiples — Theatrical, Director's Cut, Extended
- Transcodage — déléguer à Tdarr ou FFmpeg externe
- Multi-utilisateurs — hors scope pour v1
- Monitoring automatique (watchdog) — exécution à la demande suffit

### Architecture Approach

L'architecture hexagonale structure le projet en couches concentriques où le domaine métier est au centre, totalement isolé de l'infrastructure. Les ports définissent des interfaces abstraites (VideoRepository, MetadataProvider, FileScanner), les services implémentent la logique métier en orchestrant ces ports, et les adapters fournissent les implémentations concrètes (SQLAlchemy, TMDbClient, CLI, Web). Cette séparation permet de tester le domaine sans infrastructure et de changer de frameworks sans toucher au coeur métier.

**Major components:**

1. **Domain** — Entités (Video, Collection), Value Objects (FilePath, Resolution), règles métier pures sans dépendances externes
2. **Application Services** — Use cases (ScanDirectory, EnrichMetadata), orchestration des ports, logique d'application
3. **Infrastructure** — Implémentations concrètes des ports secondaires (repositories SQLAlchemy, clients API TMDB/TVDB, scanner de fichiers)
4. **Adapters** — Points d'entrée primaires (CLI Typer, Web FastAPI) qui consomment les services applicatifs
5. **Bootstrap** — Container d'injection de dépendances qui assemble toutes les couches

### Critical Pitfalls

1. **Couplage CLI/métier (Lava Flow)** — La logique métier mélangée avec l'interface rend l'évolution impossible. C'est l'erreur fatale de la v1 de CineOrg. Solution : architecture en couches stricte, le domaine ne doit JAMAIS importer typer, fastapi ou tout framework d'interface. Toute communication avec l'utilisateur passe par des DTOs.

2. **Rate limiting TMDB** — TMDB limite à ~50 req/s et 20 connexions simultanées. Sans rate limiting, les traitements de gros lots échouent avec HTTP 429. Solution : aiolimiter à 40 req/s (marge de sécurité), tenacity pour retry avec backoff exponentiel, cache local (24h-7j), et utilisation de `append_to_response` pour réduire le nombre d'appels.

3. **Symlinks sur Windows** — La création de symlinks nécessite des privilèges spéciaux sur Windows. Sans détection, l'application échoue silencieusement. Solution : détecter le système d'exploitation, vérifier les privilèges, documenter le Developer Mode Windows, prévoir un fallback (copie ou hardlink) si impossible.

4. **Ambiguïté film vs série dans GuessIt** — GuessIt détecte les séries via les patterns d'épisodes, mais certains films contiennent "Episode" dans le titre (Star Wars). Solution : utiliser le contexte du répertoire source comme indice primaire, post-traiter pour corriger les patterns suspects (S07E20 = probablement 720p), valider avec l'API.

5. **God Object (Big Ball of Mud)** — Une classe qui accumule trop de responsabilités devient impossible à maintenir. Solution : appliquer le Single Responsibility Principle dès le début, découper en modules spécialisés (scanner, parser, matcher, renamer, transferer), chaque module n'a qu'une seule raison de changer.

6. **Race conditions fichiers** — Les opérations fichiers non-atomiques peuvent corrompre les données. Solution : pattern "write to temp, then rename" pour écritures atomiques, ne jamais faire check-then-act (TOCTOU), utiliser atomicwrites pour opérations critiques.

7. **Validation manuelle sous-estimée** — Dans la v1, la validation manuelle était un afterthought avec une interface CLI peu ergonomique. Or ~10% des fichiers nécessitent une intervention humaine. Solution : concevoir le workflow de validation dès le début, afficher poster/synopsis/durée/bande-annonce, prévoir stockage et reprise des validations en cours.

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: Fondations (Domain + Ports + Config)
**Rationale:** Établir l'architecture en couches AVANT tout code fonctionnel pour éviter le couplage CLI/métier. Le domaine métier pur et les interfaces abstraites permettent de développer en parallèle par la suite.
**Delivers:** Entités du domaine (Video, Collection), Value Objects, interfaces des ports (VideoRepository, MetadataProvider, FileScanner), configuration Pydantic
**Addresses:** Architecture hexagonale (ARCHITECTURE.md), séparation stricte des couches
**Avoids:** Couplage CLI/métier (PITFALLS.md #1), God Object (PITFALLS.md #5)

### Phase 2: Infrastructure (Persistence + APIs + Scanner)
**Rationale:** Implémenter les adaptateurs secondaires (base de données, APIs externes, file system) avant les interfaces primaires. Permet de tester l'infrastructure indépendamment.
**Delivers:** SQLModel repositories avec SQLite + WAL mode, clients API TMDB/TVDB avec rate limiting et retry, scanner de fichiers async, parser GuessIt avec corrections
**Addresses:** Stack technique (STACK.md), gestion des APIs externes, parsing de fichiers
**Avoids:** Rate limiting TMDB (PITFALLS.md #2), ambiguïté parsing (PITFALLS.md #4), race conditions (PITFALLS.md #6)
**Uses:** SQLModel, httpx, aiolimiter, tenacity, guessit, pymediainfo

### Phase 3: Services Métier (Use Cases + DI Container)
**Rationale:** Implémenter la logique métier qui orchestre l'infrastructure. Container DI permet l'assemblage propre et facilite les tests.
**Delivers:** LibraryService, ScanService, MetadataService, MatcherService, container d'injection de dépendances manuel
**Addresses:** Coeur métier réutilisable entre CLI et Web
**Implements:** Application Services layer (ARCHITECTURE.md)

### Phase 4: Interface CLI
**Rationale:** CLI d'abord car plus simple que le Web, permet de valider tout le coeur métier avant d'ajouter la complexité Web. Utilisable immédiatement pour traiter des fichiers.
**Delivers:** Commandes scan, search, enrich, validate, config, import, repair
**Addresses:** Table stakes CLI (FEATURES.md)
**Uses:** Typer, Rich pour output formatté

### Phase 5: Validation Manuelle (UI Web - Core)
**Rationale:** La validation manuelle est critique (~10% des fichiers) et nécessite une interface riche. C'est la feature la plus importante du Web.
**Delivers:** Interface Web pour validation de correspondances ambiguës, affichage poster/synopsis/bande-annonce, recherche manuelle override, workflow de validation par lot
**Addresses:** Must-have validation manuelle (FEATURES.md), leçon v1 (PITFALLS.md #7)
**Avoids:** Validation manuelle sous-estimée (PITFALLS.md #7)
**Uses:** FastAPI, HTMX ou frontend simple

### Phase 6: Import Vidéothèque Existante
**Rationale:** Fonctionnalité critique pour adoption : permet de migrer une vidéothèque existante sans repartir de zéro. Leçon importante de la v1.
**Delivers:** Scan complet d'une vidéothèque organisée, parsing et import BDD, enrichissement différé avec rate limiting, gestion symlinks cassés, reprise après interruption
**Addresses:** Should-have import (FEATURES.md), leçon v1 (PITFALLS.md #6.4)

### Phase 7: Features Avancées (Dashboard + Maintenance)
**Rationale:** Une fois le coeur fonctionnel, ajouter les features de confort et de maintenance.
**Delivers:** Dashboard Web avec stats, détection et réparation symlinks cassés, detection doublons, preview dry-run, historique de renommage
**Addresses:** Should-have features (FEATURES.md)

### Phase 8: Organisation Avancée (Subdivision + Collections)
**Rationale:** Features différenciantes mais non critiques, peuvent être différées.
**Delivers:** Subdivision dynamique si > 50 fichiers, gestion collections/sagas, support éditions multiples, articles ignorés pour tri (The Matrix -> M)
**Addresses:** Should-have organisation (FEATURES.md)

### Phase Ordering Rationale

- **Foundation-first (Phase 1-2):** Établir l'architecture et l'infrastructure AVANT les interfaces évite le couplage et permet le développement parallèle des adapters. C'est la leçon la plus importante de la v1.
- **CLI before Web (Phase 4 avant 5):** La CLI valide tout le coeur métier avec moins de complexité. Le Web ajoute ensuite la richesse d'interface pour la validation manuelle.
- **Validation manual early (Phase 5):** La validation manuelle impacte ~10% des fichiers, c'est un composant critique, pas un afterthought. L'interface Web est justifiée principalement pour cette feature.
- **Import in core roadmap (Phase 6):** Pas en v2, mais dans le MVP. C'est une fonctionnalité d'adoption critique basée sur l'expérience v1.
- **Advanced features deferred (Phase 7-8):** Collections, subdivisions, historique sont du polish, pas des blockers pour l'utilisation quotidienne.

### Research Flags

Phases likely needing deeper research during planning:

- **Phase 2 (Infrastructure):** Recherche approfondie sur l'implémentation du rate limiting TMDB avec aiolimiter + tenacity. Tester les limites réelles, optimiser le batch processing, valider la stratégie de cache.
- **Phase 5 (Validation Web):** Recherche UX pour workflow de validation optimal. Quelle stack frontend (HTMX, Alpine.js, React) ? Comment structurer le flux de validation par lot ?
- **Phase 6 (Import):** Recherche sur la détection et réparation de symlinks cassés. Comment gérer les vidéothèques mal organisées ? Quel niveau de tolérance aux erreurs ?

Phases with standard patterns (skip research-phase):

- **Phase 1 (Fondations):** Patterns Domain-Driven Design bien établis, documentation AWS et articles complets disponibles.
- **Phase 3 (Services):** Pattern Service Layer + Repository standard, multiples exemples Python disponibles.
- **Phase 4 (CLI):** Typer très bien documenté, patterns CLI standards.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Technologies matures, documentation officielle complète, versions stables disponibles. SQLModel en évolution mais fallback SQLAlchemy garanti. |
| Features | HIGH | Comparaison avec Radarr, Sonarr, FileBot, mnamer fournit un consensus clair sur les table stakes. Plex/Jellyfin définissent les conventions de nommage standards. |
| Architecture | HIGH | Architecture hexagonale pattern établi avec multiples implémentations Python de référence (GitHub). AWS Prescriptive Guidance valide l'approche. |
| Pitfalls | HIGH | Sources multiples (TMDB docs officiels, issues GitHub GuessIt, expérience v1 CineOrg). Rate limiting et parsing documentés avec solutions éprouvées. |

**Overall confidence:** HIGH

### Gaps to Address

- **Performance SQLite à grande échelle:** La recherche couvre SQLite jusqu'à ~10 000 entrées. Au-delà, migration vers PostgreSQL potentiellement nécessaire. Valider lors de l'implémentation avec tests de charge.

- **Parsing animes:** GuessIt a des limitations connues sur les animes (numérotation absolue, titres avec tirets). La recherche identifie le problème mais pas de solution complète. Considérer intégration AniDB/MyAnimeList en v2 ou accepter le traitement manuel pour les animes.

- **Support multi-langues API:** TMDB language parameter pas toujours fiable (~50% coverage pour titres français). La stratégie de fallback (titre original -> titre traduit -> recherche manuelle) est définie mais nécessitera calibration pendant l'implémentation.

- **Windows symlink fallback:** La détection de privilèges Windows est documentée, mais le choix du fallback (hardlink vs copie) nécessite tests utilisateurs. Hardlinks ne fonctionnent pas cross-filesystem, copie consomme espace disque.

## Recommandations Clés pour CineOrg

1. **Architecture hexagonale stricte dès le jour 1** — Le domaine métier ne doit JAMAIS importer typer ou fastapi. C'est la garantie d'évolutivité et la leçon principale de la v1.

2. **Rate limiting TMDB à 40 req/s avec marge de sécurité** — Utiliser aiolimiter + tenacity, cacher les réponses 24h-7j, utiliser append_to_response pour réduire les appels.

3. **Validation manuelle comme feature première classe** — Interface riche avec poster/synopsis/bande-annonce, workflow par lot, stockage des validations en cours. ~10% des fichiers en dépendent.

4. **SQLite en mode WAL pour éviter les locks** — Configuration PRAGMA journal_mode=WAL, transactions courtes, pool de connexions bien configuré.

5. **GuessIt avec post-traitement** — Utiliser le contexte du répertoire source comme indice primaire, corriger les patterns suspects (720 -> 720p pas S07E20), valider avec API.

6. **Import de vidéothèque existante dans MVP** — Pas en v2, fonctionnalité d'adoption critique basée sur expérience v1.

7. **Tests couvrant les edge cases identifiés** — Symlinks Windows, caractères spéciaux dans noms de fichiers, race conditions, résolutions sans "p", ambiguïté film/série.

## Sources

### Primary (HIGH confidence)

- [TMDB Rate Limiting Documentation](https://developer.themoviedb.org/docs/rate-limiting) — Limites officielles et recommandations
- [SQLModel Official Documentation](https://sqlmodel.tiangolo.com/) — Integration FastAPI + Pydantic
- [AWS Prescriptive Guidance - Hexagonal Architecture](https://docs.aws.amazon.com/prescriptive-guidance/latest/patterns/structure-a-python-project-in-hexagonal-architecture-using-aws-lambda.html) — Pattern architectural validé
- [Plex Naming Guide](https://support.plex.tv/articles/naming-and-organizing-your-movie-media-files/) — Conventions de nommage standard
- [GuessIt GitHub Issues](https://github.com/guessit-io/guessit/issues) — Limitations documentées et workarounds

### Secondary (MEDIUM confidence)

- [Building Maintainable Python Applications with Hexagonal Architecture](https://dev.to/hieutran25/building-maintainable-python-applications-with-hexagonal-architecture-and-domain-driven-design-chp) — Implémentation Python détaillée
- [RapidFuzz GitHub](https://github.com/rapidfuzz/RapidFuzz) — Benchmarks et comparaisons
- [TRaSH Guides - Recommended Naming Scheme](https://trash-guides.info/Radarr/Radarr-recommended-naming-scheme/) — Best practices communauté
- [Going Fast with SQLite and Python](https://charlesleifer.com/blog/going-fast-with-sqlite-and-python/) — Optimisations SQLite

### Tertiary (LOW confidence)

- Multiples articles Medium sur Python design patterns — Consensus général mais nécessite validation
- Issues GitHub communautaires sur parsing — Expériences utilisateurs à valider lors de l'implémentation

---
*Research completed: 2026-01-26*
*Ready for roadmap: yes*
