"""
Tests des routes sandbox de la page maintenance.

Vérifient que la vue expose le statut d'audit et que la suppression refuse
côté serveur les fichiers dont aucun remplaçant n'existe.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.services.sandbox_audit import MISSING, REPLACED, UNKNOWN
from src.services.sandbox_service import (
    REPLACED_VERSION,
    DeletionReport,
    SandboxedFile,
)
from src.web.routes.maintenance import _sandbox_context, sandbox_delete


def _fichier(nom: str, statut: str, taille: int = 1000, partage: bool = False):
    from datetime import datetime

    return SandboxedFile(
        path=Path("/media/NAS64/.sandbox/Series") / nom,
        name=nom,
        size=taille,
        modified=datetime(2026, 8, 10),
        original_path=Path("/media/NAS64/Series") / nom,
        origin=REPLACED_VERSION,
        status=statut,
        shares_inode=partage,
        reclaimable_bytes=0 if partage else taille,
    )


class TestContexteAffichage:
    """Le tableau doit exposer le statut et l'espace réellement récupérable."""

    def test_compteurs_et_volumes(self):
        ctx = _sandbox_context(
            [
                _fichier("a.mkv", REPLACED, 2_000_000_000),
                _fichier("b.mkv", REPLACED, 1_000_000_000, partage=True),
                _fichier("c.mkv", MISSING, 500_000_000),
                _fichier("d.json", UNKNOWN, 1000),
            ]
        )

        assert ctx["sandbox_count"] == 4
        assert ctx["sandbox_purgeable_count"] == 2
        assert ctx["sandbox_blocked_count"] == 2
        # Le hardlink ne compte pas dans l'espace récupérable
        assert ctx["sandbox_reclaimable"] == "1.86 Go"

    def test_badges_par_statut(self):
        ctx = _sandbox_context(
            [_fichier("a.mkv", REPLACED), _fichier("b.mkv", MISSING)]
        )
        par_nom = {i["name"]: i for i in ctx["sandbox_items"]}

        assert par_nom["a.mkv"]["purgeable"] is True
        assert par_nom["a.mkv"]["status_class"] == "sandbox-badge-ok"
        assert par_nom["b.mkv"]["purgeable"] is False
        assert par_nom["b.mkv"]["status_label"] == "Seule copie"

    def test_hardlink_signale(self):
        ctx = _sandbox_context([_fichier("a.mkv", REPLACED, 1000, partage=True)])
        assert ctx["sandbox_items"][0]["shares_inode"] is True
        assert ctx["sandbox_items"][0]["reclaimable_bytes"] == 0


class TestRouteSuppression:
    """La route doit relayer le refus serveur et le rapporter à l'utilisateur."""

    def _requete(self, hote: str, form: dict, service):
        request = MagicMock()
        request.client.host = hote
        request.app.state.container = MagicMock()

        donnees = MagicMock()
        donnees.getlist.return_value = form.get("selected", [])
        donnees.get.side_effect = lambda k, d=None: form.get(k, d)

        async def _form():
            return donnees

        request.form = _form
        return request

    @pytest.mark.asyncio
    async def test_refus_hors_machine_maitre(self, monkeypatch):
        request = self._requete("192.168.1.50", {"selected": ["/x.mkv"]}, None)
        reponse = await sandbox_delete(request)
        assert reponse.status_code == 403

    @pytest.mark.asyncio
    async def test_rapporte_les_fichiers_epargnes(self, monkeypatch):
        import src.web.routes.maintenance as mod

        epargne = Path("/media/NAS64/.sandbox/Series/seule-copie.mkv")
        service = MagicMock()
        service.delete_files.return_value = DeletionReport(
            deleted=1,
            refused=[(epargne, "aucun remplaçant en bibliothèque")],
            reclaimed_bytes=2_000_000_000,
        )
        service.list_sandboxed.return_value = [_fichier("reste.mkv", MISSING)]
        monkeypatch.setattr(mod, "_get_sandbox_service", lambda *a, **k: service)

        request = self._requete(
            "127.0.0.1", {"selected": ["/a.mkv", str(epargne)]}, service
        )
        reponse = await sandbox_delete(request)
        corps = reponse.body.decode()

        assert "1 fichier(s) supprimé(s)" in corps
        assert "1.86 Go libéré(s)" in corps
        assert "aucun remplaçant en bibliothèque" in corps

    @pytest.mark.asyncio
    async def test_transmet_allow_unknown(self, monkeypatch):
        import src.web.routes.maintenance as mod

        service = MagicMock()
        service.delete_files.return_value = DeletionReport(deleted=1)
        service.list_sandboxed.return_value = []
        monkeypatch.setattr(mod, "_get_sandbox_service", lambda *a, **k: service)

        request = self._requete(
            "127.0.0.1", {"selected": ["/a.mkv"], "allow_unknown": "1"}, service
        )
        await sandbox_delete(request)

        assert service.delete_files.call_args[0][1] is True

    @pytest.mark.asyncio
    async def test_sans_case_cochee_pas_de_forcage(self, monkeypatch):
        import src.web.routes.maintenance as mod

        service = MagicMock()
        service.delete_files.return_value = DeletionReport(deleted=0)
        service.list_sandboxed.return_value = []
        monkeypatch.setattr(mod, "_get_sandbox_service", lambda *a, **k: service)

        request = self._requete("127.0.0.1", {"selected": ["/a.mkv"]}, service)
        await sandbox_delete(request)

        assert service.delete_files.call_args[0][1] is False


class TestRenduSection:
    """Ergonomie du cartouche : actions visibles, case de forçage explicite."""

    def _rendu(self, fichiers):
        from src.web.deps import templates

        return templates.env.get_template("maintenance/_sandbox_section.html").render(
            is_local=True, **_sandbox_context(fichiers)
        )

    def test_case_de_forcage_avec_bulle_daide(self):
        """La case « à vérifier » doit être expliquée, pas seulement nommée."""
        html = self._rendu([_fichier("a.mkv", REPLACED), _fichier("b.json", UNKNOWN)])

        assert "sandbox-allow-unknown" in html
        assert "field-hint" in html  # bulle d'aide du projet
        assert "Seule copie" in html  # la bulle rappelle ce qui reste protégé

    def test_case_masquee_sans_fichier_a_verifier(self):
        """Inutile d'exposer un réglage qui ne s'applique à rien."""
        html = self._rendu([_fichier("a.mkv", REPLACED)])
        assert "sandbox-allow-unknown" not in html

    def test_barre_dactions_toujours_rendue(self):
        """Les boutons ne doivent pas dépendre du filtre affiché."""
        html = self._rendu([_fichier("a.mkv", MISSING)])

        assert 'id="sandbox-btn-delete"' in html
        assert 'id="sandbox-btn-reinject"' in html

    def test_donnees_de_selection_exposees(self):
        """Le JS a besoin du statut et de l'espace récupérable par ligne."""
        html = self._rendu([_fichier("a.mkv", REPLACED, 1234)])

        assert 'data-status="replaced"' in html
        assert 'data-reclaimable="1234"' in html


class TestPurgeAvecProgression:
    """Une purge de centaines de fichiers doit rendre compte de son avancement."""

    @pytest.mark.asyncio
    async def test_depot_de_la_selection(self, monkeypatch):
        """delete-start mémorise la sélection pour le flux SSE."""
        import src.web.routes.maintenance as mod
        from src.web.routes.maintenance import sandbox_delete_start

        request = MagicMock()
        request.client.host = "127.0.0.1"
        donnees = MagicMock()
        donnees.getlist.return_value = ["/a.mkv", "/b.mkv"]
        donnees.get.side_effect = lambda k, d=None: {"allow_unknown": "1"}.get(k, d)

        async def _form():
            return donnees

        request.form = _form

        reponse = await sandbox_delete_start(request)

        assert reponse.status_code == 204
        depot = mod._analysis_cache["sandbox_delete"]
        assert depot["paths"] == [Path("/a.mkv"), Path("/b.mkv")]
        assert depot["allow_unknown"] is True
        mod._analysis_cache.pop("sandbox_delete", None)

    @pytest.mark.asyncio
    async def test_depot_refuse_hors_machine_maitre(self):
        from src.web.routes.maintenance import sandbox_delete_start

        request = MagicMock()
        request.client.host = "192.168.1.50"
        reponse = await sandbox_delete_start(request)
        assert reponse.status_code == 403

    @pytest.mark.asyncio
    async def test_flux_emet_progression_puis_resultat(self, monkeypatch):
        """Le flux SSE relaie l'avancement fichier par fichier, puis le HTML final."""
        import src.web.routes.maintenance as mod
        from src.web.routes.maintenance import sandbox_delete_progress

        def _supprime(paths, allow_unknown, on_progress=None):
            for i, p in enumerate(paths, start=1):
                if on_progress:
                    on_progress(i, len(paths), p.name)
            return DeletionReport(deleted=len(paths), reclaimed_bytes=1024)

        service = MagicMock()
        service.delete_files.side_effect = _supprime
        service.list_sandboxed.return_value = []
        monkeypatch.setattr(mod, "_get_sandbox_service", lambda *a, **k: service)

        mod._analysis_cache["sandbox_delete"] = {
            "paths": [Path("/a.mkv"), Path("/b.mkv")],
            "allow_unknown": False,
        }

        request = MagicMock()
        request.client.host = "127.0.0.1"
        reponse = await sandbox_delete_progress(request)

        recu = ""
        async for morceau in reponse.body_iterator:
            recu += morceau

        assert "event: progress" in recu
        assert "event: complete" in recu
        assert "2 fichier(s) supprimé(s)" in recu

    @pytest.mark.asyncio
    async def test_flux_sans_selection(self, monkeypatch):
        import src.web.routes.maintenance as mod
        from src.web.routes.maintenance import sandbox_delete_progress

        mod._analysis_cache.pop("sandbox_delete", None)
        request = MagicMock()
        request.client.host = "127.0.0.1"
        reponse = await sandbox_delete_progress(request)

        recu = ""
        async for morceau in reponse.body_iterator:
            recu += morceau
        assert "Aucun fichier sélectionné" in recu
