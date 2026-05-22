# Courts-métrages : masquage par défaut dans la grille + collection en masse

**Date** : 2026-05-22
**Branche** : `feat/migrate-nas-raw-mode`
**Statut** : design validé, prêt pour planification

## Contexte

Le traitement des courts-métrages est déjà largement en place (phases P1→P5) :

- `MovieModel.is_short` (booléen indexé, défaut `False`) et `MovieModel.local_collection_id`
  (FK vers `local_collections`).
- `LocalCollectionModel` (`id`, `name` unique, `description`) — regroupement local pour des
  courts qui ne sont pas dans une collection TMDB.
- Classification (`classify_media`, `MediaType.SHORT`, seuil
  `Settings.short_film_duration_threshold_seconds`).
- Routage des courts vers `video/Films/Courts/{franchise}/`, où
  `franchise = collection_name (TMDB) → local_collection_name → "Divers"`
  (`organizer.get_short_video_destination`).
- `ShortReclassifier` : déplace le symlink d'un court vers sa destination calculée, sans
  toucher au storage physique. Son `find_candidates()` capte déjà le cas « franchise changée »
  (assignation d'une collection locale → déplacement de `Divers/` vers la nouvelle franchise).
- CLI `collections list/suggest` (suggestion par préfixe de titre) et page web
  `/library/collections` (liste collections TMDB + locales).

## Problèmes à résoudre

1. **Les courts polluent la grille principale.** `browse.py` ne filtre pas sur `is_short` :
   les courts (ex. cartoons Looney Tunes) apparaissent mélangés aux films. Ils ne devraient
   apparaître que si l'utilisateur le demande explicitement.
2. **L'auto-regroupement des Looney Tunes a échoué.** Le suggester repose sur un préfixe de
   titre commun ; or ces courts n'en partagent aucun (« Quel opéra, docteur ? », « Titi au
   cirque », « 3 Bee-Bops »…). Il faut une sélection manuelle en masse permettant de les
   placer dans une collection, sur le modèle de la suppression en masse existante.

## Décisions de conception (validées)

| Décision | Choix retenu |
| --- | --- |
| Masquage des courts | Troisième valeur **« Courts »** dans le sélecteur de type. `Tous` et `Films` excluent les courts ; `Courts` les affiche seuls. Pas de case à cocher. |
| Action de masse | **Étendre le mode sélection existant** (un seul mode, barre flottante avec « Supprimer » + « Ajouter à une collection »). |
| Symlinks | **Association DB + déplacement immédiat des symlinks** via `ShortReclassifier`. |

## Design détaillé

### Volet 1 — Filtre « Courts » dans la grille

**`src/web/routes/library/browse.py`**

- Le bloc Films s'exécute pour `type ∈ {"all", "movie", "courts"}`. Ajout d'un filtre
  `is_short` sur `movie_stmt` :
  - `type == "courts"` → `.where(MovieModel.is_short == True)` (uniquement les courts) ;
  - sinon (`"all"` / `"movie"`) → `.where(MovieModel.is_short == False)` (courts exclus).
- Le bloc Séries reste conditionné à `type ∈ {"all", "series"}` : `"courts"` exclut donc
  nativement les séries (un court est toujours un film).
- `current_type` est déjà transmis au contexte ; aucun nouveau paramètre de route.

**`src/web/templates/library/_filters.html`**

- Sélecteur `name="type"` : ajout `<option value="courts">Courts</option>` →
  Tous / Films / Séries / Courts.
- Bloc « filtres actifs » (`lib-filter-tag` pour `current_type`) : gérer le 3ᵉ libellé
  (`courts` → « Court »), aujourd'hui binaire `Film`/`Serie`.

**Comportement** : par défaut (Tous) les courts disparaissent de la grille ; on les retrouve
via Type → Courts.

### Volet 2 — Sélection en masse « Ajouter à une collection » (mode étendu)

L'état de sélection (`Map` + persistance `sessionStorage`), les cases sur les jaquettes, la
barre flottante et la ré-attache après swap HTMX sont réutilisés tels quels depuis `delete.js`.

**`src/web/templates/library/index.html`** (bloc `{% if is_local %}` uniquement)

- Barre flottante `#delete-bar` : ajout d'un bouton d'action
  **« Ajouter à une collection »** (`#collection-confirm-btn`) aux côtés de
  « Supprimer la sélection ».
- Nouvel overlay `#collection-overlay` (même structure visuelle que `#delete-overlay`) :
  - titre « Ajouter `<span id="collection-overlay-count">` élément(s) à une collection » ;
  - champ texte `#collection-name-input` lié à un `<datalist>` des noms de collections
    locales existantes — **un nom existant est réutilisé, un nom inédit crée la collection** ;
  - texte d'info : « Les courts sélectionnés seront déplacés vers `Films/Courts/{collection}/`. » ;
  - boutons Annuler (`#collection-overlay-cancel`) / Confirmer (`#collection-overlay-confirm`).

**`src/web/routes/library/browse.py`** — contexte

- Ajouter au contexte `local_collections` : la liste des noms de `LocalCollectionModel`
  (pour alimenter le `<datalist>`).

**`src/web/static/js/delete.js`** (étendu)

- Récupère les nouveaux éléments DOM (bouton collection + overlay) ; no-op s'ils sont absents.
- Clic « Ajouter à une collection » → ouvre `#collection-overlay`, renseigne le compteur,
  met le focus sur le champ.
- Confirmation → `POST /library/collection-batch` avec
  `{ collection_name: <valeur du champ, trim>, items: [{type, id}] }`.
  - Les items `series` sont envoyés mais ignorés côté serveur (cf. Volet 3) : seuls les
    films possèdent `local_collection_id`.
  - Nom vide → bouton confirmer désactivé (pas d'envoi).
- Réponses : `403` → `alert` du message + abandon (comme la suppression) ; succès →
  `clearState()` puis rechargement `/library/`.
- `Escape` ferme `#collection-overlay` si actif (logique miroir de `#delete-overlay`).

### Volet 3 — Endpoint backend + déplacement des symlinks

**`src/web/routes/library/collections.py`** — nouvelle route `POST /collection-batch`

Modèles Pydantic locaux (miroir de `delete.py`) :

```python
class CollectionAssignItem(BaseModel):
    type: str          # "movie" | "series"
    id: int

class CollectionAssignRequest(BaseModel):
    collection_name: str
    items: list[CollectionAssignItem]
```

Logique :

1. **Garde localhost** : `request.client.host ∉ {"127.0.0.1", "::1", "localhost"}` → `403`
   (réutiliser le même ensemble que `delete.py`).
2. Valider `collection_name` (trim ; **vide → `400`**, défense en profondeur — le bouton
   confirmer est déjà désactivé côté JS quand le champ est vide).
3. **Trouve-ou-crée** la collection via `SQLModelLocalCollectionRepository` :
   `repo.get_by_name(name)` sinon `repo.save(LocalCollection(name=name))`
   (même logique que `collections_command.py`).
4. Pour chaque item `type == "movie"` : charger `MovieModel`, fixer
   `local_collection_id = collection.id`, `session.add`. Ignorer les items `series`.
   `commit`.
5. **Déplacement des symlinks** :
   - `settings = request.app.state.container.config()` ;
   - `reclassifier = ShortReclassifier(session, settings.video_dir,
     settings.short_film_duration_threshold_seconds)` ;
   - `candidates = reclassifier.find_candidates()` puis `apply()` sur ceux dont
     `candidate.model.id` est dans l'ensemble des IDs assignés.
   - Réutilise intégralement le calcul de destination (`get_short_video_destination`) et la
     vérification `is_short` ; **aucune logique de chemin dupliquée**.
6. Retour JSON : `{"assigned": int, "moved": int, "errors": list[str], "collection_id": int}`.

Notes :

- Un film sélectionné non détecté comme court (`is_short == False`, ou durée > seuil) reçoit
  l'association DB mais ne sera pas déplacé par `find_candidates()` — comportement attendu
  (les collections locales ne pilotent le routage que pour les courts). Voir « Hors périmètre ».
- La session web est obtenue via `next(get_session())` et fermée en `finally` (pattern des
  autres routes du module).

### Volet 4 — Tests (TDD)

Écrire les tests avant l'implémentation. Emplacement : `tests/unit/web/`.
- Filtre Courts → nouveau `tests/unit/web/test_browse_shorts_filter.py`.
- Endpoint + déplacement symlink → compléter `tests/unit/web/test_library_collections_routes.py`
  (existant), avec un `video_dir` temporaire (`tmp_path`).

**Filtre Courts (`browse.py`)**
- `type=all` et `type=movie` excluent les films `is_short=True`.
- `type=courts` renvoie uniquement les films `is_short=True`.
- `type=courts` n'inclut aucune série.

**Endpoint `/collection-batch`**
- Crée la collection si le nom est inédit ; la réutilise si le nom existe (pas de doublon).
- Assigne `local_collection_id` aux films sélectionnés ; ignore les items `series`.
- Garde localhost : requête non locale → `403`.

**Déplacement de symlink (test d'intégration)**
- Avec un `video_dir` temporaire et un court symlinké dans `Films/Courts/Divers/`, après
  assignation à la collection « Looney Tunes » le symlink se retrouve dans
  `Films/Courts/Looney Tunes/` et `MovieModel.symlink_path` est mis à jour ; la cible
  physique est inchangée.

## Hors périmètre

- **Marquage manuel `is_short`** depuis l'UI pour les courts non détectés
  (durée absente / supérieure au seuil). L'action de collection n'assigne alors que la DB
  sans déplacer le symlink. À traiter dans une itération ultérieure si le besoin se confirme.
- Évolution du suggester par préfixe (le besoin manuel le couvre déjà pour les Looney Tunes).
- Assignation de collections à des séries (le modèle ne le supporte pas).

## Fichiers impactés

| Fichier | Nature |
| --- | --- |
| `src/web/routes/library/browse.py` | filtre `is_short` + contexte `local_collections` |
| `src/web/templates/library/_filters.html` | option « Courts » + tag filtre actif |
| `src/web/templates/library/index.html` | bouton barre + overlay collection |
| `src/web/static/js/delete.js` | action « Ajouter à une collection » |
| `src/web/routes/library/collections.py` | route `POST /collection-batch` |
| `tests/unit/web/test_browse_shorts_filter.py` | tests filtre « Courts » (nouveau) |
| `tests/unit/web/test_library_collections_routes.py` | tests endpoint + déplacement symlink |

## Documentation

Mettre à jour `README.md` après implémentation : filtre « Courts » dans la grille et action
de masse « Ajouter à une collection » (usage, comportement symlinks, restriction machine maître).
