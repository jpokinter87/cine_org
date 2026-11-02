# Purge des hardlinks de seeding pilotée par Deluge — design

Date : 2026-11-02 · Branche : `feat/deluge-purge`

## Contexte

Après transfert, CineOrg laisse dans `downloads/` un hardlink de seeding (`nlink = 2`)
enregistré dans la table `hardlinks`. Le scanner ignore les fichiers `nlink > 1`.
À expiration, `purge-hardlinks` (timer systemd quotidien) **supprime le lien côté downloads
sans prévenir Deluge**, alors que le torrent est toujours actif :

1. Deluge passe le torrent en erreur (fichier manquant) ;
2. si l'utilisateur relance le torrent, Deluge **re-télécharge** le fichier : copie physique
   neuve (`nlink = 1`), donc vue comme nouvelle par le scanner ;
3. le workflow la repropose à chaque passage alors qu'elle est déjà en bibliothèque.

Constat du 2026-11-02 : 28 fichiers / 92,8 Go dans ce cas (The Plague, Silo S03E07, Stations of
the Cross, House of the Dragon S03…), nettoyés à la main (15 torrents retirés via RPC).

## Objectif

À expiration, CineOrg **retire le torrent de Deluge avec ses données** au lieu d'effacer le
fichier lui-même. Le torrent ne passe plus en erreur, le fichier ne revient plus, les
`.nfo`/`.srt` partent avec lui. Durée de seed portée à 90 jours (fait : `.env`).

## Décisions

1. **Identifiants dans le `.env`** : `CINEORG_DELUGE_HOST` (défaut `127.0.0.1`),
   `CINEORG_DELUGE_PORT` (défaut `58846`), `CINEORG_DELUGE_USERNAME`, `CINEORG_DELUGE_PASSWORD`.
   L'intégration est active si `USERNAME` et `PASSWORD` sont renseignés.
2. **Torrent multi-fichiers : attendre le dernier.** Un torrent n'est retiré que lorsque
   **tous** ses fichiers vidéo suivis dans `hardlinks` ont expiré. Les entrées expirées d'un
   torrent non encore retirable restent en base (reportées).
3. **Jamais de perte de copie unique.** Un torrent est bloqué (non retiré, signalé) s'il
   contient un fichier vidéo présent sur disque qui n'a pas d'autre copie :
   - fichier non suivi dans `hardlinks` avec `nlink == 1` ;
   - fichier suivi dont la cible `storage_path` est absente ou n'a pas le même inode
     (cas Spider-Noir : version storage écartée après coup).
4. **Deluge injoignable → aucune purge** pendant ce passage (erreur reportée, entrées
   conservées) : on ne retombe pas sur l'ancien `unlink`, qui casserait les torrents.
5. **Entrée expirée sans torrent** (torrent déjà retiré à la main) : comportement actuel
   (`unlink` du lien s'il existe, nettoyage des résidus et des dossiers vides, entrée supprimée).
6. **Intégration non configurée** : comportement actuel conservé, avec un avertissement
   explicite dans la sortie de la commande.
7. **Port + adaptateur** : `ITorrentClient` (`src/core/ports/torrent_client.py`) et
   `DelugeTorrentClient` (`src/adapters/torrent/deluge_client.py`, lib `deluge-client`).
   `HardlinkService` reçoit le client par injection (tests avec un faux client).
8. **`--dry-run` / `--force`** de `purge-hardlinks` conservés ; la sortie liste les torrents
   retirés, reportés (avec le nombre de fichiers encore actifs) et bloqués (avec la raison).

## Correspondance fichier ↔ torrent

`core.get_torrents_status({}, ["name", "save_path", "files"])` ; chemin absolu d'un fichier =
`save_path / files[i].path`. Index `chemin absolu → torrent_id`, comparé à
`hardlinks.download_path`. Retrait : `core.remove_torrent(torrent_id, True)`.

## Hors périmètre

- Détection des copies identiques déposées à la main dans `downloads/` (cas Pinocchio).
- Rangement erroné de Terranova en film multi-parties (anomalie séparée).
- Autres clients BitTorrent (le port le permettra plus tard).

## Critères de succès

- Tests unitaires du service de purge (faux client) : retrait si tout expiré, report si un
  fichier actif, blocage copie unique (2 cas), Deluge injoignable, entrée sans torrent,
  intégration non configurée, dry-run.
- Test de l'adaptateur avec un client RPC simulé (mapping `save_path/files`, `remove_torrent`).
- `purge-hardlinks --dry-run` réel contre le `deluged` local : sortie cohérente, rien retiré.
- README et `docs/hardlinks.md` à jour (variables, comportement, 90 jours).
