# Phase Context

**Phase:** 42 — Overrides Manuels
**Generated:** 2026-04-14
**Status:** Ready for planning

## Goals

- **Débloquer les épisodes hors canon** : plus aucun épisode légitime bloqué en `/downloads` parce que le distributeur a découpé la saison différemment des bases en ligne (cas typique : *The Big C* S04 = 4 épisodes officiels sur TVDB mais 8 dans la version téléchargée avec épisodes de 30' au lieu de 50'). Les bases TMDB/TVDB ne gèrent qu'une seule numérotation ; il faut pouvoir déclarer localement qu'une saison compte N épisodes.
- **Compléter manuellement les fiches incomplètes** : pouvoir mettre à jour depuis la fiche détaillée web les rares cas où il manque une jaquette, un synopsis ou un casting, sans passer par le CLI ou une édition manuelle en DB.
- **Protéger les modifications manuelles** : toute donnée saisie par l'utilisateur ne doit plus jamais être écrasée silencieusement par une tâche automatique (enrichissement, re-import, re-association).

## Approach

**Découpage en deux plans livrables indépendamment :**

### Plan 42-01 — Épisodes hors canon
- Override du **nombre d'épisodes par saison** (réglage au niveau de la saison, pas par épisode) — cas (a) retenu contre le cas-par-cas (b) pour éviter de revalider à chaque nouveau fichier de la même saison.
- Stockage DB : champ override sur `SeriesModel` ou `SeasonModel` (JSON `{season: count}` ou table dédiée).
- Le `matching_step` / workflow consulte l'override **avant** de rejeter un épisode « hors canon ».
- Les épisodes acceptés au-delà du canon officiel portent un flag `is_extra=True` pour trace et affichage éventuel.

### Plan 42-02 — Overrides métadonnées
- **Bouton « Éditer »** sur la fiche détaillée web (films + séries).
- Champs éditables : **affiche**, **synopsis**, **casting** (format simple : liste nom + rôle, sans IDs TMDB).
- **Sources d'affiche** : upload local OU URL externe (au choix utilisateur à l'édition).
- **Stockage** : répertoire caché `storage/.metadata/` (même volume, poids négligeable) — posters sous `.metadata/posters/{id}.{ext}`, overrides texte probablement en JSON par entité ou en DB selon ce qui s'intègre le mieux à l'architecture (à trancher au plan).
- **Protection** : **flag global** « ne jamais écraser les overrides manuels » — retenu contre le verrou par champ pour simplicité. Consulté par `EnricherService` et toute tâche automatique qui toucherait poster / synopsis / casting.

## Constraints

- **SQLite** : migration additive (nouveaux champs/colonnes, pas de restructuration).
- **Usage local** : uploads via FastAPI, pas de service de stockage externe.
- **CLI doit rester fonctionnel** : les overrides peuvent être exposés via commandes si utile, mais l'UI web est la surface principale (Key Decision PROJECT.md : « Web = complément du CLI »).
- **Storage physique inchangé** : les fichiers vidéo ne sont jamais touchés par ces overrides, seuls les champs DB et le répertoire `.metadata/` sont impactés.

## Open Questions

- Format final du casting : liste `[{name, role}]` stockée en JSON dans un champ DB, ou fichier `.metadata/casting/{id}.json` ? (décision au plan)
- Synopsis override : même question — champ DB `synopsis_override` ou fichier JSON dans `.metadata/` ? (cohérence avec choix casting)
- Faut-il une commande CLI dédiée pour purger / lister les overrides ? (probablement non v1, à confirmer)
- Affichage des overrides dans la fiche web : badge discret « modifié manuellement » ou transparent ?

## Additional Context

- Contexte d'origine : session de discussion 2026-04-14 déclenchée par blocage concret sur *The Big C* S04 (4 épisodes « orphelins » revenant à chaque workflow).
- Architecture existante réutilisable : `EnricherService` (à étendre avec flag `preserve_overrides`), `MovieModel`/`SeriesModel`/`SeasonModel`/`EpisodeModel` (migrations), fiche détaillée web (à enrichir d'un bouton et d'un formulaire).
- Priorité utilisateur : pas de cas prioritaire explicite, mais *The Big C* est le déclencheur concret — un plan 42-01 livré en premier débloquerait immédiatement la situation.

---

*This file is temporary. It informs planning but is not required.*
*Created by /paul:discuss, consumed by /paul:plan.*
