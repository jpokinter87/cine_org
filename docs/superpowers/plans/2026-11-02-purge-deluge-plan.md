# Purge pilotée par Deluge — plan

Spec : `docs/superpowers/specs/2026-11-02-purge-deluge-design.md` · Branche : `feat/deluge-purge`

Boucle : `uv sync --extra dev && uv run --extra dev pytest <fichiers>` ; ruff limité aux
fichiers modifiés.

## Étapes

1. **Dépendance + configuration**
   - `uv add deluge-client` ; `Settings` : `deluge_host`, `deluge_port`, `deluge_username`,
     `deluge_password` (optionnels) + propriété `deluge_enabled`.
   - Défaut `hardlink_retention_days` : 60 → 90 (le `.env` de prod est déjà à 90).
   → vérifier : test de config (valeurs par défaut, activation si identifiants présents).

2. **Port `ITorrentClient`** (`src/core/ports/torrent_client.py`)
   - `TorrentInfo(id: str, name: str, files: tuple[Path, ...])` (chemins absolus).
   - `list_torrents() -> list[TorrentInfo]`, `remove(torrent_id: str) -> None` (avec données).
   - Exception `TorrentClientUnavailable`.

3. **Adaptateur `DelugeTorrentClient`** (`src/adapters/torrent/deluge_client.py`) — TDD
   - Tests avec un `DelugeRPCClient` simulé : `save_path/files[i].path` → chemins absolus,
     `remove_torrent(id, True)`, erreur de connexion → `TorrentClientUnavailable`.

4. **`HardlinkService.purge_expired`** — TDD (faux `ITorrentClient`)
   - Tests d'abord (un par décision 2-6 de la spec + dry-run), puis implémentation :
     regrouper les entrées expirées par torrent ; retirer / reporter / bloquer ; entrées sans
     torrent → chemin actuel ; client injoignable → rien purgé, erreur dans `PurgeResult`.
   - `PurgeResult` : ajouter `removed_torrents`, `deferred` (nom, nb actifs), `blocked`
     (nom, raison). Le chemin « sans Deluge » reste couvert par les tests existants.

5. **Câblage**
   - `container.py` : provider du client Deluge (None si non configuré) injecté dans
     `HardlinkService` ; `hardlink_commands.py` : affichage retirés / reportés / bloqués,
     avertissement si intégration non configurée.
   → vérifier : `uv run cineorg purge-hardlinks --dry-run` contre le `deluged` local.

6. **Documentation** : README (variables `.env`, comportement, 90 jours), `docs/hardlinks.md`,
   `deploy/README-deploy.md` (ajouter les identifiants Deluge au `.env`).

7. **Vérification finale** : pytest ciblé + `test_hardlink_service.py`, ruff sur les fichiers
   modifiés, commit conventionnel `feat(seeding): …`, `cz bump`, PR.

## Risques

- Chemins Deluge vs chemins CineOrg (accents, liens symboliques de montage) : comparer des
  chemins normalisés (`os.path.normpath`) ; test avec « Séries ».
- `remove_torrent` est asynchrone côté disque (constaté : quelques secondes) : ne pas vérifier
  l'absence du fichier juste après ; le nettoyage des dossiers vides tolère un dossier encore
  plein (passage suivant).
