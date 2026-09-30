"""Derived source structure: who a file uses and who uses it. Never stored in registers."""

from __future__ import annotations

import ast
import re
import sqlite3
from pathlib import Path
from typing import Protocol

SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".codegraph",
    ".pacer",
    "dist",
    "build",
    ".cache",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "archive",
}
JS_IMPORT = re.compile(r"""(?:from\s+|import\s*\(?\s*|require\s*\(\s*)['"](\.{1,2}/[^'"]+)['"]""")
JS_EXT = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")


class Provider(Protocol):
    name: str

    def users(self, path: str) -> list[str]: ...

    def deps(self, path: str) -> list[str]: ...


class NullProvider:
    name = "none"

    def users(self, path: str) -> list[str]:
        return []

    def deps(self, path: str) -> list[str]:
        return []


class CodegraphProvider:
    """Read the codegraph SQLite index directly; cross-file edges are dependencies."""

    name = "codegraph"

    def __init__(self, root: Path):
        self.db = root / ".codegraph" / "codegraph.db"
        if not self.db.is_file():
            raise FileNotFoundError(self.db)

    def _query(self, sql: str, path: str) -> list[str]:
        try:
            with sqlite3.connect(f"file:{self.db.as_posix()}?mode=ro", uri=True) as c:
                rows = c.execute(sql, (path, path)).fetchall()
        except sqlite3.Error:
            return []
        return sorted({r[0] for r in rows})

    def deps(self, path: str) -> list[str]:
        return self._query(
            "SELECT DISTINCT n2.file_path FROM edges e JOIN nodes n1 ON e.source=n1.id "
            "JOIN nodes n2 ON e.target=n2.id WHERE n1.file_path=? AND n2.file_path<>?",
            path,
        )

    def users(self, path: str) -> list[str]:
        return self._query(
            "SELECT DISTINCT n1.file_path FROM edges e JOIN nodes n1 ON e.source=n1.id "
            "JOIN nodes n2 ON e.target=n2.id WHERE n2.file_path=? AND n1.file_path<>?",
            path,
        )


class BuiltinProvider:
    """Python via ast; JS/TS via relative import regex. One scan, cached per instance."""

    name = "builtin"

    def __init__(self, root: Path):
        self.root = root.resolve()
        self._deps: dict[str, set[str]] = {}
        self._users: dict[str, set[str]] = {}
        self._scan()

    def _files(self):
        for path in self.root.rglob("*"):
            if any(part in SKIP_DIRS for part in path.relative_to(self.root).parts):
                continue
            if path.is_file() and (path.suffix == ".py" or path.suffix in JS_EXT):
                yield path

    def _scan(self):
        files = list(self._files())
        py = {p.relative_to(self.root).as_posix() for p in files if p.suffix == ".py"}
        tops = {p.split("/")[0] for p in py if "/" in p}
        for path in files:
            rel = path.relative_to(self.root).as_posix()
            if path.suffix == ".py":
                targets = self._python_targets(path, rel, py, tops)
            else:
                targets = self._js_targets(path, rel)
            for target in targets:
                if target != rel:
                    self._deps.setdefault(rel, set()).add(target)
                    self._users.setdefault(target, set()).add(rel)

    def _python_targets(self, path: Path, rel: str, py: set[str], tops: set[str]) -> set[str]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError):
            return set()
        found = set()
        package = rel.rsplit("/", 1)[0] if "/" in rel else ""
        for node in ast.walk(tree):
            modules: list[tuple[str, int]] = []
            if isinstance(node, ast.Import):
                modules = [(a.name, 0) for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                leaves: set[str] = set()
                for alias in node.names:
                    leaf = f"{base}.{alias.name}" if base else alias.name
                    leaves |= self._resolve(leaf, node.level, package, py, tops)
                found |= leaves
                if not leaves and base:
                    modules = [(base, node.level)]
            for name, level in modules:
                found.update(self._resolve(name, level, package, py, tops))
        return found

    def _resolve(
        self, name: str, level: int, package: str, py: set[str], tops: set[str]
    ) -> set[str]:
        dotted = name.replace(".", "/")
        if level:
            parts = package.split("/") if package else []
            if level > 1:
                parts = parts[: max(0, len(parts) - (level - 1))]
            base = "/".join(parts)
            candidates = [f"{base}/{dotted}" if base and dotted else (base or dotted)]
        else:
            candidates = [dotted, f"src/{dotted}"] + [f"{top}/{dotted}" for top in tops]
        out = set()
        for c in candidates:
            if not c:
                continue
            for form in (f"{c}.py", f"{c}/__init__.py"):
                if form in py:
                    out.add(form)
        return out

    def _js_targets(self, path: Path, rel: str) -> set[str]:
        text = path.read_text(encoding="utf-8", errors="replace")
        found = set()
        base = Path(rel).parent
        for spec in JS_IMPORT.findall(text):
            normalized: list[str] = []
            for part in Path((base / spec).as_posix()).parts:
                if part == "..":
                    if normalized:
                        normalized.pop()
                elif part != ".":
                    normalized.append(part)
            t = "/".join(normalized)
            candidates = (
                [t] + [f"{t}{ext}" for ext in JS_EXT] + [f"{t}/index{ext}" for ext in JS_EXT]
            )
            for c in candidates:
                if (self.root / c).is_file():
                    found.add(c)
                    break
        return found

    def deps(self, path: str) -> list[str]:
        return sorted(self._deps.get(path, set()))

    def users(self, path: str) -> list[str]:
        return sorted(self._users.get(path, set()))


def select_provider(root: Path, preference: str = "auto") -> Provider:
    """codegraph when indexed, else the builtin scanner; 'none' disables structure."""
    if preference in {"auto", "codegraph"}:
        try:
            return CodegraphProvider(root)
        except FileNotFoundError:
            if preference == "codegraph":
                return NullProvider()
    if preference == "none":
        return NullProvider()
    return BuiltinProvider(root)
