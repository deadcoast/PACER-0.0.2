"""Assemble the PACER 3 kit: a self-contained marketplace, project templates and docs.

Usage (repository root):
    uv run --locked python scripts/build_kit.py            # dist/PACER3-KIT-<version>/ and .zip
    uv run --locked python scripts/build_kit.py --out DIR  # alternative output directory
"""

from __future__ import annotations

import argparse
import json
import shutil
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "pacer"
KIT_SRC = ROOT / "kit"
EXCLUDE_DIRS = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "dist"}


def plugin_version() -> str:
    return tomllib.loads((PLUGIN / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]


def copy_plugin(destination: Path) -> int:
    count = 0
    for path in sorted(PLUGIN.rglob("*")):
        rel = path.relative_to(PLUGIN)
        if any(part in EXCLUDE_DIRS for part in rel.parts) or not path.is_file():
            continue
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        count += 1
    return count


def write_marketplaces(market: Path, version: str) -> None:
    claude = {
        "name": "pacer3",
        "owner": {"name": "MIVIM"},
        "description": "PACER 3: hook-delivered project context for coding agents.",
        "plugins": [
            {
                "name": "pacer",
                "source": "./plugins/pacer",
                "description": f"PACER {version}: hook-delivered project context for agents.",
            }
        ],
    }
    codex = {
        "name": "pacer3",
        "interface": {"displayName": "PACER 3"},
        "plugins": [
            {
                "name": "pacer",
                "source": {"source": "local", "path": "./plugins/pacer"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Productivity",
            }
        ],
    }
    (market / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (market / ".agents" / "plugins").mkdir(parents=True, exist_ok=True)
    (market / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(claude, indent=2) + "\n", encoding="utf-8"
    )
    (market / ".agents" / "plugins" / "marketplace.json").write_text(
        json.dumps(codex, indent=2) + "\n", encoding="utf-8"
    )


def build(out_dir: Path) -> tuple[Path, Path]:
    version = plugin_version()
    kit = out_dir / f"PACER3-KIT-{version}"
    if kit.exists():
        shutil.rmtree(kit)
    kit.mkdir(parents=True)
    market = kit / "marketplace"
    copied = copy_plugin(market / "plugins" / "pacer")
    write_marketplaces(market, version)
    for entry in sorted(KIT_SRC.rglob("*")):
        rel = entry.relative_to(KIT_SRC)
        if entry.is_file():
            target = kit / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry, target)
    docs = kit / "docs"
    docs.mkdir(exist_ok=True)
    shutil.copy2(PLUGIN / "references" / "FORMAT.md", docs / "FORMAT.md")
    shutil.copy2(PLUGIN / "skills" / "pacer" / "SKILL.md", docs / "CARDS.md")
    (kit / "VERSION").write_text(version + "\n", encoding="utf-8")
    archive = out_dir / f"PACER3-KIT-{version}.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(kit.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(out_dir).as_posix())
    print(f"kit: {kit}  plugin files: {copied}")
    print(f"zip: {archive}  bytes: {archive.stat().st_size}")
    return kit, archive


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the PACER 3 kit")
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    build(args.out.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
