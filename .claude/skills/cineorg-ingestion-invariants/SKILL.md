---
name: cineorg-ingestion-invariants
description: >-
  Invariants métier de CineOrg pour toute ingestion, transfert ou réorganisation de médias.
  À utiliser AVANT d'écrire ou modifier du code qui fait entrer/déplacer/réorganiser des films
  ou séries : workflow `process`, migrate-nas, consolidate, dédup séries, réparation ou réorg
  manuelle de symlinks. À utiliser AUSSI quand un résultat diffère entre deux chemins (ex. notes
  TMDB/IMDb manquantes après migrate-nas ou consolidation, symlinks cassés, désync storage↔DB,
  transfert NAS bloqué, mauvais matching). Réflexe : le workflow `process` est la référence
  canonique — confronter tout autre chemin à ses invariants avant de coder.
---

# Invariants d'ingestion CineOrg

## Principe directeur

Il existe **plusieurs chemins d'entrée** pour les médias, mais **un seul comportement correct**.
Le workflow `process` (`src/services/workflow/`) est la **référence canonique** : il fonctionne de
façon plus que satisfaisante. Tout autre chemin (migrate-nas, consolidation, dédup, réorg manuelle)
**doit produire le même résultat**. Avant d'écrire du code sur un chemin alternatif, **chercher la
fonction/service que `process` utilise déjà et la réutiliser** plutôt que réimplémenter — c'est la
correction la plus fréquente dans l'historique de ce projet.

## Pipeline canonique (à réutiliser)

`WorkflowService.execute()` (`src/services/workflow/workflow_service.py`) enchaîne :

1. `_cleanup_orphans` — purge PendingValidation/VideoFile des runs interrompus
2. `_scan_downloads` (`scan_step.py`)
3. `_perform_matching` → `pending_factory.create_pending_validation` (recherche API + scoring + enrichissement candidats)
4. `_auto_validate` (score ≥ 85 % ET candidat unique) puis `_manual_validate`
5. `_batch_transfer` → **`build_transfers_batch`** (`src/adapters/cli/batch_builder.py`) → `execute_batch_transfer`
6. `_update_file_paths` — écrit `file_path` **ET** `symlink_path` sur `MovieModel`/`EpisodeModel`

## Les invariants (checklist avant de coder)

1. **Enrichissement des notes — sur CHAQUE chemin.** Les notes (`vote_average`, `imdb_rating`) sont
   attachées dans `batch_builder.py` via `_enrich_movie_metadata` / `_enrich_series_metadata`,
   appelés par `build_transfers_batch`. Un chemin qui **contourne** `build_transfers_batch`
   (migrate-nas, `consolidation.py`, réinjection sandbox…) doit appeler le même enrichissement,
   sinon les notes manquent. C'est le bug récurrent (séries sans note après migrate-nas/consolidation,
   notes TMDB sans IMDb). Réutiliser `ratings_enricher`/`series_enricher`, ne pas réinventer.

2. **storage ≠ vérité ; symlink = vérité.** La zone `storage/` (arbo physique canonique) peut être
   « éclatée » ou mal rangée (épisodes d'une même série répartis sur plusieurs lettres) **sans aucun
   problème** tant que les **symlinks de `video/` sont intacts**. Pour la réparation/réorg, raisonner
   à partir des symlinks, pas du storage. → voir `references/symlink-db-reconciliation.md`.

3. **Réorg > 50 fichiers = symlinks uniquement.** Les subdivisions alphabétiques
   (`max_files_per_subdir = 50`) ne déplacent QUE les symlinks de `video/`, **jamais** les fichiers
   physiques de `storage/`.

4. **DB cohérente après tout déplacement.** Mettre à jour `file_path` **et** `symlink_path` sur
   `MovieModel`/`EpisodeModel` (cf. `_update_file_paths`). Pour retrouver une entité par `file_path`,
   passer par `_session` du repo (champ indexé sur les models, pas sur les entités domaine).

5. **Séries — répertoire avec année + garde-fou anti-homonymes.** Toujours privilégier le répertoire
   comportant l'année canonique ; y reverser les épisodes en ajoutant l'année au titre. Le garde-fou
   anti-homonymes (`series_enricher`, comptes d'épisodes) refuse les matches dont l'année n'est pas
   alignée — ne pas le court-circuiter (cas Shameless US sous « Shameless (2004) », trilogie Paris Police).

6. **Pas de hardlink seeding pour le NAS.** Un vieux NAS n'est pas une source de seeding : la
   différence avec `process` est l'absence de hardlink seeding + la suppression source, rien d'autre.

## Débogage (références dédiées)

- **Transfert NAS lent/bloqué** (rsync coincé à 99 %, débit dégressif inutile, barre de progression) :
  lire `references/nas-transfer-debug.md`.
- **Symlinks cassés / désync storage↔DB / réorg manuelle** (Paris Police, Torchwood, suffixes
  « (2) ») : lire `references/symlink-db-reconciliation.md`.
