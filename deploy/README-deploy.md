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
