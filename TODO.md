# TODO - Fonctionnalités futures

## Analyse IA du générique pour validation automatique

**Priorité** : Moyenne
**Complexité** : Élevée
**Dépendances** : ffmpeg, Claude Vision API

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
- [ ] Clé API Anthropic avec accès Claude Vision
- [ ] Configuration du timeout (analyse ~30s)
- [ ] Gestion du cache des analyses (éviter de ré-analyser)

### Points d'attention

- Coût API Claude Vision (images volumineuses)
- Qualité variable des génériques (police, contraste)
- Films sans générique lisible (animations, etc.)
- Fallback si l'analyse échoue
