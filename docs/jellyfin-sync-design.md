# Sous-projet 1 — Jellyfin local + identification fiable (export NFO + arbre dédié)

> Spec de conception. Date : 2026-06-28.
> Statut : validée pour rédaction du plan d'implémentation.

## 1. Contexte et problème

CineOrg organise sa vidéothèque pour ses propres besoins : les symlinks exposés
sous `/media/Serveur/Collection/` sont rangés par genre puis par subdivision
alphabétique sur plusieurs niveaux :

- Films : `Films/{Genre}/{Lettre}/{Subdivision}/Titre (Année) … .mkv`
- Séries : `Series/TV/{Lettre}/{Série}/Saison XX/Titre (Année) - SxxExx - … .mkv`
  (plus une branche `Series/Animation…`).

Cette arborescence — adaptée à CineOrg — est **hostile aux media centers**. Lors
d'une tentative précédente, Jellyfin « zappait » des séries entières et
identifiait mal des films. Cause la plus probable : les niveaux de subdivision
intercalés entre la racine de bibliothèque et le dossier de série cassent le
regroupement saisons/épisodes du scanner TV ; côté films, l'empilement favorise
les erreurs d'année/titre sur les titres ambigus.

**Atout décisif :** la base CineOrg contient déjà les identifiants exacts de
chaque œuvre (`tmdb_id`, `tvdb_id`, `imdb_id`) plus genres, casting, notes,
synopsis. En exposant ces identifiants à Jellyfin via des fichiers `.nfo`,
Jellyfin **n'a plus rien à deviner**.

## 2. Objectif et périmètre

**Objectif :** permettre à un serveur Jellyfin local de présenter, de façon
fiable, les **films et séries gérés par CineOrg**, sans erreur d'identification
ni série « zappée ».

**Périmètre (décidé) :**
- Uniquement les **Films + Séries gérés par CineOrg** (périmètre A). Les autres
  dossiers de `Collection/` (documentaires, musique, vidéos famille…) sont hors
  périmètre : non connus de la base, donc non « NFO-isables ».
- **Approche 2** : CineOrg génère un **arbre de symlinks dédié et « à plat »**
  pour Jellyfin, séparé de l'arbre genré de CineOrg (qui ne bouge pas), avec
  sidecars `.nfo` à identité verrouillée par ID.
- **Maintenance (choix C, volet manuel pour ce sous-projet) :** une **commande
  CLI manuelle** de synchronisation (init + rattrapage). L'intégration
  automatique au workflow `process` est explicitement reportée à un sous-projet
  ultérieur.

**Hors périmètre de ce sous-projet :**
- Accès distant / téléphone (Tailscale) → sous-projet 2.
- Visionnage partagé / SyncPlay → sous-projet 3.
- Intégration au workflow `process` → suite du choix C.
- Réparation de la désynchro base ↔ disque (voir §7) → nettoyage séparé via les
  outils existants (`repair-links`, `cleanup`).

## 3. Architecture

Une nouvelle commande CLI **`jellyfin-sync`** lit la base et génère, dans un
répertoire dédié `CINEORG_JELLYFIN_DIR` (défaut : `/media/Serveur/JellyfinLib`),
un arbre de symlinks au format attendu par Jellyfin, accompagné de NFO.

### 3.1 Arbre cible

```
JellyfinLib/
  Films/
    Inception (2010)/
      Inception (2010).mkv          → fichier physique réel
      movie.nfo
    Le Hobbit (2012)/               ← film multi-parties
      Le Hobbit (2012) - cd1.mkv
      Le Hobbit (2012) - cd2.mkv
      movie.nfo
  Séries/
    12 Monkeys (2015)/
      tvshow.nfo
      Saison 01/
        12 Monkeys (2015) S01E01.mkv   → fichier physique réel
        12 Monkeys (2015) S01E01.nfo
```

- **Un dossier par film** (bonne pratique Jellyfin : gère proprement les films
  multi-parties par empilement `- cdN`).
- **Séries à plat** : `Séries/{Titre} ({Année})/Saison NN/…` — **aucun** niveau
  genre/lettre intercalé.
- Les symlinks pointent vers le **fichier physique réel** (voir §3.2), pas vers
  l'arbre `Collection/`, afin de n'exposer à Jellyfin qu'un seul montage
  physique (`/media/NAS64`) et d'éviter les symlinks-de-symlinks.

### 3.2 Résolution de la source du lien (chaîne de repli)

Pour chaque film / épisode, la cible du symlink Jellyfin est déterminée ainsi :

1. `realpath(symlink_path)` si `symlink_path` existe et se résout vers un
   fichier présent → on l'utilise ;
2. sinon `file_path` s'il pointe vers un fichier présent → on l'utilise (repli) ;
3. sinon l'élément est **ignoré et listé** dans le rapport (jamais d'abandon).

Cette chaîne récupère les ~111 éléments dont le `symlink_path` est périmé mais
dont le fichier physique existe (voir §7), et ne laisse de côté que les rares
fichiers réellement absents.

### 3.3 Contenu des NFO (identité verrouillée par ID)

Grâce aux balises `<uniqueid>`, Jellyfin **n'interroge plus les API pour
identifier** ; il ne les sollicite que pour récupérer affiches/fanarts via l'ID
exact.

- **Film** → `movie.nfo` :
  ```xml
  <movie>
    <title>…</title>
    <year>…</year>
    <uniqueid type="tmdb" default="true">12345</uniqueid>
    <uniqueid type="imdb">tt…</uniqueid>
    <plot>…</plot>        <!-- si overview disponible -->
    <genre>…</genre>      <!-- répété, si genres disponibles -->
  </movie>
  ```
- **Série** → `tvshow.nfo` :
  ```xml
  <tvshow>
    <title>…</title>
    <year>…</year>
    <uniqueid type="tvdb" default="true">…</uniqueid>
    <uniqueid type="tmdb">…</uniqueid>
    <uniqueid type="imdb">…</uniqueid>
  </tvshow>
  ```
- **Épisode** → `{nom}.nfo` (`<episodedetails>`) : `<title>`, `<season>`,
  `<episode>`, `<plot>` si dispo. La base n'a pas d'ID par épisode ; le matching
  s'appuie sur le `SxxExx` du nom (fiable dans l'arbre à plat) et le `tvshow.nfo`
  ancre la série.

XML correctement échappé (accents, `&`, `<`, `>`, `"`).

## 4. Composants (unités isolées et testables)

- **Config** : nouveau réglage `CINEORG_JELLYFIN_DIR` dans `src/config.py`
  (préfixe `CINEORG_`, défaut `/media/Serveur/JellyfinLib`), aux côtés de
  `storage_dir` / `video_dir`.
- **Service** `src/services/jellyfin/` :
  - `nfo_builder.py` — fonctions **pures** : entité → chaîne XML (film, série,
    épisode). Aucune E/S. Hautement testable.
  - `tree_builder.py` — calcul des chemins cibles + création **idempotente** des
    symlinks ; assainissement des noms ; gestion des collisions.
  - `jellyfin_sync_service.py` — orchestration : parcours DB, résolution source
    (§3.2), écriture arbre + NFO, élagage optionnel, agrégation du rapport.
  - `dataclasses.py` — `JellyfinSyncReport` (créés, mis à jour, ignorés,
    élagués, erreurs, avec les listes de chemins concernés).
- **Commande CLI** `src/adapters/cli/commands/jellyfin_command.py` →
  `jellyfin-sync`, enregistrée dans `src/main.py`. Pattern existant + affichage
  Rich (`Progress`). Opération purement fichiers + DB (pas d'appel API) → pas
  besoin d'`asyncio`.
  Options : `--movies-only` / `--series-only`, `--dry-run`, `--prune`.

Réutilisation : helper d'assainissement de noms de fichiers (caractères
illégaux) ; `_strip_article` n'est **pas** nécessaire ici (arbre à plat, pas de
tri alphabétique).

## 5. Flux de données

1. Lire la config (`jellyfin_dir`).
2. **Films** : requêter `movies` (titre, année, `tmdb_id`, `imdb_id`, genres,
   overview, `symlink_path`, `file_path`) + `movie_parts`. Pour chacun :
   résoudre la/les source(s) (§3.2), calculer `Films/{Titre} ({Année})/`, créer
   le(s) symlink(s) + `movie.nfo`.
3. **Séries** : requêter `series` + `episodes`. Pour chaque série : créer
   `Séries/{Titre} ({Année})/` + `tvshow.nfo` ; pour chaque épisode :
   `Saison {NN}/{Titre} ({Année}) S{NN}E{NN}.{ext}` + `.nfo`.
4. **Élagage** (`--prune`, désactivé par défaut) : supprimer de `JellyfinLib`
   les entrées qui ne correspondent plus à la base. Par défaut : signalées
   seulement.
5. **Rapport** Rich : créés / mis à jour / ignorés (source absente) / élagués /
   erreurs.

**Idempotence :** rejouer la commande met à jour les NFO et (re)crée les liens
manquants sans casser les liens corrects existants. C'est ce qui fait office
d'init **et** de rattrapage.

## 6. Volet ops — installation & configuration Jellyfin (runbook, pas du code)

Repart proprement de Docker (daemon système actif) :

- `docker run` avec montages :
  - `-v /media/Serveur/JellyfinLib:/media/Serveur/JellyfinLib:ro`
  - `-v /media/NAS64:/media/NAS64:ro` (racine physique de ~99 % des fichiers)
  - `-v /media/Serveur:/media/Serveur:ro` (pour les rares fichiers résolus hors
    NAS64) — à confirmer en énumérant les racines distinctes au moment du sync
  - volumes `config` et `cache` persistants.
- Deux bibliothèques :
  - **Films** (type *Films*) → `JellyfinLib/Films`
  - **Séries** (type *Séries / Émissions*) → `JellyfinLib/Séries`
- Réglages clés de chaque bibliothèque : activer la **lecture des NFO locaux**
  comme **source de métadonnées prioritaire**, langue **fr**. Les `<uniqueid>`
  sont alors honorés → identification déterministe, zéro devinette.

Le runbook exact (commande `docker run` complète, captures des réglages) sera
détaillé dans le plan d'implémentation.

## 7. Constat d'intégrité (préexistant, hors périmètre)

L'analyse de la base a révélé une désynchro base ↔ disque, **indépendante de
Jellyfin** :

| | Valides | `symlink_path` périmé mais **fichier physique présent** | Réellement introuvables |
|---|---|---|---|
| Films (5792) | 5730 | 62 | 0 |
| Épisodes (éch. 4000) | 3947 | 49 | 4 (~0,1 %) |

- **Rien (ou presque) n'est perdu** : `/media/Serveur` ne contient que des liens,
  aucun fichier physique égaré.
- Le « 1 % » = des `symlink_path` enregistrés en base qui ne correspondent plus à
  rien sur le disque (lien déplacé/supprimé lors d'une réorg de subdivision sans
  MAJ de la base).
- **Traitement :** la chaîne de repli (§3.2) garantit que ces éléments
  récupérables apparaissent quand même dans Jellyfin. La **correction de fond**
  de la désynchro (régénérer/mettre à jour les `symlink_path`) est un
  **nettoyage séparé** via les outils existants (`repair-links`, `cleanup`),
  hors de ce sous-projet.

## 8. Gestion d'erreurs

Aucune erreur n'interrompt la synchronisation ; tout est compté et listé :

- Source introuvable (chaîne de repli épuisée) → ignoré + listé.
- Film/série sans ID (`tmdb_id`/`tvdb_id` absents) → arbre + NFO créés quand même
  (titre/année seuls) ; comptés à part (Jellyfin retombe sur le matching par nom
  pour ces rares cas).
- Collision de nom `Titre (Année)` (deux œuvres homonymes) → suffixe `tmdb_id`
  sur le dossier.
- Caractères illégaux dans les noms → assainis.
- Symlink existant pointant ailleurs → remplacé (idempotence).

## 9. Tests (TDD, sans API)

- `nfo_builder` (valeur la plus élevée, facile) : génération XML film/série/
  épisode ; présence et type des `<uniqueid>` ; échappement des caractères
  spéciaux (accents, `&`, `<`).
- `tree_builder` (`tmp_path`) : structure produite ; idempotence ; gestion des
  collisions ; source cassée correctement ignorée ; films multi-parties.
- `jellyfin_sync_service` : DB SQLite `:memory:` ensemencée (films, séries,
  épisodes, `movie_parts`) → exécution vers `tmp_path` → assertions sur le
  rapport (compteurs) et sur les fichiers/links créés.

Aucun mock externe (pas d'appel réseau) : tests purement système de fichiers + DB.

## 10. Critères de succès (vérifiables)

1. `jellyfin-sync --dry-run` puis exécution réelle : l'arbre `JellyfinLib` est
   généré, le rapport est cohérent (≈ totaux DB moins les rares introuvables).
2. Scan Jellyfin sur les deux bibliothèques : **aucune série zappée**.
3. Identification correcte sur un échantillon (~10 films + 5 séries) incluant des
   cas délicats : titres ambigus, film multi-parties, titres accentués.

Succès = (2) **et** (3) vérifiés.
