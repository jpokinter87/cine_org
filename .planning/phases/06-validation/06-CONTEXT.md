# Phase 6: Validation - Context

**Gathered:** 2026-01-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Valider automatiquement les correspondances avec score >= 85% et permettre la validation manuelle pour les cas ambigus via CLI. L'utilisateur peut voir les candidats, sélectionner le bon match, rechercher manuellement, ou saisir un ID externe. La validation finale batch affiche tous les fichiers avec leurs destinations avant transfert.

</domain>

<decisions>
## Implementation Decisions

### Affichage des candidats
- Format cartes détaillées (bloc multi-lignes par candidat)
- Contenu : titre, année, score, source API, genres, synopsis tronqué, durée, langues disponibles
- Meilleur candidat mis en avant avec badge ★ RECOMMANDÉ en couleur verte
- Top 5 candidats affichés par défaut
- Pagination automatique : si l'utilisateur refuse tous les candidats ('n' ou 'aucun'), affiche les 5 suivants

### Workflow de sélection
- Sélection par numéro simple (1, 2, 3...)
- Actions complètes disponibles :
  - [numéro] sélectionner un candidat
  - [s] passer (skip) — fichier reste en pending
  - [t] corbeille (trash)
  - [r] recherche manuelle
  - [i] saisir ID externe
  - [d] voir détails complets
  - [?] aide
  - [q] quitter
- Après sélection : mini-récap avec destination proposée, possibilité d'éditer le titre
- Aucun candidat acceptable : choix proposé (passer, rechercher, corbeille)

### Recherche manuelle
- Recherche directe : tout texte non reconnu comme commande lance une recherche
- Détection auto des IDs : tt1234567 = IMDB, numérique = demander source (TMDB/TVDB)
- Format séries : Claude's discretion (probablement titre seul puis navigation saison/épisode)

### Confirmation batch finale
- Récapitulatif avec détails complets : chemin source et destination pour chaque fichier
- Modification individuelle possible avant validation finale
- Progression pendant transfert : barre de progression avec % et fichier en cours

### Claude's Discretion
- Comportement recherche manuelle sans résultat (retry simple ou suggestions)
- Format recherche séries (titre seul vs structuré)
- Gestion erreurs pendant transfert (continuer + rapport ou pause + choix)

</decisions>

<specifics>
## Specific Ideas

- Le badge ★ RECOMMANDÉ doit être visuellement distinct (couleur verte)
- La pagination des candidats est automatique après refus, pas besoin de commande explicite
- Le mini-récap après sélection permet de corriger le titre si l'API a un titre différent de celui souhaité

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 06-validation*
*Context gathered: 2026-01-27*
