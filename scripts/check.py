"""Verify tests, style, source registration, example coherence and plugin packaging."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from maintain import ROOT, source_assets
from pacer_mcp.schema import HEADERS
from pacer_mcp.service import Service
from pacer_mcp.store import parse_csv
from pacer_mcp.validation import validate_web


def main() -> int:
    """Fail before commit if checks or the source-to-register correspondence fail."""
    commands = [
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            "plugins/pacer/pyproject.toml",
            "plugins/pacer/src",
            "plugins/pacer/tests",
            "scripts",
        ],
        [
            sys.executable,
            "-m",
            "ruff",
            "format",
            "--check",
            "--config",
            "plugins/pacer/pyproject.toml",
            "plugins/pacer/src",
            "plugins/pacer/tests",
            "scripts",
        ],
        [sys.executable, "-m", "pytest", "plugins/pacer/tests", "-q"],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    service = Service(ROOT)
    validation = service.validate()
    if not validation["valid"]:
        print(json.dumps(validation, indent=2))
        return 1
    mapped = {}
    offset = 0
    while True:
        page = service.query("overlord", fields=HEADERS["overlord"], limit=100, offset=offset)
        mapped.update({(r["Path"], r["AssetType"], r["Symbol"]): r for r in page["rows"]})
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    errors = []
    expected = source_assets()
    for row in expected:
        key = (row["Path"], row["AssetType"], row["Symbol"])
        actual = mapped.get(key)
        if actual is None:
            errors.append(f"Off-register source interface: {key}")
        elif any(actual.get(field) != row[field] for field in ("Purpose", "Exports", "Imports")):
            errors.append(f"Source correspondence drift: {key}")
    for key, row in mapped.items():
        if (
            key not in {(r["Path"], r["AssetType"], r["Symbol"]) for r in expected}
            and "#dead" not in row["Tags"].split()
        ):
            errors.append(f"Stale OVR interface: {key}")
    tables, headers = {}, {}
    for name in HEADERS:
        headers[name], tables[name] = parse_csv(
            (ROOT / "TEMPLATES" / f"{name}.PACER.csv").read_bytes(), name
        )
        for row in tables[name]:
            if "#template-example" not in row.get("Tags", "").split():
                errors.append(f"Unmarked worked example: {row['ID']}")
            row["Tags"] = row["Tags"].replace("#template-example", "").strip()
    with tempfile.TemporaryDirectory() as temporary:
        fixture = Path(temporary)
        for row in tables["overlord"]:
            path = fixture / row["Path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        report = validate_web(tables, fixture, headers)
        errors.extend(report["errors"])
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "valid": True,
                "source_interfaces": len(expected),
                "examples": sum(map(len, tables.values())),
                "revision": validation["revision"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
