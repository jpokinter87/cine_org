"""Test de la commande CLI `version` (sortie alignée sur get_version())."""

from src.main import version
from src.version import get_version


def test_version_command_outputs_pyproject_version(capsys) -> None:
    """La commande affiche `CineOrg v<version pyproject>`."""
    version()
    out = capsys.readouterr().out
    assert "CineOrg" in out
    assert get_version() in out
    assert "0.1.0" not in out  # plus de valeur hardcodée périmée
