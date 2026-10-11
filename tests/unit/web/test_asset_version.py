"""Tests : le cache-buster des assets suit les fichiers JS, pas seulement le CSS.

Il ne dépendait que du mtime de style.css : une modification de merge.js sans
toucher au CSS gardait la même URL, et le navigateur servait l'ancien script
(fusion cassée après la livraison de la fusion à N fiches).
"""

import os

from src.web import deps


def _touch(path, mtime):
    path.write_text("x")
    os.utime(path, (mtime, mtime))


def test_asset_version_changes_when_a_js_file_changes(tmp_path, monkeypatch):
    (tmp_path / "static" / "css").mkdir(parents=True)
    (tmp_path / "static" / "js").mkdir()
    _touch(tmp_path / "static" / "css" / "style.css", 1_000)
    _touch(tmp_path / "static" / "js" / "merge.js", 1_000)
    monkeypatch.setattr(deps, "_WEB_DIR", tmp_path)

    before = deps._asset_version()
    _touch(tmp_path / "static" / "js" / "merge.js", 2_000)

    assert deps._asset_version() != before


def test_asset_version_without_static_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(deps, "_WEB_DIR", tmp_path)
    assert deps._asset_version() == "0"
