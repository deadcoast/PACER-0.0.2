"""Verify style, tests and register validity before a commit."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "pacer" / "src"))

from pacer_mcp.service import Service  # noqa: E402


def main() -> int:
    """Fail before commit if lint, tests or the register web fail."""
    basetemp = Path(tempfile.gettempdir()) / "claude" / "pacer-check"
    basetemp.mkdir(parents=True, exist_ok=True)
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
        [
            sys.executable,
            "-m",
            "pytest",
            "plugins/pacer/tests",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp={basetemp}",
        ],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    report = Service(ROOT).validate()
    if not report["valid"]:
        print(json.dumps(report, indent=2))
        return 1
    unpurposed = [w for w in report["warnings"] if "#unpurposed" in w]
    print(f"registers valid; {len(unpurposed)} #unpurposed asset rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
