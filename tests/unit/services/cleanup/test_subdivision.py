"""Tests pour l'algorithme de subdivision et ses helpers."""

from pathlib import Path

from src.services.cleanup import (
    SubdivisionPlan,
    _normalize_sort_key,
    _parse_parent_range,
)


# ============================================================================
# Phase 5 : Subdivision
# ============================================================================


class TestCalculateSubdivisionRanges:
    """Tests pour _calculate_subdivision_ranges."""

    def test_calculate_ranges_60_items(self, cleanup_service, tmp_path):
        """60 items -> 2 plages (50+10)."""
        parent = tmp_path / "Films" / "Action"
        parent.mkdir(parents=True)

        # Creer 60 symlinks avec des noms tries
        names = []
        for i in range(60):
            letter = chr(ord("A") + (i // 3))  # A, A, A, B, B, B, ...
            suffix = chr(ord("a") + (i % 3))
            name = f"{letter}{suffix}_Film_{i:03d} (2020).mkv"
            names.append(name)

        for name in sorted(names):
            link = parent / name
            link.symlink_to(f"/storage/{name}")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        assert plan.parent_dir == parent
        assert plan.current_count == 60
        assert len(plan.ranges) == 2
        assert len(plan.items_to_move) == 60

    def test_calculate_ranges_with_articles(self, cleanup_service, tmp_path):
        """'Le Parrain' trie sous P, pas sous L."""
        parent = tmp_path / "Films" / "Drame"
        parent.mkdir(parents=True)

        # Creer quelques symlinks dont un avec article
        (parent / "Le Parrain (1972).mkv").symlink_to("/storage/parrain.mkv")
        (parent / "Alien (1979).mkv").symlink_to("/storage/alien.mkv")
        (parent / "Blade Runner (1982).mkv").symlink_to("/storage/blade.mkv")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=2)

        # Verifier que "Le Parrain" est trie sous P
        # Alien (A), Blade Runner (B) dans le premier groupe
        # Le Parrain (P) dans le deuxieme groupe
        assert len(plan.ranges) == 2

        # Trouver le mouvement pour Le Parrain
        parrain_moves = [
            (src, dst) for src, dst in plan.items_to_move
            if "Le Parrain" in src.name
        ]
        assert len(parrain_moves) == 1
        # Le Parrain devrait etre dans un repertoire different de Alien/Blade Runner
        alien_moves = [
            (src, dst) for src, dst in plan.items_to_move
            if "Alien" in src.name
        ]
        assert parrain_moves[0][1].parent != alien_moves[0][1].parent

    def test_subdivide_creates_dirs_and_moves(
        self, cleanup_service, mock_video_file_repo, tmp_path,
    ):
        """subdivide_oversized_dirs cree les sous-repertoires et deplace."""
        parent = tmp_path / "Films" / "Action"
        parent.mkdir(parents=True)

        # Creer des symlinks
        link1 = parent / "Alpha (2020).mkv"
        link1.symlink_to("/storage/alpha.mkv")
        link2 = parent / "Zeta (2020).mkv"
        link2.symlink_to("/storage/zeta.mkv")

        dest_a = parent / "Al-Al"
        dest_z = parent / "Ze-Ze"

        plans = [
            SubdivisionPlan(
                parent_dir=parent,
                current_count=2,
                max_allowed=1,
                ranges=[("Al", "Al"), ("Ze", "Ze")],
                items_to_move=[
                    (link1, dest_a / "Alpha (2020).mkv"),
                    (link2, dest_z / "Zeta (2020).mkv"),
                ],
            ),
        ]

        result = cleanup_service.subdivide_oversized_dirs(plans)

        assert result.subdivisions_created == 1
        assert result.symlinks_redistributed == 2
        assert (dest_a / "Alpha (2020).mkv").is_symlink()
        assert (dest_z / "Zeta (2020).mkv").is_symlink()

    def test_subdivide_moves_out_of_range_items(
        self, cleanup_service, mock_video_file_repo, tmp_path,
    ):
        """subdivide_oversized_dirs deplace aussi les items hors plage."""
        grandparent = tmp_path / "Films" / "Action"
        parent = grandparent / "S-Z"
        parent.mkdir(parents=True)
        sibling = grandparent / "G-L"
        sibling.mkdir()

        # Item in-range
        link_in = parent / "Super (2020).mkv"
        link_in.symlink_to("/storage/super.mkv")
        # Item hors-plage
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

        result = cleanup_service.subdivide_oversized_dirs(plans)

        # L'item in-range est deplace dans la subdivision
        assert (dest_sub / "Super (2020).mkv").is_symlink()
        # L'item hors-plage est deplace vers le frere
        assert (sibling / "Jadotville (2016).mkv").is_symlink()
        assert not link_out.exists()
        # La BDD est mise a jour pour les deux
        assert mock_video_file_repo.update_symlink_path.call_count == 2

    def test_subdivide_updates_db(
        self, cleanup_service, mock_video_file_repo, tmp_path,
    ):
        """subdivide_oversized_dirs met a jour symlink_path en BDD."""
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

        cleanup_service.subdivide_oversized_dirs(plans)

        mock_video_file_repo.update_symlink_path.assert_called_once_with(
            link, dest / "Film (2020).mkv",
        )

    def test_subdivide_out_of_range_lands_in_new_subdivision(
        self, cleanup_service, mock_video_file_repo, tmp_path,
    ):
        """Bug 9 : les hors-plage doivent atterrir dans les nouvelles subdivisions.

        Scenario : E-F et C sont tous les deux surcharges.
        El Chapo est hors plage de E-F (cle CH -> C).
        C est subdivise en Ca-Ch et Ci-Cz.
        El Chapo doit finir dans C/Ca-Ch/, pas a la racine de C/.
        """
        grandparent = tmp_path / "Séries" / "Séries TV"
        grandparent.mkdir(parents=True)
        (grandparent / "#").mkdir()

        # Parent E-F : contient El Chapo (hors plage)
        parent_ef = grandparent / "E-F"
        parent_ef.mkdir()
        link_echo = parent_ef / "Echo (2020)"
        link_echo.mkdir()
        link_el_chapo = parent_ef / "El Chapo (2017)"
        link_el_chapo.mkdir()

        # Parent C : surcharge, sera subdivise
        parent_c = grandparent / "C"
        parent_c.mkdir()
        link_cal = parent_c / "Californication (2007)"
        link_cal.mkdir()
        link_csi = parent_c / "CSI Miami (2002)"
        link_csi.mkdir()

        # Plan pour C : subdivise en Ca-Ch et Ci-Cz
        dest_ca_ch = parent_c / "Ca-Ch"
        dest_ci_cz = parent_c / "Ci-Cz"

        plan_c = SubdivisionPlan(
            parent_dir=parent_c,
            current_count=2,
            max_allowed=1,
            ranges=[("Ca", "Ch"), ("Ci", "Cz")],
            items_to_move=[
                (link_cal, dest_ca_ch / "Californication (2007)"),
                (link_csi, dest_ci_cz / "CSI Miami (2002)"),
            ],
        )

        # Plan pour E-F : El Chapo hors plage -> destination C/
        dest_ea = parent_ef / "Ea-Ea"
        plan_ef = SubdivisionPlan(
            parent_dir=parent_ef,
            current_count=2,
            max_allowed=1,
            ranges=[("Ea", "Ea")],
            items_to_move=[
                (link_echo, dest_ea / "Echo (2020)"),
            ],
            out_of_range_items=[
                (link_el_chapo, parent_c / "El Chapo (2017)"),
            ],
        )

        # L'ordre des plans ne doit pas importer :
        # E-F est traite avant C, mais El Chapo doit quand meme
        # atterrir dans la subdivision de C
        result = cleanup_service.subdivide_oversized_dirs([plan_ef, plan_c])

        # El Chapo doit etre dans C/Ca-Ch/, pas dans C/
        assert (dest_ca_ch / "El Chapo (2017)").exists(), (
            "El Chapo devrait etre dans C/Ca-Ch/"
        )
        assert not (parent_c / "El Chapo (2017)").exists(), (
            "El Chapo ne devrait PAS etre a la racine de C/"
        )

    def test_subdivide_out_of_range_no_subdivision_stays_in_sibling(
        self, cleanup_service, mock_video_file_repo, tmp_path,
    ):
        """Si le sibling n'a pas ete subdivise, le hors-plage reste a sa racine."""
        grandparent = tmp_path / "Films" / "Action"
        parent = grandparent / "S-Z"
        parent.mkdir(parents=True)
        sibling = grandparent / "G-L"
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

        result = cleanup_service.subdivide_oversized_dirs(plans)

        # Sibling G-L non subdivise -> Jadotville a la racine
        assert (sibling / "Jadotville (2016).mkv").is_symlink()
        assert not link_out.exists()


# ============================================================================
# Phase 10 : Helpers subdivision (_normalize_sort_key, _parse_parent_range)
# ============================================================================


class TestNormalizeSortKey:
    """Tests pour _normalize_sort_key (suppression des diacritiques)."""

    def test_accent_aigu(self):
        """'Eternel' (accent aigu) -> 'Eternel'."""
        assert _normalize_sort_key("Éternel") == "Eternel"

    def test_accent_grave(self):
        """'A' (accent grave) -> 'A'."""
        assert _normalize_sort_key("À bout de souffle") == "A bout de souffle"

    def test_cedille(self):
        """'Français' (cedille) -> 'Francais'."""
        assert _normalize_sort_key("Français") == "Francais"

    def test_trema(self):
        """'Noël' (trema) -> 'Noel'."""
        assert _normalize_sort_key("Noël") == "Noel"

    def test_ascii_inchange(self):
        """Un texte ASCII reste inchange."""
        assert _normalize_sort_key("Matrix") == "Matrix"


class TestParseParentRange:
    """Tests pour _parse_parent_range (parsing du nom de repertoire en plage)."""

    def test_lettre_simple(self):
        """Lettre simple 'C' -> ('CA', 'CZ')."""
        assert _parse_parent_range("C") == ("CA", "CZ")

    def test_plage_simple(self):
        """Plage 'E-F' -> ('EA', 'FZ')."""
        assert _parse_parent_range("E-F") == ("EA", "FZ")

    def test_plage_large(self):
        """Plage 'S-Z' -> ('SA', 'ZZ')."""
        assert _parse_parent_range("S-Z") == ("SA", "ZZ")

    def test_plage_prefixe(self):
        """Plage avec prefixe 'L-Ma' -> ('LA', 'MA')."""
        assert _parse_parent_range("L-Ma") == ("LA", "MA")

    def test_non_plage(self):
        """Nom de genre 'Action' -> ('AA', 'ZZ') (tout accepter)."""
        assert _parse_parent_range("Action") == ("AA", "ZZ")


# ============================================================================
# Phase 11 : Algorithme de subdivision corrige (7 bugs)
# ============================================================================


class TestSubdivisionAlgorithmBugs:
    """Tests pour les 7 bugs identifies dans _calculate_subdivision_ranges."""

    def test_bug1_balanced_splits(self, cleanup_service, tmp_path):
        """Bug 1 : 59 items -> 2 groupes equilibres (~30+29), pas 50+9."""
        parent = tmp_path / "Films" / "Action"
        parent.mkdir(parents=True)

        for i in range(59):
            letter = chr(ord("A") + (i * 26 // 59))
            suffix = chr(ord("a") + (i % 26))
            name = f"{letter}{suffix}_Film_{i:03d} (2020).mkv"
            (parent / name).symlink_to(f"/storage/{name}")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        assert len(plan.ranges) == 2
        # Compter les items par plage
        counts = []
        for start, end in plan.ranges:
            label = f"{start}-{end}"
            count = sum(
                1 for _, dst in plan.items_to_move
                if dst.parent.name == label
            )
            counts.append(count)
        # Chaque groupe devrait etre ~29-30, pas 50+9
        assert all(c <= 50 for c in counts)
        assert max(counts) - min(counts) <= 1  # equilibre

    def test_bug2_ranges_cover_parent(self, cleanup_service, tmp_path):
        """Bug 2 : parent S-Z -> premier groupe commence a Sa, dernier finit a Zz."""
        parent = tmp_path / "Films" / "Action" / "S-Z"
        parent.mkdir(parents=True)

        # Creer 55 items dans la plage S-Z
        names = []
        for i, letter in enumerate("STUVWXYZ"):
            for j in range(7):
                suffix = chr(ord("a") + j)
                name = f"{letter}{suffix}_Film_{i*7+j:03d} (2020).mkv"
                names.append(name)
        for name in names[:55]:
            (parent / name).symlink_to(f"/storage/{name}")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        assert len(plan.ranges) >= 2
        # Premier groupe commence a Sa
        assert plan.ranges[0][0].upper()[:1] == "S"
        # Dernier groupe finit a Zz
        assert plan.ranges[-1][1].upper()[:1] == "Z"

    def test_bug3_out_of_range_moved_to_sibling(self, cleanup_service, tmp_path):
        """Bug 3 : Jadotville (J) dans S-Z -> deplace vers le repertoire frere J ou contenant J."""
        grandparent = tmp_path / "Films" / "Action"
        parent = grandparent / "S-Z"
        parent.mkdir(parents=True)
        # Creer le repertoire frere qui devrait accueillir Jadotville
        sibling_j = grandparent / "G-L"
        sibling_j.mkdir()

        # Items dans la plage
        for i in range(55):
            letter = chr(ord("S") + (i * 8 // 55))
            suffix = chr(ord("a") + (i % 26))
            name = f"{letter}{suffix}_Film_{i:03d} (2020).mkv"
            (parent / name).symlink_to(f"/storage/{name}")

        # Item hors plage (J < S)
        (parent / "Jadotville (2016).mkv").symlink_to("/storage/jadotville.mkv")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        # Jadotville doit etre dans out_of_range_items avec une destination
        out_sources = [src.name for src, _ in plan.out_of_range_items]
        assert "Jadotville (2016).mkv" in out_sources

        # La destination doit etre dans le repertoire frere G-L
        jadotville_move = [
            (src, dst) for src, dst in plan.out_of_range_items
            if src.name == "Jadotville (2016).mkv"
        ]
        assert len(jadotville_move) == 1
        assert jadotville_move[0][1].parent == sibling_j

        # Jadotville ne doit PAS etre dans items_to_move
        moved_names = [src.name for src, _ in plan.items_to_move]
        assert "Jadotville (2016).mkv" not in moved_names

    def test_bug3b_el_chapo_out_of_range_ef(self, cleanup_service, tmp_path):
        """Bug 3b : El Chapo (article 'el' strip -> Chapo=CH) exclu de E-F, deplace vers C-D."""
        grandparent = tmp_path / "Films" / "Action"
        parent = grandparent / "E-F"
        parent.mkdir(parents=True)
        # Repertoire frere pour C
        sibling_cd = grandparent / "C-D"
        sibling_cd.mkdir()

        # Items dans la plage E-F
        for i in range(55):
            letter = "E" if i < 28 else "F"
            suffix = chr(ord("a") + (i % 26))
            name = f"{letter}{suffix}_Film_{i:03d} (2020).mkv"
            (parent / name).symlink_to(f"/storage/{name}")

        # El Chapo : article "el" strip -> cle "CH", hors plage E-F
        (parent / "El Chapo (2017).mkv").symlink_to("/storage/elchapo.mkv")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        out_sources = [src.name for src, _ in plan.out_of_range_items]
        assert "El Chapo (2017).mkv" in out_sources
        # Destination dans C-D
        chapo_move = [
            (src, dst) for src, dst in plan.out_of_range_items
            if src.name == "El Chapo (2017).mkv"
        ]
        assert chapo_move[0][1].parent == sibling_cd

    def test_bug3c_das_boot_out_of_range_d(self, cleanup_service, tmp_path):
        """Bug 3c : das Boot (article 'das' strip -> Boot=BO) exclu de D, deplace vers B ou A-C."""
        grandparent = tmp_path / "Films" / "Guerre"
        parent = grandparent / "D"
        parent.mkdir(parents=True)
        # Repertoire frere pour B
        sibling_b = grandparent / "A-C"
        sibling_b.mkdir()

        # Items dans la plage D
        for i in range(55):
            suffix = chr(ord("a") + (i % 26))
            name = f"D{suffix}_Film_{i:03d} (2020).mkv"
            (parent / name).symlink_to(f"/storage/{name}")

        # das Boot : article "das" strip -> cle "BO", hors plage D
        (parent / "Das Boot (1981).mkv").symlink_to("/storage/dasboot.mkv")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        out_sources = [src.name for src, _ in plan.out_of_range_items]
        assert "Das Boot (1981).mkv" in out_sources
        # Destination dans A-C
        boot_move = [
            (src, dst) for src, dst in plan.out_of_range_items
            if src.name == "Das Boot (1981).mkv"
        ]
        assert boot_move[0][1].parent == sibling_b

    def test_out_of_range_no_sibling_stays_in_grandparent(self, cleanup_service, tmp_path):
        """Si aucun frere ne correspond, l'item va dans le grand-parent."""
        grandparent = tmp_path / "Films" / "Action"
        parent = grandparent / "S-Z"
        parent.mkdir(parents=True)
        # Pas de repertoire frere pour J

        for i in range(55):
            letter = chr(ord("S") + (i * 8 // 55))
            suffix = chr(ord("a") + (i % 26))
            name = f"{letter}{suffix}_Film_{i:03d} (2020).mkv"
            (parent / name).symlink_to(f"/storage/{name}")

        (parent / "Jadotville (2016).mkv").symlink_to("/storage/jadotville.mkv")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        jadotville_move = [
            (src, dst) for src, dst in plan.out_of_range_items
            if src.name == "Jadotville (2016).mkv"
        ]
        assert len(jadotville_move) == 1
        # Pas de frere -> destination dans le grand-parent
        assert jadotville_move[0][1].parent == grandparent

    def test_bug4_no_overlap(self, cleanup_service, tmp_path):
        """Bug 4 : pas de chevauchement entre plages."""
        parent = tmp_path / "Films" / "Action"
        parent.mkdir(parents=True)

        for i in range(120):
            letter = chr(ord("A") + (i * 26 // 120))
            suffix = chr(ord("a") + (i % 26))
            name = f"{letter}{suffix}_Film_{i:03d} (2020).mkv"
            (parent / name).symlink_to(f"/storage/{name}")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        assert len(plan.ranges) >= 2
        # Verifier qu'il n'y a pas de chevauchement
        for i in range(len(plan.ranges) - 1):
            end_current = plan.ranges[i][1].upper()
            start_next = plan.ranges[i + 1][0].upper()
            # La fin d'un groupe doit etre strictement avant le debut du suivant
            assert end_current < start_next, (
                f"Chevauchement: {plan.ranges[i]} et {plan.ranges[i+1]}"
            )

    def test_bug5_accents_sorted_correctly(self, cleanup_service, tmp_path):
        """Bug 5 : Eternel (E accent) trie entre D et F, pas apres Z."""
        parent = tmp_path / "Films" / "Drame"
        parent.mkdir(parents=True)

        (parent / "Damien (2020).mkv").symlink_to("/storage/d.mkv")
        (parent / "Éternel (2020).mkv").symlink_to("/storage/e.mkv")
        (parent / "Fatal (2020).mkv").symlink_to("/storage/f.mkv")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=2)

        # Eternel doit etre trie entre Damien et Fatal
        eternel_moves = [
            (src, dst) for src, dst in plan.items_to_move
            if "ternel" in src.name
        ]
        damien_moves = [
            (src, dst) for src, dst in plan.items_to_move
            if "Damien" in src.name
        ]
        assert len(eternel_moves) == 1
        assert len(damien_moves) == 1
        # Damien et Eternel devraient etre dans le meme groupe (D et E consecutifs)
        assert damien_moves[0][1].parent == eternel_moves[0][1].parent

    def test_bug6_de_article_stripped(self, cleanup_service, tmp_path):
        """Bug 6 : 'De parfaites demoiselles' dans P-Q -> in-range (cle PA)."""
        parent = tmp_path / "Films" / "Drame" / "P-Q"
        parent.mkdir(parents=True)

        # Items dans la plage P-Q
        for i in range(55):
            letter = "P" if i < 28 else "Q"
            suffix = chr(ord("a") + (i % 26))
            name = f"{letter}{suffix}_Film_{i:03d} (2020).mkv"
            (parent / name).symlink_to(f"/storage/{name}")

        # "De parfaites demoiselles" -> article "de" strip -> "parfaites" -> cle "PA"
        (parent / "De parfaites demoiselles (2020).mkv").symlink_to(
            "/storage/deparfaites.mkv"
        )

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        # "De parfaites demoiselles" doit etre in-range (PA est dans P-Q)
        moved_names = [src.name for src, _ in plan.items_to_move]
        assert "De parfaites demoiselles (2020).mkv" in moved_names
        # Et pas dans out_of_range
        out_names = [src.name for src, _ in plan.out_of_range_items]
        assert "De parfaites demoiselles (2020).mkv" not in out_names

    def test_cb_strike_dots_stripped_in_range_c(self, cleanup_service, tmp_path):
        """C.B. Strike : les points sont ignores, cle 'CB' dans plage C (CA-CZ)."""
        parent = tmp_path / "Séries" / "Séries TV" / "C"
        parent.mkdir(parents=True)

        # Items dans la plage C
        for i in range(52):
            suffix = chr(ord("a") + (i % 26))
            name = f"C{suffix}_Serie_{i:03d} (2020)"
            (parent / name).mkdir()

        # C.B. Strike -> sans points -> "CB Strike" -> cle "CB" -> in range
        (parent / "C.B. Strike (2017)").mkdir()

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        # C.B. Strike doit etre in-range (pas dans out_of_range)
        out_names = [src.name for src, _ in plan.out_of_range_items]
        assert "C.B. Strike (2017)" not in out_names
        # Et present dans items_to_move
        moved_names = [src.name for src, _ in plan.items_to_move]
        assert "C.B. Strike (2017)" in moved_names

    def test_au_service_in_range_s(self, cleanup_service, tmp_path):
        """'Au service de la France' : article 'au' strip -> cle 'SE' dans S."""
        parent = tmp_path / "Séries" / "Séries TV" / "S"
        parent.mkdir(parents=True)

        # Items dans la plage S
        for i in range(52):
            suffix = chr(ord("a") + (i % 26))
            name = f"S{suffix}_Serie_{i:03d} (2020)"
            (parent / name).mkdir()

        # "Au service de la France" -> strip "au" -> "service de la France"
        # -> strip premier mot seulement -> cle "SE" -> in range S (SA-SZ)
        (parent / "Au service de la France").mkdir()
        (parent / "Au service du passé (2022)").mkdir()

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        out_names = [src.name for src, _ in plan.out_of_range_items]
        assert "Au service de la France" not in out_names
        assert "Au service du passé (2022)" not in out_names
        moved_names = [src.name for src, _ in plan.items_to_move]
        assert "Au service de la France" in moved_names
        assert "Au service du passé (2022)" in moved_names

    def test_bug7_always_two_bounds(self, cleanup_service, tmp_path):
        """Bug 7 : toujours format 'Start-End' (jamais borne unique)."""
        parent = tmp_path / "Films" / "Action"
        parent.mkdir(parents=True)

        # Items tous avec la meme premiere lettre -> pourrait donner "Cr" seul
        for i in range(55):
            suffix = chr(ord("a") + (i % 26))
            name = f"C{suffix}_Film_{i:03d} (2020).mkv"
            (parent / name).symlink_to(f"/storage/{name}")

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        # Chaque plage doit avoir 2 bornes (format Start-End)
        for start, end in plan.ranges:
            assert start != end or len(start) >= 2, (
                f"Borne unique detectee: {start}"
            )
            # Les destinations doivent utiliser le format "Start-End"
            for _, dst in plan.items_to_move:
                dir_name = dst.parent.name
                assert "-" in dir_name, f"Format sans tiret: {dir_name}"

    def test_bug8_hash_sibling_does_not_capture_all(self, cleanup_service, tmp_path):
        """Bug 8 : le repertoire '#' ne doit pas capturer les items alphabetiques hors plage.

        Le repertoire '#' (non-alphabetique) retourne la plage ("AA", "ZZ") via
        _parse_parent_range, et comme '#' trie avant les lettres, il est le premier
        sibling teste -> il capture tout. Les items doivent aller vers le bon frere
        alphabetique.
        """
        grandparent = tmp_path / "Séries" / "Séries TV"
        grandparent.mkdir(parents=True)

        # Creer les repertoires freres incluant '#'
        (grandparent / "#").mkdir()
        sibling_cd = grandparent / "C-D"
        sibling_cd.mkdir()
        sibling_ik = grandparent / "I-K"
        sibling_ik.mkdir()
        sibling_b = grandparent / "B"
        sibling_b.mkdir()
        sibling_s = grandparent / "S"
        sibling_s.mkdir()

        # Le parent surcharge E-F
        parent = grandparent / "E-F"
        parent.mkdir()

        # Items dans la plage E-F
        for i in range(55):
            letter = "E" if i < 28 else "F"
            suffix = chr(ord("a") + (i % 26))
            name = f"{letter}{suffix}_Serie_{i:03d} (2020)"
            (parent / name).mkdir()

        # Items hors plage avec articles
        (parent / "El Chapo (2017)").mkdir()       # El strip -> CH -> C-D
        (parent / "El jardinero (2025)").mkdir()    # El strip -> JA -> I-K

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        # El Chapo doit aller vers C-D, PAS vers #
        chapo_move = [
            (src, dst) for src, dst in plan.out_of_range_items
            if "El Chapo" in src.name
        ]
        assert len(chapo_move) == 1
        assert chapo_move[0][1].parent == sibling_cd, (
            f"El Chapo devrait aller dans C-D, pas {chapo_move[0][1].parent.name}"
        )

        # El jardinero doit aller vers I-K, PAS vers #
        jardinero_move = [
            (src, dst) for src, dst in plan.out_of_range_items
            if "El jardinero" in src.name
        ]
        assert len(jardinero_move) == 1
        assert jardinero_move[0][1].parent == sibling_ik, (
            f"El jardinero devrait aller dans I-K, pas {jardinero_move[0][1].parent.name}"
        )

    def test_bug8b_hash_sibling_all_article_cases(self, cleanup_service, tmp_path):
        """Bug 8b : tous les cas d'articles avec # present comme frere."""
        grandparent = tmp_path / "Séries" / "Séries TV"
        grandparent.mkdir(parents=True)

        # Creer les repertoires freres incluant '#'
        (grandparent / "#").mkdir()
        sibling_b = grandparent / "A-B"
        sibling_b.mkdir()
        sibling_gh = grandparent / "G-H"
        sibling_gh.mkdir()
        sibling_mz = grandparent / "Me-Mz"
        sibling_mz.mkdir()
        sibling_s = grandparent / "S"
        sibling_s.mkdir()

        # Le parent surcharge D
        parent = grandparent / "D"
        parent.mkdir()

        for i in range(55):
            suffix = chr(ord("a") + (i % 26))
            name = f"D{suffix}_Serie_{i:03d} (2020)"
            (parent / name).mkdir()

        # Cas varies d'articles
        (parent / "Das Boot (1981)").mkdir()             # Das strip -> BO -> A-B
        (parent / "La Servante écarlate (2017)").mkdir()  # La strip -> SE -> S
        (parent / "Los mil días de allende").mkdir()      # Los strip -> MI -> Me-Mz

        plan = cleanup_service._calculate_subdivision_ranges(parent, max_per_subdir=50)

        # Das Boot -> A-B
        boot_move = [
            (src, dst) for src, dst in plan.out_of_range_items
            if "Das Boot" in src.name
        ]
        assert len(boot_move) == 1
        assert boot_move[0][1].parent == sibling_b, (
            f"Das Boot devrait aller dans A-B, pas {boot_move[0][1].parent.name}"
        )

        # La Servante -> S
        servante_move = [
            (src, dst) for src, dst in plan.out_of_range_items
            if "Servante" in src.name
        ]
        assert len(servante_move) == 1
        assert servante_move[0][1].parent == sibling_s, (
            f"La Servante devrait aller dans S, pas {servante_move[0][1].parent.name}"
        )

        # Los mil dias -> Me-Mz (Los strip -> mil -> MI)
        allende_move = [
            (src, dst) for src, dst in plan.out_of_range_items
            if "allende" in src.name
        ]
        assert len(allende_move) == 1
        assert allende_move[0][1].parent == sibling_mz, (
            f"Los mil dias devrait aller dans Me-Mz, pas {allende_move[0][1].parent.name}"
        )
