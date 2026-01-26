# CineOrg

## What This Is

Application de gestion de vidéothèque personnelle. Scanne les téléchargements, identifie les contenus via TMDB/TVDB, renomme et organise les fichiers selon un format standardisé, crée des symlinks pour le mediacenter. Réécriture complète d'une application existante devenue difficile à maintenir.

## Core Value

**Architecture propre avec séparation claire entre logique métier et interfaces.** Le cœur métier doit être réutilisable par CLI et Web sans duplication de code. Le code doit être maintenable et évolutif — c'est la raison de cette réécriture.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Cœur métier séparé et testable (scan, parsing, matching, renommage, transfert)
- [ ] CLI complète avec toutes les commandes
- [ ] Validation manuelle via CLI (affichage candidats, sélection utilisateur)
- [ ] Import de la vidéothèque existante dans la BDD
- [ ] Compatibilité avec la structure existante (stockage + symlinks)
- [ ] Intégration TMDB pour les films
- [ ] Intégration TVDB pour les séries
- [ ] Base de données SQLite avec SQLModel
- [ ] Système de scoring pour le matching automatique (seuil 85%)
- [ ] Gestion des fichiers non reconnus (traitement_manuel/)

### Out of Scope

- Interface web — v2, après que le CLI soit stable
- Recherche/filtrage dans l'interface — mentionné comme non prévu dans les specs
- Génération de fichiers poster.jpg/fanart.jpg — explicitement exclu
- Intégration AniDB/MAL — évolution future, architecture prête mais pas implémenté

## Context

**Historique :** Application existante développée sur plusieurs années. A évolué par couches successives jusqu'à devenir difficile à maintenir. Tentative d'ajout d'interface web impossible car logique métier trop couplée au CLI — a nécessité de séparer les deux codebases.

**Leçon principale :** Le couplage CLI/métier a rendu l'évolution impossible. Cette réécriture doit avoir une séparation nette dès le départ.

**Vidéothèque existante :** Structure déjà en place (Films/Genre/Lettre/, Séries/Lettre/), symlinks déjà nommés selon format standardisé. La nouvelle application doit être compatible "drop-in".

**Validation manuelle :** ~10% des fichiers nécessitent intervention humaine même avec bonne automatisation. Fonctionnalité critique, pas optionnelle.

## Constraints

- **Stack**: Python 3.11+, FastAPI, SQLModel, Typer, guessit, pymediainfo — choix fixés dans les specs
- **Compatibilité**: Doit fonctionner avec la structure de fichiers existante sans migration
- **APIs**: TMDB pour films, TVDB pour séries — rate limiting à gérer
- **TDD**: Tests écrits avant le code, couverture ≥ 90%

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Réécriture from scratch | L'ancienne base était impossible à refactorer proprement | — Pending |
| CLI avant Web | Permet de valider le cœur métier avant d'ajouter la complexité web | — Pending |
| Import existant en v1 | Nécessaire pour remplacer l'ancienne application | — Pending |

---
*Last updated: 2025-01-26 after initialization*
