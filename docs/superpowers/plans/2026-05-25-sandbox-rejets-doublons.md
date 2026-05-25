# Sandbox : correctif « Garder l'ancien » + gestion enrichie — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faire en sorte que « Garder l'ancien » déplace le doublon rejeté hors de `downloads/` vers le sandbox, et enrichir la gestion du sandbox (liste multi-catégories, garde-fou « version conservée », suppression sûre).

**Architecture:** Le sandbox est organisé en sous-dossiers par origine (`orphans/`, `anciennes_versions/`, `rejets_doublons/`). `SandboxService` déduit la catégorie du sous-dossier (aucune persistance). Le garde-fou « version conservée » réutilise `DuplicateDetector.detect_duplicate()` (mémoïsé par titre) pour vérifier en direct si une copie existe dans `video/`. L'UI étend la section sandbox existante de `/maintenance`.

**Tech Stack:** Python 3.11, FastAPI, Jinja2 + HTMX, SQLModel, pytest, `uv`.

**Environnement :** pytest est dans l'extra `dev`. Lancer une fois `uv sync --extra dev`, puis utiliser `uv run pytest ...`. Lint/format : `uv run ruff check` / `uv run ruff format`.

---

## Interfaces (référence — types/signatures partagés entre tâches)

Dans `src/services/sandbox_service.py` :

```python
# Constantes de catégories (noms de sous-dossiers réels sur disque)
ORPHANS_SUBDIR = "orphans"
REPLACED_SUBDIR = "anciennes_versions"
REJECTED_SUBDIR = "rejets_doublons"

# Libellés de catégorie exposés (valeur du champ SandboxedFile.category)
CATEGORY_ORPHAN = "orphelin"
CATEGORY_REPLACED = "ancienne_version"
CATEGORY_REJECTED = "rejet_doublon"
CATEGORY_OTHER = "autre"

@dataclass
class SandboxedFile:
    path: Path
    name: str
    size: int
    modified: datetime
    original_path: Path
    category: str = CATEGORY_OTHER          # nouveau
    kept_version: Optional[str] = None       # nouveau (chemin relatif video/ ou None)

class SandboxService:
    def _classify(self, path: Path) -> tuple[str, Path, Path]: ...
        # → (category, base_pour_original_path, relative_sous_catégorie)
    def sandbox_rejected(self, paths: list[Path]) -> int: ...
    def annotate_kept_versions(self, files: list[SandboxedFile], video_dir: Path) -> None: ...
```

Dans `src/web/routes/maintenance.py` : helper `_build_sandbox_items(sandbox_svc, video_dir) -> list[dict]`.

---

## Task 1 : `SandboxService` — catégories + `_classify` + `list_sandboxed` multi-catégories

**Files:**
- Modify: `src/services/sandbox_service.py`
- Test: `tests/unit/test_sandbox_service.py`

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter à la fin de `tests/unit/test_sandbox_service.py` :

```python
from src.services.sandbox_service import (
    CATEGORY_ORPHAN,
    CATEGORY_REPLACED,
    CATEGORY_REJECTED,
    CATEGORY_OTHER,
    REPLACED_SUBDIR,
    REJECTED_SUBDIR,
)


class TestListSandboxedCategories:
    """list_sandboxed scanne toutes les catégories."""

    def test_categories_and_original_base(self, service, dirs):
        sb = dirs["sandbox"]
        _create_file(sb / "orphans" / "Films" / "Action" / "o.mkv")
        _create_file(sb / REPLACED_SUBDIR / "Films" / "SF" / "r.mkv")
        _create_file(sb / REJECTED_SUBDIR / "Series" / "T (2021)" / "Saison 01" / "x.mkv")
        _create_file(sb / "vieux_a_la_racine.mkv")  # legacy

        result = {f.name: f for f in service.list_sandboxed()}

        assert result["o.mkv"].category == CATEGORY_ORPHAN
        assert result["o.mkv"].original_path == dirs["storage"] / "Films" / "Action" / "o.mkv"
        assert result["r.mkv"].category == CATEGORY_REPLACED
        assert result["r.mkv"].original_path == dirs["storage"] / "Films" / "SF" / "r.mkv"
        assert result["x.mkv"].category == CATEGORY_REJECTED
        # rejet : base = downloads
        assert (
            result["x.mkv"].original_path
            == dirs["downloads"] / "Series" / "T (2021)" / "Saison 01" / "x.mkv"
        )
        assert result["vieux_a_la_racine.mkv"].category == CATEGORY_OTHER
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `uv run pytest tests/unit/test_sandbox_service.py::TestListSandboxedCategories -v`
Expected: FAIL (ImportError sur les constantes, puis AttributeError `category`).

- [ ] **Step 3 : Implémenter les constantes + le champ dataclass + `_classify` + `list_sandboxed`**

En tête de `src/services/sandbox_service.py`, après les imports, ajouter les constantes :

```python
# Sous-dossiers de catégories (noms réels sur disque)
ORPHANS_SUBDIR = "orphans"
REPLACED_SUBDIR = "anciennes_versions"
REJECTED_SUBDIR = "rejets_doublons"

# Libellés de catégorie (valeur de SandboxedFile.category)
CATEGORY_ORPHAN = "orphelin"
CATEGORY_REPLACED = "ancienne_version"
CATEGORY_REJECTED = "rejet_doublon"
CATEGORY_OTHER = "autre"
```

Étendre le dataclass `SandboxedFile` (ajouter 2 champs avec valeurs par défaut) :

```python
@dataclass
class SandboxedFile:
    """Fichier présent dans le sandbox."""

    path: Path
    name: str
    size: int
    modified: datetime
    original_path: Path
    category: str = CATEGORY_OTHER
    kept_version: Optional[str] = None
```

Ajouter la méthode `_classify` dans la classe `SandboxService` :

```python
    def _classify(self, path: Path) -> tuple[str, Path, Path]:
        """Déduit (catégorie, base de l'original_path, relative sous la catégorie).

        La catégorie vient du sous-dossier de premier niveau dans le sandbox.
        - orphans/, anciennes_versions/ → base storage_dir
        - rejets_doublons/ → base downloads_dir
        - racine / inconnu → catégorie "autre", base storage_dir
        """
        try:
            rel = path.relative_to(self._sandbox_dir)
        except ValueError:
            return (CATEGORY_OTHER, self._storage_dir, Path(path.name))

        parts = rel.parts
        first = parts[0] if parts else ""
        sub = Path(*parts[1:]) if len(parts) > 1 else Path(parts[-1]) if parts else rel

        if first == ORPHANS_SUBDIR:
            return (CATEGORY_ORPHAN, self._storage_dir, sub)
        if first == REPLACED_SUBDIR:
            return (CATEGORY_REPLACED, self._storage_dir, sub)
        if first == REJECTED_SUBDIR:
            return (CATEGORY_REJECTED, self._downloads_dir, sub)
        return (CATEGORY_OTHER, self._storage_dir, rel)
```

Remplacer `list_sandboxed()` par une version qui scanne tout le sandbox :

```python
    def list_sandboxed(self) -> list[SandboxedFile]:
        """Liste tous les fichiers du sandbox, toutes catégories confondues.

        Returns:
            Liste de SandboxedFile avec métadonnées + catégorie.
        """
        if not self._sandbox_dir.exists():
            return []

        files: list[SandboxedFile] = []
        for entry in sorted(self._sandbox_dir.rglob("*")):
            if entry.is_dir() or entry.is_symlink():
                continue
            category, base, relative = self._classify(entry)
            stat = entry.stat()
            files.append(
                SandboxedFile(
                    path=entry,
                    name=entry.name,
                    size=stat.st_size,
                    modified=datetime.fromtimestamp(stat.st_mtime),
                    original_path=base / relative,
                    category=category,
                )
            )
        return files
```

- [ ] **Step 4 : Lancer les tests, vérifier le succès (+ non-régression)**

Run: `uv run pytest tests/unit/test_sandbox_service.py -v`
Expected: PASS (y compris `TestListSandboxed` existant : `orphans/Films/Action/film.mkv` → `original_path == storage/Films/Action/film.mkv`, catégorie orphelin).

- [ ] **Step 5 : Commit**

```bash
git add src/services/sandbox_service.py tests/unit/test_sandbox_service.py
git commit -m "feat(sandbox): list_sandboxed multi-catégories + _classify"
```

---

## Task 2 : `SandboxService.sandbox_rejected()`

**Files:**
- Modify: `src/services/sandbox_service.py`
- Test: `tests/unit/test_sandbox_service.py`

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter à `tests/unit/test_sandbox_service.py` :

```python
class TestSandboxRejected:
    """sandbox_rejected déplace un doublon rejeté de downloads → rejets_doublons/."""

    def test_preserve_arborescence_from_downloads(self, service, dirs):
        src = _create_file(
            dirs["downloads"] / "Series" / "Octobre (2021)" / "ep01.mkv", "x265"
        )

        count = service.sandbox_rejected([src])

        assert count == 1
        dest = (
            dirs["sandbox"] / REJECTED_SUBDIR / "Series" / "Octobre (2021)" / "ep01.mkv"
        )
        assert dest.exists()
        assert dest.read_text() == "x265"
        assert not src.exists()

    def test_fallback_name_when_outside_downloads(self, service, dirs):
        src = _create_file(dirs["storage"] / "ailleurs.mkv", "data")

        count = service.sandbox_rejected([src])

        assert count == 1
        assert (dirs["sandbox"] / REJECTED_SUBDIR / "ailleurs.mkv").exists()

    def test_skip_missing(self, service, dirs):
        count = service.sandbox_rejected([dirs["downloads"] / "nope.mkv"])
        assert count == 0
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `uv run pytest tests/unit/test_sandbox_service.py::TestSandboxRejected -v`
Expected: FAIL (`AttributeError: 'SandboxService' object has no attribute 'sandbox_rejected'`).

- [ ] **Step 3 : Implémenter `sandbox_rejected`**

Ajouter dans `SandboxService` (après `sandbox_orphans`) :

```python
    def sandbox_rejected(self, paths: list[Path]) -> int:
        """Déplace des doublons rejetés (« Garder l'ancien ») vers le sandbox.

        Cible le sous-dossier rejets_doublons/, en préservant l'arborescence
        relative à downloads_dir (fallback : nom de fichier si hors downloads).

        Returns:
            Nombre de fichiers déplacés.
        """
        rejected_dir = self._sandbox_dir / REJECTED_SUBDIR
        moved = 0
        for src in paths:
            if not src.exists():
                logger.warning("Rejet introuvable, ignoré : {}", src)
                continue
            try:
                relative = src.relative_to(self._downloads_dir)
            except ValueError:
                relative = Path(src.name)
            dest = rejected_dir / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            moved += 1
            logger.info("Doublon rejeté sandboxé : {} → {}", src, dest)
        return moved
```

- [ ] **Step 4 : Lancer les tests, vérifier le succès**

Run: `uv run pytest tests/unit/test_sandbox_service.py::TestSandboxRejected -v`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add src/services/sandbox_service.py tests/unit/test_sandbox_service.py
git commit -m "feat(sandbox): sandbox_rejected (doublons rejetés → rejets_doublons/)"
```

---

## Task 3 : Garde-fou « version conservée » (`annotate_kept_versions`)

**Files:**
- Modify: `src/services/sandbox_service.py`
- Test: `tests/unit/test_sandbox_service.py`

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter à `tests/unit/test_sandbox_service.py` :

```python
class TestAnnotateKeptVersions:
    """annotate_kept_versions marque vert/rouge selon présence dans video/."""

    def test_movie_present_and_absent(self, service, dirs, tmp_path):
        video = tmp_path / "video"
        # Film présent dans la vidéothèque
        _create_file(video / "Films" / "Action" / "A-B" / "Heat (1995)" / "Heat (1995) VF.mkv")
        sb = dirs["sandbox"]
        present = _create_file(sb / REJECTED_SUBDIR / "Films" / "Heat (1995)" / "Heat (1995) VF x265.mkv")
        absent = _create_file(sb / REJECTED_SUBDIR / "Films" / "Inconnu (2099)" / "Inconnu (2099).mkv")

        files = service.list_sandboxed()
        service.annotate_kept_versions(files, video)
        by_name = {f.name: f for f in files}

        assert by_name["Heat (1995) VF x265.mkv"].kept_version is not None
        assert by_name["Inconnu (2099).mkv"].kept_version is None

    def test_series_episode_presence(self, service, dirs, tmp_path):
        video = tmp_path / "video"
        _create_file(
            video / "Series" / "O" / "Octobre (2021)" / "Saison 01"
            / "Octobre (2021) - S01E01 - VF.mkv"
        )
        sb = dirs["sandbox"]
        ep1 = _create_file(
            sb / REJECTED_SUBDIR / "Series" / "Octobre (2021)" / "Saison 01"
            / "Octobre (2021) - S01E01 - x265.mkv"
        )
        ep9 = _create_file(
            sb / REJECTED_SUBDIR / "Series" / "Octobre (2021)" / "Saison 01"
            / "Octobre (2021) - S01E09 - x265.mkv"
        )

        files = service.list_sandboxed()
        service.annotate_kept_versions(files, video)
        by_name = {f.name: f for f in files}

        assert by_name["Octobre (2021) - S01E01 - x265.mkv"].kept_version is not None
        assert by_name["Octobre (2021) - S01E09 - x265.mkv"].kept_version is None

    def test_video_dir_missing_is_safe(self, service, dirs, tmp_path):
        sb = dirs["sandbox"]
        _create_file(sb / REJECTED_SUBDIR / "Films" / "X (2000)" / "X (2000).mkv")
        files = service.list_sandboxed()
        service.annotate_kept_versions(files, tmp_path / "inexistant")
        assert all(f.kept_version is None for f in files)
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `uv run pytest tests/unit/test_sandbox_service.py::TestAnnotateKeptVersions -v`
Expected: FAIL (`AttributeError: ... 'annotate_kept_versions'`).

- [ ] **Step 3 : Implémenter `annotate_kept_versions` + helper d'identité**

Ajouter en tête de `src/services/sandbox_service.py` (après les imports existants) :

```python
import re

_EPISODE_RE = re.compile(r"S(\d+)E(\d+)", re.IGNORECASE)
_TITLE_YEAR_RE = re.compile(r"^(.+?)\s*\((\d{4})\)$")
_SERIES_PARTS = {"Series", "Séries"}
```

Ajouter les méthodes dans `SandboxService` :

```python
    def _parse_identity(
        self, f: "SandboxedFile"
    ) -> tuple[Optional[str], Optional[int], bool, Optional[str]]:
        """Extrait (titre, année, is_series, SxxExx) d'un fichier sandboxé.

        Titre/année : composant de chemin « Titre (AAAA) ». Épisode : regex
        SxxExx sur le nom de fichier. Retourne (None, ...) si indéterminable.
        """
        _, _, relative = self._classify(f.path)
        parts = relative.parts
        is_series = bool(parts) and parts[0] in _SERIES_PARTS

        title: Optional[str] = None
        year: Optional[int] = None
        for part in parts:
            m = _TITLE_YEAR_RE.match(part)
            if m:
                title, year = m.group(1).strip(), int(m.group(2))
                break
        if title is None:
            # Fallback : tenter sur le nom de fichier (sans extension)
            m = _TITLE_YEAR_RE.match(Path(f.name).stem)
            if m:
                title, year = m.group(1).strip(), int(m.group(2))

        episode = None
        em = _EPISODE_RE.search(f.name)
        if em:
            episode = f"S{int(em.group(1)):02d}E{int(em.group(2)):02d}"

        return title, year, is_series, episode

    def annotate_kept_versions(
        self, files: list["SandboxedFile"], video_dir: Path
    ) -> None:
        """Renseigne f.kept_version : chemin d'une copie présente dans video/,
        ou None si aucune trouvée. Réutilise DuplicateDetector (mémoïsé)."""
        from src.services.duplicate_detector import DuplicateDetector, _normalize_title

        detector = DuplicateDetector()
        cache: dict[tuple[str, Optional[int], bool], object] = {}

        for f in files:
            title, year, is_series, episode = self._parse_identity(f)
            if not title:
                f.kept_version = None
                continue
            key = (_normalize_title(title), year, is_series)
            if key not in cache:
                cache[key] = detector.detect_duplicate(
                    title, year, video_dir, is_series=is_series
                )
            match = cache[key]
            if match is None:
                f.kept_version = None
            elif is_series and episode:
                eps = getattr(match, "existing_episodes", None) or set()
                f.kept_version = str(match.existing_dir) if episode in eps else None
            else:
                f.kept_version = str(match.existing_dir)
```

- [ ] **Step 4 : Lancer les tests, vérifier le succès**

Run: `uv run pytest tests/unit/test_sandbox_service.py::TestAnnotateKeptVersions -v`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add src/services/sandbox_service.py tests/unit/test_sandbox_service.py
git commit -m "feat(sandbox): garde-fou version conservée (annotate_kept_versions)"
```

---

## Task 4 : Généraliser `reinject_files` + `_cleanup_empty_parents` aux catégories

**Files:**
- Modify: `src/services/sandbox_service.py`
- Test: `tests/unit/test_sandbox_service.py`

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter à `tests/unit/test_sandbox_service.py` :

```python
class TestReinjectAllCategories:
    """reinject_files fonctionne pour les catégories hors orphans/."""

    def test_reinject_rejected_series(self, service, dirs):
        f = _create_file(
            dirs["sandbox"] / REJECTED_SUBDIR / "Series" / "T (2021)" / "ep.mkv", "d"
        )
        count = service.reinject_files([f])
        assert count == 1
        assert (dirs["downloads"] / "Series" / "ep.mkv").exists()
        assert not f.exists()

    def test_delete_rejected_cleans_dirs(self, service, dirs):
        f = _create_file(
            dirs["sandbox"] / REJECTED_SUBDIR / "Films" / "X (2000)" / "x.mkv"
        )
        count = service.delete_files([f])
        assert count == 1
        assert not (dirs["sandbox"] / REJECTED_SUBDIR / "Films" / "X (2000)").exists()
        # la racine du sandbox subsiste
        assert dirs["sandbox"].exists()
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `uv run pytest tests/unit/test_sandbox_service.py::TestReinjectAllCategories -v`
Expected: FAIL (`test_reinject_rejected_series` : `ValueError` sur `relative_to(self._orphans_dir)`).

- [ ] **Step 3 : Corriger `reinject_files` (type via `_classify`) + `_cleanup_empty_parents` (root sandbox)**

Dans `reinject_files`, remplacer le bloc de calcul de `type_dir` :

```python
            # Conserver le sous-répertoire de type (Films/ ou Series/) pour
            # que le scan workflow détecte correctement le type de contenu
            try:
                relative = path.relative_to(self._orphans_dir)
                # Premier segment = Films, Series, Documentaires...
                type_dir = relative.parts[0] if relative.parts else ""
            except ValueError:
                type_dir = ""
```

par (utilise `_classify`, valable pour toutes les catégories) :

```python
            # Conserver le sous-répertoire de type (Films/ ou Series/) pour
            # que le scan workflow détecte correctement le type de contenu
            _, _, relative = self._classify(path)
            type_dir = relative.parts[0] if relative.parts else ""
```

Dans `delete_files` et `reinject_files`, changer l'appel de nettoyage de
`root=self._orphans_dir` vers `root=self._sandbox_dir` :

```python
        self._cleanup_empty_parents(paths, root=self._sandbox_dir)
```

- [ ] **Step 4 : Lancer les tests, vérifier le succès (+ non-régression)**

Run: `uv run pytest tests/unit/test_sandbox_service.py -v`
Expected: PASS (y compris `TestReinjectFiles` et `TestDeleteFiles` existants).

- [ ] **Step 5 : Commit**

```bash
git add src/services/sandbox_service.py tests/unit/test_sandbox_service.py
git commit -m "fix(sandbox): reinject/cleanup généralisés à toutes les catégories"
```

---

## Task 5 : `_sandbox_existing` dépose les anciennes versions sous `anciennes_versions/`

**Files:**
- Modify: `src/web/routes/transfer.py` (fonction `_sandbox_existing`, ~`:186-264`)
- Test: `tests/unit/web/test_transfer_sandbox.py` (créer)

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/unit/web/test_transfer_sandbox.py` :

```python
"""Tests des opérations sandbox de la route transfert."""

from pathlib import Path

from src.web.routes.transfer import _sandbox_existing
from src.services.sandbox_service import REPLACED_SUBDIR


def test_sandbox_existing_movie_goes_to_replaced_subdir(tmp_path: Path):
    storage = tmp_path / "storage"
    video = tmp_path / "video"
    sandbox = tmp_path / ".sandbox"

    # Film existant dans storage + symlink dans video
    movie_storage = storage / "Films" / "SF" / "A-B" / "Alien (1979)"
    movie_storage.mkdir(parents=True)
    real = movie_storage / "Alien (1979) AV1.mkv"
    real.write_text("av1")

    movie_video = video / "Films" / "SF" / "A-B" / "Alien (1979)"
    movie_video.mkdir(parents=True)
    (movie_video / "Alien (1979) AV1.mkv").symlink_to(real)

    _sandbox_existing(movie_video, sandbox, storage, video)

    dest = sandbox / REPLACED_SUBDIR / "Films" / "SF" / "A-B" / "Alien (1979)"
    assert dest.exists()
    assert (dest / "Alien (1979) AV1.mkv").exists()
    assert not movie_storage.exists()
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `uv run pytest tests/unit/web/test_transfer_sandbox.py -v`
Expected: FAIL (le fichier va à `sandbox/Films/...` et non `sandbox/anciennes_versions/Films/...`).

- [ ] **Step 3 : Modifier `_sandbox_existing`**

En tête de `src/web/routes/transfer.py`, ajouter l'import de la constante :

```python
from src.services.sandbox_service import REPLACED_SUBDIR
```

Dans `_sandbox_existing`, brancher la cible sous `REPLACED_SUBDIR`.

Pour la branche **série** (épisode unique), remplacer :

```python
                item_rel = item.relative_to(storage_dir)
                dest = sandbox_dir / item_rel
```

par :

```python
                item_rel = item.relative_to(storage_dir)
                dest = sandbox_dir / REPLACED_SUBDIR / item_rel
```

Pour la branche **film** (dossier entier), remplacer :

```python
        # Films : déplacer tout le dossier (comportement original)
        dest = sandbox_dir / relative
```

par :

```python
        # Films : déplacer tout le dossier sous la catégorie « ancienne version »
        dest = sandbox_dir / REPLACED_SUBDIR / relative
```

- [ ] **Step 4 : Lancer le test, vérifier le succès**

Run: `uv run pytest tests/unit/web/test_transfer_sandbox.py -v`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add src/web/routes/transfer.py tests/unit/web/test_transfer_sandbox.py
git commit -m "feat(transfer): anciennes versions remplacées → sandbox/anciennes_versions/"
```

---

## Task 6 : « Garder l'ancien » déplace le rejet vers le sandbox

**Files:**
- Modify: `src/web/routes/transfer.py` (branches `keep_old` : pré-résolue `~:604-610`, SSE `~:804-810`)
- Test: `tests/unit/web/test_transfer_sandbox.py`

- [ ] **Step 1 : Écrire le test qui échoue**

Ajouter à `tests/unit/web/test_transfer_sandbox.py` :

```python
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.web.routes.transfer import _run_web_transfer, TransferProgress
from src.services.sandbox_service import SandboxService, REJECTED_SUBDIR
from src.services.duplicate_detector import DuplicateMatch


def _make_container(tmp_path):
    storage = tmp_path / "storage"
    video = tmp_path / "video"
    downloads = tmp_path / "downloads"
    sandbox = tmp_path / ".sandbox"
    for d in (storage, video, downloads):
        d.mkdir(parents=True, exist_ok=True)

    settings = SimpleNamespace(
        storage_dir=storage,
        video_dir=video,
        downloads_dir=downloads,
        sandbox_dir=sandbox,
        resolved_sandbox_dir=sandbox,
    )
    container = MagicMock()
    container.config.return_value = settings
    container.transferer_service.return_value = MagicMock()
    container.sandbox_service.side_effect = lambda **kw: SandboxService(**kw)
    return container, settings


def test_keep_old_moves_source_to_sandbox(tmp_path):
    container, settings = _make_container(tmp_path)
    src = settings.downloads_dir / "Series" / "Octobre (2021)" / "ep01.mkv"
    src.parent.mkdir(parents=True)
    src.write_text("x265")

    existing_dir = settings.video_dir / "Series" / "Octobre (2021)"
    existing_dir.mkdir(parents=True)

    transfers = [
        {
            "source": src,
            "destination": settings.storage_dir / "Series" / "x" / "ep01.mkv",
            "symlink_destination": None,
            "new_filename": "Octobre (2021) - S01E01 - x265.mkv",
            "is_series": True,
            "has_duplicate": True,
            "duplicate_resolution": "keep_old",
            "duplicate_match": DuplicateMatch(
                existing_dir=existing_dir,
                existing_title="Octobre",
                existing_files=[],
                similarity_reason="même nom",
            ),
            "title": "Octobre",
            "year": 2021,
        }
    ]

    progress = TransferProgress()
    asyncio.run(_run_web_transfer(container, transfers, progress, dry_run=False))

    dest = settings.sandbox_dir / REJECTED_SUBDIR / "Series" / "Octobre (2021)" / "ep01.mkv"
    assert dest.exists()
    assert not src.exists()
    # keep_old ne transfère jamais
    container.transferer_service.return_value.transfer_file.assert_not_called()
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `uv run pytest tests/unit/web/test_transfer_sandbox.py::test_keep_old_moves_source_to_sandbox -v`
Expected: FAIL (le fichier source reste dans downloads, `dest` n'existe pas).

- [ ] **Step 3 : Implémenter le déplacement dans les deux branches `keep_old`**

Dans `_run_web_transfer`, **branche pré-résolue** (`if pre_resolution == "keep_old":`), remplacer le corps :

```python
                if pre_resolution == "keep_old":
                    progress.conflicts_resolved += 1
                    progress.message = (
                        f"Doublon résolu (pré) : ancien conservé pour {display_name}"
                    )
                    await asyncio.sleep(0.1)
                    continue
```

par :

```python
                if pre_resolution == "keep_old":
                    if not dry_run:
                        _reject_source_to_sandbox(container, settings, source)
                    progress.conflicts_resolved += 1
                    progress.message = (
                        f"Doublon résolu (pré) : ancien conservé pour {display_name}"
                    )
                    await asyncio.sleep(0.1)
                    continue
```

Dans la **branche SSE** (`if choice == "keep_old":`), remplacer :

```python
                if choice == "keep_old":
                    progress.conflicts_resolved += 1
                    progress.message = (
                        f"Doublon résolu : ancien conservé pour {display_name}"
                    )
                    await asyncio.sleep(0.1)
                    continue
```

par :

```python
                if choice == "keep_old":
                    if not dry_run:
                        _reject_source_to_sandbox(container, settings, source)
                    progress.conflicts_resolved += 1
                    progress.message = (
                        f"Doublon résolu : ancien conservé pour {display_name}"
                    )
                    await asyncio.sleep(0.1)
                    continue
```

Ajouter la fonction helper au niveau module dans `src/web/routes/transfer.py` (près de `_get_sandbox_dir`) :

```python
def _reject_source_to_sandbox(container, settings, source: Path) -> None:
    """Déplace un nouveau fichier rejeté (« Garder l'ancien ») vers le sandbox.

    Sort le fichier de downloads/ pour qu'il ne soit plus re-détecté aux
    traitements suivants. Échec → log, on ne bloque pas le transfert.
    """
    try:
        sandbox_svc = container.sandbox_service(
            sandbox_dir=settings.resolved_sandbox_dir,
            storage_dir=settings.storage_dir,
            downloads_dir=settings.downloads_dir,
        )
        sandbox_svc.sandbox_rejected([source])
    except Exception as e:
        logger.warning("Échec sandbox du rejet %s: %s", source, e)
```

- [ ] **Step 4 : Lancer le test, vérifier le succès**

Run: `uv run pytest tests/unit/web/test_transfer_sandbox.py -v`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add src/web/routes/transfer.py tests/unit/web/test_transfer_sandbox.py
git commit -m "fix(transfer): « Garder l'ancien » déplace le rejet vers le sandbox"
```

---

## Task 7 : `maintenance.py` — annoter `category` + `kept_version` + taille dans les items

**Files:**
- Modify: `src/web/routes/maintenance.py` (GET `:160-233`, delete `:1537-1581`, reinject `:1584-1628`, move-orphans SSE `:1452-1535`)
- Test: `tests/unit/web/test_maintenance_sandbox_items.py` (créer)

- [ ] **Step 1 : Écrire le test qui échoue (helper `_build_sandbox_items`)**

Créer `tests/unit/web/test_maintenance_sandbox_items.py` :

```python
from pathlib import Path

from src.web.routes.maintenance import _build_sandbox_items
from src.services.sandbox_service import SandboxService, REJECTED_SUBDIR


def test_build_sandbox_items_exposes_category_and_kept(tmp_path: Path):
    storage = tmp_path / "storage"
    downloads = tmp_path / "downloads"
    sandbox = tmp_path / ".sandbox"
    video = tmp_path / "video"
    for d in (storage, downloads):
        d.mkdir()

    # Film présent dans video/ (→ kept_version non None)
    kept = video / "Films" / "Action" / "Heat (1995)" / "Heat (1995) VF.mkv"
    kept.parent.mkdir(parents=True)
    kept.write_text("vf")
    # Rejet dans sandbox correspondant au même film
    rej = sandbox / REJECTED_SUBDIR / "Films" / "Heat (1995)" / "Heat (1995) x265.mkv"
    rej.parent.mkdir(parents=True)
    rej.write_text("x265")

    svc = SandboxService(sandbox_dir=sandbox, storage_dir=storage, downloads_dir=downloads)
    items = _build_sandbox_items(svc, video)

    assert len(items) == 1
    it = items[0]
    assert it["category"] == "rejet_doublon"
    assert it["kept_version"] is not None
    assert "size" in it and it["size_bytes"] == len("x265")
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `uv run pytest tests/unit/web/test_maintenance_sandbox_items.py -v`
Expected: FAIL (`ImportError: cannot import name '_build_sandbox_items'`).

- [ ] **Step 3 : Ajouter `_build_sandbox_items` et l'utiliser dans les 4 endpoints**

Dans `src/web/routes/maintenance.py`, ajouter le helper après `_get_sandbox_service` :

```python
def _build_sandbox_items(sandbox_svc, video_dir) -> list[dict]:
    """Liste les fichiers sandboxés + annote la version conservée pour l'UI."""
    files = sandbox_svc.list_sandboxed()
    sandbox_svc.annotate_kept_versions(files, video_dir)
    return [
        {
            "path": str(f.path),
            "name": f.name,
            "size": _format_size(f.size),
            "size_bytes": f.size,
            "modified": f.modified.strftime("%d/%m/%Y"),
            "original_path": _relative_from_root(f.original_path),
            "category": f.category,
            "kept_version": _relative_from_root(f.kept_version)
            if f.kept_version
            else None,
        }
        for f in files
    ]
```

Dans **`maintenance_page` (GET)** `:205-219`, remplacer la construction manuelle :

```python
    # Charger les fichiers sandbox
    sandbox_svc = _get_sandbox_service(container)
    sandboxed_files = sandbox_svc.list_sandboxed()
    sandbox_total_size = sum(f.size for f in sandboxed_files)
    sandbox_items = [
        {
            "path": str(f.path),
            "name": f.name,
            "size": _format_size(f.size),
            "size_bytes": f.size,
            "modified": f.modified.strftime("%d/%m/%Y"),
            "original_path": _relative_from_root(f.original_path),
        }
        for f in sandboxed_files
    ]
```

par :

```python
    # Charger les fichiers sandbox
    settings = container.config()
    sandbox_svc = _get_sandbox_service(container)
    sandbox_items = _build_sandbox_items(sandbox_svc, settings.video_dir)
    sandbox_total_size = sum(it["size_bytes"] for it in sandbox_items)
```

Dans **`sandbox_delete`** `:1559-1572`, remplacer le bloc :

```python
    # Retourner la section mise à jour
    sandboxed = sandbox_svc.list_sandboxed()
    total_size = sum(f.size for f in sandboxed)
    sandbox_items = [
        {
            "path": str(f.path),
            "name": f.name,
            "size": _format_size(f.size),
            "size_bytes": f.size,
            "modified": f.modified.strftime("%d/%m/%Y"),
            "original_path": _relative_from_root(f.original_path),
        }
        for f in sandboxed
    ]
```

par :

```python
    # Retourner la section mise à jour
    settings = container.config()
    sandbox_items = _build_sandbox_items(sandbox_svc, settings.video_dir)
    total_size = sum(it["size_bytes"] for it in sandbox_items)
```

Appliquer le **même remplacement** dans `sandbox_reinject` `:1606-1619` et dans la fonction SSE `sandbox_move_orphans_sse` `:1503-1516` (le bloc qui construit `sandbox_items` après `list_sandboxed()` ; y récupérer `settings = container.config()` puis `sandbox_items = _build_sandbox_items(sandbox_svc, settings.video_dir)` et `total_size = sum(it["size_bytes"] for it in sandbox_items)`).

> Note : ces 4 emplacements passent ensuite `sandbox_items`, `sandbox_count=len(sandbox_items)`, `sandbox_total_size=_format_size(total_size)` au template — inchangé.

- [ ] **Step 4 : Lancer le test + non-régression routes**

Run: `uv run pytest tests/unit/web/test_maintenance_sandbox_items.py -v`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add src/web/routes/maintenance.py tests/unit/web/test_maintenance_sandbox_items.py
git commit -m "feat(maintenance): expose catégorie + version conservée dans les items sandbox"
```

---

## Task 8 : UI — badges catégorie, colonne « version conservée », filtre, overlay enrichi

**Files:**
- Modify: `src/web/templates/maintenance/_sandbox_section.html`
- Modify: `src/web/templates/maintenance/index.html` (overlay `:199-216`, JS `:410-446`)

> Tâche UI : pas de test unitaire automatisé. Vérification manuelle décrite en Step 3.

- [ ] **Step 1 : `_sandbox_section.html` — colonnes Catégorie + Version conservée + filtre**

Dans `src/web/templates/maintenance/_sandbox_section.html`, ajouter les en-têtes de colonnes dans `<thead><tr>` après `<th>Fichier</th>` :

```html
                    <th>Catégorie</th>
```

et après `<th>Modifié</th>` :

```html
                    <th>Version conservée</th>
```

Dans le `<tbody>`, dans chaque `<tr class="sandbox-row">`, ajouter un attribut de catégorie et les deux cellules. Remplacer la ligne d'ouverture :

```html
                <tr class="sandbox-row">
```

par :

```html
                <tr class="sandbox-row" data-category="{{ item.category }}">
```

Après la cellule `sandbox-td-name`, ajouter la cellule badge :

```html
                    <td class="sandbox-td-cat">
                        {% set labels = {'orphelin': 'Orphelin', 'ancienne_version': 'Ancienne version', 'rejet_doublon': 'Doublon rejeté', 'autre': 'Autre'} %}
                        <span class="sandbox-badge sandbox-badge-{{ item.category }}">{{ labels.get(item.category, item.category) }}</span>
                    </td>
```

Après la cellule `sandbox-td-date`, ajouter la cellule « version conservée » :

```html
                    <td class="sandbox-td-kept">
                        {% if item.kept_version %}
                        <span class="sandbox-kept sandbox-kept-yes" title="{{ item.kept_version }}">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
                            présente
                        </span>
                        {% else %}
                        <span class="sandbox-kept sandbox-kept-no" title="Aucune autre copie trouvée dans la vidéothèque">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                            unique ?
                        </span>
                        {% endif %}
                    </td>
```

Juste avant `<div class="sandbox-table-wrap">`, ajouter la barre de filtre (visible si fichiers présents) :

```html
    <div class="sandbox-filter">
        <button type="button" class="sandbox-filter-btn active" data-filter="all" onclick="sandboxFilter(this, 'all')">Tout</button>
        <button type="button" class="sandbox-filter-btn" data-filter="orphelin" onclick="sandboxFilter(this, 'orphelin')">Orphelins</button>
        <button type="button" class="sandbox-filter-btn" data-filter="ancienne_version" onclick="sandboxFilter(this, 'ancienne_version')">Anciennes versions</button>
        <button type="button" class="sandbox-filter-btn" data-filter="rejet_doublon" onclick="sandboxFilter(this, 'rejet_doublon')">Doublons rejetés</button>
    </div>
```

- [ ] **Step 2 : `index.html` — JS filtre, récap suppression enrichi, CSS**

Dans `src/web/templates/maintenance/index.html`, remplacer le contenu du dialogue de suppression (`:206-208`) :

```html
        <h3 class="delete-dialog-title">Supprimer définitivement ?</h3>
        <p class="delete-dialog-text">Les fichiers sélectionnés seront <strong>supprimés physiquement</strong>. Cette action est irréversible.</p>
        <div class="delete-dialog-warning" id="sandbox-delete-count-msg">0 fichier(s) sélectionné(s)</div>
```

par (ajout taille totale + liste des noms + avertissement « unique ») :

```html
        <h3 class="delete-dialog-title">Supprimer définitivement ?</h3>
        <p class="delete-dialog-text">Les fichiers sélectionnés seront <strong>supprimés physiquement</strong>. Cette action est irréversible.</p>
        <div class="delete-dialog-warning" id="sandbox-delete-count-msg">0 fichier(s) sélectionné(s)</div>
        <div id="sandbox-delete-unique-warn" class="sandbox-delete-unique-warn" style="display:none;">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            <span id="sandbox-delete-unique-msg"></span>
        </div>
        <ul class="sandbox-delete-list" id="sandbox-delete-list"></ul>
```

Mettre à jour `sandboxUpdateActions()` (`:416-428`) pour calculer la taille totale, la liste des noms et l'avertissement « unique ». Remplacer la fonction par :

```javascript
function sandboxUpdateActions() {
    var checked = document.querySelectorAll('.sandbox-cb:checked');
    var count = checked.length;
    var countEl = document.getElementById('sandbox-sel-count');
    var btnDel = document.getElementById('sandbox-btn-delete');
    var btnReinject = document.getElementById('sandbox-btn-reinject');
    var countMsg = document.getElementById('sandbox-delete-count-msg');

    if (countEl) countEl.textContent = count + ' sélectionné(s)';
    if (btnDel) btnDel.disabled = count === 0;
    if (btnReinject) btnReinject.disabled = count === 0;

    // Récap suppression : nombre + taille totale + noms + avertissement unique
    var totalBytes = 0, uniques = 0, names = [];
    checked.forEach(function(cb) {
        var row = cb.closest('tr');
        totalBytes += parseInt(row.getAttribute('data-size-bytes') || '0', 10);
        if (row.getAttribute('data-kept') === 'no') uniques++;
        var nameEl = row.querySelector('.sandbox-td-name');
        if (nameEl) names.push(nameEl.textContent.trim());
    });
    if (countMsg) {
        countMsg.textContent = count + ' fichier(s) — ' + sandboxFmtSize(totalBytes) + ' libéré(s)';
    }
    var warn = document.getElementById('sandbox-delete-unique-warn');
    var warnMsg = document.getElementById('sandbox-delete-unique-msg');
    if (warn && warnMsg) {
        if (uniques > 0) {
            warnMsg.textContent = uniques + ' fichier(s) sans autre copie connue dans la vidéothèque.';
            warn.style.display = '';
        } else {
            warn.style.display = 'none';
        }
    }
    var list = document.getElementById('sandbox-delete-list');
    if (list) {
        list.innerHTML = names.slice(0, 10).map(function(n) {
            return '<li>' + n.replace(/</g, '&lt;') + '</li>';
        }).join('') + (names.length > 10 ? '<li>… +' + (names.length - 10) + '</li>' : '');
    }
}

function sandboxFmtSize(b) {
    if (b >= 1073741824) return (b / 1073741824).toFixed(1) + ' Go';
    if (b >= 1048576) return Math.round(b / 1048576) + ' Mo';
    return Math.round(b / 1024) + ' Ko';
}

function sandboxFilter(btn, cat) {
    document.querySelectorAll('.sandbox-filter-btn').forEach(function(b) {
        b.classList.toggle('active', b === btn);
    });
    document.querySelectorAll('.sandbox-row').forEach(function(row) {
        var show = cat === 'all' || row.getAttribute('data-category') === cat;
        row.style.display = show ? '' : 'none';
        if (!show) {
            var cb = row.querySelector('.sandbox-cb');
            if (cb && cb.checked) { cb.checked = false; }
        }
    });
    sandboxUpdateActions();
}
```

Pour que le JS lise la taille et l'état « unique » par ligne, ajouter ces `data-*` sur chaque `<tr>` dans `_sandbox_section.html`. Reprendre la ligne d'ouverture modifiée au Step 1 et la compléter :

```html
                <tr class="sandbox-row" data-category="{{ item.category }}" data-size-bytes="{{ item.size_bytes }}" data-kept="{{ 'yes' if item.kept_version else 'no' }}">
```

- [ ] **Step 3 : CSS — badges, indicateurs, filtre, liste**

Localiser le bloc de styles `.sandbox-*` (chercher `sandbox-table` dans `index.html` ou la feuille de styles incluse) et ajouter :

```css
.sandbox-filter { display: flex; gap: 0.4rem; margin-bottom: 0.6rem; flex-wrap: wrap; }
.sandbox-filter-btn { font-size: 0.75rem; padding: 0.25rem 0.6rem; border-radius: 6px;
    border: 1px solid var(--border, #333); background: transparent; color: var(--text-muted, #aaa); cursor: pointer; }
.sandbox-filter-btn.active { background: rgba(168,130,255,0.15); border-color: #a882ff; color: #c9b3ff; }
.sandbox-badge { font-size: 0.7rem; padding: 0.12rem 0.45rem; border-radius: 5px; white-space: nowrap; }
.sandbox-badge-orphelin { background: rgba(120,160,255,0.15); color: #8fb3ff; }
.sandbox-badge-ancienne_version { background: rgba(168,130,255,0.15); color: #c9b3ff; }
.sandbox-badge-rejet_doublon { background: rgba(232,93,117,0.15); color: #f08ca0; }
.sandbox-badge-autre { background: rgba(150,150,150,0.15); color: #aaa; }
.sandbox-kept { display: inline-flex; align-items: center; gap: 0.25rem; font-size: 0.72rem; }
.sandbox-kept-yes { color: #4caf78; }
.sandbox-kept-no { color: #e8a14d; }
.sandbox-delete-unique-warn { display: flex; align-items: center; gap: 0.4rem; color: #e8a14d;
    font-size: 0.8rem; margin: 0.5rem 0; }
.sandbox-delete-list { text-align: left; max-height: 140px; overflow-y: auto; margin: 0.4rem 0 0;
    padding-left: 1.1rem; font-size: 0.78rem; color: var(--text-muted, #aaa); }
```

- [ ] **Step 4 : Vérification manuelle**

```bash
uv run uvicorn src.web.app:app --reload --host 0.0.0.0
```
Ouvrir `/maintenance` depuis la machine maître. Vérifier : badges de catégorie, colonne « version conservée » (vert/orange), filtres fonctionnels, et que l'overlay de suppression affiche nombre + taille libérée + noms + avertissement « unique » si applicable. Tester une suppression et une réinjection.

- [ ] **Step 5 : Commit**

```bash
git add src/web/templates/maintenance/_sandbox_section.html src/web/templates/maintenance/index.html
git commit -m "feat(maintenance): UI sandbox — badges, version conservée, filtre, récap suppression"
```

---

## Task 9 : Documentation README + suite de tests complète

**Files:**
- Modify: `README.md`

- [ ] **Step 1 : Mettre à jour le README**

Dans `README.md`, dans la section traitant du sandbox / maintenance (chercher « sandbox » ou « Maintenance »), documenter :
- Le comportement « Garder l'ancien » : le nouveau fichier rejeté part automatiquement dans le sandbox (`anciennes_versions/` pour les versions remplacées, `rejets_doublons/` pour les rejets), il ne sera plus re-proposé aux traitements suivants.
- La gestion enrichie du sandbox : liste de tous les fichiers par catégorie (orphelin / ancienne version / doublon rejeté), filtre, indicateur « version conservée » (vert = une copie existe dans la vidéothèque, orange = aucune trouvée), et suppression définitive sécurisée (récap taille + noms, restreinte à la machine maître).

Ajouter une entrée à la table des matières si pertinent.

- [ ] **Step 2 : Lancer toute la suite + lint/format sur les fichiers modifiés**

```bash
uv sync --extra dev
uv run pytest tests/unit/test_sandbox_service.py tests/unit/web/test_transfer_sandbox.py tests/unit/web/test_maintenance_sandbox_items.py -v
uv run ruff check src/services/sandbox_service.py src/web/routes/transfer.py src/web/routes/maintenance.py
uv run ruff format src/services/sandbox_service.py src/web/routes/transfer.py src/web/routes/maintenance.py
```
Expected: tests PASS, ruff clean sur les fichiers touchés.

- [ ] **Step 3 : Commit**

```bash
git add README.md
git commit -m "docs(sandbox): documenter « Garder l'ancien » + gestion enrichie du sandbox"
```

---

## Récapitulatif des fichiers

| Fichier | Tâches |
|---|---|
| `src/services/sandbox_service.py` | 1, 2, 3, 4 |
| `src/web/routes/transfer.py` | 5, 6 |
| `src/web/routes/maintenance.py` | 7 |
| `src/web/templates/maintenance/_sandbox_section.html` | 8 |
| `src/web/templates/maintenance/index.html` | 8 |
| `tests/unit/test_sandbox_service.py` | 1, 2, 3, 4 |
| `tests/unit/web/test_transfer_sandbox.py` | 5, 6 |
| `tests/unit/web/test_maintenance_sandbox_items.py` | 7 |
| `README.md` | 9 |
