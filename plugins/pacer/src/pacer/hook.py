"""Harness adapter: one event's JSON on stdin, frame text or decision JSON on stdout.

Claude Code and Codex call the same entry point. The adapter stays silent when
the working directory is not governed, when an event repeats, and when there is
nothing to say; a hook that talks without cause costs the agent context.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

from pacer.layout import STATE_DIR, Layout, find_root
from pacer.lock import FileLock, LockTimeout

EVENTS = {
    "session-start": "SessionStart",
    "prompt": "UserPromptSubmit",
    "pre-edit": "PreToolUse",
    "post-edit": "PostToolUse",
    "stop": "Stop",
}
PATCH_FILE = re.compile(r"^\*\*\* (?:Update|Add) File: (.+)$", re.MULTILINE)
DEDUPE_WINDOW = 3.0
SCAN_LIMIT = 200
PAIR_LIMIT = 50


def edit_path(tool_name: str, tool_input: dict, root: Path) -> str | None:
    """Project-relative path of an edit: Claude's Edit/Write/NotebookEdit, Codex's apply_patch."""
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw and tool_name == "apply_patch":
        text = tool_input.get("command") or tool_input.get("patch") or tool_input.get("input") or ""
        match = PATCH_FILE.search(str(text))
        raw = match.group(1).strip() if match else None
    if not raw:
        return None
    path = Path(raw)
    try:
        inside = path.resolve().relative_to(root.resolve()) if path.is_absolute() else path
    except ValueError:
        return None
    rel = inside.as_posix()
    return None if rel == STATE_DIR or rel.startswith(STATE_DIR + "/") else rel


def hook_output(event_name: str, context: str, *, deny: str = "", block: bool = False) -> str:
    """Shape a reply for the harness. Never grants permission; only adds context or refuses."""
    if event_name == "SessionStart":
        return context
    if event_name == "Stop":
        # Any output from a non-blocking Stop re-prompts the model into empty turns.
        return json.dumps({"decision": "block", "reason": context}) if block else ""
    if not context and not deny:
        return ""
    specific: dict = {"hookEventName": event_name}
    if deny:
        specific["permissionDecision"] = "deny"
        specific["permissionDecisionReason"] = deny
    if context:
        specific["additionalContext"] = context
    return json.dumps({"hookSpecificOutput": specific})


# -- repeated events ---------------------------------------------------------
def event_key(event: str, payload: dict) -> str:
    """Identity of one harness event; a second copy of the plugin sends the same payload."""
    basis = {
        "event": event,
        "session": payload.get("session_id", ""),
        "source": payload.get("source", ""),
        "tool_use": payload.get("tool_use_id", ""),
        "tool": payload.get("tool_name", ""),
        "input": payload.get("tool_input", {}),
        "prompt": payload.get("prompt") or payload.get("user_prompt") or "",
    }
    digest = hashlib.sha256(json.dumps(basis, sort_keys=True, default=str).encode())
    return digest.hexdigest()[:16]


class HookState:
    """Small per-project memory under run/: which events and file versions were already seen."""

    def __init__(self, root: Path):
        self.layout = Layout(root)
        self.path = self.layout.hook_state

    def _update(self, change):
        try:
            with FileLock(self.layout.run / "hook.lock", timeout=2.0):
                try:
                    state = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    state = {}
                result = change(state)
                self.path.write_text(json.dumps(state), encoding="utf-8")
                return result
        except (OSError, LockTimeout):
            return None

    def seen_recently(self, key: str, window: float = DEDUPE_WINDOW) -> bool:
        """Record the event; True when the same event arrived inside the window."""

        def change(state: dict) -> bool:
            now = time.time()
            seen = {k: t for k, t in state.get("seen", {}).items() if now - t < 60}
            duplicate = key in seen and now - seen[key] < window
            if not duplicate:
                seen[key] = now
            state["seen"] = seen
            return duplicate

        return bool(self._update(change))

    def fresh(self, versions: dict[str, int]) -> list[str]:
        """Paths whose on-disk version was not reported before; remembers them."""

        def change(state: dict) -> list[str]:
            known = state.get("versions", {})
            new = [path for path, version in versions.items() if known.get(path) != version]
            state["versions"] = {**known, **versions}
            return new

        return self._update(change) or []


# -- working tree ------------------------------------------------------------
def _git(root: Path, *args: str) -> bytes | None:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def _same_content(root: Path, committed: str, candidate: str) -> bool:
    """True when a working file equals a committed one, whatever the line endings."""
    blob = _git(root, "cat-file", "blob", f"HEAD:{committed}")
    try:
        current = (root / candidate).read_bytes()
    except OSError:
        return False
    return blob is not None and blob.replace(b"\r\n", b"\n") == current.replace(b"\r\n", b"\n")


def worktree(root: Path) -> tuple[dict[str, int], list[tuple[str, str]]]:
    """Changed files with their modification stamp, and renames, from `git status`.

    A staged rename is reported by git. An unstaged move shows as one deletion
    and one untracked file; the two are paired when their content is identical.
    """
    listing = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if listing is None:
        return {}, []
    entries = listing.decode("utf-8", "replace").split("\0")
    changed, deleted, untracked, renames = [], [], [], []
    position = 0
    while position < len(entries):
        entry = entries[position]
        position += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if "R" in code:
            renames.append((entries[position], path))
            position += 1
            changed.append(path)
        elif code == "??":
            untracked.append(path)
        elif "D" in code:
            deleted.append(path)
        else:
            changed.append(path)
    for old in deleted[:PAIR_LIMIT]:
        name = old.rsplit("/", 1)[-1]
        for candidate in (p for p in untracked if p.rsplit("/", 1)[-1] == name):
            if _same_content(root, old, candidate):
                renames.append((old, candidate))
                break
    versions = {}
    for path in [*changed, *untracked][:SCAN_LIMIT]:
        if path == STATE_DIR or path.startswith(STATE_DIR + "/") or path.endswith("/"):
            continue
        try:
            versions[path] = (root / path).stat().st_mtime_ns
        except OSError:
            continue
    return versions, renames


# -- dispatch ----------------------------------------------------------------
def run(event: str, payload: dict) -> tuple[int, str]:
    """Handle one harness event."""
    if event not in EVENTS:
        return 2, f"unknown hook event {event}"
    cwd = Path(payload.get("cwd") or Path.cwd())
    root = find_root(cwd)
    if root is None:
        return 0, _upgrade_notice(cwd) if event == "session-start" else ""
    deduped = HookState(root).seen_recently(event_key(event, payload))
    code, out = (0, "") if deduped else _dispatch(event, payload, root)
    _trace(event, payload, deduped, code, out)
    return code, out


def _upgrade_notice(cwd: Path) -> str:
    """A project still in an older PACER layout gets one line at session start, not silence."""
    from pacer.migrate import detect

    for folder in (cwd, *cwd.parents):
        try:
            source = detect(folder)
        except (OSError, ValueError):
            return ""
        if source:
            return (
                f"PACER: {folder.as_posix()} holds a {source} layout and is not being tracked. "
                "Preview the upgrade with pacer_migrate, then apply it with preview=false."
            )
    return ""


def _dispatch(event: str, payload: dict, root: Path) -> tuple[int, str]:
    from pacer.service import Service

    service = Service(root)
    name = EVENTS[event]
    if event == "session-start":
        return 0, hook_output(name, service.frame("session"))
    if event == "prompt":
        prompt = str(payload.get("prompt") or payload.get("user_prompt") or "")
        return 0, hook_output(name, service.frame("prompt", focus=prompt))
    if event == "stop":
        result = service.stop("hook")
        return 0, hook_output(name, result["text"], block=result["block"])
    tool = str(payload.get("tool_name", ""))
    path = edit_path(tool, payload.get("tool_input") or {}, root)
    if event == "pre-edit":
        if not path:
            return 0, ""
        decision = service.edit_decision(path)
        deny = decision["reason"] if decision["deny"] else ""
        return 0, hook_output(name, service.frame("edit", focus=path), deny=deny)
    if path:
        return 0, hook_output(name, service.record([path], [], "hook", register_new=True))
    versions, renames = worktree(root)
    fresh = HookState(root).fresh(versions)
    if not fresh and not renames:
        return 0, ""
    return 0, hook_output(name, service.record(fresh, renames, "hook", register_new=False))


def _trace(event: str, payload: dict, deduped: bool, code: int, out: str) -> None:
    """Append one line per event to $PACER_HOOK_LOG, for diagnosing a harness integration."""
    log = os.environ.get("PACER_HOOK_LOG")
    if not log:
        return
    record = {
        "event": event,
        "cwd": payload.get("cwd"),
        "tool": payload.get("tool_name"),
        "source": payload.get("source"),
        "keys": sorted(payload),
        "deduped": deduped,
        "exit": code,
        "out": out,
    }
    try:
        with open(log, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass
