# CineOrg

## What This Is

Application de gestion de vidéothèque personnelle. Scanne les téléchargements, identifie les contenus via TMDB/TVDB, renomme et organise les fichiers selon un format standardisé, crée des symlinks pour le mediacenter. Réécriture complète d'une application existante devenue difficile à maintenir.

**v1.0 shipped:** Application CLI complète avec architecture hexagonale, parsing guessit/mediainfo, clients API TMDB/TVDB avec cache et rate limiting, base SQLite, validation interactive Rich, et outils d'import/maintenance.

## Core Value

**Architecture propre avec séparation claire entre logique métier et interfaces.** Le cœur métier est réutilisable par CLI et Web sans duplication de code. Le code est maintenable et évolutif — objectif atteint avec v1.0.

## Requirements

### Validated

- ✓ Structure hexagonale avec séparation domain/application/infrastructure/adapters — v1.0
- ✓ Container DI partagé entre CLI et Web — v1.0
- ✓ Configuration via pydantic-settings avec validation — v1.0
- ✓ Logging structuré avec rotation et niveaux configurables — v1.0
- ✓ Scan récursif des répertoires téléchargements — v1.0
- ✓ Extraction métadonnées via guessit (titre, année, saison, épisode) — v1.0
- ✓ Extraction infos techniques via mediainfo (codec, résolution, langues, durée) — v1.0
- ✓ Détection automatique du type (film vs série) — v1.0
- ✓ Client TMDB pour films — v1.0
- ✓ Client TVDB pour séries — v1.0
- ✓ Système de scoring (50/25/25) avec seuil 85% — v1.0
- ✓ Cache API (24h recherches, 7j détails) — v1.0
- ✓ Rate limiting avec retry et backoff — v1.0
- ✓ Validation automatique si score >= 85% et unique — v1.0
- ✓ Interface CLI validation manuelle avec Rich — v1.0
- ✓ Recherche manuelle par titre et saisie ID — v1.0
- ✓ Validation finale batch avant transfert — v1.0
- ✓ Renommage format standardisé — v1.0
- ✓ Organisation films par genre/lettre — v1.0
- ✓ Organisation séries par lettre/saison — v1.0
- ✓ Symlinks dans video/ vers stockage/ — v1.0
- ✓ Base SQLite avec SQLModel — v1.0
- ✓ Tables pending_validation et trash — v1.0
- ✓ Index sur colonnes fréquentes — v1.0
- ✓ Hash fichier pour détection doublons — v1.0
- ✓ Commandes CLI: process, pending, validate, import, enrich, repair-links, check — v1.0
- ✓ Import vidéothèque existante — v1.0
- ✓ Enrichissement métadonnées via API — v1.0
- ✓ Détection et réparation symlinks cassés — v1.0
- ✓ Vérification intégrité BDD vs fichiers — v1.0

### Active

- [ ] Interface Web FastAPI avec commande serve
- [ ] Dashboard statistiques vidéothèque
- [ ] Validation manuelle avec posters et bandes-annonces
- [ ] Page de validation finale visuelle
- [ ] Détection doublons avant transfert
- [ ] Subdivision dynamique des répertoires (>50 fichiers)
- [ ] Mode dry-run / preview pour simulation
- [ ] Commande stats (statistiques vidéothèque)
- [ ] Commande reorganize (réorganisation et subdivision)
- [ ] Collections et sagas (regroupement franchises)

### Out of Scope

- Intégration AniDB/MAL — évolution future, architecture prête mais pas implémenté
- Recherche/filtrage dans l'interface — mentionné comme non prévu dans les specs
- Génération poster.jpg/fanart.jpg — explicitement exclu
- Multi-utilisateurs — usage personnel uniquement
- Streaming intégré — délégué à Plex/Jellyfin
- Daemon/watchdog — exécution manuelle uniquement

## Context

**Historique:** Application existante développée sur plusieurs années. A évolué par couches successives jusqu'à devenir difficile à maintenir. Tentative d'ajout d'interface web impossible car logique métier trop couplée au CLI — a nécessité de séparer les deux codebases.

**Leçon principale:** Le couplage CLI/métier a rendu l'évolution impossible. Cette réécriture a maintenant une séparation nette.

**État actuel (v1.0):**
- 9,573 lignes Python dans src/
- 400+ tests avec couverture élevée
- Architecture hexagonale respectée (vérifié par audit)
- 8 phases, 17 plans, 32 requirements complétés
- Prêt pour l'interface Web v2.0

**Vidéothèque existante:** Structure en place (Films/Genre/Lettre/, Séries/Lettre/), symlinks nommés selon format standardisé. L'application est compatible "drop-in".

## Constraints

- **Stack**: Python 3.11+, FastAPI, SQLModel, Typer, guessit, pymediainfo — choix fixés
- **Compatibilité**: Fonctionne avec la structure de fichiers existante sans migration
- **APIs**: TMDB pour films, TVDB pour séries — rate limiting géré
- **TDD**: Tests écrits avant le code, couverture ≥ 90%

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Réécriture from scratch | L'ancienne base était impossible à refactorer proprement | ✓ Good — architecture propre |
| CLI avant Web | Permet de valider le cœur métier avant d'ajouter la complexité web | ✓ Good — CLI v1.0 shipped |
| Import existant en v1 | Nécessaire pour remplacer l'ancienne application | ✓ Good — import fonctionnel |
| Architecture hexagonale | Éviter le couplage CLI/métier de la v1 | ✓ Good — séparation nette |
| diskcache pour cache API | File-based, pas de serveur externe requis | ✓ Good — simple et efficace |
| xxhash pour hash fichiers | Rapide avec échantillons début/fin/taille | ✓ Good — détection doublons fiable |
| Rich pour CLI validation | Interface interactive avec cartes et couleurs | ✓ Good — UX agréable |
| Symlinks relatifs | Portabilité entre systèmes | ✓ Good — fonctionne partout |

---
*Last updated: 2026-01-28 after v1.0 milestone*
