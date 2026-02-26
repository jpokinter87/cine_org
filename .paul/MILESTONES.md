# Milestones

Completed milestone log for this project.

| Milestone | Completed | Duration | Stats |
|-----------|-----------|----------|-------|
| v1.0 Interface Web | 2026-02-23 | ~3 days | 5 phases, 8 plans |
| v1.1 Enrichissement Données | 2026-02-24 | ~1 day | 3 phases, 3 plans |
| v1.2 Gestion Associations | 2026-02-25 | ~2 days | 4 phases, 4 plans |
| v1.3 Qualité & Fluidité | 2026-02-25 | ~1 day | 3 phases, 5 plans |
| v1.4 Expérience Utilisateur | 2026-02-26 | ~1 day | 2 phases, 4 plans |
| v1.5 Polish & Corrections UX | 2026-02-26 | ~1 day | 3 phases, 4 plans |

---

## v1.5 Polish & Corrections UX

**Completed:** 2026-02-26
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 3 (17, 18, 19) |
| Plans | 4 |
| Files modified | ~21 |

### Key Accomplishments

- Bouton Visionner sur page Surprends-moi (films et séries, premier épisode S01E01)
- Bouton "Renvoyer en validation" par fichier sur page transfert avec cascade inverse séries
- Section "Auto-validés" sur page validation avec bouton Revalider et cascade série
- Fix NullPool pour SQLite (résout QueuePool exhaustion avec providers.Factory)
- Dialogues custom overlay pour toutes les confirmations destructives (remplacement confirm() natif)
- Page config avec sections pliables (accordéon) et animation CSS fluide
- Version footer dynamique lue depuis pyproject.toml via tomllib

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Route series/play → premier épisode S01E01 | Plus propre que passer episode_id au template |
| NullPool pour SQLite | Résout définitivement le QueuePool exhaustion avec providers.Factory |
| Cascade inverse séries (send-back + reset) | Miroir de l'auto-validation cascade existante |
| Dialogues custom overlay partout | Cohérence charte graphique, remplacement confirm() natif |
| Version footer via tomllib dans deps.py | Centralisé avec les templates Jinja2 |

---

## v1.4 Expérience Utilisateur

**Completed:** 2026-02-26
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 2 (15, 16) |
| Plans | 4 |

### Key Accomplishments

- Tag "déjà vu" et note étoiles (1-5) sur fiches films et séries
- Page "Surprends-moi" avec suggestion aléatoire et filtres (genre, durée, note, type)
- Navigation historique des suggestions (avant/arrière)
- Bouton accueil avec animation glow ambrée
- Lecteur vidéo configurable (mpv/vlc, local/remote, SSH)
- Profils lecteur nommés avec CRUD et sélection rapide (JSON)
- Mapping de chemins cross-platform (Linux→Linux, Linux→Windows)
- Migration transparente des paramètres .env vers profils JSON

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Suggestion random parmi éligibles | Simple et efficace, pas de ML |
| Profils lecteur JSON plutôt que .env | Basculement rapide entre machines sans redémarrer |
| SSH BatchMode=yes + ConnectTimeout=5 | Évite les blocages interactifs |
| Path mapping par préfixe | Cross-platform Linux→Linux et Linux→Windows |

---

## v1.0 Interface Web

**Completed:** 2026-02-23
**Duration:** ~3 days

### Stats

| Metric | Value |
|--------|-------|
| Phases | 5 |
| Plans | 8 |

### Key Accomplishments

- Foundation web : FastAPI app, layout Jinja2 thème sombre, HTMX, page d'accueil stats
- Validation visuelle : liste pending, détail candidats enrichis, actions HTMX
- Orchestration workflow : scan, matching, auto-validation avec SSE temps réel
- Transfert et résolution de conflits via le web
- Navigation bibliothèque films/séries avec filtres, fiches détaillées
- Page configuration (répertoires, clés API, seuils)
- Maintenance : diagnostics intégrité et cleanup avec SSE temps réel

---

## v1.1 Enrichissement Données

**Completed:** 2026-02-24
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 3 |
| Plans | 3 |

### Key Accomplishments

- Ratings films enrichis à 100% (IMDb via TMDB, progress bar Rich)
- Séries enrichies : tmdb_id 99.7%, imdb_id 98.3%
- Fiches web enrichies : liens IMDb/TMDB, crédits cliquables, filtre par personne

---

## v1.2 Gestion Associations

**Completed:** 2026-02-25
**Duration:** ~2 days (2026-02-24 → 2026-02-25)

### Stats

| Metric | Value |
|--------|-------|
| Phases | 4 (9, 9b, 10, 11) |
| Plans | 4 |
| Files created | ~10 |
| Files modified | ~25 |

### Key Accomplishments

- Correction manuelle d'associations TMDB : overlay de recherche avec indicateurs de confiance durée/saisons, dialog de confirmation custom
- Filtres avancés bibliothèque : résolution (4K/1080p/720p/SD), codec vidéo/audio, recherche étendue synopsis
- Cartouches techniques cliquables sur fiches détaillées + badges Multi langues
- Navigation prev/next entre fiches avec prefetch et flèches clavier
- Propagation complète des métadonnées techniques dans le pipeline workflow
- Détection automatique d'associations suspectes : AssociationChecker avec heuristiques titre/année/durée, scan SSE temps réel, cache 24h
- Confirmation manuelle des associations avec persistance en DB
- Dashboard qualité : métriques de couverture enrichissement, résumé suspects, historique corrections
- Enrichissement 923 séries avec tvdb_id via TMDB API + purge 29 séries documentaires

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Durée fichier via mediainfo (pas la DB) | La durée DB peut correspondre à une mauvaise association TMDB |
| SSE + cache fichier 24h pour scan qualité | 5000+ fichiers trop lent pour requête bloquante, cache survit aux --reload |
| Comparaison original_title | Réduit les faux positifs pour les films étrangers |
| data-* attributes au lieu de onclick | Les apostrophes dans les titres cassaient le JS |
| Durée en pourcentage (30%/15%) | Évite les faux positifs selon la durée du film |
| Séries documentaires exclues | Identification trop difficile, hors périmètre |

---

## v1.3 Qualité & Fluidité

**Completed:** 2026-02-25
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 3 (12, 13, 14) |
| Plans | 5 |
| Files created | ~7 |
| Files modified | ~20 |

### Key Accomplishments

- Tri bibliothèque normalisé : accents, ligatures (œ/æ), articles, caractères invisibles
- Recherche unicode-aware avec variantes de ligatures
- Enrichissement batch : link-movies (file_path), enrich-tech (métadonnées techniques), enrich-episode-titles (titres épisodes TVDB)
- Code matching partagé CLI/web via pending_factory.py (factory functions standalone)
- Package library/ découpé en 6 modules spécialisés (1250 lignes → 6 fichiers)
- Boutons d'accès rapide guidant workflow → validation → transfert
- Cohérence visuelle boutons page d'accueil

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Ligatures par expansion explicite (œ→oe) | Plus simple et fiable que table Unicode |
| Recherche SQL via OR sur variantes | Contourne limitation SQLite LIKE unicode |
| Factory standalone pour code partagé | Plus simple qu'une classe abstraite, deps explicites |
| Package library/ avec sous-routers | Découpage fichier monolithique en modules cohérents |
| Boutons accès rapide plutôt que redirections auto | Respect du rythme utilisateur |

---

*Last updated: 2026-02-26*
