---
name: cineorg-dev-conventions
description: >-
  Boucle de développement et conventions mécaniques du projet CineOrg. À utiliser dès qu'on lance
  des tests, du lint, du typage, qu'on commite, qu'on ouvre une PR ou qu'on cherche dans le code de
  ce dépôt. Couvre : le préfixe obligatoire `uv sync --extra dev` avant pytest, le scope du lint aux
  seuls fichiers modifiés, le format des commits conventionnels en français, la stratégie de
  branches/PR, le contournement de rtk qui brouille `grep`, et la mise à jour du README après une
  fonctionnalité. À utiliser pour éviter les frictions récurrentes (« pytest introuvable », lint sur
  tout le dépôt, commits non conventionnels, grep illisible).
---

# Conventions de dev CineOrg

`uv` est le gestionnaire de dépendances. **Toujours `uv run …`**, jamais `python3`/`pyenv` direct.

## Tests

**Toujours** préfixer par `uv sync --extra dev` — `pytest` est dans l'extra `dev` du `pyproject`,
pas dans les deps principales. Sans ça : « pytest introuvable ».

```bash
uv sync --extra dev && uv run pytest tests/unit/services/test_xxx.py -v   # ciblé sur le module modifié
uv sync --extra dev && uv run pytest                                       # suite complète si besoin
uv run pytest --cov=src --cov-fail-under=90                                # couverture min 90 %
```

TDD : écrire le test qui échoue avant le correctif. Mocks (`MagicMock`) pour repos/services,
`respx` pour httpx, `create_engine("sqlite:///:memory:")` pour tester les repos, `tmp_path` pour les
fichiers. Pour chaque bug → un test de régression qui échoue avant, passe après.

## Lint, format, types — scopés aux fichiers modifiés

Le dépôt a une **dette lint préexistante** (≈ 144 fichiers à reformater / 139 erreurs) : la traiter
en bloc = bruit ingérable. **Scoper aux fichiers touchés** :

```bash
uv run ruff check src/chemin/fichier_modifie.py
uv run ruff format src/chemin/fichier_modifie.py
uv run mypy src/chemin/fichier_modifie.py   # si pertinent
```

Ne **pas** lancer ruff/format sur tout le dépôt.

## Recherche dans le code — rtk brouille `grep`

Un hook réécrit les commandes via **rtk** (token killer), ce qui **brouille la sortie de `grep`**
shell. Préférer l'**outil Grep** ou **Read** (dédiés, non filtrés). Pour une sortie brute en dernier
recours : `rtk proxy grep …`.

## Commits — conventionnels, en français

Format : `type(scope): description` en français. Types observés : `feat`, `fix`, `docs`, `refactor`,
`test`, `chore`, `perf`. Exemples du dépôt :

```
feat(maintenance): UI sandbox — badges, version conservée, filtre, récap suppression
fix(sandbox): extraction titre non ancrée pour fiabiliser le garde-fou version conservée
test(transfer): couvrir la branche série de _sandbox_existing
```

## Branches & PR

- Fonctionnalité **indépendante** → brancher **depuis `master`** + ouvrir une PR. Ne pas empiler sur
  `feat/migrate-nas-raw-mode` ; au besoin **cherry-pick** vers une branche issue de `master`.
- **Ne pas merger `migrate-nas` dans `master`** tant qu'il n'est pas finalisé (PR #2 reste ouverte).
- Commiter/pousser **seulement** quand l'utilisateur le demande.

## Après une fonctionnalité visible → README

Nouvelle commande CLI, nouveau service, ou changement de comportement visible : **mettre à jour
`README.md`** (usage, options, exemples), ajouter à la table des matières et à la section Dépannage
si pertinent.
