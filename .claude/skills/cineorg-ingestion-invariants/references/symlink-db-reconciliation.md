# Réconciliation symlinks ↔ storage ↔ DB

Playbook pour réparer des symlinks cassés, une désorganisation storage, ou une base de données qui
ne reflète plus l'organisation réelle.

## Modèle mental (à ne pas réapprendre à chaque fois)

- **`video/` (symlinks) = source de vérité.** Si un symlink existe et n'est **pas brisé**, le
  candidat est trouvé : la réparation/identification se fait à partir de là.
- **`storage/` peut être « éclaté ».** Les fichiers physiques d'une même série peuvent être répartis
  sur plusieurs lettres/sous-dossiers sans gêner la lecture, tant que les symlinks pointent juste.
  → **Ne pas chercher dans la zone storage** pour identifier un média si le symlink suffit.
- La **DB** doit être réconciliée séparément : elle peut ne pas refléter une réorg manuelle des
  symlinks. Corriger la DB (`file_path`, `symlink_path`) **sans casser** les symlinks corrects.

## Services réutilisables (ne pas réimplémenter)

`RepairService` : `find_broken_symlinks()`, `find_possible_targets()`, `repair_symlink()`,
`build_file_index()`. `OrganizerService` : `get_movie_video_destination()`,
`get_series_video_destination()`. Tri alphabétique : `_strip_article()` + `normalize_accents()`.

## Règles de réorganisation de séries

- Toujours privilégier le **répertoire comportant l'année** canonique et y reverser les épisodes en
  **ajoutant l'année au titre**.
- Garde-fou **anti-homonymes** : un titre seul ne suffit pas (ex. « Shameless » US classé à tort sous
  « Shameless (2004) » avec des titres FR injectés depuis la mauvaise série TVDB). Vérifier l'année
  et, si besoin, les **comptes d'épisodes** par saison.

## Cas particuliers déjà rencontrés

- **Trilogie Paris Police** (1900 / 1905 / 1910) : titres très proches → mélange. Ancrer
  l'extraction de titre et mesurer empiriquement les scores entre les trois avant de corriger.
- **Torchwood saison 4** : chaque épisode est en double (une version FR + une multi). Doublon
  légitime à traiter, pas une erreur de classement.
- **Suffixe cosmétique « (2) »** sur des symlinks (ex. 6 premiers épisodes Paris Police 1900) :
  problème purement cosmétique à faire disparaître **sans casser la base** (renommer le symlink,
  mettre à jour `symlink_path`).

## Réflexe

Quand l'utilisateur signale un mélange/désync : confirmer d'abord que **les épisodes ne sont pas
mélangés** (souvent c'est cosmétique), puis corriger le minimum (symlink + DB) sans toucher au reste.
Écrire un **test de régression** pour le type de cas avant de corriger.
