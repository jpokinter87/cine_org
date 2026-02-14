"""Tests pour les chemins d'erreur et cas limites du CleanupService."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.core.entities.video import VideoFile
from src.services.cleanup import (
    BrokenSymlinkInfo,
    CleanupResult,
    MisplacedSymlink,
    SubdivisionPlan,
    _find_sibling_for_key,
    _refine_out_of_range_dest,
)


# ============================================================================
# Phase 12 : Tests de couverture supplementaires
# ============================================================================


class TestRefineOutOfRangeDest:
    """Tests pour _refine_out_of_range_dest (affinage de destination hors-plage)."""

    def test_target_dir_does_not_exist(self, tmp_path):
        """Si le repertoire cible n'existe pas, retourne la destination planifiee."""
        planned_dest = tmp_path / "inexistant" / "Film (2020)"
        result = _refine_out_of_range_dest(planned_dest)
        assert result == planned_dest

    def test_target_dir_exists_no_subdirs(self, tmp_path):
        """Si le repertoire cible existe mais sans subdivisions, retourne la destination planifiee."""
        target_dir = tmp_path / "C"
        target_dir.mkdir()
        planned_dest = target_dir / "Film (2020)"
        result = _refine_out_of_range_dest(planned_dest)
        assert result == planned_dest

    def test_target_dir_with_matching_subdivision(self, tmp_path):
        """Si le repertoire cible a une subdivision correspondante, redirige vers elle."""
        target_dir = tmp_path / "C"
        target_dir.mkdir()
        sub_ca_ch = target_dir / "Ca-Ch"
        sub_ca_ch.mkdir()
        sub_ci_cz = target_dir / "Ci-Cz"
        sub_ci_cz.mkdir()

        # "Californication" -> cle "CA" -> devrait aller dans Ca-Ch
        planned_dest = target_dir / "Californication (2007)"
        result = _refine_out_of_range_dest(planned_dest)
        assert result == sub_ca_ch / "Californication (2007)"

    def test_no_matching_subdivision(self, tmp_path):
        """Si aucune subdivision ne correspond a la cle, retourne la destination planifiee."""
        target_dir = tmp_path / "C"
        target_dir.mkdir()
        # Subdivisions qui ne couvrent pas "ZA"
        sub_ca_ch = target_dir / "Ca-Ch"
        sub_ca_ch.mkdir()
        sub_ci_cz = target_dir / "Ci-Cz"
        sub_ci_cz.mkdir()

        # "Zorro" -> cle "ZO" -> aucune subdivision ne correspond
        planned_dest = target_dir / "Zorro (1998)"
        result = _refine_out_of_range_dest(planned_dest)
        assert result == planned_dest

    def test_short_sort_key_padded(self, tmp_path):
        """Un item avec une seule lettre produit une cle paddee (ex: 'X' -> 'XA')."""
        target_dir = tmp_path / "X"
        target_dir.mkdir()
        sub = target_dir / "Xa-Xz"
        sub.mkdir()

        # "X (2011)" -> stripped "X" -> letters_only "X" -> cle "XA"
        planned_dest = target_dir / "X (2011)"
        result = _refine_out_of_range_dest(planned_dest)
        assert result == sub / "X (2011)"

    def test_item_with_article_stripped(self, tmp_path):
        """Un item avec article est correctement strip pour la cle de tri."""
        target_dir = tmp_path / "S"
        target_dir.mkdir()
        sub_sa_sm = target_dir / "Sa-Sm"
        sub_sa_sm.mkdir()
        sub_sn_sz = target_dir / "Sn-Sz"
        sub_sn_sz.mkdir()

        # "La Servante" -> strip "La" -> "Servante" -> cle "SE" -> Sa-Sm
        planned_dest = target_dir / "La Servante ecarlate (2017)"
        result = _refine_out_of_range_dest(planned_dest)
        assert result == sub_sa_sm / "La Servante ecarlate (2017)"

    def test_content_dirs_not_treated_as_subdivisions(self, tmp_path):
        """Les repertoires de contenu (series, films) ne doivent pas etre pris pour des subdivisions.

        Bug : apres affinage par _refine_plans_destinations, la destination est
        C/Ca-Ch/El Chapo. Le fallback _refine_out_of_range_dest voit les series
        dans Ca-Ch/ (C.B. Strike, Californication) et les prend pour des
        subdivisions, redirigeant El Chapo dans le premier repertoire alphabetique.
        """
        target_dir = tmp_path / "C" / "Ca-Ch"
        target_dir.mkdir(parents=True)
        # Contenu : series deja deplacees dans Ca-Ch
        (target_dir / "C.B. Strike (2017)").mkdir()
        (target_dir / "Californication (2007)").mkdir()
        (target_dir / "Charmed (1998)").mkdir()

        # El Chapo deja affine vers Ca-Ch/
        planned_dest = target_dir / "El Chapo (2017)"
        result = _refine_out_of_range_dest(planned_dest)
        # Ne doit PAS aller dans C.B. Strike/, doit rester dans Ca-Ch/
        assert result == planned_dest

    def test_mixed_subdivisions_and_content(self, tmp_path):
        """Si un repertoire contient a la fois des subdivisions et du contenu,
        seules les subdivisions sont considerees."""
        target_dir = tmp_path / "M"
        target_dir.mkdir()
        # Subdivision valide
        sub_me_mz = target_dir / "Me-Mz"
        sub_me_mz.mkdir()
        # Contenu direct (pas une subdivision)
        (target_dir / "Matrix (1999)").mkdir()

        planned_dest = target_dir / "Los mil dias de allende (2023)"
        result = _refine_out_of_range_dest(planned_dest)
        # "Los mil dias" -> strip "Los" -> "mil dias" -> cle "MI" -> Me-Mz
        assert result == sub_me_mz / "Los mil dias de allende (2023)"


class TestFindSiblingForKeyGrandparentMissing:
    """Tests pour _find_sibling_for_key quand le grand-parent n'existe pas."""

    def test_grandparent_does_not_exist(self, tmp_path):
        """Si le grand-parent n'existe pas, retourne le chemin du grand-parent."""
        # parent_dir pointe vers un chemin dont le parent n'existe pas
        parent_dir = tmp_path / "inexistant" / "enfant"
        # Ne pas creer les repertoires
        result = _find_sibling_for_key(parent_dir, "AB")
        assert result == parent_dir.parent


class TestCleanupEdgeCases:
    """Tests pour les chemins d'erreur non couverts du CleanupService."""

    # ------------------------------------------------------------------
    # analyze() - _scan_misplaced_symlinks retourne une liste (pas tuple)
    # ------------------------------------------------------------------

    def test_analyze_misplaced_returns_list(
        self, cleanup_service, temp_dirs,
    ):
        """analyze() gere le cas ou _scan_misplaced_symlinks retourne une liste."""
        video_dir = temp_dirs["video"]
        # Creer Films/ pour eviter des erreurs
        (video_dir / "Films").mkdir(parents=True, exist_ok=True)

        # Mocker _scan_misplaced_symlinks pour retourner une liste (pas un tuple)
        misplaced_item = MisplacedSymlink(
            symlink_path=Path("/video/Films/film.mkv"),
            target_path=Path("/storage/film.mkv"),
            current_dir=Path("/video/Films/Drame"),
            expected_dir=Path("/video/Films/Action"),
        )
        with patch.object(
            cleanup_service, "_scan_misplaced_symlinks", return_value=[misplaced_item]
        ):
            report = cleanup_service.analyze(video_dir)

        assert len(report.misplaced_symlinks) == 1
        assert report.not_in_db_count == 0

    # ------------------------------------------------------------------
    # _is_in_managed_scope - ValueError quand path n'est pas relatif a video_dir
    # ------------------------------------------------------------------

    def test_is_in_managed_scope_unrelated_path(self, cleanup_service):
        """Un chemin non relatif a video_dir retourne False."""
        result = cleanup_service._is_in_managed_scope(
            Path("/other/random/path"), Path("/video")
        )
        assert result is False

    # ------------------------------------------------------------------
    # _scan_misplaced_symlinks - symlinks casses/OSError ignores
    # ------------------------------------------------------------------

    def test_scan_misplaced_skips_broken_symlinks(
        self, cleanup_service, mock_video_file_repo, temp_dirs,
    ):
        """Les symlinks casses sont ignores lors du scan des mal-places."""
        video_dir = temp_dirs["video"]
        action_dir = video_dir / "Films" / "Action"
        action_dir.mkdir(parents=True)

        # Creer un symlink casse (cible inexistante)
        broken_link = action_dir / "Film Casse (2020).mkv"
        broken_link.symlink_to("/storage/inexistant.mkv")

        result, not_in_db = cleanup_service._scan_misplaced_symlinks(video_dir)

        # Le symlink casse est ignore, pas de MisplacedSymlink ni not_in_db
        assert len(result) == 0
        assert not_in_db == 0

    # ------------------------------------------------------------------
    # _find_expected_dir - episode path lookup (bloc episode complet)
    # ------------------------------------------------------------------

    def test_find_expected_dir_episode(
        self, cleanup_service, mock_movie_repo, mock_episode_repo,
        mock_series_repo, mock_organizer_service,
    ):
        """_find_expected_dir trouve un episode et retourne le bon repertoire."""
        video_dir = Path("/video")
        video_file = VideoFile(
            id="1",
            path=Path("/storage/series/episode.mkv"),
            filename="episode.mkv",
            size_bytes=1000,
        )

        # Mock: pas de film trouve
        mock_movie_repo._session.exec.return_value.first.return_value = None

        # Mock: episode trouve
        mock_episode_model = MagicMock(
            id=1,
            series_id=42,
            season_number=2,
            episode_number=5,
            title="Pilot",
            file_path="/storage/series/episode.mkv",
        )
        mock_episode_repo._session.exec.return_value.first.return_value = mock_episode_model

        # Mock: serie trouvee
        mock_series_model = MagicMock(
            id=42,
            tvdb_id=12345,
            title="Breaking Bad",
            original_title="Breaking Bad",
            year=2008,
            genres_json='["Drame", "Thriller"]',
        )
        mock_series_repo._session.exec.return_value.first.return_value = mock_series_model

        # Mock: destination attendue
        expected_dir = Path("/video/Séries/B/Breaking Bad (2008)/Saison 02")
        mock_organizer_service.get_series_video_destination.return_value = expected_dir

        result = cleanup_service._find_expected_dir(video_file, video_dir)

        assert result == expected_dir
        mock_organizer_service.get_series_video_destination.assert_called_once()

    def test_find_expected_dir_episode_no_series(
        self, cleanup_service, mock_movie_repo, mock_episode_repo,
        mock_series_repo,
    ):
        """_find_expected_dir retourne None si l'episode n'a pas de serie associee."""
        video_dir = Path("/video")
        video_file = VideoFile(
            id="1",
            path=Path("/storage/series/episode.mkv"),
            filename="episode.mkv",
            size_bytes=1000,
        )

        # Mock: pas de film
        mock_movie_repo._session.exec.return_value.first.return_value = None

        # Mock: episode trouve mais pas de serie
        mock_episode_model = MagicMock(
            id=1, series_id=42, season_number=1, episode_number=1,
            title="Pilot", file_path="/storage/series/episode.mkv",
        )
        mock_episode_repo._session.exec.return_value.first.return_value = mock_episode_model

        # Mock: serie introuvable
        mock_series_repo._session.exec.return_value.first.return_value = None

        result = cleanup_service._find_expected_dir(video_file, video_dir)

        assert result is None

    def test_find_expected_dir_episode_series_no_genres(
        self, cleanup_service, mock_movie_repo, mock_episode_repo,
        mock_series_repo, mock_organizer_service,
    ):
        """_find_expected_dir gere une serie sans genres_json (None)."""
        video_dir = Path("/video")
        video_file = VideoFile(
            id="1",
            path=Path("/storage/series/episode.mkv"),
            filename="episode.mkv",
            size_bytes=1000,
        )

        # Mock: pas de film
        mock_movie_repo._session.exec.return_value.first.return_value = None

        # Mock: episode trouve
        mock_episode_model = MagicMock(
            id=1, series_id=42, season_number=1, episode_number=1,
            title="Pilot", file_path="/storage/series/episode.mkv",
        )
        mock_episode_repo._session.exec.return_value.first.return_value = mock_episode_model

        # Mock: serie avec genres_json=None
        mock_series_model = MagicMock(
            id=42, tvdb_id=12345, title="Test Show",
            original_title=None, year=2020, genres_json=None,
        )
        mock_series_repo._session.exec.return_value.first.return_value = mock_series_model

        expected_dir = Path("/video/Séries/T/Test Show (2020)/Saison 01")
        mock_organizer_service.get_series_video_destination.return_value = expected_dir

        result = cleanup_service._find_expected_dir(video_file, video_dir)

        assert result == expected_dir

    def test_find_expected_dir_episode_exception(
        self, cleanup_service, mock_movie_repo, mock_episode_repo,
    ):
        """_find_expected_dir retourne None si une exception survient lors de la recherche d'episode."""
        video_dir = Path("/video")
        video_file = VideoFile(
            id="1",
            path=Path("/storage/series/episode.mkv"),
            filename="episode.mkv",
            size_bytes=1000,
        )

        # Mock: pas de film
        mock_movie_repo._session.exec.return_value.first.return_value = None

        # Mock: exception lors de la recherche d'episode
        mock_episode_repo._session.exec.side_effect = Exception("DB error")

        result = cleanup_service._find_expected_dir(video_file, video_dir)

        assert result is None

    # ------------------------------------------------------------------
    # _scan_duplicate_symlinks - OSError lors de la resolution
    # ------------------------------------------------------------------

    def test_scan_duplicate_skips_oserror(self, cleanup_service, temp_dirs):
        """Les symlinks provoquant une OSError lors de la resolution sont ignores."""
        video_dir = temp_dirs["video"]
        action_dir = video_dir / "Films" / "Action"
        action_dir.mkdir(parents=True)

        # Creer un symlink valide
        storage_dir = temp_dirs["storage"]
        target = storage_dir / "film.mkv"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
        valid_link = action_dir / "Film (2020).mkv"
        valid_link.symlink_to(target)

        # Mocker _iter_managed_paths pour inclure un path qui leve OSError
        original_iter = cleanup_service._iter_managed_paths

        def patched_iter(vdir):
            yield from original_iter(vdir)
            # Creer un mock qui se comporte comme un symlink mais leve OSError sur resolve
            mock_path = MagicMock(spec=Path)
            mock_path.is_symlink.return_value = True
            mock_path.resolve.side_effect = OSError("Erreur I/O")
            mock_path.parent = action_dir
            yield mock_path

        with patch.object(cleanup_service, "_iter_managed_paths", side_effect=patched_iter):
            result = cleanup_service._scan_duplicate_symlinks(video_dir)

        # Pas de doublon puisque le mock est ignore
        assert len(result) == 0

    # ------------------------------------------------------------------
    # _is_under_series - ValueError quand path n'est pas relatif
    # ------------------------------------------------------------------

    def test_is_under_series_unrelated_path(self, cleanup_service):
        """_is_under_series retourne False si le chemin n'est pas relatif a video_dir."""
        result = cleanup_service._is_under_series(
            Path("/other/random/path"), Path("/video")
        )
        assert result is False

    # ------------------------------------------------------------------
    # _scan_empty_dirs - PermissionError
    # ------------------------------------------------------------------

    def test_scan_empty_dirs_permission_error(self, cleanup_service, temp_dirs):
        """PermissionError lors de iterdir() est gracieusement ignore."""
        video_dir = temp_dirs["video"]
        films_dir = video_dir / "Films"
        films_dir.mkdir(parents=True)

        # Creer un repertoire normal vide
        empty_dir = films_dir / "Vide"
        empty_dir.mkdir()

        # Creer un repertoire qui va lever PermissionError
        perm_dir = films_dir / "Protege"
        perm_dir.mkdir()

        # Mocker iterdir pour lever PermissionError sur le repertoire protege
        original_iterdir = Path.iterdir

        def patched_iterdir(self_path):
            if self_path == perm_dir:
                raise PermissionError("Acces refuse")
            return original_iterdir(self_path)

        with patch.object(Path, "iterdir", patched_iterdir):
            result = cleanup_service._scan_empty_dirs(video_dir)

        # Seul le repertoire vide accessible est detecte
        assert empty_dir in result
        assert perm_dir not in result

    # ------------------------------------------------------------------
    # repair_broken_symlinks - echec et exception
    # ------------------------------------------------------------------

    def test_repair_broken_symlinks_failure(
        self, cleanup_service, mock_repair_service,
    ):
        """repair_symlink retourne False -> incremente failed_repairs."""
        mock_repair_service.repair_symlink.return_value = False
        broken = [
            BrokenSymlinkInfo(
                symlink_path=Path("/video/Films/film.mkv"),
                original_target=Path("/storage/old.mkv"),
                best_candidate=Path("/storage/new.mkv"),
                candidate_score=95.0,
            ),
        ]

        result = cleanup_service.repair_broken_symlinks(broken, min_score=90.0)

        assert result.repaired_symlinks == 0
        assert result.failed_repairs == 1

    def test_repair_broken_symlinks_exception(
        self, cleanup_service, mock_repair_service,
    ):
        """Exception lors de repair_symlink -> incremente failed_repairs et ajoute erreur."""
        mock_repair_service.repair_symlink.side_effect = OSError("Erreur disque")
        broken = [
            BrokenSymlinkInfo(
                symlink_path=Path("/video/Films/film.mkv"),
                original_target=Path("/storage/old.mkv"),
                best_candidate=Path("/storage/new.mkv"),
                candidate_score=95.0,
            ),
        ]

        result = cleanup_service.repair_broken_symlinks(broken, min_score=90.0)

        assert result.repaired_symlinks == 0
        assert result.failed_repairs == 1
        assert len(result.errors) == 1
        assert "Reparation echouee" in result.errors[0]

    # ------------------------------------------------------------------
    # delete_broken_symlinks - exception non-FileNotFoundError
    # ------------------------------------------------------------------

    def test_delete_broken_symlinks_generic_exception(self, cleanup_service, tmp_path):
        """Exception autre que FileNotFoundError lors de la suppression."""
        broken_link = tmp_path / "video" / "Films" / "film.mkv"
        broken_link.parent.mkdir(parents=True)
        broken_link.symlink_to("/storage/inexistant.mkv")

        broken = [
            BrokenSymlinkInfo(
                symlink_path=broken_link,
                original_target=Path("/storage/inexistant.mkv"),
            ),
        ]

        # Mocker unlink pour lever PermissionError
        with patch.object(Path, "unlink", side_effect=PermissionError("Acces refuse")):
            result = cleanup_service.delete_broken_symlinks(broken)

        assert result.broken_symlinks_deleted == 0
        assert len(result.errors) == 1
        assert "Suppression echouee" in result.errors[0]

    # ------------------------------------------------------------------
    # fix_misplaced_symlinks - exception lors du deplacement
    # ------------------------------------------------------------------

    def test_fix_misplaced_symlinks_exception(self, cleanup_service, tmp_path):
        """Exception lors du rename -> ajoute erreur sans crash."""
        current_dir = tmp_path / "video" / "Films" / "Drame"
        current_dir.mkdir(parents=True)
        target = tmp_path / "storage" / "film.mkv"
        target.parent.mkdir(parents=True)
        target.touch()

        symlink = current_dir / "Film (2020).mkv"
        symlink.symlink_to(target)

        misplaced = [
            MisplacedSymlink(
                symlink_path=symlink,
                target_path=target,
                current_dir=current_dir,
                expected_dir=Path("/repertoire/impossible"),
            ),
        ]

        # Le rename echouera car le repertoire cible n'est pas creeable
        # (on mock mkdir pour qu'il passe, mais rename echoue)
        with patch.object(Path, "rename", side_effect=OSError("Deplacement impossible")):
            result = cleanup_service.fix_misplaced_symlinks(misplaced)

        assert result.moved_symlinks == 0
        assert len(result.errors) == 1
        assert "Deplacement echoue" in result.errors[0]

    # ------------------------------------------------------------------
    # subdivide_oversized_dirs - chemins d'erreur
    # ------------------------------------------------------------------

    def test_subdivide_in_range_move_exception(
        self, cleanup_service, mock_video_file_repo, tmp_path,
    ):
        """Exception lors du deplacement d'un item in-range -> erreur enregistree."""
        parent = tmp_path / "Films" / "Action"
        parent.mkdir(parents=True)

        link = parent / "Film (2020).mkv"
        link.symlink_to("/storage/film.mkv")

        dest = parent / "Fi-Fi"

        plans = [
            SubdivisionPlan(
                parent_dir=parent,
                current_count=1,
                max_allowed=1,
                ranges=[("Fi", "Fi")],
                items_to_move=[
                    (link, dest / "Film (2020).mkv"),
                ],
            ),
        ]

        # Mocker rename pour lever une exception
        with patch.object(Path, "rename", side_effect=OSError("Erreur deplacement")):
            result = cleanup_service.subdivide_oversized_dirs(plans)

        assert result.subdivisions_created == 1  # La subdivision est comptee
        assert result.symlinks_redistributed == 0
        assert len(result.errors) == 1
        assert "Deplacement echoue" in result.errors[0]

    def test_subdivide_plan_exception(
        self, cleanup_service, mock_video_file_repo, tmp_path,
    ):
        """Exception lors de la creation des repertoires -> erreur enregistree."""
        parent = tmp_path / "Films" / "Action"
        # Ne pas creer parent pour que mkdir echoue...
        # En fait mkdir avec parents=True ne devrait pas echouer.
        # On mock plutot mkdir pour lever une exception

        plans = [
            SubdivisionPlan(
                parent_dir=parent,
                current_count=1,
                max_allowed=1,
                ranges=[("Fi", "Fi")],
                items_to_move=[
                    (Path("/fake/source"), Path("/fake/dest/Film.mkv")),
                ],
            ),
        ]

        with patch.object(Path, "mkdir", side_effect=OSError("Creation impossible")):
            result = cleanup_service.subdivide_oversized_dirs(plans)

        assert result.subdivisions_created == 0
        assert len(result.errors) == 1
        assert "Subdivision echouee" in result.errors[0]

    def test_subdivide_out_of_range_move_exception(
        self, cleanup_service, mock_video_file_repo, tmp_path,
    ):
        """Exception lors du deplacement d'un item hors-plage -> erreur enregistree."""
        parent = tmp_path / "Films" / "Action" / "S-Z"
        parent.mkdir(parents=True)
        sibling = tmp_path / "Films" / "Action" / "G-L"
        sibling.mkdir()

        link_in = parent / "Super (2020).mkv"
        link_in.symlink_to("/storage/super.mkv")
        link_out = parent / "Jadotville (2016).mkv"
        link_out.symlink_to("/storage/jadotville.mkv")

        dest_sub = parent / "Sa-Zz"

        plans = [
            SubdivisionPlan(
                parent_dir=parent,
                current_count=2,
                max_allowed=1,
                ranges=[("Sa", "Zz")],
                items_to_move=[
                    (link_in, dest_sub / "Super (2020).mkv"),
                ],
                out_of_range_items=[
                    (link_out, sibling / "Jadotville (2016).mkv"),
                ],
            ),
        ]

        # Autoriser le rename pour l'item in-range, puis faire echouer pour le hors-plage
        original_rename = Path.rename
        call_count = [0]

        def selective_rename(self_path, target):
            call_count[0] += 1
            if call_count[0] <= 1:
                return original_rename(self_path, target)
            raise OSError("Deplacement hors-plage impossible")

        with patch.object(Path, "rename", selective_rename):
            result = cleanup_service.subdivide_oversized_dirs(plans)

        assert result.subdivisions_created == 1
        assert len(result.errors) == 1
        assert "Deplacement hors-plage echoue" in result.errors[0]
