# Jellyfin SP3b — Bouton « Partager / Départager » (partage éphémère + SyncPlay)

**Statut** : spec validée (2026-06-30)
**Sous-projet** : 3/3 du plan d'intégration CineOrg → Jellyfin (cf. `jellyfin-sync-design.md` pour SP1, `jellyfin-sp2-tailscale-design.md` pour SP2)
**Pré-requis levés** : SP3a (PoC manuel) a validé le streaming via Funnel, la restriction de la bibliothèque « Partage » et la synchro SyncPlay.

## Objectif

Permettre à l'utilisateur (le fils) de **partager en un clic** un film ou une série avec un ami
distant, pour un visionnage **synchronisé (SyncPlay)**, sans exposer le reste de la vidéothèque,
puis de **tout démonter** d'un clic (ou automatiquement). Toute l'opération doit être pilotée
depuis l'**interface web CineOrg**, sans manipulation manuelle de Jellyfin ni de Tailscale.

## Principe

Un **seul partage actif à la fois**. Le service web CineOrg — déjà permanent via
`cineorg.service` (`uv run cineorg serve`, utilisateur `jp` qui est **opérateur Tailscale**) —
orchestre l'ensemble :

- remplir/vider une **bibliothèque Jellyfin « Partage » éphémère** (symlinks + NFO),
- déclencher le **scan** de cette bibliothèque (API Jellyfin),
- **activer/couper le Funnel** Tailscale (exposition publique à la demande),
- **surveiller la fin de séance** pour démonter automatiquement.

### Flux « Partager »

Déclenché par un clic sur la fiche détaillée d'un film ou d'une série :

1. Si un partage est déjà actif → demander confirmation du **remplacement**.
2. **Vider** le dossier `Partage/`.
3. **Générer** les symlinks + NFO du titre dans `Partage/` (réutilise `jellyfin-sync`).
4. **Scanner** la bibliothèque Partage (API Jellyfin, scan ciblé).
5. **Activer** le Funnel (`tailscale funnel --bg 8096`).
6. **Enregistrer** l'état du partage (type, id, titre, `started_at`).

### Flux « Départager »

Déclenché par le bouton de la fiche, l'indicateur global, ou le fallback automatique :

1. **Couper** le Funnel (`tailscale funnel --https=443 off`).
2. **Vider** le dossier `Partage/`.
3. **Scanner** la bibliothèque Partage (pour qu'elle se vide côté Jellyfin).
4. **Effacer** l'état du partage.

## Configuration & prérequis

Nouveaux réglages (Settings/config CineOrg) :

| Réglage | Défaut | Rôle |
|---|---|---|
| `CINEORG_JELLYFIN_URL` | `http://localhost:8096` | Base des appels API Jellyfin |
| `CINEORG_JELLYFIN_API_KEY` | — | Clé API admin Jellyfin (**déjà générée**) |
| `CINEORG_JELLYFIN_PARTAGE_DIR` | `<CINEORG_JELLYFIN_DIR>/Partage` | Dossier de la lib éphémère |
| `CINEORG_FUNNEL_PORT` | `8096` | Port exposé par le Funnel |
| `share_idle_timeout` | `30 min` | Démontage après fin de lecture |
| `share_hard_cap` | `6 h` | Plafond de sécurité (filet) |

Prérequis ops (une fois), en partie hérités de SP3a :
- **Deux bibliothèques Jellyfin** restreintes à `Alex` (à reconfigurer depuis SP3a qui n'en avait
  qu'une) : « **Partage Films** » (type Films → `/media/Serveur/JellyfinLib/Partage/Films`) et
  « **Partage Séries** » (type Séries/Shows → `/media/Serveur/JellyfinLib/Partage/Series`), NFO
  activé, « Actualiser depuis Internet = Jamais ».
- Compte `Alex` non-admin avec SyncPlay, accès limité à ces deux bibliothèques.
- **Clé API Jellyfin** (déjà générée) → `CINEORG_JELLYFIN_API_KEY`.
- Opérateur Tailscale (`jp`) + prérequis Funnel (HTTPS certs + Funnel activé) — déjà faits en SP3a.

## Composants (briques isolées)

### `JellyfinClient` — `src/adapters/api/jellyfin_client.py`
Client httpx async authentifié par la clé API (en-tête `X-Emby-Token`).
- `refresh_partage_library(media_type)` : scan **ciblé** de la seule bibliothèque concernée
  (« Partage Films » ou « Partage Séries » selon le type), pas un scan de toute la vidéothèque.
  L'ItemId de chaque lib est résolu par son nom via `GET /Library/VirtualFolders`, puis
  `POST /Items/{itemId}/Refresh` (récursif).
- `get_active_sessions()` : `GET /Sessions` → sessions avec `NowPlayingItem` (id + chemin),
  pour le watcher.

### `JellyfinShareService` — `src/services/share/`
Réutilise les briques pures existantes de `src/services/jellyfin/` (`resolve_source`,
`folder_name`, `episode_filename`, `ensure_symlink` de `tree_builder` ; `build_movie_nfo`,
`build_tvshow_nfo`, `build_episode_nfo` de `nfo_builder`) pour émettre **un seul** titre dans le
dossier Partage, en interrogeant les models via une `Session` SQLModel (même approche que
`jellyfin_sync_service`, qui passe par les models et non les repositories). La granularité dépend
du type :
- **film** → uniquement ce film : `Partage/Films/{Titre (Année)}/` (symlink + `movie.nfo`) ;
- **série** → la **série intégrale** : `Partage/Series/{Titre (Année)}/Saison NN/` pour **toutes les
  saisons et tous les épisodes** présents en base (symlinks + NFO sidecar par épisode + `tvshow.nfo`).
  Le partage se fait toujours au niveau de la série entière (jamais une saison ou un épisode isolé).

> **Deux bibliothèques typées** (au lieu d'une) : un dossier `Partage/Films` (bibliothèque Jellyfin
> de type *Films*) et un dossier `Partage/Series` (type *Séries/Shows*). Une bibliothèque de type
> *Films* n'afficherait pas correctement une série (chaque épisode deviendrait un « film » isolé).
> On reproduit donc la séparation Films/Séries déjà en place dans la vidéothèque principale.

Source du lien = même chaîne de repli que `jellyfin-sync` (`realpath(symlink_path)` → `file_path`).
Méthodes : `populate(media_type, media_id)` et `clear()` (vide le dossier Partage).

### `FunnelController` — `src/adapters/funnel.py`
Pilote `tailscale` par sous-processus (utilisateur `jp` opérateur → **sans sudo**) :
`enable(port)` (`tailscale funnel --bg {port}`), `disable()` (`tailscale funnel --https=443 off`),
`status()` (`tailscale funnel status`). Journalise les erreurs ; échec d'activation → le partage
n'est pas marqué actif.

### `ShareSession` — table SQLModel (une ligne active)
Champs : `media_type`, `media_id`, `title`, `started_at`, `last_played_at` (dernier visionnage
observé). **Persisté** → survit à un redémarrage du service (le watcher reprend, le plafond de
sécurité reste valable).

### `ShareService` — orchestrateur, `src/services/share/share_service.py`
- `start_share(media_type, media_id, replace=False)` : applique le flux « Partager » ; lève une
  erreur explicite si un partage est actif et `replace` est faux.
- `stop_share()` : applique le flux « Départager ».
- `get_active_share()` : pour l'indicateur et l'état des boutons.

## Interface web

- **Bouton Partager / Départager** sur les fiches film et série (même pattern HTMX que le bouton
  « Visionner » existant dans `detail.html`). Endpoints `POST /share/{type}/{id}` et `POST /share/stop`.
  L'état du bouton dépend de `get_active_share()` (ce titre est-il le partage actif ?).
- **Remplacement** : cliquer Partager sur un autre titre alors qu'un partage est actif → **dialog
  de confirmation** (pattern overlay déjà utilisé pour la résolution des doublons).
- **Indicateur global persistant** : bandeau injecté dans le layout de base, affiché tant qu'un
  partage est actif — « 🔴 Partage en cours : *Titre* — Départager ». Rafraîchi par un **poll HTMX
  (~60 s)** pour refléter aussi un démontage automatique survenu côté serveur.

## Démontage & filets de sécurité

**Watcher** = tâche asyncio démarrée au lancement de l'app (FastAPI *lifespan*), boucle ~60 s,
active uniquement s'il existe un `ShareSession` :
- Interroge `/Sessions` : le contenu partagé est-il en lecture ? (un `NowPlayingItem` dont le
  chemin est sous `Partage/`). Si oui, met à jour `last_played_at`.
- **Idle** : `now - max(started_at, last_played_at) ≥ 30 min` sans lecture → démontage auto.
- **Plafond** : `now - started_at ≥ 6 h` → démontage auto (filet, même si la détection idle échoue).
- **Auto-réparation au démarrage** : si aucun `ShareSession` actif mais le Funnel est allumé →
  le couper (jamais d'exposition orpheline après un crash/redémarrage).

## Tests (TDD)

- `JellyfinClient` : mock httpx via **respx** (refresh ciblé, parsing des sessions).
- `FunnelController` : mock du sous-processus (commandes émises, gestion d'échec).
- `JellyfinShareService` : `tmp_path` pour vérifier l'arbre Partage généré (film + série), et le vidage.
  Réutilise les 44 tests existants des builders `jellyfin`.
- `ShareService` : orchestration avec dépendances mockées (start/replace/stop, erreur si actif).
- **Watcher** : horloge et sessions injectées → vérifie déclenchement idle (30 min), plafond (6 h),
  et auto-réparation au démarrage.
- Web : endpoints `POST /share/...` (mock `ShareService`), rendu du bouton selon l'état, bandeau global.

## Hors périmètre

- Gestion des comptes Jellyfin (le compte `Alex` existe déjà ; sa création/maintenance reste manuelle).
- Notification de l'ami (l'URL publique est constante ; la coordination se fait hors application).
- Accélération matérielle NVENC (RTX 3060) : optimisation ops séparée, non bloquante.
- Partages simultanés multiples (un seul partage actif par conception).

## Critères de succès

1. Depuis la fiche d'une série, un clic « Partager » rend le programme visible pour `Alex`
   (et seulement lui), le Funnel est actif, SyncPlay fonctionne.
2. Un clic « Départager » (ou l'indicateur global) coupe le Funnel et vide la lib Partage.
3. Si personne ne démonte, le partage se ferme tout seul : 30 min après la fin de lecture, et au
   plus tard 6 h après le partage.
4. Après un redémarrage du service en cours de partage, l'état est préservé ; un Funnel orphelin
   (sans partage actif) est coupé automatiquement au démarrage.
