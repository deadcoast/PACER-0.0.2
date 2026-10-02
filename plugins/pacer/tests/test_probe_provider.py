import sqlite3
import sys
from pathlib import Path

from pacer.probe import format_evidence, freshness, parse_evidence, run_probe, src_digest
from pacer.provider import BuiltinProvider, CodegraphProvider, NullProvider, select_provider
from tests.conftest import row, tables


def test_evidence_cell_round_trips():
    cell = format_evidence("abc1234", "1234567", 0, "89abcde", "2026-09-29T00:00:00Z")
    assert cell == "rev:abc1234 src:1234567 exit:0 out:89abcde at:2026-09-29T00:00:00Z"
    assert parse_evidence(cell) == {
        "rev": "abc1234",
        "src": "1234567",
        "exit": 0,
        "out": "89abcde",
        "at": "2026-09-29T00:00:00Z",
    }
    assert parse_evidence("garbage") is None and parse_evidence("") is None


def test_digest_ignores_line_endings_but_not_content(tmp_path):
    (tmp_path / "f.txt").write_bytes(b"one\ntwo\n")
    unix = src_digest(tmp_path, ["f.txt"])
    (tmp_path / "f.txt").write_bytes(b"one\r\ntwo\r\n")
    assert src_digest(tmp_path, ["f.txt"]) == unix  # the same file checked out on Windows
    (tmp_path / "f.txt").write_bytes(b"one\ntwo!\n")
    assert src_digest(tmp_path, ["f.txt"]) != unix
    assert src_digest(tmp_path, ["gone.txt"]) != src_digest(tmp_path, [])
    assert src_digest(tmp_path, ["f.txt", "f.txt"]) == src_digest(tmp_path, ["f.txt"])


def test_freshness_states(seeded):
    requirement = row(seeded, "OGM-001")
    assert freshness(requirement, tables(seeded), seeded.root) == "UNBOUND"
    seeded.probe("OGM-001", "t")
    assert freshness(row(seeded, "OGM-001"), tables(seeded), seeded.root) == "CURRENT"
    (seeded.root / "src" / "a.py").write_text("x = 2\n")
    assert freshness(row(seeded, "OGM-001"), tables(seeded), seeded.root) == "STALE"
    (seeded.root / "src" / "b.py").write_text("unbound file\n")
    seeded.probe("OGM-001", "t")
    assert freshness(row(seeded, "OGM-001"), tables(seeded), seeded.root) == "CURRENT"


def test_probe_failure_and_timeout_are_evidence_too(seeded):
    t = tables(seeded)
    requirement = dict(row(seeded, "OGM-001"))
    requirement["Probe"] = f'"{sys.executable}" -c "import sys; print(\'boom\'); sys.exit(3)"'
    failed = run_probe(requirement, t, seeded.root, "t")
    assert failed["exit"] == 3 and failed["freshness"] == "FAIL"
    assert "boom" in (seeded.root / failed["output_path"]).read_text()
    requirement["Evidence"] = failed["evidence"]
    assert freshness(requirement, t, seeded.root) == "FAIL"
    requirement["Probe"] = f'"{sys.executable}" -c "import time; time.sleep(5)"'
    slow = run_probe(requirement, t, seeded.root, "t", timeout=1)
    assert (
        slow["exit"] == 124
        and "timeout after 1s" in (seeded.root / slow["output_path"]).read_text()
    )


def test_probe_does_not_inherit_stdin(seeded):
    requirement = dict(row(seeded, "OGM-001"))
    requirement["Probe"] = f'"{sys.executable}" -c "import sys; sys.exit(len(sys.stdin.read()))"'
    assert run_probe(requirement, tables(seeded), seeded.root, "t")["exit"] == 0


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
    (root / "old").mkdir()
    (root / "old" / "legacy.py").write_text("from pkg import util\n")
    (root / ".hidden").mkdir()
    (root / ".hidden" / "x.py").write_text("from pkg import util\n")


def test_builtin_provider_resolves_python_and_js(tmp_path):
    _python_project(tmp_path)
    provider = BuiltinProvider(tmp_path)
    assert provider.deps("pkg/core.py") == ["pkg/other.py", "pkg/util.py"]
    assert provider.users("pkg/core.py") == ["app.py"]
    assert provider.users("pkg/util.py") == [
        "old/legacy.py",
        "pkg/core.py",
    ]  # dot-directories are never scanned
    assert provider.deps("web.js") == ["lib/a.js", "lib/b.js"] and provider.users("lib/a.js") == [
        "web.js"
    ]
    assert provider.deps("missing.py") == []


def test_builtin_provider_honours_excludes_and_caches_under_run(tmp_path):
    _python_project(tmp_path)
    provider = BuiltinProvider(tmp_path, exclude=["old"])
    assert provider.users("pkg/util.py") == ["pkg/core.py"]
    cache = tmp_path / ".pacer" / "run" / "provider-cache.json"
    assert cache.is_file()
    stamp = cache.stat().st_mtime_ns
    assert BuiltinProvider(tmp_path, exclude=["old"]).users("pkg/util.py") == ["pkg/core.py"]
    assert cache.stat().st_mtime_ns == stamp  # nothing changed, nothing rewritten
    (tmp_path / "app.py").write_text("from pkg import util\n")
    assert BuiltinProvider(tmp_path, exclude=["old"]).users("pkg/util.py") == [
        "app.py",
        "pkg/core.py",
    ]


def test_codegraph_provider_reads_the_index(tmp_path):
    (tmp_path / ".codegraph").mkdir()
    db = sqlite3.connect(tmp_path / ".codegraph" / "codegraph.db")
    db.executescript(
        "CREATE TABLE nodes(id TEXT PRIMARY KEY, kind TEXT, name TEXT, file_path TEXT);"
        "CREATE TABLE edges(id INTEGER PRIMARY KEY, source TEXT, target TEXT, kind TEXT);"
        "INSERT INTO nodes VALUES('a','function','f','src/a.py'),('b','function','g','src/b.py'),('c','function','h','src/c.py');"
        "INSERT INTO edges(source,target,kind) VALUES('a','b','calls'),('c','a','imports'),('a','a','calls');"
    )
    db.commit()
    db.close()
    provider = CodegraphProvider(tmp_path)
    assert provider.deps("src/a.py") == ["src/b.py"] and provider.users("src/a.py") == ["src/c.py"]
    assert select_provider(tmp_path).name == "codegraph"
    assert select_provider(tmp_path, "builtin").name == "builtin"
    assert select_provider(tmp_path, "none").name == "none"


def test_provider_selection_falls_back(tmp_path):
    assert select_provider(tmp_path).name == "builtin"
    assert select_provider(tmp_path, "codegraph").name == "none"
    assert NullProvider().users("x") == [] and NullProvider().deps("x") == []


def test_stale_evidence_names_only_the_files_that_changed(seeded):
    seeded.write([{"op": "link", "id": "OGM-001", "field": "Binds", "target": "OVR-002"}], "t")
    result = seeded.probe("OGM-001", "t")
    assert "files" not in result and result["card"].endswith("CURRENT | Binds: OVR-001;OVR-002")
    recorded = seeded.log("OGM-001", 1)[0]["detail"]["files"]
    assert sorted(recorded) == ["src/a.py", "src/b.py"] and all(
        len(d) == 7 for d in recorded.values()
    )
    (seeded.root / "src" / "b.py").write_text("x = 2\n")
    assert "STALE(src/b.py)" in seeded.q("OGM-001").splitlines()[0]
    (seeded.root / "src" / "a.py").unlink()
    assert "STALE(src/a.py,src/b.py)" in seeded.q("OGM-001").splitlines()[0]
    # Evidence whose probe event is not in the ledger is still STALE; it just cannot say why.
    seeded.layout.ledger.write_text("")
    assert " STALE |" in seeded.q("OGM-001").splitlines()[0]


def test_probe_output_is_read_as_utf8(seeded):
    requirement = dict(row(seeded, "OGM-001"))
    code = "import sys; sys.stdout.buffer.write('ok ✔'.encode('utf-8'))"
    requirement["Probe"] = f'"{sys.executable}" -c "{code}"'
    result = run_probe(requirement, tables(seeded), seeded.root, "t")
    assert (seeded.root / result["output_path"]).read_text(encoding="utf-8").endswith("ok ✔")
