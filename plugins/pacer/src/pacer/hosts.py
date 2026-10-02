"""The hosts PACER installs into, and the `pacer` command.

Each host is driven through its own CLI. A host is current when it holds exactly
one copy of the plugin, from this marketplace, at this version, with the same
bytes as the source. Anything else is reinstalled: hosts do not refresh a plugin
whose version string has not changed, so a reinstall is the only sync.

On Windows a host's installed copy can be locked by the MCP servers running
from it. Those are PACER's own processes; they are stopped by path and the
removal is tried again.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pacer.display import StepError
from pacer.identity import MARKET, PLUGIN, PLUGIN_ID

MANIFESTS = (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json")
SKIP = {"__pycache__", ".venv", ".ruff_cache", ".mypy_cache", ".pytest_cache", "node_modules"}
LEGACY_TOOLS = ("pacer-mcp",)
IN_USE = ("being used by another process", "os error 32", "os error 5", "Access is denied")
Note = Callable[[str], None]


def call(*command: str, cwd: Path | None = None) -> tuple[int, str]:
    """Run a command; its exit code and combined output."""
    done = subprocess.run(
        command,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return done.returncode, done.stdout.strip()


def local(path: str) -> Path:
    """A directory as a host reports it; Codex prefixes Windows paths with `\\\\?\\`."""
    return Path(path.removeprefix("\\\\?\\"))


def offers(directory: str) -> set[str] | None:
    """Plugin names a marketplace directory offers; None when it has no readable manifest."""
    if not directory:
        return None
    for manifest in MANIFESTS:
        try:
            data = json.loads((local(directory) / manifest).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        return {str(p.get("name")) for p in data.get("plugins", []) if isinstance(p, dict)}
    return None


def digests(root: Path) -> dict[str, str]:
    """A short digest per file under `root`, by relative path; caches and environments left out."""
    found: dict[str, str] = {}
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP)
        for name in files:
            if name.endswith(".pyc"):
                continue
            path = Path(base) / name
            try:
                data = path.read_bytes()
            except OSError:
                continue
            found[path.relative_to(root).as_posix()] = hashlib.sha256(data).hexdigest()[:12]
    return found


def differences(source: Path, installed: Path) -> list[str]:
    """Files of `source` that `installed` lacks or holds with other bytes."""
    theirs = digests(installed)
    return sorted(p for p, d in digests(source).items() if theirs.get(p) != d)


def in_use(message: str) -> bool:
    return any(mark in message for mark in IN_USE)


def stop_servers(under: Path) -> int:
    """Stop processes running from `under`: PACER's own servers, started by a host. Windows only."""
    if sys.platform != "win32":
        return 0
    root = str(under).replace("'", "''")
    script = (
        "Get-CimInstance Win32_Process | Where-Object { "
        f"($_.ExecutablePath -and $_.ExecutablePath.StartsWith('{root}', 'OrdinalIgnoreCase')) -or "
        f"($_.CommandLine -and $_.CommandLine.IndexOf('{root}', 'OrdinalIgnoreCase') -ge 0) "
        "} | Select-Object -ExpandProperty ProcessId"
    )
    code, out = call("powershell", "-NoProfile", "-NonInteractive", "-Command", script)
    pids = (
        [line.strip() for line in out.splitlines() if line.strip().isdigit()] if code == 0 else []
    )
    for pid in pids:
        call("taskkill", "/PID", pid, "/T", "/F")
    if pids:
        time.sleep(1.0)  # the hosts' own launchers exit once their servers are gone
    return len(pids)


@dataclass
class Copy:
    """One installed PACER plugin as a host lists it."""

    plugin_id: str
    market: str
    scope: str = "user"
    version: str = ""
    path: Path | None = None
    project: Path | None = None  # the project a project- or local-scope entry belongs to


class Host:
    """The plugin commands of one agent CLI. Subclasses supply the vocabulary."""

    name = ""
    command = ""

    def __init__(self, exe: str, root: Path):
        self.exe, self.root = exe, root

    def run(self, *args: str) -> str:
        code, out = call(self.exe, *args)
        if code:
            reason = out.splitlines()[-1] if out else f"exit {code}"
            raise RuntimeError(f"{self.command} {' '.join(args)}: {reason}")
        return out

    def listing(self, *args: str) -> object:
        """A `--json` listing; empty when the command fails or prints something else."""
        code, out = call(self.exe, *args, "--json")
        try:
            return json.loads(out) if code == 0 else {}
        except ValueError:
            return {}

    def version(self) -> str:
        return (call(self.exe, "--version")[1].splitlines() or ["unknown version"])[0]

    # -- vocabulary ----------------------------------------------------------
    def markets(self) -> dict[str, str]:
        """Configured marketplaces: name to directory ("" when not a directory)."""
        raise NotImplementedError

    def copies(self) -> list[Copy]:
        raise NotImplementedError

    def uninstall(self, copy: Copy, *, keep_data: bool) -> None:
        raise NotImplementedError

    def add_market(self) -> None:
        raise NotImplementedError

    def add_plugin(self) -> None:
        raise NotImplementedError

    def cache_root(self) -> Path:
        """Where this host keeps its copies of the plugin, every version."""
        raise NotImplementedError

    def advice(self) -> list[str]:
        return []

    # -- procedure -----------------------------------------------------------
    def remove(self, *, keep_market: bool) -> list[str]:
        """Uninstall every PACER copy and drop marketplaces that existed only to serve it."""
        notes = []
        markets = self.markets()
        sources = set()
        for copy in self.copies():
            if keep_market and copy.plugin_id == PLUGIN_ID and copy.scope != "user":
                # A project enables the same installed copy; refreshing that copy is enough.
                continue
            # A reinstall keeps the plugin's data directory: the MCP server's environment is there.
            self.uninstall(copy, keep_data=keep_market and copy.plugin_id == PLUGIN_ID)
            notes.append(f"removed {copy.plugin_id}")
            sources.add(copy.market)
        for name, directory in markets.items():
            # An earlier PACER distribution: it offers only PACER, or PACER came from it
            # and its directory is gone. A marketplace with anything else is left alone.
            offered = offers(directory)
            spent = offered == {PLUGIN} or (offered is None and name in sources)
            if name != MARKET and spent:
                self.run("plugin", "marketplace", "remove", name)
                notes.append(f"removed marketplace {name}")
        if MARKET in markets:
            here = markets[MARKET] and local(markets[MARKET]).resolve() == self.root.resolve()
            if not (keep_market and here):
                self.run("plugin", "marketplace", "remove", MARKET)
                if not keep_market:
                    notes.append(f"removed marketplace {MARKET}")
        return notes

    def install(self, note: Note) -> list[str]:
        """A fresh copy. When the old one is in use, PACER's servers are stopped and it is retried.

        A version bump or a changed file both end here: hosts refresh nothing on their own.
        """
        try:
            notes = self.remove(keep_market=True)
        except RuntimeError as error:
            if not in_use(str(error)):
                raise
            stopped = stop_servers(self.cache_root())
            if not stopped:
                raise StepError(f"the installed copy is in use: {error}") from error
            note(f"stopped {stopped} PACER server(s) running from the previous copy")
            notes = [*self.remove(keep_market=True), f"stopped {stopped} server(s)"]
        if MARKET not in self.markets():
            self.add_market()
        self.add_plugin()
        return [*notes, f"installed {PLUGIN_ID}"]

    def status(self, version: str) -> tuple[bool, list[str], list[str]]:
        """Whether this host runs exactly the source: (current, notes, files that differ)."""
        copies, markets = self.copies(), self.markets()
        # One plugin enabled at several scopes (user, project) is one copy listed more than once.
        installed: dict[tuple[str, str], list[str]] = {}
        for copy in copies:
            installed.setdefault((copy.plugin_id, copy.version), []).append(copy.scope)
        notes = [
            f"{plugin_id}  {found or 'unknown version'}  ({', '.join(scopes)} scope)"
            for (plugin_id, found), scopes in installed.items()
        ]
        here = MARKET in markets and local(markets[MARKET]).resolve() == self.root.resolve()
        if MARKET in markets:
            where = local(markets[MARKET])
            notes.append(
                f"marketplace {MARKET}: {where}" + ("" if here else "  (another directory)")
            )
        current = list(installed) == [(PLUGIN_ID, version)] and here
        changed: list[str] = []
        if current:
            path = next((c.path for c in copies if c.path), None)
            if path is not None and path.is_dir():
                changed = differences(self.root / "plugins" / PLUGIN, path)
                current = not changed
        if not copies:
            notes.append("not installed")
        elif changed:
            notes.append(f"installed copy differs from the source in {len(changed)} file(s)")
        elif not current:
            notes.append(f"expected only {PLUGIN_ID} {version} from this directory")
        return current, notes, changed

    def sync(self, version: str, note: Note, *, force: bool = False) -> tuple[str, str]:
        """One journey stage: install unless the host already runs exactly the source."""
        current, _, changed = self.status(version)
        if current and not force:
            return "skip", f"{PLUGIN_ID} {version} current"
        notes = self.install(note)
        for line in notes:
            note(line)
        extra = [f"{len(changed)} file(s) refreshed"] if changed else []
        extra += [line for line in notes if line.startswith("stopped")]
        return "done", ", ".join([f"{PLUGIN_ID} {version}", *extra])


class Claude(Host):
    name, command = "Claude Code", "claude"

    def markets(self) -> dict[str, str]:
        found = self.listing("plugin", "marketplace", "list")
        rows = found if isinstance(found, list) else []
        return {m["name"]: str(m.get("path", "")) for m in rows if isinstance(m, dict)}

    def copies(self) -> list[Copy]:
        found = self.listing("plugin", "list")
        rows = [p for p in (found if isinstance(found, list) else []) if isinstance(p, dict)]
        mine = [p for p in rows if str(p.get("id", "")).startswith(f"{PLUGIN}@")]
        return [
            Copy(
                p["id"],
                p["id"].split("@", 1)[1],
                str(p.get("scope", "user")),
                str(p.get("version", "")),
                Path(p["installPath"]) if p.get("installPath") else None,
                Path(p["projectPath"]) if p.get("projectPath") else None,
            )
            for p in mine
        ]

    def uninstall(self, copy: Copy, *, keep_data: bool) -> None:
        keep = ["--keep-data"] if keep_data else []
        args = ("plugin", "uninstall", copy.plugin_id, "--scope", copy.scope, *keep)
        if copy.project is not None and copy.project.is_dir():
            code, out = call(self.exe, *args, cwd=copy.project)
            if code:
                raise RuntimeError(
                    f"{self.command} {' '.join(args)}: {out.splitlines()[-1] if out else code}"
                )
            return
        self.run(*args)

    def add_market(self) -> None:
        self.run("plugin", "marketplace", "add", str(self.root), "--scope", "user")

    def add_plugin(self) -> None:
        self.run("plugin", "install", PLUGIN_ID, "--scope", "user")

    def cache_root(self) -> Path:
        return Path.home() / ".claude" / "plugins" / "cache" / MARKET / PLUGIN


class Codex(Host):
    name, command = "Codex", "codex"

    def home(self) -> Path:
        return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")

    def markets(self) -> dict[str, str]:
        found = self.listing("plugin", "marketplace", "list")
        rows = found.get("marketplaces", []) if isinstance(found, dict) else []
        return {m["name"]: str(m.get("root", "")) for m in rows if isinstance(m, dict)}

    def copies(self) -> list[Copy]:
        found = self.listing("plugin", "list")
        rows = found.get("installed", []) if isinstance(found, dict) else []
        mine = [p for p in rows if isinstance(p, dict) and p.get("name") == PLUGIN]
        return [
            Copy(
                str(p["pluginId"]),
                str(p.get("marketplaceName", "")),
                version=str(p.get("version", "")),
                path=self.cache_root().parent / PLUGIN / str(p.get("version", "")),
            )
            for p in mine
        ]

    def uninstall(self, copy: Copy, *, keep_data: bool) -> None:
        # Codex keeps the server's environment inside the installed copy; there is nothing to keep.
        self.run("plugin", "remove", copy.plugin_id)

    def add_market(self) -> None:
        self.run("plugin", "marketplace", "add", str(self.root))

    def add_plugin(self) -> None:
        self.run("plugin", "add", PLUGIN_ID)

    def cache_root(self) -> Path:
        return self.home() / "plugins" / "cache" / MARKET / PLUGIN

    def advice(self) -> list[str]:
        code, features = call(self.exe, "features", "list")
        state = [line.split() for line in features.splitlines() if line.startswith("hooks ")]
        if code == 0 and state and state[0][-1] == "false":
            return [
                "Codex has hooks disabled, so no frames arrive there: codex features enable hooks, "
                "then trust the plugin's hooks once with /hooks"
            ]
        return []


HOSTS: dict[str, type[Host]] = {"claude": Claude, "codex": Codex}


class Command:
    """The `pacer` command: an editable uv tool, so it runs the source and never needs replacing.

    An entry point in use cannot be rewritten on Windows, which is exactly the
    situation `pacer update` is in. With an editable install the launcher stays
    the same across versions; only the environment is refreshed, and that works
    while the launcher runs.
    """

    def __init__(self, uv: str, plugin_dir: Path):
        self.uv, self.plugin_dir = uv, plugin_dir

    def fingerprint(self) -> str:
        """What the tool environment depends on: version, interpreter and dependencies."""
        try:
            data = tomllib.loads((self.plugin_dir / "pyproject.toml").read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return ""
        project = data.get("project", {})
        basis = json.dumps(
            {k: project.get(k) for k in ("version", "requires-python", "dependencies", "scripts")},
            sort_keys=True,
        )
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]

    def listed(self) -> dict[str, str]:
        """Installed uv tools by name, with the line uv prints for each."""
        code, out = call(self.uv, "tool", "list")
        tools: dict[str, str] = {}
        if code == 0:
            for line in out.splitlines():
                if line and not line.startswith(("-", " ")):
                    tools[line.split()[0]] = line
        return tools

    def status(self, record: dict) -> tuple[bool, str]:
        """Whether the command is installed from this source at this fingerprint."""
        tools = self.listed()
        if PLUGIN not in tools:
            return False, "not installed"
        wanted = {"source": str(self.plugin_dir), "fingerprint": self.fingerprint()}
        if {k: record.get(k) for k in wanted} != wanted:
            return False, f"{tools[PLUGIN]}  (another source or version)"
        return True, tools[PLUGIN]

    def sync(self, record: dict, note: Note, *, force: bool = False) -> tuple[str, str, dict]:
        """One journey stage. Returns (state, text, the record to keep)."""
        tools = self.listed()
        for legacy in LEGACY_TOOLS:
            if legacy in tools:
                call(self.uv, "tool", "uninstall", legacy)
                note(f"removed the earlier tool {legacy}")
        current, text = self.status(record)
        if current and not force:
            return "skip", "pacer command current", record
        code, out = call(
            self.uv, "tool", "install", "--force", "--editable", "--python", ">=3.11",
            str(self.plugin_dir),
        )  # fmt: skip
        kept = {"source": str(self.plugin_dir), "fingerprint": self.fingerprint()}
        if code != 0 and in_use(out) and PLUGIN in tools:
            # The environment was refreshed; only the launcher copy failed, and it is unchanged.
            return "done", "pacer command refreshed (launcher in use, kept)", kept
        if code != 0:
            raise StepError(f"uv tool install: {out.splitlines()[-1] if out else code}")
        warning = next((line for line in out.splitlines() if "not on your PATH" in line), "")
        if warning:
            note(warning.strip())
        return "done", "pacer command installed", kept

    def remove(self) -> str:
        code, _ = call(self.uv, "tool", "uninstall", PLUGIN)
        for legacy in LEGACY_TOOLS:
            call(self.uv, "tool", "uninstall", legacy)
        return "removed" if code == 0 else "not installed"
