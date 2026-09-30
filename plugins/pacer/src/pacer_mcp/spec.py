"""Project frame: the only doctrine file. An absent file means defaults."""

from __future__ import annotations

import tomllib
from pathlib import Path

DEFAULT_BUDGETS = {"session": 4000, "prompt": 2000, "edit": 1500, "stop": 1000}


def read_spec(root: Path) -> dict:
    spec = {
        "project": root.resolve().name,
        "tier": "prototype",
        "provider": "auto",
        "budgets": dict(DEFAULT_BUDGETS),
    }
    path = root / ".MIVIM.spec"
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            return spec
        project = data.get("project", {})
        spec["project"] = str(project.get("name", spec["project"]))
        spec["tier"] = str(project.get("tier", spec["tier"]))
        spec["provider"] = str(data.get("provider", {}).get("name", spec["provider"]))
        for key in DEFAULT_BUDGETS:
            value = data.get("frames", {}).get(key)
            if isinstance(value, int) and 256 <= value <= 64000:
                spec["budgets"][key] = value
    return spec
