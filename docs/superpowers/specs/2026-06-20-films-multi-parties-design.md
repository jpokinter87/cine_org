# Films multi-parties — Design

**Date** : 2026-06-20
**Branche** : `feat/sandbox-rejets-doublons` (ou branche dédiée depuis `master`)
**Statut** : approuvé, prêt pour plan d'implémentation

## Problème

Certains films rares sont diffusés en plusieurs parties (un seul film, plusieurs
fichiers vidéo). Exemples dans la vidéothèque :

- **Nos meilleures années** (2003, tmdb 11659) — 6 h, 2 parties.
- **Docteur Mabuse le joueur** (1922, tmdb 5998) — 2 parties.

Le workflow détecte et déplace correctement les deux fichiers (renommés
`… Partie 1 …` / `… Partie 2 …`, symlinks créés dans `video/`), **mais** le
modèle de données n'associe qu'**un seul `file_path` par film**. Conséquence
observée : une seule fiche `Movie` existe (pointant sur la Partie 1) ; le fichier
Partie 2 est physiquement présent mais **orphelin** (aucune entité ne le
référence), donc inaccessible depuis la fiche.

### Cause technique

- `MovieModel` / entité `Movie` n'ont qu'un champ `file_path`
  (`src/core/entities/media.py:57`, `src/infrastructure/persistence/models.py:49`).
- `MovieRepository.save` fait un **upsert par `tmdb_id`**
  (`src/infrastructure/persistence/repositories/movie_repository.py:208-210`) :
  les deux parties partageant le même `tmdb_id`, la 2ᵉ sauvegarde met à jour la
  même ligne. Une seule fiche subsiste.
- En transfert, chaque partie crée et sauvegarde un `Movie`
  (`src/adapters/cli/batch_builder.py:728`) **avant** `_fix_duplicate_filenames`
  (`batch_builder.py:785`), qui ne fait que renommer les fichiers en `Partie N`
  sans enregistrer la 2ᵉ partie comme entité.

## Objectif

Permettre à un film d'avoir plusieurs parties, présentées sur la fiche **comme
les épisodes d'une mini-série** (une ligne par partie : libellé, nom de fichier,
bouton play), et faire en sorte que le **workflow regroupe automatiquement** les
parties d'un même film sous une seule fiche au moment du transfert.

Modèle de référence : la relation `Series → Episodes` (un-à-plusieurs).

## Approche retenue

Table dédiée `movie_parts` (une-à-plusieurs), de préférence à une colonne JSON :
identifiant stable par partie (utile pour la lecture, la suppression et la
détection d'orphelins), intégration propre avec le reste, et cohérence avec le
modèle Series→Episodes.

## Conception détaillée

### 1. Modèle de données

Nouvelle table `movie_parts` calquée sur `episodes` :

| champ          | type                          | note                                            |
|----------------|-------------------------------|-------------------------------------------------|
| `id`           | int PK                        |                                                 |
| `movie_id`     | int FK → `movies.id`, indexé  |                                                 |
| `part_number`  | int                           | 2, 3, … (la Partie 1 reste portée par le Movie) |
| `file_path`    | str, indexé                   | chemin physique storage                         |
| `symlink_path` | str, indexé                   | symlink dans `video/`                           |

- Entité domaine `MoviePart` dans `src/core/entities/media.py`.
- `MoviePartModel` (SQLModel, `table=True`) dans
  `src/infrastructure/persistence/models.py`.
- Méthodes sur `MovieRepository` :
  - `get_parts(movie_id) -> list[MoviePart]` (triées par `part_number`) ;
  - `save_part(part: MoviePart) -> MoviePart` (idempotent sur
    `(movie_id, part_number)` : met à jour si déjà présent) ;
  - `delete_parts(movie_id) -> int` ;
  - `find_part_by_path(path) -> MoviePart | None`.

**Invariant** : la Partie 1 n'est **pas** dupliquée dans `movie_parts` ; elle
reste le `file_path` / `symlink_path` du `Movie`. La table ne contient que les
parties ≥ 2. Le chemin « film à un seul fichier » reste 100 % inchangé (table
vide pour ces films).

### 2. Workflow de transfert (bout-en-bout)

`_fix_duplicate_filenames` (`batch_builder.py:785`) identifie déjà les transferts
visant la même destination et en extrait les numéros de partie. On enrichit ce
point pour les groupes **film** (`is_series == False`) :

- la partie de numéro le plus bas devient la **primaire** : elle porte la fiche
  `Movie` (comportement actuel) ;
- les autres transferts du groupe sont annotés
  `movie_part = {"movie_id": <id>, "part_number": <n>}`. Tous les transferts du
  groupe partagent déjà le même `movie_id` (conséquence de l'upsert par
  `tmdb_id`).

À l'**exécution** du transfert (`src/services/workflow/transfer_step.py`) : après
déplacement du fichier et création du symlink, un transfert annoté `movie_part`
crée une ligne `MoviePart(movie_id, part_number, file_path=destination,
symlink_path)` au lieu de réécrire le `file_path` de la fiche.

Résultat : une fiche `Movie` (Partie 1) + N lignes `movie_parts`. Plus aucune
partie orpheline après transfert.

> Note d'implémentation : vérifier le point exact de `transfer_step` où le
> `file_path` du `Movie` est persisté après déplacement, pour y brancher la
> création de `MoviePart` sur les transferts non primaires.

### 3. Fiche web + lecture par partie

- `src/web/routes/library/detail.py` (`movie_detail`) : charger
  `get_parts(movie_id)` et passer `parts` au template.
- `src/web/templates/library/movie_detail.html` : **si** `parts` non vide,
  afficher un bloc **« Parties »** (sinon ne rien afficher, comme aujourd'hui) :
  - `Partie 1` — nom de fichier (depuis `movie.file_path`) — bouton play
    (endpoint film existant `/library/movies/{id}/play`) ;
  - `Partie N` — nom de fichier — bouton play (nouvel endpoint) ;
  - réutiliser `library/_play_btn.html` et le style des lignes d'épisodes de
    `series_detail.html` (classes `lib-episode-row` / `lib-episode-playable`).
- Le bouton « Visionner » du haut reste inchangé et lance la Partie 1.
- Nouvel endpoint `POST /library/movie-parts/{part_id}/play` dans
  `src/web/routes/library/player.py`, calqué sur `movie_play`
  (`player.py:327-355`) : résolution du `symlink_path` / `file_path` via
  `_resolve_video_path`, lancement via `_launch_player`, polling existant.

### 4. Suppression

`src/web/routes/library/delete.py` : à la suppression d'un film, supprimer aussi
les fichiers + symlinks référencés par ses `movie_parts` puis les lignes
(`delete_parts`). Cohérent avec la suppression d'une série et de ses épisodes ;
évite de laisser des orphelins.

### 5. Rattachement des parties déjà sur le disque (backfill)

Nouvelle commande CLI `link-movie-parts` (`src/adapters/cli/commands/`, pattern
fonction sync + `asyncio.run`, enregistrée dans `src/main.py`) :

- scanne `video/` à la recherche de symlinks `… Partie N …` avec N ≥ 2 ;
- retrouve le `Movie` correspondant via la Partie 1 (même répertoire / même
  titre+année) ;
- crée les lignes `MoviePart` manquantes (idempotent grâce à `save_part`).

Sert à régulariser **Docteur Mabuse** (et, le cas échéant, tout film
multi-parties déjà transféré) sans manipulation manuelle.

### 6. Hors périmètre

- Métadonnées techniques par partie (on réutilise celles du film ; les parties
  sont quasi identiques).
- Lecture enchaînée automatique des parties (playlist).
- Détection de parties sans numéro `Partie N` exploitable dans le nom (hors de
  portée du parser actuel).

## Tests (TDD)

- `MovieRepository.save_part` / `get_parts` / `delete_parts` /
  `find_part_by_path` sur base `sqlite:///:memory:`, dont l'idempotence de
  `save_part` sur `(movie_id, part_number)`.
- `_fix_duplicate_filenames` : pour un groupe **film** multi-parties, annote la
  partie la plus basse comme primaire et les autres avec
  `movie_part = {movie_id, part_number}` ; comportement séries inchangé.
- Exécution du transfert : un transfert annoté `movie_part` crée bien une ligne
  `MoviePart` (et ne réécrit pas le `file_path` du Movie).
- `link-movie-parts` : crée les parts manquantes à partir de symlinks `Partie N`,
  idempotent (seconde exécution sans effet).
- Rendu `movie_detail` : bloc « Parties » présent ssi `parts` non vide, absent
  sinon.
- Endpoint `POST /library/movie-parts/{id}/play` : 404 si part inconnue ; lance
  le bon chemin sinon (player mocké).

## Validation de bout en bout

1. **Docteur Mabuse** : régularisation via `link-movie-parts` → la fiche affiche
   2 parties, chacune jouable.
2. **Nos meilleures années** (test workflow complet) : **déconstruire** la fiche
   et remettre les deux fichiers dans un état rejouable par le workflow
   (supprimer la fiche `Movie` + d'éventuelles lignes `movie_parts`, retirer les
   symlinks `video/`, replacer les deux fichiers source dans le répertoire de
   téléchargements/scan), puis **relancer le workflow** (scan → match → transfert)
   et vérifier que le programme crée **une seule fiche** avec **deux parties**
   accessibles. Sauvegarder la base (`cineorg.db.bak.*`) avant l'opération.

## Critères de succès

- Une fiche `Movie` peut référencer N parties ; les films à un seul fichier sont
  inchangés.
- Le workflow regroupe automatiquement les parties d'un même film sous une seule
  fiche (plus d'orphelin de Partie ≥ 2).
- La fiche web affiche un bloc « Parties » (libellé + nom de fichier + play par
  partie) façon mini-série ; le bouton « Visionner » du haut lance la Partie 1.
- La suppression d'un film nettoie aussi ses parties.
- `link-movie-parts` régularise les films multi-parties déjà transférés.
- « Nos meilleures années » repasse le workflow et produit une fiche à 2 parties
  jouables.
- Tests verts ; lint propre sur les fichiers modifiés.
