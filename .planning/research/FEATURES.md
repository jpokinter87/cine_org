# Recherche : Fonctionnalites des Applications de Gestion de Videotheque

> Document de recherche pour CineOrg
> Date : 2026-01-26
> Sources : Radarr, Sonarr, Plex, Jellyfin, FileBot, tinyMediaManager, mnamer

---

## Table des Matieres

1. [Table Stakes (Indispensables)](#1-table-stakes-indispensables)
2. [Differenciateurs](#2-differenciateurs)
3. [Anti-Features (A Ne Pas Faire)](#3-anti-features-a-ne-pas-faire)
4. [Gestion du Matching et Renommage](#4-gestion-du-matching-et-renommage)
5. [Edge Cases Frequents](#5-edge-cases-frequents)
6. [Matrice de Dependances](#6-matrice-de-dependances)

---

## 1. Table Stakes (Indispensables)

Ces fonctionnalites sont attendues par defaut et leur absence serait redhibitoire.

### 1.1 Parsing et Identification

| Feature | Description | Complexite | Statut CineOrg |
|---------|-------------|------------|----------------|
| **Parsing nom de fichier** | Extraction titre, annee, saison, episode via guessit | Moyenne | Prevu |
| **Extraction metadonnees techniques** | Codec video/audio, resolution, langues via mediainfo | Moyenne | Prevu |
| **Detection type media** | Distinguer film vs serie automatiquement | Faible | Prevu |
| **Support multi-extensions** | .mkv, .mp4, .avi, .mov, .m4v, .webm | Faible | Prevu |

### 1.2 Matching API

| Feature | Description | Complexite | Statut CineOrg |
|---------|-------------|------------|----------------|
| **Integration TMDB** | Recherche et enrichissement films | Moyenne | Prevu |
| **Integration TVDB** | Recherche et enrichissement series | Moyenne | Prevu |
| **Scoring de correspondance** | Algorithme titre + annee + duree | Moyenne | Prevu |
| **Validation automatique** | Si score >= seuil et resultat unique | Faible | Prevu |
| **Validation manuelle** | Interface pour cas ambigus | Haute | Prevu |

### 1.3 Renommage et Organisation

| Feature | Description | Complexite | Statut CineOrg |
|---------|-------------|------------|----------------|
| **Format de nommage configurable** | Templates personnalisables | Moyenne | Prevu |
| **Organisation par genre (films)** | Arborescence Genre/Lettre | Moyenne | Prevu |
| **Organisation alphabetique (series)** | Arborescence Lettre/Titre | Faible | Prevu |
| **Gestion des saisons** | Structure Titre/Saison XX/ | Faible | Prevu |
| **Creation de symlinks** | Separation stockage/presentation | Moyenne | Prevu |

### 1.4 Conventions de Nommage Standards

| Feature | Description | Complexite | Statut CineOrg |
|---------|-------------|------------|----------------|
| **Format Plex-compatible** | `Titre (Annee)/Titre (Annee).ext` | Faible | Prevu |
| **Episodes S##E##** | Format standard `S01E01` | Faible | Prevu |
| **ID dans nom de fichier** | Support `{tmdb-123456}` ou `{tvdb-123456}` | Faible | A considerer |
| **Annee obligatoire** | Inclure l'annee pour desambiguer | Faible | Prevu |

### 1.5 Gestion des Erreurs

| Feature | Description | Complexite | Statut CineOrg |
|---------|-------------|------------|----------------|
| **Repertoire de quarantaine** | Fichiers non resolus -> traitement_manuel/ | Faible | Prevu |
| **Logging detaille** | Tracabilite des operations | Faible | Prevu |
| **Gestion rate limiting API** | Backoff exponentiel, retry | Moyenne | Prevu |
| **Detection fichiers corrompus** | Via mediainfo | Faible | Prevu |

---

## 2. Differenciateurs

Ces fonctionnalites ajoutent de la valeur mais ne sont pas critiques pour un MVP.

### 2.1 Fonctionnalites Avancees de Matching

| Feature | Description | Complexite | Priorite | Dependances |
|---------|-------------|------------|----------|-------------|
| **Fix Match manuel** | Recherche libre + saisie ID IMDB/TMDB | Moyenne | Haute | UI Web |
| **Preview avant renommage** | Dry-run avec apercu des changements | Moyenne | Haute | - |
| **Historique de renommage** | Rollback possible vers nom original | Haute | Moyenne | BDD |
| **Detection doublons** | Par hash ou par ID API | Moyenne | Haute | BDD |
| **Multi-sources API** | Fallback TMDB -> IMDB -> OMDB | Haute | Basse | API clients |

### 2.2 Organisation Avancee

| Feature | Description | Complexite | Priorite | Dependances |
|---------|-------------|------------|----------|-------------|
| **Subdivision dynamique** | Split automatique si > 50 fichiers | Haute | Haute | Reorganizer |
| **Collections/Sagas** | Regroupement films d'une meme franchise | Moyenne | Moyenne | BDD + TMDB |
| **Editions multiples** | Theatrical, Director's Cut, Extended | Moyenne | Basse | Parser |
| **Articles ignores pour tri** | "The Matrix" -> classe sous M | Faible | Haute | - |

### 2.3 Interface et UX

| Feature | Description | Complexite | Priorite | Dependances |
|---------|-------------|------------|----------|-------------|
| **Affichage poster** | Vignette visuelle pour validation | Faible | Haute | TMDB API |
| **Lien bande-annonce** | Lecture YouTube integree | Faible | Moyenne | TMDB API |
| **Lecture fichier local** | Lancer lecteur systeme | Faible | Haute | OS integration |
| **Validation par lot** | Traiter plusieurs fichiers a la fois | Moyenne | Moyenne | UI Web |
| **Progression en temps reel** | Barre de progression, ETA | Moyenne | Basse | WebSocket/HTMX |

### 2.4 Maintenance et Reparation

| Feature | Description | Complexite | Priorite | Dependances |
|---------|-------------|------------|----------|-------------|
| **Detection symlinks casses** | Verification periodique | Faible | Haute | - |
| **Reparation automatique** | Recherche fichier deplace | Moyenne | Haute | Scanner |
| **Corbeille avec retention** | Suppression differee | Faible | Moyenne | BDD |
| **Verification integrite** | Coherence BDD/filesystem | Moyenne | Moyenne | BDD |

### 2.5 Import et Migration

| Feature | Description | Complexite | Priorite | Dependances |
|---------|-------------|------------|----------|-------------|
| **Import bibliotheque existante** | Scan + parsing + import BDD | Haute | Critique | Scanner, Parser |
| **Enrichissement differe** | API calls avec rate limiting | Moyenne | Haute | API clients |
| **Reprise apres interruption** | Sauvegarde progression | Moyenne | Haute | BDD |

---

## 3. Anti-Features (A Ne Pas Faire)

### 3.1 Complexite Inutile

| Anti-Feature | Raison d'eviter | Alternative |
|--------------|-----------------|-------------|
| **Daemon/Watchdog permanent** | Surcharge systeme, complexite | Execution manuelle a la demande |
| **Multi-utilisateurs** | Hors scope, complexite auth | Application mono-utilisateur |
| **Streaming integre** | Reinventer Plex/Jellyfin | Symlinks compatibles mediacenter |
| **Telechargement automatique** | Hors scope, legal, complexite | Integration externe (Radarr/Sonarr) |
| **Transcodage** | Ressources, complexite | Delegation a Tdarr ou FFmpeg externe |

### 3.2 UX Anti-Patterns

| Anti-Feature | Raison d'eviter | Alternative |
|--------------|-----------------|-------------|
| **Actions irreversibles sans confirmation** | Perte de donnees | Dry-run par defaut, confirmation explicite |
| **Renommage fichiers stockage** | Risque de perte, lent | Renommer uniquement les symlinks |
| **Suppression automatique sans corbeille** | Perte definitive | Corbeille avec retention 30 jours |
| **Modification silencieuse** | Utilisateur perd le controle | Rapport systematique des changements |
| **Matching automatique sans seuil** | Mauvaises correspondances | Seuil configurable (85% par defaut) |

### 3.3 Integration Anti-Patterns

| Anti-Feature | Raison d'eviter | Alternative |
|--------------|-----------------|-------------|
| **Appels API sans cache** | Rate limiting, lenteur | Cache local 24h-7j |
| **Dependance API unique** | Point de defaillance unique | File d'attente si API down |
| **Mixing databases** | TMDB vs TVDB ordering conflicts | Choisir une source par type |
| **Hardlinks cross-filesystem** | Ne fonctionne pas | Symlinks ou verification meme FS |

### 3.4 Architecture Anti-Patterns

| Anti-Feature | Raison d'eviter | Alternative |
|--------------|-----------------|-------------|
| **God Object** | Maintenance impossible | Modules separes (SOLID) |
| **Couplage fort aux APIs** | Difficulte tests et evolution | Interface abstraite MediaAPIClient |
| **Configuration hardcodee** | Inflexibilite | Fichier config.json + env vars |
| **Pas de dry-run** | Modifications non previsibles | Option --dry-run systematique |

---

## 4. Gestion du Matching et Renommage

### 4.1 Approche Radarr/Sonarr

**Points forts a reprendre :**
- Profils de qualite configurables
- Renommage automatique selon template
- Integration avec indexers et download clients
- Preview des changements avant application

**Points a ne pas reprendre (hors scope) :**
- Telechargement automatique
- Monitoring RSS feeds
- Integration torrent/usenet

### 4.2 Approche Plex/Jellyfin

**Conventions de nommage recommandees :**

```
Films:
/Movies/Titre (Annee)/Titre (Annee).ext
/Movies/Titre (Annee) {tmdb-123456}/Titre (Annee) {tmdb-123456}.ext

Series:
/TV Shows/Titre (Annee)/Season 01/Titre (Annee) - S01E01 - Titre Episode.ext
/TV Shows/Titre (Annee) {tvdb-123456}/Season 01/...
```

**Bonnes pratiques :**
- Toujours inclure l'annee pour desambiguer (ex: "It" 1990 vs 2017)
- Utiliser des espaces, pas des points entre les mots
- Season avec numero 2 chiffres (Season 01, pas Season 1)
- Eviter caracteres speciaux : `< > : " / \ | ? *`

### 4.3 Approche FileBot

**Points forts :**
- Templates de renommage puissants (expressions Groovy)
- Multi-sources (TMDB, TVDB, AniDB, OMDB)
- Mode batch efficace
- AMC script pour automatisation complete

**Lecons a retenir :**
- Presets pour cas d'usage courants
- Override manuel avec `--id-tmdb` ou `--id-tvdb`
- Option `--no-guess` si reseau down

### 4.4 Approche mnamer

**Points forts :**
- Simple et Python-natif
- Support TMDB + TVDB + OMDB + TVMaze
- CLI moderne avec options explicites

**Commandes inspirantes :**
```bash
mnamer --id-tmdb=27205 movie.mkv    # Override avec ID specifique
mnamer --no-guess movie.mkv         # Pas de matching auto
mnamer --dry-run movie.mkv          # Apercu sans modification
```

---

## 5. Edge Cases Frequents

### 5.1 Episodes Multiples

| Cas | Format fichier | Format renomme | Gestion |
|-----|---------------|----------------|---------|
| Episode double | `Show.S01E01E02.mkv` | `Show - S01E01E02 - Titre.mkv` | Parser detecte, titre du 1er episode |
| Episode triple | `Show.S01E01-E03.mkv` | `Show - S01E01E02E03 - Titre.mkv` | Normaliser format |
| Episode range | `Show.S01E01-03.mkv` | `Show - S01E01E02E03 - Titre.mkv` | Expander la range |

### 5.2 Films Multi-Parties

| Cas | Format fichier | Format renomme | Gestion |
|-----|---------------|----------------|---------|
| Film 2 parties | `Movie.CD1.mkv` | `Movie (2010) - CD1.mkv` | Detecter pattern CDx, ptx |
| Film 2 fichiers | `Movie.Part1.mkv` | `Movie (2010) - Part1.mkv` | Garder dans meme dossier |

**Patterns de stacking reconnus :**
- `cd1`, `cd2`, `cd3`...
- `part1`, `part2`, `part3`...
- `pt1`, `pt2`, `pt3`...
- `disc1`, `disc2`...
- `a`, `b`, `c`, `d`

### 5.3 Editions de Films

| Cas | Detection | Format renomme |
|-----|-----------|----------------|
| Director's Cut | `DC`, `Directors.Cut` | `{edition-Director's Cut}` |
| Extended | `Extended`, `Ext.Ed` | `{edition-Extended}` |
| Theatrical | `Theatrical` | `{edition-Theatrical}` |
| Unrated | `Unrated` | `{edition-Unrated}` |
| Remastered | `Remaster`, `4K.Remaster` | `{edition-Remastered}` |

### 5.4 Anime et Ordonnancement

| Probleme | Description | Solution |
|----------|-------------|----------|
| Absolute ordering | Episodes 1-700+ sans saisons | Option `--absolute` ou detection auto |
| TVDB vs AniDB ordering | Numerotation differente | Choisir une source et s'y tenir |
| OVA/ONA/Specials | Hors saisons regulieres | Season 00 pour specials |
| Films dans series | Film lie a une serie anime | Traiter comme film separe |

**Exemple problematique : One Piece**
- TVDB : 21+ saisons avec numerotation complexe
- Fansubs : Numerotation absolute (1-1000+)
- Solution : Support du pattern `E###` comme absolute ordering

### 5.5 Series Problematiques

| Probleme | Exemple | Solution |
|----------|---------|----------|
| Annee ambigue | Doctor Who (1963 vs 2005) | Toujours inclure l'annee |
| Meme titre | "Battlestar Galactica" (1978, 2003) | ID TVDB explicite |
| Reboot/Remake | "Hawaii Five-0" vs "Hawaii Five-O" | Titre + annee + ID |
| Mini-series | "Band of Brothers" | Traiter comme saison unique |

### 5.6 Noms de Fichiers Problematiques

| Probleme | Exemple | Solution |
|----------|---------|----------|
| Caracteres interdits | `Star Wars: A New Hope` | Remplacer `:` par ` -` |
| Noms tres longs | Titre japonais complet | Tronquer intelligemment |
| Accents | `Amelie` vs `Amelie` | Conserver accents, normaliser pour tri |
| Chiffres romains | `Rocky IV` | Conserver tel quel |
| "The" prefix | `The Matrix` | Ignorer pour tri, conserver dans nom |

### 5.7 Problemes de Matching

| Probleme | Cause | Solution |
|----------|-------|----------|
| Faux positif | Titre generique ("It", "Her") | Exiger annee + duree |
| Aucun resultat | Titre mal orthographie | Recherche fuzzy + manuelle |
| Multiples resultats | Film tres commun | Duree comme discriminant |
| Film pas sur TMDB | Film rare/recent | File traitement_manuel |
| Annee decalee | Pre-release vs sortie | Tolerance +-1 an dans scoring |

### 5.8 Fichiers Techniques

| Type | Action | Raison |
|------|--------|--------|
| Sample | Ignorer | Pattern `sample` + taille < 100MB |
| Trailer | Ignorer | Pattern `trailer` |
| Extras/Bonus | Ignorer ou separer | Pattern `extras`, `bonus`, `featurette` |
| .nfo | Ignorer | Metadonnees externes |
| .srt/.sub | Ignorer (pour l'instant) | Sous-titres externes |

---

## 6. Matrice de Dependances

```
                    ┌─────────────┐
                    │   Scanner   │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │   Parser    │
                    │  (guessit)  │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼──────┐     │     ┌──────▼──────┐
       │   MediaInfo │     │     │  API Client │
       │  Extractor  │     │     │ (TMDB/TVDB) │
       └──────┬──────┘     │     └──────┬──────┘
              │            │            │
              └────────────┼────────────┘
                           │
                    ┌──────▼──────┐
                    │   Matcher   │
                    │  (Scoring)  │
                    └──────┬──────┘
                           │
              ┌────────────┴────────────┐
              │                         │
       ┌──────▼──────┐          ┌──────▼──────┐
       │  Auto Valid │          │Manual Valid │
       │  (>=85%)    │          │  (UI Web)   │
       └──────┬──────┘          └──────┬──────┘
              │                         │
              └────────────┬────────────┘
                           │
                    ┌──────▼──────┐
                    │   Renamer   │
                    │ (Templates) │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Organizer  │
                    │ (Paths)     │
                    └──────┬──────┘
                           │
              ┌────────────┴────────────┐
              │                         │
       ┌──────▼──────┐          ┌──────▼──────┐
       │  Transferer │          │  Symlinker  │
       │  (Storage)  │          │  (Video)    │
       └──────┬──────┘          └──────┬──────┘
              │                         │
              └────────────┬────────────┘
                           │
                    ┌──────▼──────┐
                    │  Database   │
                    │ (SQLModel)  │
                    └─────────────┘
```

### Ordre d'Implementation Recommande

| Phase | Modules | Dependances | Priorite |
|-------|---------|-------------|----------|
| 1 | Scanner, Parser | - | Critique |
| 2 | API Clients (TMDB, TVDB) | - | Critique |
| 3 | MediaInfo Extractor | - | Critique |
| 4 | Matcher (Scoring) | Parser, APIs | Critique |
| 5 | Database Models | - | Critique |
| 6 | Renamer | Parser, Matcher | Haute |
| 7 | Organizer | Renamer | Haute |
| 8 | Transferer + Symlinker | Organizer | Haute |
| 9 | CLI Commands | Tous les modules | Haute |
| 10 | Web UI - Dashboard | Database | Moyenne |
| 11 | Web UI - Validation | Matcher, Database | Moyenne |
| 12 | Importer (existant) | Scanner, Parser, Database | Moyenne |
| 13 | Enricher | APIs, Database | Moyenne |
| 14 | Repair/Integrity | Scanner, Database | Moyenne |
| 15 | Reorganizer | Organizer, Database | Basse |

---

## Sources

### Documentation Officielle
- [Plex Naming Guide](https://support.plex.tv/articles/naming-and-organizing-your-movie-media-files/)
- [Jellyfin TV Shows Documentation](https://jellyfin.org/docs/general/server/media/shows/)
- [Radarr Troubleshooting Wiki](https://wiki.servarr.com/radarr/troubleshooting)
- [Sonarr Troubleshooting Wiki](https://wiki.servarr.com/sonarr/troubleshooting)

### Guides Communautaires
- [TRaSH Guides - Recommended Naming Scheme](https://trash-guides.info/Radarr/Radarr-recommended-naming-scheme/)
- [FileBot Naming Schemes](https://www.filebot.net/forums/viewtopic.php?t=4116)

### Outils de Reference
- [FileBot](https://www.filebot.net/)
- [mnamer (PyPI)](https://pypi.org/project/mnamer/)
- [tinyMediaManager](https://www.tinymediamanager.org/)
- [Absolute Series Scanner (Plex)](https://github.com/ZeroQI/Absolute-Series-Scanner)

### Ecosysteme *arr
- [Servarr Wiki](https://wiki.servarr.com/)
- [Prowlarr](https://prowlarr.com/) - Indexer manager
- [Bazarr](https://www.bazarr.media/) - Subtitle management
- [Tdarr](https://home.tdarr.io/) - Transcoding automation
