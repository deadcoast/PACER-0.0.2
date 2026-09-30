import sqlite3
from pathlib import Path

from pacer_mcp.provider import BuiltinProvider, CodegraphProvider, NullProvider, select_provider


def _python_project(root: Path):
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "core.py").write_text(
        "import json\nfrom pkg import util\nfrom .other import x\n"
    )
    (root / "pkg" / "util.py").write_text("VALUE = 1\n")
    (root / "pkg" / "other.py").write_text("x = 2\n")
    (root / "app.py").write_text("from pkg.core import run\n")
    (root / "web.js").write_text("import a from './lib/a.js';\nconst b = require('./lib/b');\n")
    (root / "lib").mkdir()
    (root / "lib" / "a.js").write_text("export default 1;")
    (root / "lib" / "b.js").write_text("module.exports = 2;")


def test_builtin_python_and_js(tmp_path):
    _python_project(tmp_path)
    p = BuiltinProvider(tmp_path)
    assert p.deps("pkg/core.py") == ["pkg/other.py", "pkg/util.py"]
    assert p.users("pkg/core.py") == ["app.py"]
    assert p.users("pkg/util.py") == ["pkg/core.py"]
    assert p.deps("web.js") == ["lib/a.js", "lib/b.js"]
    assert p.users("lib/a.js") == ["web.js"]
    assert p.deps("missing.py") == []


def test_codegraph_reads_sqlite(tmp_path):
    db_dir = tmp_path / ".codegraph"
    db_dir.mkdir()
    c = sqlite3.connect(db_dir / "codegraph.db")
    c.executescript(
        "CREATE TABLE nodes(id TEXT PRIMARY KEY, kind TEXT, name TEXT, file_path TEXT);"
        "CREATE TABLE edges(id INTEGER PRIMARY KEY, source TEXT, target TEXT, kind TEXT);"
        "INSERT INTO nodes VALUES('a','function','f','src/a.py'),('b','function','g','src/b.py'),('c','function','h','src/c.py');"
        "INSERT INTO edges(source,target,kind) VALUES('a','b','calls'),('c','a','imports'),('a','a','calls');"
    )
    c.commit()
    c.close()
    p = CodegraphProvider(tmp_path)
    assert p.deps("src/a.py") == ["src/b.py"]
    assert p.users("src/a.py") == ["src/c.py"]
    assert select_provider(tmp_path).name == "codegraph"
    assert select_provider(tmp_path, "builtin").name == "builtin"


def test_select_falls_back(tmp_path):
    assert select_provider(tmp_path).name == "builtin"
    assert NullProvider().users("x") == []
