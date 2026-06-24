# Déploiement CineOrg

## Prérequis

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) installé
- git
- systemd (Linux)

## Installation initiale

```bash
# Cloner le projet
git clone <url-du-repo> /home/jp/PythonProject/cine_org
cd /home/jp/PythonProject/cine_org

# Installer les dépendances
uv sync

# Configurer l'environnement
cp .env.example .env   # ou éditer .env directement
# Renseigner : chemins, clés API TMDB/TVDB, options de logging
```

## Installation du service systemd

```bash
# Copier le fichier service
sudo cp deploy/cineorg.service /etc/systemd/system/

# Recharger systemd
sudo systemctl daemon-reload

# Activer au démarrage
sudo systemctl enable cineorg

# Démarrer le service
sudo systemctl start cineorg
```

> **Note :** Adapter `User`, `Group`, `WorkingDirectory` et `EnvironmentFile` dans le fichier `.service` si les chemins diffèrent.

## Purge automatique des hardlinks (seeding)

Après transfert, un hardlink est conservé dans `downloads/` pour maintenir le
partage BitTorrent (le fichier physique vit dans `storage/`). Ces hardlinks sont
suivis en base avec une expiration (`hardlink_retention_days`, **60 jours** par
défaut) et purgés par la commande `cineorg purge-hardlinks`. Le timer systemd
`cineorg-purge.timer` automatise cette rotation **chaque jour**.

```bash
# Copier le service oneshot + son timer
sudo cp deploy/cineorg-purge.service deploy/cineorg-purge.timer /etc/systemd/system/

# Recharger systemd
sudo systemctl daemon-reload

# Activer + démarrer le timer
sudo systemctl enable --now cineorg-purge.timer

# Vérifier la planification (prochain déclenchement)
systemctl list-timers cineorg-purge*
```

Le timer est `Persistent=true` : un déclenchement manqué (machine éteinte) est
rattrapé au prochain démarrage. L'activation seule ne lance **pas** de purge
immédiate ; pour résorber un arriéré tout de suite :

```bash
# Aperçu sans rien supprimer
uv run cineorg purge-hardlinks --dry-run

# Purge réelle (ou : sudo systemctl start cineorg-purge.service)
uv run cineorg purge-hardlinks
```

> **À savoir :** purger un hardlink le supprime de `downloads/` — le client
> torrent marquera alors le torrent correspondant en erreur « fichiers
> manquants ». C'est le comportement attendu de la rotation ; le fichier reste
> intact dans `storage/`. Retirer ces vieux torrents du client reste manuel.

Logs de la purge : `journalctl -u cineorg-purge.service`.

## Commandes de gestion

```bash
# Statut du service
sudo systemctl status cineorg

# Redémarrer
sudo systemctl restart cineorg

# Arrêter
sudo systemctl stop cineorg

# Logs en temps réel
journalctl -u cineorg -f

# Logs des dernières 24h
journalctl -u cineorg --since "24 hours ago"
```

## Mise à jour

### Via le script de déploiement

```bash
./deploy/deploy.sh
```

Le script effectue : `git pull` → `uv sync` → `systemctl restart` → affichage du statut.

### Manuellement

```bash
cd /home/jp/PythonProject/cine_org
git pull
uv sync
sudo systemctl restart cineorg
sudo systemctl status cineorg
```

## Options du serveur

```bash
# Lancer avec plusieurs workers (production)
uv run cineorg serve --workers 2

# Désactiver les logs d'accès HTTP
uv run cineorg serve --no-access-log

# Mode développement (rechargement automatique)
uv run cineorg serve --reload
```

## Vérification post-déploiement

```bash
# Vérifier que le service tourne
sudo systemctl status cineorg

# Tester l'accès web
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000
# Attendu : 200
```

## Dépannage

| Problème | Solution |
|----------|----------|
| Port 8000 déjà utilisé | `sudo lsof -i :8000` pour identifier le processus, ou changer le port dans le `.service` |
| Permission denied | Vérifier `User`/`Group` dans le `.service` et les droits sur le répertoire projet |
| Service crash en boucle | `journalctl -u cineorg -n 50` pour voir les erreurs |
| Dépendances manquantes | `uv sync` pour réinstaller |
| Base de données verrouillée | Vérifier qu'une seule instance tourne : `systemctl status cineorg` |
| Hardlinks jamais purgés (vieux fichiers en seeding) | Vérifier que le timer est actif : `systemctl list-timers cineorg-purge*` ; sinon l'activer (voir « Purge automatique des hardlinks ») |
