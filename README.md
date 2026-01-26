# CineOrg

Application de gestion de vidéothèque personnelle avec organisation automatique des fichiers.

## Description

CineOrg permet de :
- Scanner un répertoire de téléchargements contenant des fichiers vidéo
- Extraire les métadonnées via `guessit` et `mediainfo`
- Valider et enrichir les informations via les APIs TMDB (films) et TVDB (séries)
- Renommer les fichiers selon un format standardisé
- Organiser les fichiers dans une arborescence structurée (par genre pour les films, alphabétique pour les séries)
- Créer des liens symboliques pour le mediacenter

## Documentation

Voir le fichier [SPECIFICATIONS.md](SPECIFICATIONS.md) pour la documentation technique complète.

## Stack Technique

- **Python 3.11+**
- **FastAPI** - Framework web
- **Jinja2 + HTMX** - Templates et interactivité
- **Typer** - Interface CLI
- **SQLModel** - ORM (SQLite)
- **guessit** - Parsing des noms de fichiers
- **pymediainfo** - Extraction métadonnées techniques

## Installation

```bash
# Cloner le dépôt
git clone https://github.com/jpokinter87/cine_org.git
cd cine_org

# Créer un environnement virtuel
python -m venv venv
source venv/bin/activate  # Linux/macOS
# ou
venv\Scripts\activate     # Windows

# Installer les dépendances
pip install -r requirements.txt

# Configurer (copier et éditer le fichier de configuration)
cp config/config.example.json config/config.json
# Éditer config.json avec vos chemins et clés API
```

## Utilisation

### Interface Web

```bash
# Lancer le serveur
cineorg serve

# Accéder à http://127.0.0.1:8000
```

### CLI

```bash
# Lancer le traitement
cineorg process

# Afficher les fichiers en attente
cineorg pending

# Voir les statistiques
cineorg stats

# Aide
cineorg --help
```

## Structure des Répertoires

```
téléchargements/
├── Films/        # Fichiers films à traiter
└── Séries/       # Fichiers séries à traiter

stockage/
├── Films/        # Fichiers organisés par genre
│   └── {Genre}/{Lettre}/{Fichier}.mkv
└── Séries/       # Fichiers organisés alphabétiquement
    └── {Lettre}/{Titre} ({Année})/Saison {XX}/{Fichier}.mkv

vidéo/            # Liens symboliques (pour mediacenter)
```

## Format de Nommage

**Films :**
```
Inception (2010) MULTi DTS x265 1080p.mkv
```

**Séries :**
```
Breaking Bad (2008) - S01E01 - Pilot - VOSTFR AAC x264 720p.mkv
```

## Licence

MIT
