"""Tests pour _refine_plans_destinations (affinage cross-plan)."""

from pathlib import Path

from src.services.cleanup import (
    SubdivisionPlan,
    _refine_plans_destinations,
)


# ============================================================================
# Phase 14 : Affinage cross-plan des destinations hors-plage
# ============================================================================


class TestRefinePlansDestinations:
    """Tests pour _refine_plans_destinations (affinage cross-plan)."""

    def test_refine_plans_cross_plan_destination(self, tmp_path):
        """El Chapo hors-plage de E-F -> C/ qui est subdivise en Ca-Ch/Ci-Cz/.

        La destination doit etre affinee vers C/Ca-Ch/El Chapo (2017).
        """
        grandparent = tmp_path / "Séries TV"
        parent_c = grandparent / "C"
        parent_ef = grandparent / "E-F"

        plan_c = SubdivisionPlan(
            parent_dir=parent_c,
            current_count=60,
            max_allowed=50,
            ranges=[("Ca", "Ch"), ("Ci", "Cz")],
            items_to_move=[],
        )

        plan_ef = SubdivisionPlan(
            parent_dir=parent_ef,
            current_count=55,
            max_allowed=50,
            ranges=[("Ea", "Fz")],
            items_to_move=[],
            out_of_range_items=[
                (parent_ef / "El Chapo (2017)", parent_c / "El Chapo (2017)"),
            ],
        )

        _refine_plans_destinations([plan_ef, plan_c])

        assert len(plan_ef.out_of_range_items) == 1
        source, dest = plan_ef.out_of_range_items[0]
        assert source == parent_ef / "El Chapo (2017)"
        assert dest == parent_c / "Ca-Ch" / "El Chapo (2017)"

    def test_refine_plans_la_servante_to_subdivided_s(self, tmp_path):
        """La Servante hors-plage de G-H -> S/ subdivise en Sa-So/Sp-Sz/.

        'La Servante' -> strip article -> 'Servante' -> cle 'SE' -> Sa-So.
        """
        grandparent = tmp_path / "Séries TV"
        parent_s = grandparent / "S"
        parent_gh = grandparent / "G-H"

        plan_s = SubdivisionPlan(
            parent_dir=parent_s,
            current_count=70,
            max_allowed=50,
            ranges=[("Sa", "So"), ("Sp", "Sz")],
            items_to_move=[],
        )

        plan_gh = SubdivisionPlan(
            parent_dir=parent_gh,
            current_count=55,
            max_allowed=50,
            ranges=[("Ga", "Hz")],
            items_to_move=[],
            out_of_range_items=[
                (parent_gh / "La Servante ecarlate (2017)", parent_s / "La Servante ecarlate (2017)"),
            ],
        )

        _refine_plans_destinations([plan_gh, plan_s])

        source, dest = plan_gh.out_of_range_items[0]
        assert dest == parent_s / "Sa-So" / "La Servante ecarlate (2017)"

    def test_refine_plans_no_subdivision_unchanged(self, tmp_path):
        """Si la destination n'a pas de plan de subdivision, la destination reste inchangee."""
        grandparent = tmp_path / "Séries TV"
        parent_b = grandparent / "B"
        parent_ef = grandparent / "E-F"

        # Pas de plan pour B
        plan_ef = SubdivisionPlan(
            parent_dir=parent_ef,
            current_count=55,
            max_allowed=50,
            ranges=[("Ea", "Fz")],
            items_to_move=[],
            out_of_range_items=[
                (parent_ef / "Das Boot (2018)", parent_b / "Das Boot (2018)"),
            ],
        )

        _refine_plans_destinations([plan_ef])

        source, dest = plan_ef.out_of_range_items[0]
        assert dest == parent_b / "Das Boot (2018)"

    def test_refine_plans_no_matching_range(self, tmp_path):
        """Si aucune plage du plan cible ne correspond a la cle, destination inchangee."""
        grandparent = tmp_path / "Séries TV"
        parent_c = grandparent / "C"
        parent_ef = grandparent / "E-F"

        # Plan C ne couvre que Ca-Cb et Cc-Cd (pas les cles CH+)
        plan_c = SubdivisionPlan(
            parent_dir=parent_c,
            current_count=60,
            max_allowed=50,
            ranges=[("Ca", "Cb"), ("Cc", "Cd")],
            items_to_move=[],
        )

        plan_ef = SubdivisionPlan(
            parent_dir=parent_ef,
            current_count=55,
            max_allowed=50,
            ranges=[("Ea", "Fz")],
            items_to_move=[],
            out_of_range_items=[
                (parent_ef / "El Chapo (2017)", parent_c / "El Chapo (2017)"),
            ],
        )

        _refine_plans_destinations([plan_ef, plan_c])

        source, dest = plan_ef.out_of_range_items[0]
        # Cle "CH" ne correspond a aucune plage -> destination inchangee
        assert dest == parent_c / "El Chapo (2017)"

    def test_scan_oversized_dirs_calls_refine(
        self, cleanup_service, tmp_path,
    ):
        """Verifier que _scan_oversized_dirs retourne des plans avec destinations deja affinees."""
        video_dir = tmp_path / "video"
        video_dir.mkdir()
        series_dir = video_dir / "Séries"
        series_dir.mkdir()
        grandparent = series_dir / "Séries TV"
        grandparent.mkdir()

        # Creer C/ avec >3 items couvrant Ca-Ch et Ci-Cz (on utilise max_per_dir=3)
        parent_c = grandparent / "C"
        parent_c.mkdir()
        for name in [
            "Californication (2007)", "Castle (2009)", "Charmed (1998)",
            "Chicago Fire (2012)", "Cobra Kai (2018)", "CSI (2000)",
        ]:
            d = parent_c / name
            d.mkdir()

        # Creer E-F/ avec >3 items dont El Chapo hors plage
        parent_ef = grandparent / "E-F"
        parent_ef.mkdir()
        for name in ["Echo (2020)", "Empire (2015)", "Fargo (2014)", "El Chapo (2017)"]:
            d = parent_ef / name
            d.mkdir()

        plans = cleanup_service._scan_oversized_dirs(video_dir, max_per_dir=3)

        # On doit avoir 2 plans (C et E-F)
        assert len(plans) == 2

        # Trouver le plan E-F
        plan_ef = next(p for p in plans if p.parent_dir == parent_ef)

        # Trouver le plan C pour verifier ses ranges
        plan_c = next(p for p in plans if p.parent_dir == parent_c)

        # Verifier que le plan C couvre bien la cle CH
        has_ch_range = any(
            start.upper() <= "CH" <= end.upper()
            for start, end in plan_c.ranges
        )
        assert has_ch_range, (
            f"Le plan C devrait avoir une plage couvrant CH, "
            f"ranges actuelles: {plan_c.ranges}"
        )

        # El Chapo doit etre hors plage et sa destination doit etre affinee
        # vers une subdivision de C (pas juste C/)
        el_chapo_items = [
            (s, d) for s, d in plan_ef.out_of_range_items
            if "El Chapo" in s.name
        ]
        assert el_chapo_items, "El Chapo devrait etre hors plage de E-F"
        source, dest = el_chapo_items[0]
        # La destination doit pointer vers une subdivision de C/
        # (ex: C/Ca-Ch/El Chapo) et non C/El Chapo
        assert dest.parent.parent == parent_c, (
            f"El Chapo devrait etre dans une subdivision de C/, "
            f"pas dans {dest.parent}"
        )
