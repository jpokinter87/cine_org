# TODO - Fonctionnalités futures

## 📊 Ajout des notes TMDB dans la base de données

**Statut** : À IMPLÉMENTER
**Priorité** : Moyenne
**Complexité** : Faible
**Dépendances** : Aucune (API TMDB retourne déjà ces données)

### Description

Ajouter les notes et nombre de votes TMDB aux entités `Movie` et `Series` pour permettre des recherches avancées basées sur la popularité et la qualité des contenus.

### Cas d'usage

Recherches avancées sur la vidéothèque :
- "Films de SF des années 90 avec une note > 8.0"
- "Films cultes (>10000 votes) peu connus (<7.0)"
- "Meilleurs films d'action toutes époques (>8.0)"
- Trier la vidéothèque par note décroissante
- Filtrer les films "sûrs" pour une soirée (>7.5)

### Modifications nécessaires

#### 1. Modèles de données (`src/core/entities/media.py`)

```python
@dataclass
class Movie:
    # ... champs existants ...
    vote_average: Optional[float] = None  # Note moyenne /10 (ex: 8.4)
    vote_count: Optional[int] = None      # Nombre de votes (ex: 32000)

@dataclass
class Series:
    # ... champs existants ...
    vote_average: Optional[float] = None
    vote_count: Optional[int] = None
```

#### 2. Interface API (`src/core/ports/api_clients.py`)

```python
@dataclass
class MediaDetails:
    # ... champs existants ...
    vote_average: Optional[float] = None
    vote_count: Optional[int] = None
```

#### 3. Client TMDB (`src/adapters/api/tmdb_client.py`)

Extraire `vote_average` et `vote_count` des réponses API :
```python
# Dans get_details()
vote_average = data.get("vote_average")
vote_count = data.get("vote_count")
```

#### 4. Migration de base de données

Ajouter les colonnes dans les tables `movies` et `series` :
```sql
ALTER TABLE movies ADD COLUMN vote_average REAL;
ALTER TABLE movies ADD COLUMN vote_count INTEGER;
ALTER TABLE series ADD COLUMN vote_average REAL;
ALTER TABLE series ADD COLUMN vote_count INTEGER;
```

#### 5. Tests

- Mettre à jour les fixtures (`tests/fixtures/tmdb_responses.py`)
- Ajouter tests unitaires pour vérifier l'extraction des notes
- Tester la migration de base de données

### Notes techniques

- TMDB fournit `vote_average` (0-10) et `vote_count` pour tous les films/séries
- TVDB ne semble pas fournir de note utilisateur (juste rating de classification d'âge)
- Les notes existantes ne seront pas rétroactivement mises à jour → nécessite un ré-enrichissement ou une commande dédiée

### Implémentation future

Une fois les notes en base, possibilité d'ajouter :
- Une commande CLI de recherche avancée
- Des filtres dans l'interface web (future)
- Un système de recommandation basé sur les notes

---

## ✅ Analyse IA du générique pour validation automatique

**Statut** : IMPLÉMENTÉ
**Priorité** : Moyenne
**Complexité** : Élevée
**Dépendances** : ffmpeg, Tesseract OCR, Claude Vision API (optionnel)

### Description

Lors de la validation manuelle, quand plusieurs candidats ont des scores similaires (ex: deux films "Cold War" avec 100% chacun), utiliser l'IA pour analyser le générique de fin du fichier vidéo et déterminer automatiquement le bon candidat.

### Workflow proposé

1. Nouvelle option `a` (analyze) dans la boucle de validation
2. Extraction des frames du générique via ffmpeg :
   ```bash
   ffmpeg -sseof -120 -i fichier.mkv -vf "fps=1/10" -q:v 2 frame_%03d.jpg
   ```
3. Envoi des frames à Claude Vision avec prompt :
   > "Liste le réalisateur et les acteurs principaux visibles dans ce générique de film"
4. Comparaison du texte extrait avec les métadonnées TMDB des candidats :
   - Réalisateur
   - Acteurs principaux
5. Calcul d'un score de confiance et proposition du meilleur match

### Exemple d'utilisation

```
Fichier: Cold.War.2018.1080p.mkv

Candidat 1: Guerre froide (2017) - Réal: J. Wilder Konschak
Candidat 2: Cold War (2018) - Réal: Paweł Pawlikowski

Choix: a
[Extraction du générique...]
[Analyse IA...]
Texte détecté: "Directed by Paweł Pawlikowski", "Joanna Kulig", "Tomasz Kot"
→ Correspondance: Candidat 2 (confiance: 95%)
Valider automatiquement ? [O/n]
```

### Prérequis techniques

- [ ] ffmpeg disponible dans le PATH
- [ ] Clé API Anthropic (même clé que Claude Code, supporte Vision)
- [ ] Configuration du timeout (analyse ~30s)
- [ ] Gestion du cache des analyses (éviter de ré-analyser)

### Alternatives pour l'OCR

#### Option 1 : Claude Vision (recommandé)
- Utilise la même clé API que Claude Code
- Très performant sur le texte stylisé des génériques
- Coût : ~$0.01-0.02 par analyse

#### Option 2 : Tesseract OCR (gratuit, local)
- Installation : `sudo apt install tesseract-ocr tesseract-ocr-fra`
- Pas de coût, fonctionne hors-ligne
- Moins performant sur les polices stylisées
- Utilisation :
  ```python
  import pytesseract
  from PIL import Image
  text = pytesseract.image_to_string(Image.open("frame.jpg"), lang="fra+eng")
  ```

L'implémentation pourrait supporter les deux avec un fallback :
1. Essayer Tesseract (gratuit)
2. Si confiance faible, proposer Claude Vision

### Points d'attention

- Qualité variable des génériques (police, contraste)
- Films sans générique lisible (animations, etc.)
- Fallback si l'analyse échoue
- Prétraitement d'image pour améliorer l'OCR (contraste, binarisation)
