# « Visionner » en un clic avec identité par navigateur

**Date** : 2026-06-28
**Statut** : design validé, prêt pour plan d'implémentation

## Problème

Le bouton « Visionner » ouvre systématiquement un menu déroulant de choix de profil
dès qu'il existe plus d'un profil lecteur. Lancer une vidéo demande donc toujours deux
gestes (cliquer « Visionner » → choisir l'utilisateur), même quand on veut juste sa
cible habituelle.

Les profils ne sont pas des cibles interchangeables : ce sont des **utilisateurs
distincts** (Local, Xubuntu Patricia, Willow…) qui peuvent regarder **en même temps**,
chacun depuis **son propre navigateur**. DuneHD a un statut particulier : il ne
« regarde » pas, il **envoie** le fichier en lecture sur le mediacenter.

Le profil « actif » actuel est stocké côté serveur (`player_profiles.json`, champ
`active`). Inadapté pour des utilisateurs simultanés : régler son profil l'écraserait
pour tout le monde.

## Objectif

Permettre à chaque personne de lancer « Visionner » **en un seul clic** sur sa propre
cible, sans interférer avec les autres, tout en gardant un choix ponctuel à portée
(autre cible occasionnelle, ou envoi DuneHD).

## Principe retenu

L'identité « qui regarde » vit **dans le navigateur de chacun** (localStorage), jamais
côté serveur. « Visionner » lance directement sur cette identité ; un chevron ▾ rouvre
le menu pour les cas ponctuels et DuneHD.

## Design

### 1. Identité côté client

- Stockée dans `localStorage`, clé `cineorg.viewer`, valeur = nom de profil.
- Valeur par défaut : **Local** (au premier passage, « Visionner » marche en un clic
  sans configuration).
- Si l'identité mémorisée ne correspond plus à aucun profil existant (profil supprimé),
  repli silencieux sur `Local`.
- Le champ `active` de `player_profiles.json` n'est plus utilisé pour piloter le défaut
  de lecture. (On ne le supprime pas pour ne pas casser le format ; il devient inerte
  pour cette fonctionnalité.)

### 2. Sélecteur d'identité dans l'en-tête

- Emplacement : `main-nav` de `base.html`, aligné à droite.
- Libellé : « Vous regardez sur : **[Nom ▾]** ».
- Contenu : **uniquement les profils personnes/écrans**, c.-à-d. tous les profils dont
  `type != "dunehd"`. DuneHD n'apparaît jamais dans ce sélecteur.
- Changer la valeur écrit dans `localStorage` et met à jour l'affichage. **Aucun appel
  serveur.**
- Masqué s'il y a un seul profil personnel (rien à choisir).
- La liste des profils personnels est rendue côté serveur (via le helper existant
  `get_player_profiles()` / `load_profiles()`), filtrée sur `type != "dunehd"`.

### 3. Bouton « Visionner » (un clic)

- Clic sur le corps du bouton = lancement direct sur l'identité courante.
- Mécanique d'injection du profil : **un seul écouteur JS global** sur
  `htmx:configRequest` dans `base.html`. Pour toute requête dont le chemin contient
  `/play` et qui ne porte **pas déjà** `profile=`, il ajoute `?profile=<identité>` au
  chemin (`evt.detail.path`). FastAPI lit déjà `profile` en query parameter.
  - Centralisé : aucune réécriture bouton par bouton, survit aux swaps HTMX.
  - Les options du ▾ portent déjà `?profile=…` dans leur URL → elles ne sont pas
    modifiées par le listener.
- Helper JS `getViewerProfile()` : lit `localStorage`, repli sur `Local`.

### 4. Chevron ▾ (cas ponctuels + DuneHD)

- Réutilise le popover existant (`.play-profile-popover`).
- Présent quand il y a plus d'un profil (toutes catégories confondues).
- Liste **tous** les profils, DuneHD inclus (présenté comme « → envoyer au
  mediacenter »).
- Un choix dans le ▾ = **lancement ponctuel** uniquement (l'URL porte `?profile=`), ne
  modifie **pas** l'identité stockée.

### 5. Disposition (bouton scindé)

```
en-tête : … Bibliothèque   Vous regardez sur : [ Willow ▾ ]

fiche   : [ ▶ Visionner │ ▾ ]
                 │        └ ▾ : menu (autres profils + DuneHD), choix ponctuel
                 └ corps : lance sur l'identité courante, un clic
```

## Composants touchés

- `src/web/templates/base.html`
  - Sélecteur d'identité dans `main-nav` (liste des profils personnels rendue côté
    serveur).
  - Bloc JS : `getViewerProfile()`, écriture localStorage au changement du sélecteur,
    listener `htmx:configRequest`, repli si profil disparu.
- `src/web/templates/library/_play_btn.html`
  - Le clic principal ne déclenche plus l'ouverture du popover : il lance (hx-post sans
    `profile=`, le listener ajoute l'identité). Le ▾ devient un déclencheur séparé pour
    le popover.
- `src/web/routes/library/player.py` → `_play_button_html()`
  - **Logique dupliquée** de `_play_btn.html` (sert à restaurer le bouton après la fin
    de lecture via `/play-status`). À modifier **en parallèle** pour rester cohérent :
    clic principal = lancement, ▾ = popover.
- `src/web/static/css/style.css`
  - Style du bouton scindé (corps + chevron accolé) pour `.play-btn`,
    `.lib-episode-play-btn`, et la variante fiche détaillée
    (`.lib-detail-poster-actions`).
  - Style du sélecteur d'en-tête.
- Helper de contexte template : vérifier que `get_player_profiles` est exposé aux
  templates (déjà utilisé dans `_play_btn.html`) ; ajouter au besoin un accès filtré
  « profils personnels » pour l'en-tête, ou filtrer dans le template.

## Comportements aux limites

- **Premier passage / navigateur neuf** : pas d'entrée localStorage → identité = Local,
  lancement direct possible immédiatement.
- **Profil d'identité supprimé** : `getViewerProfile()` renvoie un nom inexistant →
  côté serveur `_launch_player` retombe déjà sur `get_active_profile()` si le profil
  est introuvable ; côté sélecteur, l'affichage retombe sur Local. Comportement
  acceptable (pas de plantage).
- **Un seul profil au total** : pas de ▾, pas de sélecteur d'en-tête ; clic = lancement
  direct (comportement déjà en place aujourd'hui).
- **Un seul profil personnel mais DuneHD présent** : sélecteur d'en-tête masqué (un seul
  choix personnel), mais ▾ présent pour accéder à DuneHD.

## Tests

Côté serveur (pytest, rendu HTML) :
- Le sélecteur d'en-tête n'inclut **pas** les profils `type == "dunehd"`.
- Le sélecteur d'en-tête est masqué quand il y a ≤ 1 profil personnel.
- Le bouton « Visionner » principal poste sur `…/play` **sans** `profile=` (l'identité
  est injectée côté client) ; le ▾ liste tous les profils avec `?profile=` dans chaque
  option (DuneHD inclus).
- Régression : les endpoints `/play` acceptent toujours le paramètre `profile`
  (déjà couvert, à confirmer).

La couche JS (lecture/écriture localStorage, injection du `profile` via
`htmx:configRequest`, repli Local) est vérifiée **manuellement** : le projet n'a pas de
tests front-end.

## Hors périmètre (YAGNI)

- Authentification / comptes utilisateurs réels.
- Synchronisation de l'identité entre appareils.
- Suppression du champ `active` de `player_profiles.json`.
- Refactoring de la duplication `_play_btn.html` / `_play_button_html` au-delà du
  strict nécessaire pour cette fonctionnalité.

## Critères de succès

1. Avec plusieurs profils, un clic sur « Visionner » lance sur l'identité du navigateur,
   sans menu intermédiaire.
2. Deux navigateurs distincts peuvent avoir deux identités différentes et lancer
   simultanément sans interférence.
3. Le ▾ permet un lancement ponctuel sur une autre cible (ou DuneHD) sans changer
   l'identité mémorisée.
4. DuneHD n'apparaît jamais comme identité dans le sélecteur d'en-tête.
5. Les tests serveur passent ; le README documente la nouvelle interaction.
