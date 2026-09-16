"""Source inventory retains project work while excluding generated local tool data."""

import importlib.util
import os
from pathlib import Path

import pytest


@pytest.fixture
def inventory(monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[3] / "scripts" / "maintain.py"
    spec = importlib.util.spec_from_file_location("inventory_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


def test_source_inventory_excludes_local_codegraph_data(inventory):
    generated = inventory.ROOT / ".codegraph"
    generated.mkdir()
    for name in (".gitignore", "codegraph.db", "codegraph.db-wal", "daemon.log", "daemon.pid"):
        (generated / name).write_text("local runtime data", encoding="utf-8")
    (inventory.ROOT / "settings.json").write_text("{}", encoding="utf-8")
    assert [row["Path"] for row in inventory.source_assets()] == ["settings.json"]


def test_source_inventory_prunes_generated_trees_before_descent(inventory, monkeypatch):
    # A scanner that merely filters returned files still touches live or inaccessible caches.
    excluded = [".codegraph", ".venv", ".cache", "nested/cache.egg-info", "archive/nodules"]
    for name in excluded:
        path = inventory.ROOT / name
        path.mkdir(parents=True)
        (path / "invalid.py").write_text("not valid python!", encoding="utf-8")
    scanned = []
    original = os.scandir

    def inspect(path):
        scanned.append(Path(path).relative_to(inventory.ROOT).as_posix())
        return original(path)

    monkeypatch.setattr(os, "scandir", inspect)
    inventory.source_assets()
    assert not set(excluded) & set(scanned)


def test_source_inventory_retains_uncommitted_source_and_interface_metadata(inventory):
    # No Git repository: new source, ordinary config and evidence must still be indexed.
    (inventory.ROOT / ".gitignore").write_text("draft.py\n", encoding="utf-8")
    (inventory.ROOT / "draft.py").write_text(
        '"""Work in progress."""\nfrom pathlib import Path\nVALUE = 1\n'
        "def public():\n    pass\nclass Tool:\n    def run(self):\n        pass\n",
        encoding="utf-8",
    )
    (inventory.ROOT / "evidence.json").write_text("{}", encoding="utf-8")
    assets = inventory.source_assets()
    assert assets == inventory.source_assets()
    assert [row["Path"] for row in assets if row["AssetType"] == "FILE"] == [
        ".gitignore",
        "draft.py",
        "evidence.json",
    ]
    rows = {row["Symbol"]: row for row in assets if row["Path"] == "draft.py"}
    assert set(rows) == {"", "draft", "public", "Tool", "Tool.run"}
    assert rows[""]["Purpose"] == "Work in progress."
    assert rows[""]["Imports"] == "pathlib.Path"
    assert rows[""]["Exports"] == "VALUE;public;Tool"


def test_source_inventory_refuses_inaccessible_project_source(inventory, monkeypatch):
    source = inventory.ROOT / "source"
    source.mkdir()
    original = os.scandir

    def inaccessible(path):
        if Path(path) == source:
            raise PermissionError("source directory unavailable")
        return original(path)

    monkeypatch.setattr(os, "scandir", inaccessible)
    with pytest.raises(PermissionError, match="source directory unavailable"):
        inventory.source_assets()
