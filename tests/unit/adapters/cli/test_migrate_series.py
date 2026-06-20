"""Tests unitaires pour la commande migrate-series."""

import json
from unittest.mock import MagicMock


from src.adapters.cli.commands.migrate_series_command import (
    _DB_REPLACEMENTS,
    _plan_directory_renames,
    _plan_reclassification,
    _repair_broken_symlinks,
)


class TestPlanDirectoryRenames:
    """Tests pour _plan_directory_renames."""

    def test_detects_series_root(self, tmp_path):
        """Detecte le repertoire Séries/ a renommer."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        (storage / "Séries" / "Séries TV").mkdir(parents=True)
        (video / "Séries" / "Séries TV").mkdir(parents=True)

        ops = _plan_directory_renames(storage, video)

        # Doit trouver 4 ops : 2 sous-dirs (Séries TV→TV) + 2 racines (Séries→Series)
        assert len(ops) == 4
        old_names = [str(o.name) for o, _ in ops]
        new_names = [str(n.name) for _, n in ops]
        assert "Séries TV" in old_names
        assert "TV" in new_names
        assert "Séries" in old_names
        assert "Series" in new_names

    def test_no_renames_if_already_migrated(self, tmp_path):
        """Pas de renommage si deja en Series/TV."""
        storage = tmp_path / "storage"
        video = tmp_path / "video"
        (storage / "Series" / "TV").mkdir(parents=True)
        (video / "Series" / "TV").mkdir(parents=True)

        ops = _plan_directory_renames(storage, video)
        assert len(ops) == 0

    def test_skips_existing_target(self, tmp_path):
        """Ne propose pas le renommage si la cible existe deja."""
        storage = tmp_path / "storage"
        (storage / "Séries").mkdir(parents=True)
        (storage / "Series").mkdir(parents=True)  # Cible existe deja

        ops = _plan_directory_renames(storage, tmp_path / "video")
        # La racine Séries ne doit pas etre proposee (Series existe deja)
        root_ops = [(o, n) for o, n in ops if n.name == "Series"]
        assert len(root_ops) == 0


class TestPlanReclassification:
    """Tests pour _plan_reclassification."""

    def _make_session(self, series_data, episodes_data):
        """Cree un mock session avec les donnees fournies."""
        session = MagicMock()

        def mock_execute(query, params=None):
            result = MagicMock()
            query_str = str(query)
            if "FROM series" in query_str:
                result.fetchall.return_value = series_data
            elif "FROM episodes" in query_str:
                sid = params.get("sid") if params else None
                result.fetchall.return_value = [
                    (ep,) for s_id, ep in episodes_data if s_id == sid
                ]
            return result

        session.execute = mock_execute
        return session

    def test_reclassify_animation(self, tmp_path):
        """Serie Animation sous TV/ → proposee pour Series/Animation/."""
        series = [
            (1, "Avatar", 2005, json.dumps(["Animation", "Action"])),
        ]
        episodes = [
            (1, "/nas/storage/Series/TV/A/Avatar (2005)/Saison 01/ep.mkv"),
        ]

        session = self._make_session(series, episodes)
        ops = _plan_reclassification(session, tmp_path, tmp_path)

        assert len(ops) == 1
        assert ops[0]["expected_type"] == "Animation"
        assert "/Series/Animation/" in ops[0]["new_path"]

    def test_reclassify_manga(self, tmp_path):
        """Serie Anime sous TV/ → proposee pour Series/Mangas/."""
        series = [
            (1, "Naruto", 2002, json.dumps(["Anime", "Action"])),
        ]
        episodes = [
            (1, "/nas/storage/Series/TV/N/Naruto (2002)/Saison 01/ep.mkv"),
        ]

        session = self._make_session(series, episodes)
        ops = _plan_reclassification(session, tmp_path, tmp_path)

        assert len(ops) == 1
        assert ops[0]["expected_type"] == "Mangas"
        assert "/Series/Mangas/" in ops[0]["new_path"]

    def test_reclassify_documentary(self, tmp_path):
        """Serie Documentaire sous TV/ → proposee pour Documentaires/Series documentaires/."""
        series = [
            (1, "Planet Earth", 2006, json.dumps(["Documentaire"])),
        ]
        episodes = [
            (1, "/nas/storage/Series/TV/P/Planet Earth (2006)/Saison 01/ep.mkv"),
        ]

        session = self._make_session(series, episodes)
        ops = _plan_reclassification(session, tmp_path, tmp_path)

        assert len(ops) == 1
        assert ops[0]["expected_type"] == "Series documentaires"
        assert "/Documentaires/Series documentaires/" in ops[0]["new_path"]

    def test_skip_already_correct(self, tmp_path):
        """Serie deja dans le bon type → pas de reclassification."""
        series = [
            (1, "Naruto", 2002, json.dumps(["Anime"])),
        ]
        episodes = [
            # Deja sous Mangas/, pas sous TV/
            (1, "/nas/storage/Series/Mangas/N/Naruto (2002)/Saison 01/ep.mkv"),
        ]

        session = self._make_session(series, episodes)
        ops = _plan_reclassification(session, tmp_path, tmp_path)

        assert len(ops) == 0

    def test_skip_tv_series(self, tmp_path):
        """Serie sans genre special → ignoree (reste TV)."""
        series = [
            (1, "Breaking Bad", 2008, json.dumps(["Drame", "Thriller"])),
        ]
        episodes = [
            (1, "/nas/storage/Series/TV/B/Breaking Bad (2008)/Saison 01/ep.mkv"),
        ]

        session = self._make_session(series, episodes)
        ops = _plan_reclassification(session, tmp_path, tmp_path)

        assert len(ops) == 0


class TestRepairBrokenSymlinks:
    """Tests pour _repair_broken_symlinks."""

    def test_repairs_symlink_with_old_target(self, tmp_path):
        """Repare un symlink pointant vers l'ancien chemin Séries/."""
        video_dir = tmp_path / "video"
        storage_dir = tmp_path / "storage"

        # Creer le fichier physique au nouveau chemin
        new_file = storage_dir / "Series" / "TV" / "ep.mkv"
        new_file.parent.mkdir(parents=True)
        new_file.write_text("data")

        # Creer un symlink pointant vers l'ancien chemin
        series_dir = video_dir / "Series" / "TV"
        series_dir.mkdir(parents=True)
        link = series_dir / "ep.mkv"
        old_target = storage_dir / "Séries" / "Séries TV" / "ep.mkv"
        link.symlink_to(old_target)

        # Le symlink est casse (old_target n'existe pas)
        assert not link.resolve().exists()

        repaired = _repair_broken_symlinks(video_dir, storage_dir)
        assert repaired == 1

        # Le symlink pointe maintenant vers le nouveau chemin
        assert link.resolve().exists()
        assert link.resolve() == new_file.resolve()

    def test_skips_valid_symlinks(self, tmp_path):
        """Ne touche pas aux symlinks valides."""
        video_dir = tmp_path / "video"
        storage_dir = tmp_path / "storage"

        target = storage_dir / "Series" / "TV" / "ep.mkv"
        target.parent.mkdir(parents=True)
        target.write_text("data")

        series_dir = video_dir / "Series" / "TV"
        series_dir.mkdir(parents=True)
        link = series_dir / "ep.mkv"
        link.symlink_to(target)

        repaired = _repair_broken_symlinks(video_dir, storage_dir)
        assert repaired == 0

    def test_no_series_dir(self, tmp_path):
        """Retourne 0 si pas de repertoire Series/."""
        video_dir = tmp_path / "video"
        video_dir.mkdir()
        repaired = _repair_broken_symlinks(video_dir, tmp_path / "storage")
        assert repaired == 0


class TestDbReplacements:
    """Tests pour les constantes de remplacement DB."""

    def test_specific_before_general(self):
        """Les remplacements specifiques sont avant les generaux."""
        # Important : "Séries TV" doit etre remplace AVANT "Séries"
        first_old = _DB_REPLACEMENTS[0][0]
        assert "Séries TV" in first_old

    def test_all_replacements_defined(self):
        """Verifie que tous les remplacements necessaires sont definis."""
        olds = [old for old, _ in _DB_REPLACEMENTS]
        assert "/Séries TV/" in olds
        assert "/Séries/" in olds


class TestRemainingSeriesRefs:
    """Verifie qu'il ne reste pas de references 'Séries' fonctionnelles."""

    def test_no_functional_series_refs_in_source(self):
        """
        Grep le code source pour verifier qu'aucune reference fonctionnelle
        a 'Séries' ne reste (hors retrocompat explicite dans scanner, file_indexer,
        repair_service detection, et reconcile_command detection).
        """
        import subprocess

        result = subprocess.run(
            ["grep", "-rn", '"Séries"', "src/", "--include=*.py"],
            capture_output=True,
            text=True,
            cwd="/home/jp/PythonProject/cine_org",
        )

        # Fichiers autorises a garder "Séries" (retrocompat ou detection)
        allowed_files = {
            "src/services/scanner.py",  # Double variante downloads
            "src/services/repair/file_indexer.py",  # Filet ["Séries", "Series"]
            "src/services/repair/repair_service.py",  # Detection part_lower in ("series", "séries")
            "src/adapters/cli/commands/reconcile_command.py",  # Detection "/séries/" + fallback
            "src/adapters/cli/commands/import_commands.py",  # Import ancienne biblio
            "src/adapters/cli/commands/migrate_series_command.py",  # Migration elle-meme
            "src/services/sandbox_service.py",  # Detection catégorie série (Series/Séries) dans les chemins sandbox
        }

        violations = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            filepath = line.split(":")[0]
            if filepath not in allowed_files:
                violations.append(line)

        assert not violations, (
            "References 'Séries' fonctionnelles trouvees :\n" + "\n".join(violations)
        )
