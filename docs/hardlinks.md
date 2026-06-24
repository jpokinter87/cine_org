# Hardlinks et seeding

Ce document explique le système de hardlinks mis en place pour préserver le seeding BitTorrent après transfert des fichiers vers la bibliothèque organisée.

## Table des matières

- [Problème résolu](#problème-résolu)
- [Principe](#principe)
- [Création au transfert](#création-au-transfert)
- [Modèle DB](#modèle-db)
- [Purge quotidienne](#purge-quotidienne)
- [Filtre scanner](#filtre-scanner)
- [Configuration](#configuration)
- [Commande CLI](#commande-cli)
- [Installation du timer systemd](#installation-du-timer-systemd)
- [Diagnostic](#diagnostic)

## Problème résolu

Un client BitTorrent (qBittorrent, Transmission, etc.) continue de partager un fichier tant que celui-ci reste au chemin d'origine dans `downloads/`. Or, le workflow CineOrg **déplace** les fichiers vers `storage/` (renommés et rangés par genre/lettre). Résultat : le seeding s'arrête dès que CineOrg traite le fichier.

**Solution** : créer un **hardlink** (lien physique) dans `downloads/` vers la nouvelle inode dans `storage/`. Le client BitTorrent voit le fichier à l'emplacement d'origine (seeding actif), tout en n'occupant l'espace disque qu'une seule fois.

Après une période configurable (30 j par défaut), le hardlink dans `downloads/` est purgé ; le fichier reste dans `storage/`.

## Principe

Un **hardlink** = deux entrées de répertoire pointant vers la même inode. Tant qu'au moins un lien existe, le fichier reste présent. Contraintes :

- Les deux chemins doivent être sur le **même volume** (inode partagée).
- `st_nlink` (stat) indique le nombre de liens ≥ 1.

**Flux CineOrg** :

```
1. Téléchargement terminé         downloads/torrent/Movie.mkv   (nlink=1)
2. Transfert CineOrg              storage/Films/…/Movie.mkv     (nlink=1, nouveau chemin)
3. Hardlink seeding créé          downloads/torrent/Movie.mkv ─┐
                                  storage/Films/…/Movie.mkv  ─┴─ même inode (nlink=2)
4. Scan suivant                   ignore downloads/torrent/Movie.mkv (nlink > 1)
5. Purge après TTL                downloads/torrent/Movie.mkv supprimé (nlink revient à 1)
```

**Cross-device** : si `downloads/` et `storage/` sont sur des volumes différents, `os.link()` échoue avec `OSError(EXDEV)`. Dans ce cas, la création du hardlink échoue silencieusement (log `warning`), **sans interrompre le transfert** — le seeding est perdu mais le fichier est correctement transféré.

## Création au transfert

**Fichier** : `src/services/transferer.py` — `TransfererService._create_seeding_hardlink()`.

Appelé **immédiatement après** `atomic_move()` réussi :

```python
def _create_seeding_hardlink(self, storage_path, original_source):
    try:
        original_source.parent.mkdir(parents=True, exist_ok=True)
        os.link(storage_path, original_source)
    except OSError as e:
        logger.warning(f"Hardlink seeding impossible : {e}")
        return  # Non bloquant

    self._register_hardlink(original_source, storage_path)
```

Points clés :

- `storage_path` = nouvelle destination (fichier physique).
- `original_source` = chemin d'origine dans `downloads/` (conservé pour le tracker).
- Le dossier parent de `original_source` est **recréé si nécessaire** (si `atomic_move()` a laissé le dossier source vide, il a pu être supprimé par un nettoyage antérieur).
- L'échec du hardlink (cross-device, permissions, quota, lien déjà existant) n'empêche pas le transfert de réussir — seul le seeding est perdu.
- Succès → `HardlinkModel` inséré en DB avec TTL.

## Modèle DB

**Fichier** : `src/infrastructure/persistence/models.py`.

```python
class HardlinkModel(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    download_path: str = Field(index=True)   # Chemin hardlink dans downloads/
    storage_path: str = Field(index=True)    # Chemin réel dans storage/
    created_at: datetime
    expires_at: datetime                     # created_at + hardlink_retention_days
```

Pas de clé étrangère vers `VideoFile` / `Movie` / `Episode` — table autonome d'audit. La relation est implicite via `storage_path` (correspond au `file_path` de la vidéo).

## Purge quotidienne

**Fichier** : `src/services/hardlink_service.py` — `HardlinkService`.

Méthodes principales :

| Méthode | Rôle |
|---------|------|
| `purge_expired(force_all=False, dry_run=False)` | Supprime les hardlinks expirés (ou tous si `force_all`). Retourne un `PurgeResult`. |
| `list_active()` | Liste les hardlinks non expirés (métadonnées affichables : `days_remaining`, `file_exists`). |
| `get_stats()` | Statistiques (`total_active`, `total_expired`, `total_entries`). |
| `_cleanup_empty_parents(file_path)` | Nettoie les résidus non-vidéo du dossier (via `_remove_residual_files`) puis remonte et supprime les dossiers parents vides (`rmdir()`) jusqu'à `downloads_dir`. Retourne le nombre de résidus supprimés. |
| `_remove_residual_files(directory)` | Supprime les fichiers non-vidéo (`.nfo`, etc.) d'un dossier de téléchargement **uniquement si plus aucun fichier vidéo n'y subsiste**. Ne touche jamais à la racine `downloads_dir`. |

**Algorithme `purge_expired`** :

1. Query DB : `expires_at < now` (ou tous si `force_all`).
2. Pour chaque entrée :
   - `download_path.unlink()` — décrémente `st_nlink` (le fichier dans `storage/` n'est pas touché).
   - Si le dossier ne contient plus aucun fichier vidéo, supprime les résidus non-vidéo (`.nfo`, etc.) qui empêcheraient le `rmdir`, comptés dans `PurgeResult.residuals_removed`.
   - Remonte et supprime les dossiers parents vides jusqu'à `downloads_dir`.
   - Supprime l'entrée DB.
3. Collecte les erreurs (permissions, fichier absent, etc.) dans `PurgeResult.errors`.
4. En `dry_run`, aucune modification filesystem — seul le plan est retourné.

Le fichier physique dans `storage/` reste intact. Si le client BitTorrent était encore en train de seeder, il perd le fichier à ce moment-là (attendu après la période de rétention).

## Filtre scanner

**Fichier** : `src/services/scanner.py` — `ScannerService._list_video_files_fallback()`.

Le scanner ignore les fichiers déjà hardlinkés pour éviter de les retraiter :

```python
for path in candidates:
    if path.is_symlink():
        continue
    stat = path.stat()
    if stat.st_nlink > 1:
        continue                          # Hardlink seeding actif → skip
    if stat.st_size < self.min_size_bytes:
        continue
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        continue
    if any(pat in path.name.lower() for pat in IGNORED_PATTERNS):
        continue
    yield path
```

**Combinaison critique** : un seul `stat()` par fichier, avec test `st_nlink > 1` avant `st_size` (moins coûteux). Évite d'ouvrir les fichiers pour les patterns.

## Configuration

**Fichier** : `src/config.py`.

| Variable d'environnement | Défaut | Rôle |
|--------------------------|-------:|------|
| `CINEORG_HARDLINK_RETENTION_DAYS` | `30` | Durée de vie d'un hardlink avant purge (minimum 1) |

Pour désactiver le seeding, il suffit de mettre `downloads/` et `storage/` sur des volumes différents — les hardlinks échoueront silencieusement.

## Commande CLI

**Fichier** : `src/adapters/cli/commands/hardlink_commands.py`.

```bash
# Purger les hardlinks expirés
uv run cineorg purge-hardlinks

# Simulation (aucune modification)
uv run cineorg purge-hardlinks --dry-run

# Forcer la purge de tous les hardlinks (ignore expires_at)
uv run cineorg purge-hardlinks --force
```

Affichage : table Rich des fichiers supprimés, liste d'erreurs, résumé final (count total / libéré / erreurs). Il n'y a **pas d'endpoint web** — la gestion est CLI + timer.

## Installation du timer systemd

Deux fichiers dans `deploy/` :

- `deploy/cineorg-purge.service` — `Type=oneshot`, exécute `uv run cineorg purge-hardlinks`.
- `deploy/cineorg-purge.timer` — `OnCalendar=daily` avec `RandomizedDelaySec=300` (jitter 5 min pour éviter la pointe de charge à minuit pile).

Installation :

```bash
sudo cp deploy/cineorg-purge.service /etc/systemd/system/
sudo cp deploy/cineorg-purge.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cineorg-purge.timer
```

Vérifications :

```bash
systemctl list-timers cineorg-purge.timer     # prochaine exécution
systemctl status cineorg-purge.service        # dernier résultat
journalctl -u cineorg-purge.service -n 100    # logs
```

## Diagnostic

**Pas de hardlink créé** :

- Vérifier que `downloads/` et `storage/` sont sur le **même volume** : `stat -c %m /chemin` doit retourner le même point de montage.
- Vérifier les permissions sur le dossier parent dans `downloads/` (recréé si supprimé, nécessite write).
- Consulter les logs loguru : message `warning` "Hardlink seeding impossible : …".

**Un fichier est re-scanné alors qu'il a été transféré** :

- Vérifier `stat -c %h fichier` : si `nlink = 1`, le hardlink n'a pas été créé (cross-device, purge prématurée, suppression manuelle).
- Requête DB : `SELECT * FROM hardlinkmodel WHERE download_path = '…'` pour voir si l'entrée existe.

**Dossiers vides résiduels dans `downloads/`** :

- La purge nettoie ascendant mais s'arrête à `downloads_dir`. Un dossier parent contenant plusieurs torrents ne sera supprimé qu'au purge du dernier fichier.
- Les fichiers résiduels non-vidéo (`.nfo`, screenshots, `Sample/`…) sont supprimés automatiquement au purge **dès que le dossier ne contient plus aucune vidéo** ; un dossier qui resterait pollué signifie donc qu'il contient encore un fichier vidéo (téléchargement encore actif).
- `find downloads/ -type d -empty -delete` peut être lancé manuellement si nécessaire (hors CineOrg).

**TTL personnalisé par fichier** : non supporté. Le TTL est global via `CINEORG_HARDLINK_RETENTION_DAYS`.

---

Pour les autres sous-systèmes, voir :
- [docs/architecture.md](architecture.md) — architecture générale.
- [docs/association.md](association.md) — association et réassociation TMDB/TVDB.
