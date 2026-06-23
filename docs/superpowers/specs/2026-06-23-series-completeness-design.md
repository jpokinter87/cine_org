# Surveillance de la complétude des séries — Design

**Date** : 2026-06-23
**Statut** : Validé (en attente de relecture utilisateur)

## Contexte et objectif

CineOrg ne sait pas, aujourd'hui, dire si une série de la vidéothèque est
**complète** ou s'il lui manque des épisodes/saisons par rapport aux bases en
ligne. On veut déléguer au programme la surveillance de cette complétude, afin
de :

- repérer les **vrais trous** (un épisode manquant suite à une erreur de
  téléchargement ou une perte de fichier) ;
- repérer les **séries dont le téléchargement épisode par épisode a été
  interrompu** et jamais repris.

Le résultat doit être exploitable comme **badge « incomplet »** et comme
**filtre** pour lister toutes les séries incomplètes. La fiche d'une série
incomplète doit afficher **les éléments qui justifient** ce statut.

## Décision structurante : définition de « incomplet » (interprétation A)

Le statut TMDB (`Returning Series` / `Ended` / `Canceled`) n'est **pas** fiable
pour ce besoin : une série dormante mais dont une saison suivante est annoncée
reste `Returning Series`. On **n'utilise donc pas le statut** comme critère.

**Critère retenu : une série est incomplète s'il lui manque au moins un épisode
dont la date de diffusion est déjà passée.**

Ce critère couvre les deux cas d'usage :

- **Trou interne** : un épisode déjà diffusé manque → sa date est ≤ aujourd'hui →
  signalé.
- **Téléchargement interrompu** : tous les épisodes diffusés après le point
  d'arrêt ont une date ≤ aujourd'hui → tous signalés, indépendamment du statut
  TMDB.
- **Faux positif évité** : une saison X+1 seulement *annoncée* (dates futures ou
  absentes) n'est **pas** comptée.

Le statut TMDB pourra être affiché comme simple information contextuelle, mais
n'entre pas dans la décision.

## Définition précise de la complétude

Pour une série donnée :

- **Épisodes attendus** = tous les épisodes fournis par la source en ligne tels
  que :
  - `season_number >= 1` (exclut la saison 0 / spéciaux),
  - `episode_number >= 1` (exclut les `SxxE00` : pilotes/récaps numérotés 00),
  - `air_date` non nulle **et** `air_date <= aujourd'hui`.
- **Épisodes détenus** = il existe un `EpisodeModel` (même `series_id`,
  `season_number`, `episode_number`) avec :
  - `file_path` non vide (fichier réellement possédé — une fiche fantôme sans
    fichier compte comme manquante),
  - `is_extra = False` (les épisodes hors-canon ne comptent pas).
- **Épisodes manquants** = attendus mais non détenus.

Verdict :

- `incomplete` s'il y a au moins un épisode manquant ;
- `complete` sinon ;
- `null` (non évalué) si la série n'a pas de `tvdb_id` (non vérifiable en V1) ou
  n'a jamais été vérifiée.

Le détail distingue deux familles de manques :

- **saison entièrement absente** (aucun épisode attendu de cette saison n'est
  détenu) ;
- **épisodes manquants dans une saison partiellement présente**.

## Source de vérité

**V1 : TVDB uniquement.** Le `TVDBClient` sait déjà récupérer tous les épisodes
d'une saison avec leurs dates de diffusion
(`_fetch_all_season_episodes_raw`, bulk paginé + cache disque) et un décompte
canonique (`get_season_episode_count`). Les séries qui n'ont **que** un
`tmdb_id` restent en `completeness_status = null` (non vérifiables).

**Évolution prévue** : ajouter un repli TMDB (appel par saison
`/tv/{id}/season/{n}` ramenant les `air_date`) si le nombre de séries non
vérifiables s'avère gênant.

## Modèle de données (migration DB)

Trois colonnes ajoutées à `SeriesModel`
(`src/infrastructure/persistence/models.py`), avec migration dans
`src/infrastructure/persistence/database.py` sur le modèle de la migration
`is_extra` (`ALTER TABLE` + `CREATE INDEX`) :

- `completeness_status: str | None` — `"complete"` / `"incomplete"` / `None`,
  **indexé** (filtre = simple `WHERE`).
- `completeness_checked_at: datetime | None` — horodatage de la dernière vérif.
- `completeness_missing_json: str | None` — détail structuré alimentant la fiche.

Format de `completeness_missing_json` :

```json
{
  "missing_seasons": [4],
  "missing_episodes": [
    {"season": 2, "episode": 7, "air_date": "2019-05-12", "title": "…"}
  ],
  "expected_aired": 30,
  "owned": 24,
  "source": "tvdb"
}
```

L'entité domaine `Series` (`src/core/entities/media.py`) reçoit les champs
correspondants si nécessaire à la lecture ; le détail JSON peut rester côté
modèle DB exposé au template.

## Service `CompletenessChecker`

Nouveau sous-package `src/services/completeness/` :

- `dataclasses.py` — `CompletenessResult`, `MissingEpisode`
  (`season`, `episode`, `air_date`, `title`), structures internes.
- `completeness_checker.py` — orchestration pour une série :
  1. si pas de `tvdb_id` → résultat `null` (non vérifiable) ;
  2. récupérer les épisodes attendus via `TVDBClient` (par saison, déjà caché) ;
  3. appliquer les règles d'attendu (saison ≥ 1, épisode ≥ 1, `air_date` passée) ;
  4. récupérer les épisodes détenus via
     `episode_repository.get_by_series(series_id)` et filtrer
     (`file_path` non vide, `is_extra = False`) ;
  5. calculer manquants / verdict / détail ;
  6. persister via `series_repository.save(...)` (ou un setter dédié des trois
     colonnes).

Réutilisation maximale de l'existant (DRY) : `TVDBClient`,
`SQLModelEpisodeRepository.get_by_series`, `SQLModelSeriesRepository.save`.

## Interfaces

### CLI

Commande `check-completeness`
(`src/adapters/cli/commands/completeness_command.py`), enregistrée dans
`src/main.py`. Pattern projet : fonction sync + `asyncio.run(_async_impl(...))`,
affichage Rich (`Progress` pendant le balayage, table récap :
nombre vérifiées / complètes / incomplètes / non vérifiables). Option
`--series-id` pour cibler une seule série ; sans option, balaye tout le parc.

### Web — bouton + progression (page Maintenance)

Bouton **« Vérifier la complétude des séries »** sur la **page Maintenance**
(cohérent avec les autres opérations batch). Lance une tâche async ; progression
diffusée en **SSE** selon le pattern déjà en place
(`WorkflowProgress` + endpoint SSE + `asyncio.to_thread`/`asyncio.run` pour le
travail réseau). À la fin, récap des compteurs.

### Web — filtre « Séries incomplètes »

- `_filters.html` : checkbox `incomplete_series=1` (à côté de `no_file` /
  `no_poster`).
- `browse.py` : nouveau paramètre `incomplete_series`, appliqué à la sélection
  des séries via `WHERE completeness_status = 'incomplete'` ; contexte template
  `current_incomplete_series` ; tag actif + lien de retrait.

### Web — badge

Pastille **« Incomplet »** (teinte ambre, distincte des badges techniques) :

- sur la carte série dans `_grid.html` ;
- sur l'en-tête de la fiche dans `series_detail.html`.

### Web — bloc justification (fiche)

Sur `series_detail.html`, quand `completeness_status = "incomplete"`, un bloc
liste, à partir de `completeness_missing_json` :

- les **saisons entièrement absentes** ;
- les **épisodes manquants** par saison (numéro `SxxEyy`, titre, date de
  diffusion) ;
- un résumé `owned / expected_aired`.

## Tests (TDD — écrits avant l'implémentation)

Unitaires `CompletenessChecker` (TVDB mocké via `respx`/MagicMock) :

- trou interne (un épisode du milieu manquant) → `incomplete` + bon détail ;
- queue interrompue (téléchargement arrêté) → tous les diffusés suivants
  manquants ;
- série en cours : épisodes à date future / sans date **non comptés** ;
- exclusions : saison 0, `SxxE00`, `is_extra = True` → ignorés ;
- épisode sans `file_path` → compté comme manquant ;
- série sans `tvdb_id` → `completeness_status = null` ;
- série complète → `complete`.

Persistance :

- test repo réel (`create_engine("sqlite:///:memory:")`) pour les trois
  nouvelles colonnes + migration.

Web :

- test route `browse` : `incomplete_series=1` ne renvoie que les séries
  `completeness_status = "incomplete"`.

## Hors périmètre V1 (évolutions notées)

- **Repli TMDB** pour les séries sans `tvdb_id`.
- **Déclenchement automatique** en fin de phase workflow `process` (fenêtre
  d'attente active — idée explicitement conservée).
- **Invalidation automatique** du verdict au transfert d'un nouvel épisode
  (V1 : on relance la vérification manuellement).
- **README** : documentation de la commande/fonctionnalité à la livraison,
  conformément aux conventions du projet.

## Critères de succès

- La commande CLI et le bouton Maintenance peuplent les trois colonnes pour les
  séries à `tvdb_id`.
- Le filtre « Séries incomplètes » liste exactement les séries
  `completeness_status = "incomplete"`.
- La fiche d'une série incomplète affiche les saisons/épisodes manquants
  justifiant le statut.
- Les spéciaux (saison 0), les `SxxE00`, les `is_extra` et les épisodes non
  encore diffusés ne provoquent jamais de faux « incomplet ».
- Couverture de tests conforme aux seuils du projet (90 %+).
