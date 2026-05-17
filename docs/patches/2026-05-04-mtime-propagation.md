# Patch « propagation mtime jusqu'à video_dir »

**Date :** 2026-05-04
**Statut :** archivé (annulé après test)
**Fichiers concernés :**
- `src/services/transferer.py` — méthode `_bump_ancestors_mtime()` + appel dans `_create_symlink_at()`
- `tests/unit/services/test_transferer.py` — 2 tests

**Patch associé :** [2026-05-04-mtime-propagation.patch](2026-05-04-mtime-propagation.patch)

## Contexte

Workflow lancé le 2026-05-04 matin (71 fichiers transférés, 4 séries + films). Le
Dune 4K, lors d'un scan incrémental, n'a détecté **aucun nouveau fichier** alors
que les symlinks étaient pourtant bien créés dans `/media/Serveur/Collection/`.

**Hypothèse retenue :** beaucoup de media-centers (Dune, Plex, Kodi) utilisent
une heuristique « skip subtree if parent.mtime < last_scan ». Or POSIX ne met à
jour que la mtime du parent direct ; les répertoires plus haut dans
l'arborescence (`Films/`, `Series/`, `Films/Action & Aventure/`…) gardaient une
mtime de plusieurs mois.

## Solution implémentée

À chaque création de symlink dans `video_dir`, on propage la mtime de chaque
dossier ancêtre jusqu'à `video_dir` inclus, via `os.utime(d, (now, now))`.
Borné : ne touche rien au-dessus de `video_dir`, ni hors de `video_dir`.

## Résultat du test en conditions réelles

- ✅ Les 71 fichiers ont bien été détectés par le Dune 4K après le bump des
  ancêtres (rattrapage manuel des fichiers du matin via le transfer log).
- ❌ **Le scan a duré énormément de temps**, le Dune ayant probablement
  considéré toute la branche comme « modifiée » et relu en profondeur.

## Décision

Patch annulé en l'état. À reprendre uniquement si on observe à nouveau des
fichiers invisibles côté media-center, et avec une approche plus chirurgicale
(ex. ne bumper que les 1-2 niveaux au-dessus du parent direct, ou ne bumper
que `Films/` et `Series/` au lieu de toute la chaîne).

## Comment réappliquer

```bash
git apply docs/patches/2026-05-04-mtime-propagation.patch
uv run pytest tests/unit/services/test_transferer.py
```
