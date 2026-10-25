# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Le gestionnaire (utilisateur principal, seul administrateur)** : ingère les téléchargements,
  valide les associations TMDB/TVDB, transfère, entretient la vidéothèque (qualité, doublons,
  maintenance, corbeille) et la consulte. Travaille depuis le serveur (poste Linux) et consulte
  aussi depuis son téléphone Android.
- **Le foyer (Patricia, Willow)** : accès en lecture seule sur le réseau local, depuis leur
  poste ou leur navigateur. Leur tâche : parcourir la bibliothèque, choisir quoi regarder et
  lancer la lecture. Ils ne gèrent ni l'ingestion ni la maintenance.

« DuneHD » n'est pas un utilisateur : c'est une cible de lecture (mediacenter relié à la TV ou
au vidéoprojecteur), choisie dans « Vous regardez sur ».

## Product Purpose

CineOrg est la source de vérité d'une vidéothèque personnelle : il scanne les
téléchargements, identifie films et séries (TMDB, TVDB, IMDb), renomme et range les fichiers
physiques (`storage/`), maintient l'arborescence de symlinks lue par les mediacenters
(`video/`), et permet de parcourir la collection et d'y lancer une lecture.

Le succès : chaque fichier est correctement identifié et rangé sans pollution de la base, et
n'importe qui du foyer trouve en quelques gestes quelque chose à regarder et le lance sur
l'écran voulu.

## Positioning

CineOrg est l'endroit où l'on décide, pas seulement où l'on regarde. Contrairement à
Jellyfin/Plex, qui lisent une arborescence existante, il fabrique cette arborescence :
identification avec arbitrage humain en cas de doute, renommage normalisé, organisation par
genre et subdivision alphabétique, détection des doublons et contrôle qualité. La consultation
est construite sur cette base fiabilisée.

## Operating Context

- Réseau local uniquement ; aucun accès extérieur voulu (le partage éphémère via Funnel
  n'expose que Jellyfin).
- Trois contextes d'usage : poste du gestionnaire (gestion, sessions longues), navigateurs du
  foyer (consultation), téléphone Android en Wi-Fi (consultation + télécommande de lecture,
  installable via le manifest).
- Cibles de lecture : mpv sur la machine locale, DuneHD (TV / vidéoprojecteur), VLC sur le
  téléphone (flux direct sans conversion).
- Flux de gestion : Traitement → Validation → Transfert, puis Qualité / Doublons /
  Maintenance / Configuration.
- La bibliothèque peut devenir un lieu où l'on flâne pour choisir (cf. « Surprends-moi »,
  collections, fiches détaillées avec résumés d'épisodes).

## Capabilities and Constraints

- Stack en place : FastAPI + Jinja2 + HTMX, une feuille `src/web/static/css/style.css`,
  quelques scripts JS ; progression en temps réel par SSE.
- Interface, messages et documentation intégralement en français.
- Actions destructives (supprimer, fusionner) réservées à l'accès depuis le serveur ; sur
  écran tactile étroit, « Partager » et « Modifier la fiche » sont masqués.
- Principe métier : en cas de doute sur une association, rendre la main à l'humain plutôt
  que d'écrire une donnée erronée.
- Terminologie : Film, Série, Épisode, Saison, Collection, Validation, Transfert, Corbeille,
  Sandbox, Doublon, Complétude.

## Brand Commitments

- Nom : CineOrg (affiché « CinéOrg »). Ton : direct, en français.
- Aucune contrainte d'identité imposée : le gestionnaire accepte explicitement des
  propositions de variante ou de thème qui amélioreraient l'aspect du programme.

## Evidence on Hand

- Jaquettes, synopsis, notes TMDB/IMDb, résumés d'épisodes TVDB issus de la base réelle.
- Captures d'écran existantes : `docs/screenshots/`.
- Icônes de l'application : `src/web/static/favicon.svg`, `src/web/static/icons/`.

## Product Principles

1. La fiabilité des données prime : jamais d'association silencieuse douteuse.
2. Gérer est dense et précis ; flâner est accueillant : chaque surface sert sa tâche.
3. Lancer une lecture doit être immédiat, quel que soit l'écran visé.
4. Le téléphone est une télécommande de consultation, pas un poste de gestion.
5. Les actions irréversibles sont visibles, confirmées et réservées au gestionnaire.
