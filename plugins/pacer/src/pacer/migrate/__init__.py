"""Bring an older PACER project to the current layout.

Three sources are recognised from what sits in the project root:

    0.5        four `*.pacer.csv` registers with profile 0.5 columns
    2.0        a `todo.pacer` plan in the v2.0.0 text syntax
    3.0-root   five registers and a ledger kept in the project root

File names are matched without regard to case, since older projects wrote
`*.PACER.csv`. Imported originals are kept verbatim under
`.pacer/archive/import-<source>/`; a relocation keeps nothing because it loses nothing.
"""

from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from pacer.config import BUDGETS, render_config
from pacer.layout import GIT_FILES, LEDGER_NAME, STATE_DIR, Layout, register_name
from pacer.migrate.importers import empty_tables, from_05, from_v2
from pacer.schema import HEADERS, REGISTERS, TIERS, refs
from pacer.store import Snapshot, Store, atomic_write, parse_csv
from pacer.validation import validate_web

SOURCES = ("0.5", "2.0", "3.0-root")
LEGACY_CONFIG = ".mivim.spec"
OLD_RUNTIME_FILES = ("lock", "hook.lock", "hook-seen.json", "provider-cache.json")


@dataclass
class Plan:
    """Everything a migration will write and move, computed before anything changes."""

    source: str
    tables: dict
    archive: dict
    config_text: str
    sizes_before: dict[str, int]
    keep: list[tuple[Path, str]] = field(default_factory=list)
    drop: list[Path] = field(default_factory=list)
    ledger: Path | None = None
    notes: list[str] = field(default_factory=list)


def _root_file(root: Path, name: str) -> Path | None:
    """A file in the project root by case-insensitive name."""
    wanted = name.lower()
    for entry in root.iterdir():
        if entry.is_file() and entry.name.lower() == wanted:
            return entry
    return None


def _columns(path: Path) -> list[str]:
    return parse_csv(path.read_bytes(), path.name)[0]


def detect(root: Path) -> str | None:
    """Which older format lives here; None when there is nothing to migrate."""
    if Layout(root).governed():
        return None
    todo = _root_file(root, register_name("todo"))
    if todo is not None:
        columns = _columns(todo)
        if "Kind" in columns:
            return "3.0-root"
        if "DoD" in columns:
            return "0.5"
    plan = _root_file(root, "todo.pacer")
    if plan is not None and plan.read_text(encoding="utf-8", errors="replace").lstrip().startswith(
        "PACER::TODO"
    ):
        return "2.0"
    return None


def _nodule_files(root: Path) -> list[Path]:
    folder = root / "archive" / "nodules"
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.name.lower().endswith(".pacer.csv"))


def _read_registers(root: Path, names: tuple[str, ...]) -> tuple[dict, dict, dict]:
    rows, files, sizes = {}, {}, {}
    for name in names:
        path = _root_file(root, register_name(name))
        if path is None:
            raise ValueError(f"Missing {register_name(name)} in {root}")
        data = path.read_bytes()
        rows[name] = parse_csv(data, path.name)[1]
        files[name], sizes[path.name] = path, len(data)
    return rows, files, sizes


def _legacy_config(root: Path) -> dict:
    """Settings from a `.MIVIM.spec` written by pre-baseline 3.0, wherever it was left."""
    for folder in (root, root / STATE_DIR):
        if folder.is_dir():
            for entry in folder.iterdir():
                if entry.is_file() and entry.name.lower() == LEGACY_CONFIG:
                    try:
                        data = tomllib.loads(entry.read_text(encoding="utf-8"))
                    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
                        return {"path": entry}
                    return {"path": entry, **data}
    return {}


def _config_text(root: Path, legacy: dict, tier: str | None = None) -> str:
    project, frames = legacy.get("project"), legacy.get("frames")
    project = project if isinstance(project, dict) else {}
    frames = frames if isinstance(frames, dict) else {}
    chosen = tier or project.get("tier")
    budgets = {k: v for k, v in frames.items() if k in BUDGETS and isinstance(v, int)}
    return render_config(
        str(project.get("name") or root.resolve().name),
        chosen if chosen in TIERS else "prototype",
        budgets,
    )


def _plan_05(root: Path) -> Plan:
    old, files, sizes = _read_registers(root, ("todo", "overlord", "organism", "nodule"))
    absorbed, keep = [], [(path, path.name) for path in files.values()]
    for path in _nodule_files(root):
        absorbed += parse_csv(path.read_bytes(), path.name)[1]
        keep.append((path, f"nodules/{path.name}"))
    tables, archive = from_05(old, absorbed, root)
    return Plan("0.5", tables, archive, _config_text(root, {}), sizes, keep=keep)


def _plan_2(root: Path) -> Plan:
    path = _root_file(root, "todo.pacer")
    if path is None:
        raise ValueError(f"Missing todo.pacer in {root}")
    text = path.read_text(encoding="utf-8")
    tables, archive, tier = from_v2(text, root)
    sizes = {path.name: len(text.encode("utf-8"))}
    return Plan(
        "2.0", tables, archive, _config_text(root, {}, tier), sizes, keep=[(path, path.name)]
    )


def _plan_relocate(root: Path) -> Plan:
    rows, files, sizes = _read_registers(root, REGISTERS)
    tables, archive = empty_tables(), empty_tables()
    drop = list(files.values())
    for register in REGISTERS:
        tables[register] = rows[register]
    # Relations are stored once now. Fold the two reverse columns into the forward ones.
    requirements = {r["ID"]: r for r in tables["organism"]}
    for asset in tables["overlord"]:
        for key in refs(asset.pop("Binds", "")):
            if key in requirements and asset["ID"] not in refs(requirements[key]["Binds"]):
                held = [*refs(requirements[key]["Binds"]), asset["ID"]]
                requirements[key]["Binds"] = ";".join(held)
    decisions = {r["ID"]: r for r in tables["decision"]}
    for register in ("todo", "overlord"):
        for row in tables[register]:
            for key in refs(row.pop("Latch", "")):
                if key in decisions and row["ID"] not in refs(decisions[key]["Subject"]):
                    held = [*refs(decisions[key]["Subject"]), row["ID"]]
                    decisions[key]["Subject"] = ";".join(held)
    absorbed = [r for r in tables["nodule"] if r.get("Status") == "ABSORBED"]
    tables["nodule"] = [r for r in tables["nodule"] if r.get("Status") != "ABSORBED"]
    for path in _nodule_files(root):
        absorbed += parse_csv(path.read_bytes(), path.name)[1]
        drop.append(path)
    archive["nodule"] = absorbed
    legacy = _legacy_config(root)
    if legacy.get("path"):
        drop.append(legacy["path"])
    plan = Plan("3.0-root", tables, archive, _config_text(root, legacy), sizes, drop=drop)
    plan.ledger = _root_file(root, LEDGER_NAME)
    return plan


def plan(root: Path, source: str | None = None) -> Plan:
    source = source or detect(root)
    if source is None:
        if Layout(root).governed():
            raise ValueError("This project already uses the current PACER layout")
        raise ValueError("No older PACER format found in the project root")
    if source not in SOURCES:
        raise ValueError(f"Unknown source {source}; expected one of {', '.join(SOURCES)}")
    if (root / STATE_DIR / "transaction.json").exists():
        raise ValueError("An interrupted write from the old layout is pending; recover it first")
    return {"0.5": _plan_05, "2.0": _plan_2, "3.0-root": _plan_relocate}[source](root)


def describe(root: Path, plan_: Plan) -> dict:
    """What the migration would produce, without writing."""
    snapshot = Snapshot(plan_.tables, plan_.archive, {r: list(HEADERS[r]) for r in REGISTERS}, {})
    tier = tomllib.loads(plan_.config_text)["project"]["tier"]
    report = validate_web(plan_.tables, root, snapshot.headers, plan_.archive, tier)
    encoded = snapshot.encode()
    return {
        "source": plan_.source,
        "sizes_before": plan_.sizes_before,
        "sizes_after": {name: len(data) for name, data in encoded.items()},
        "live": {name: len(rows) for name, rows in plan_.tables.items()},
        "archived": {name: len(rows) for name, rows in plan_.archive.items() if rows},
        "validation": report,
    }


def apply(root: Path, plan_: Plan, actor: str) -> dict:
    """Write `.pacer/`, keep or remove the originals, and report what moved."""
    result = describe(root, plan_)
    if not result["validation"]["valid"]:
        return {**result, "applied": False}
    layout = Layout(root)
    store = Store(root)
    snapshot = Snapshot(plan_.tables, plan_.archive, {r: list(HEADERS[r]) for r in REGISTERS}, {})
    with store.locked(create=True):
        _clear_old_runtime(layout, plan_)
        for name, data in snapshot.encode().items():
            atomic_write(layout.state / name, data)
        atomic_write(layout.config, plan_.config_text.encode("utf-8"))
        for path, text in layout.git_files().items():
            atomic_write(path, text.encode("utf-8"))
        if plan_.ledger is not None:
            shutil.move(str(plan_.ledger), str(layout.ledger))
        kept = layout.archive / f"import-{plan_.source}"
        for path, name in plan_.keep:
            target = kept / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
        for path in plan_.drop:
            path.unlink(missing_ok=True)
        _remove_if_empty(root / "archive" / "nodules")
        _remove_if_empty(root / "archive")
        plan_.notes.append(unignore_state(root))
        counts = {"live": result["live"], "archived": result["archived"]}
        detail = {"from": plan_.source, **counts}
        store.ledger_append({"actor": actor, "op": "migrate", "id": "-", "detail": detail})
    leftover = sorted(
        entry.name
        for entry in layout.state.iterdir()
        if entry.name not in {"archive", "run", *GIT_FILES}
        and not entry.name.endswith((".pacer.csv", ".pacer.jsonl", ".pacer.toml"))
    )
    if leftover:
        plan_.notes.append(f"left untouched in {STATE_DIR}/: {', '.join(leftover)}")
    return {**result, "applied": True, "notes": [n for n in plan_.notes if n]}


def _clear_old_runtime(layout: Layout, plan_: Plan) -> None:
    """Pre-baseline runtimes kept scratch directly in `.pacer/`; move what is worth keeping."""
    probes = layout.state / "probes"
    if probes.is_dir() and not (layout.run / "probes").exists():
        layout.run.mkdir(parents=True, exist_ok=True)
        shutil.move(str(probes), str(layout.run / "probes"))
        plan_.notes.append("moved probe output to run/probes")
    for name in OLD_RUNTIME_FILES:
        (layout.state / name).unlink(missing_ok=True)


def _remove_if_empty(folder: Path) -> None:
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()


def unignore_state(root: Path) -> str:
    """Registers are tracked files now; drop a blanket `.pacer/` ignore left by older kits."""
    path = root / ".gitignore"
    if not path.is_file():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [
        line for line in lines if line.strip() not in {".pacer/", ".pacer", "/.pacer/", "/.pacer"}
    ]
    if kept == lines:
        return ""
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return f"removed the {STATE_DIR}/ line from .gitignore; {STATE_DIR}/.gitignore ignores run/"
