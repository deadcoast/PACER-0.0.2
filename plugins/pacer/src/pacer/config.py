"""The project frame: `.pacer/project.pacer.toml`.

One small file of settings. Everything has a default, so a project that never
edits it still works; its presence is what marks a directory as governed.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pacer.layout import FORMAT, Layout
from pacer.schema import TIERS

BUDGETS = {"session": 4000, "prompt": 2000, "edit": 1500, "stop": 1000}
PROVIDERS = ("auto", "codegraph", "builtin", "none")
BUDGET_RANGE = (256, 64000)
PROBE_TIMEOUT = 120
PROBE_TIMEOUT_RANGE = (1, 3600)

TEMPLATE = """\
# PACER project frame. Every key is optional; these are the defaults.
format = "{format}"

[project]
name = "{name}"
# sketch | prototype | playable | integrated | release | protected
# sketch..playable never block; integrated blocks a stop on a FAILED probe;
# release also blocks on STALE evidence; protected denies edits without a USER latch.
tier = "{tier}"

[provider]
# Where derived source structure comes from:
# auto (codegraph when .codegraph/ exists, else builtin) | codegraph | builtin | none
name = "auto"
# Directories the builtin scanner skips, relative to the project root.
exclude = []

[frames]
# Byte budget per frame. The spine always fits; the rest fills by relevance.
session = {session}
prompt = {prompt}
edit = {edit}
stop = {stop}

[probe]
# Seconds a requirement's Probe may run before it is stopped and recorded as exit 124.
timeout = {timeout}
"""


def default_config(root: Path) -> dict:
    return {
        "format": FORMAT,
        "project": root.resolve().name,
        "tier": "prototype",
        "provider": "auto",
        "exclude": [],
        "budgets": dict(BUDGETS),
        "probe_timeout": PROBE_TIMEOUT,
    }


def render_config(name: str, tier: str = "prototype", budgets: dict | None = None) -> str:
    """Text of a fresh project frame."""
    sizes = BUDGETS | (budgets or {})
    return TEMPLATE.format(format=FORMAT, name=name, tier=tier, timeout=PROBE_TIMEOUT, **sizes)


def _table(data: dict, key: str) -> dict:
    """A TOML table by name; anything else counts as absent."""
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def read_config(root: Path) -> dict:
    """Parse the project frame; unreadable or out-of-range values fall back to defaults."""
    config = default_config(root)
    path = Layout(root).config
    if not path.is_file():
        return config
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError):
        return config
    config["format"] = str(data.get("format", FORMAT))
    project = _table(data, "project")
    if isinstance(project.get("name"), str) and project["name"].strip():
        config["project"] = project["name"].strip()
    if project.get("tier") in TIERS:
        config["tier"] = project["tier"]
    provider = _table(data, "provider")
    if provider.get("name") in PROVIDERS:
        config["provider"] = provider["name"]
    exclude = provider.get("exclude")
    if isinstance(exclude, list) and all(isinstance(e, str) for e in exclude):
        config["exclude"] = [e.strip("/") for e in exclude if e.strip("/")]
    frames = _table(data, "frames")
    low, high = BUDGET_RANGE
    for key in BUDGETS:
        value = frames.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high:
            config["budgets"][key] = value
    timeout = _table(data, "probe").get("timeout")
    low, high = PROBE_TIMEOUT_RANGE
    if isinstance(timeout, int) and not isinstance(timeout, bool) and low <= timeout <= high:
        config["probe_timeout"] = timeout
    return config
