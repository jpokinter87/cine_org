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
