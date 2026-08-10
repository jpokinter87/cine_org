"""
Tests de l'index de recherche utilisé par la commande reconcile.

Le répertoire de téléchargement et le sandbox vivent sous storage_dir : sans
exclusion, reconcile « répare » des symlinks de la vidéothèque en les faisant
pointer vers un fichier en cours de seeding ou une ancienne version écartée.
"""

from pathlib import Path

import pytest

from src.adapters.cli.commands.reconcile_command import _index_candidates


@pytest.fixture
def storage(tmp_path):
    """Storage contenant aussi downloads et sandbox, comme en production."""
    racine = tmp_path / "NAS"
    (racine / "Series/TV/A").mkdir(parents=True)
    (racine / "Films/Action").mkdir(parents=True)
    (racine / "temp/Séries/Show").mkdir(parents=True)
    (racine / ".sandbox/Series/TV/A").mkdir(parents=True)

    (racine / "Series/TV/A/vrai.mkv").write_bytes(b"x")
    (racine / "Films/Action/film.mkv").write_bytes(b"x")
    (racine / "temp/Séries/Show/seeding.mkv").write_bytes(b"x")
    (racine / ".sandbox/Series/TV/A/ancienne.mkv").write_bytes(b"x")
    return racine


def test_exclut_downloads_et_sandbox(storage):
    """Seuls les fichiers de la vidéothèque rangée sont indexables."""
    trouves = {
        p.name
        for p in _index_candidates(storage, [storage / "temp", storage / ".sandbox"])
    }
    assert trouves == {"vrai.mkv", "film.mkv"}


def test_zones_parasites_hors_dossiers_geres(storage):
    """downloads/ et .sandbox/ étant hors Films/Series, ils sont déjà écartés.

    L'exclusion explicite reste une défense en profondeur, utile si le repli
    sur la racine s'applique (installation sans Films/ ni Series/).
    """
    trouves = {p.name for p in _index_candidates(storage, [])}
    assert "seeding.mkv" not in trouves
    assert "ancienne.mkv" not in trouves


def test_exclusion_effective_sur_le_repli(tmp_path):
    """Sans dossier géré, on balaie la racine : l'exclusion doit alors jouer."""
    (tmp_path / "temp").mkdir()
    (tmp_path / "temp/seeding.mkv").write_bytes(b"x")
    (tmp_path / "autre.mkv").write_bytes(b"x")

    trouves = {p.name for p in _index_candidates(tmp_path, [tmp_path / "temp"])}
    assert trouves == {"autre.mkv"}


def test_ignore_les_non_video(storage):
    (storage / "Series/TV/A/notes.txt").write_text("x")
    trouves = {p.name for p in _index_candidates(storage, [])}
    assert "notes.txt" not in trouves


def test_ignore_les_symlinks(storage):
    lien = storage / "Series/TV/A/lien.mkv"
    lien.symlink_to(storage / "Series/TV/A/vrai.mkv")
    trouves = [p for p in _index_candidates(storage, [])]
    assert all(not p.is_symlink() for p in trouves)
    assert lien.name not in {p.name for p in trouves}


def test_racine_exclue_inexistante_sans_effet(storage):
    """Une racine d'exclusion absente ne doit pas faire échouer l'indexation."""
    trouves = {p.name for p in _index_candidates(storage, [Path("/inexistant")])}
    assert "vrai.mkv" in trouves
