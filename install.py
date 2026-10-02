"""Install PACER into Claude Code and Codex from this directory.

    uv run install.py                  every host found, plus the `pacer` command
    uv run install.py --host claude    one host: claude or codex
    uv run install.py --no-cli         leave the `pacer` command alone
    uv run install.py --status         report what each host runs; exit 0 when it is this copy
    uv run install.py --uninstall      remove PACER from every host

This directory is a plugin marketplace named `mivim`: a repository checkout or an
unpacked kit, the layout is the same. The installer registers it with each host,
installs `pacer@mivim`, and removes any other installed copy of the plugin so a
host never runs two. Standard library only; needs uv and Python 3.11 or newer.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLUGIN = ROOT / "plugins" / "pacer"
MARKET = "mivim"
PLUGIN_ID = f"pacer@{MARKET}"
MANIFESTS = (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json")


def call(*command: str) -> tuple[int, str]:
    """Run a command; returns its exit code and combined output."""
    done = subprocess.run(
        command,
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
        plugins = data.get("plugins", [])
        return {str(p.get("name")) for p in plugins if isinstance(p, dict)}
    return None


@dataclass
class Copy:
    """One installed PACER plugin: its id, the marketplace it came from, its scope, its version."""

    plugin_id: str
    market: str
    scope: str = "user"
    version: str = ""


class Host:
    """The plugin commands of one agent CLI. Subclasses supply the vocabulary."""

    name = ""
    command = ""

    def __init__(self, exe: str):
        self.exe = exe

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

    def advice(self) -> list[str]:
        return []

    # -- procedure -----------------------------------------------------------
    def remove(self, *, keep_market: bool) -> list[str]:
        """Uninstall every PACER copy and drop marketplaces that existed only to serve it."""
        notes = []
        markets = self.markets()
        sources = set()
        for copy in self.copies():
            # A reinstall keeps the plugin's data directory: the MCP server's environment is there.
            self.uninstall(copy, keep_data=keep_market and copy.plugin_id == PLUGIN_ID)
            notes.append(f"removed {copy.plugin_id}")
            sources.add(copy.market)
        for name, directory in markets.items():
            # An earlier PACER distribution: it offers only PACER, or PACER came from it
            # and its directory is gone. A marketplace with anything else is left alone.
            offered = offers(directory)
            spent = offered == {"pacer"} or (offered is None and name in sources)
            if name != MARKET and spent:
                self.run("plugin", "marketplace", "remove", name)
                notes.append(f"removed marketplace {name}")
        if MARKET in markets:
            here = markets[MARKET] and local(markets[MARKET]).resolve() == ROOT
            if not (keep_market and here):
                self.run("plugin", "marketplace", "remove", MARKET)
                if not keep_market:
                    notes.append(f"removed marketplace {MARKET}")
        return notes

    def install(self) -> list[str]:
        """A fresh copy every time: hosts do not refresh a plugin whose version is unchanged."""
        notes = self.remove(keep_market=True)
        if MARKET not in self.markets():
            self.add_market()
        self.add_plugin()
        return [*notes, f"installed {PLUGIN_ID}", *self.advice()]

    def status(self, version: str) -> tuple[bool, list[str]]:
        """Whether this host runs exactly this directory's PACER, and what it has instead."""
        copies, markets = self.copies(), self.markets()
        # One plugin enabled at several scopes (user, project) is one copy listed more than once.
        installed: dict[tuple[str, str], list[str]] = {}
        for copy in copies:
            installed.setdefault((copy.plugin_id, copy.version), []).append(copy.scope)
        notes = [
            f"{plugin_id}  {found or 'unknown version'}  ({', '.join(scopes)} scope)"
            for (plugin_id, found), scopes in installed.items()
        ]
        here = MARKET in markets and local(markets[MARKET]).resolve() == ROOT
        if MARKET in markets:
            where = local(markets[MARKET])
            notes.append(
                f"marketplace {MARKET}: {where}" + ("" if here else "  (another directory)")
            )
        current = list(installed) == [(PLUGIN_ID, version)]
        if not copies:
            notes.append("not installed")
        elif not (current and here):
            notes.append(f"expected only {PLUGIN_ID} {version} from this directory")
        return current and here, [*notes, *self.advice()]


class Claude(Host):
    name, command = "Claude Code", "claude"

    def markets(self) -> dict[str, str]:
        found = self.listing("plugin", "marketplace", "list")
        rows = found if isinstance(found, list) else []
        return {m["name"]: str(m.get("path", "")) for m in rows if isinstance(m, dict)}

    def copies(self) -> list[Copy]:
        found = self.listing("plugin", "list")
        rows = [p for p in (found if isinstance(found, list) else []) if isinstance(p, dict)]
        mine = [p for p in rows if str(p.get("id", "")).startswith("pacer@")]
        return [
            Copy(
                p["id"],
                p["id"].split("@", 1)[1],
                str(p.get("scope", "user")),
                str(p.get("version", "")),
            )
            for p in mine
        ]

    def uninstall(self, copy: Copy, *, keep_data: bool) -> None:
        keep = ["--keep-data"] if keep_data else []
        self.run("plugin", "uninstall", copy.plugin_id, "--scope", copy.scope, *keep)

    def add_market(self) -> None:
        self.run("plugin", "marketplace", "add", str(ROOT), "--scope", "user")

    def add_plugin(self) -> None:
        self.run("plugin", "install", PLUGIN_ID, "--scope", "user")


class Codex(Host):
    name, command = "Codex", "codex"

    def markets(self) -> dict[str, str]:
        found = self.listing("plugin", "marketplace", "list")
        rows = found.get("marketplaces", []) if isinstance(found, dict) else []
        return {m["name"]: str(m.get("root", "")) for m in rows if isinstance(m, dict)}

    def copies(self) -> list[Copy]:
        found = self.listing("plugin", "list")
        rows = found.get("installed", []) if isinstance(found, dict) else []
        mine = [p for p in rows if isinstance(p, dict) and p.get("name") == "pacer"]
        return [
            Copy(
                str(p["pluginId"]),
                str(p.get("marketplaceName", "")),
                version=str(p.get("version", "")),
            )
            for p in mine
        ]

    def uninstall(self, copy: Copy, *, keep_data: bool) -> None:
        # Codex keeps the server's environment inside the installed copy; there is nothing to keep.
        self.run("plugin", "remove", copy.plugin_id)

    def add_market(self) -> None:
        self.run("plugin", "marketplace", "add", str(ROOT))

    def add_plugin(self) -> None:
        self.run("plugin", "add", PLUGIN_ID)

    def advice(self) -> list[str]:
        notes = []
        code, features = call(self.exe, "features", "list")
        state = [line.split() for line in features.splitlines() if line.startswith("hooks ")]
        if code == 0 and state and state[0][-1] == "false":
            notes.append(
                "hooks are disabled in this Codex configuration, so frames are not delivered; "
                "enable them with `codex features enable hooks`"
            )
        notes.append("Codex runs a plugin's hooks only after you review and trust them: /hooks")
        return notes


HOSTS: dict[str, type[Host]] = {"claude": Claude, "codex": Codex}


def pacer_command(uv: str, *, remove: bool) -> tuple[bool, str]:
    if remove:
        code, _ = call(uv, "tool", "uninstall", "pacer")
        return True, "removed" if code == 0 else "not installed"
    code, out = call(uv, "tool", "install", "--force", "--python", ">=3.11", str(PLUGIN))
    return code == 0, "installed with `uv tool install`" if code == 0 else f"FAILED: {out}"


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--host", choices=[*HOSTS, "all"], default="all")
    parser.add_argument("--no-cli", action="store_true", help="leave the `pacer` command alone")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--uninstall", action="store_true", help="remove PACER from the hosts")
    action.add_argument("--status", action="store_true", help="report what each host runs")
    args = parser.parse_args()

    project = tomllib.loads((PLUGIN / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    print(f"PACER {version}  {ROOT}")
    uv = shutil.which("uv")
    if uv is None:
        print("uv is required: https://docs.astral.sh/uv/", file=sys.stderr)
        return 2

    wanted = list(HOSTS) if args.host == "all" else [args.host]
    found = {name: shutil.which(name) for name in wanted}
    missing = [name for name, exe in found.items() if exe is None]
    if args.host != "all" and missing:
        print(f"{missing[0]} is not on PATH", file=sys.stderr)
        return 2

    ok = True
    hosts = [HOSTS[name](exe) for name, exe in found.items() if exe]
    for host in hosts:
        print(f"\n{host.name}  ({host.version()})")
        try:
            if args.status:
                current, notes = host.status(version)
                ok = ok and current
            else:
                notes = host.remove(keep_market=False) if args.uninstall else host.install()
        except RuntimeError as exc:
            print(f"  FAILED: {exc}")
            ok = False
            continue
        for note in notes or ["nothing to remove"]:
            print(f"  {note}")
    for name in missing:
        print(f"\n{name}: not on PATH, skipped")

    if args.status:
        # Ask uv, not PATH: a development environment may put its own `pacer` first.
        listed = call(uv, "tool", "list")[1].splitlines()
        tool = next((line for line in listed if line.startswith("pacer ")), "not installed")
        print(f"\npacer command\n  {tool}")
        return 0 if ok and hosts else 1
    if not args.no_cli:
        done, note = pacer_command(uv, remove=args.uninstall)
        print(f"\npacer command\n  {note}")
        ok = ok and done

    if not hosts and not args.uninstall:
        print("\nNo host found. Install Claude Code or Codex, then run this again.")
    elif ok and not args.uninstall:
        print(
            "\nStart a new session. In a project: `pacer init`, or ask the agent to pace a request."
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
