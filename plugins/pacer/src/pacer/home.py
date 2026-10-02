"""PACER's user-level home: what is installed, what was last checked, how long things take.

Project state lives in each project's `.pacer/`. This is the other kind: facts
about the installation on this machine, shared by every project. It sits under
the organisation's name so later MIVIM tools have a place beside it:

    Windows   %LOCALAPPDATA%\\mivim\\pacer
    macOS     ~/Library/Application Support/mivim/pacer
    other     $XDG_STATE_HOME/mivim/pacer   (default ~/.local/state)

`PACER_HOME` overrides the location; the tests rely on that.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from pacer.identity import AGENT, ORG
from pacer.lock import FileLock, LockTimeout

T = TypeVar("T")
STATE = "state.json"


def home() -> Path:
    override = os.environ.get("PACER_HOME")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / ORG.lower() / AGENT.lower()


def read_state() -> dict:
    """The stored state; empty when there is none or it cannot be read."""
    try:
        data = json.loads((home() / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def update_state(change: Callable[[dict], T]) -> T | None:
    """Apply `change` to the state under a lock and store it; None when that is not possible."""
    directory = home()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with FileLock(directory / "state.lock", timeout=2.0):
            state = read_state()
            result = change(state)
            scratch = directory / f"{STATE}.{os.getpid()}.tmp"
            scratch.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
            os.replace(scratch, directory / STATE)
            return result
    except (OSError, LockTimeout):
        return None
