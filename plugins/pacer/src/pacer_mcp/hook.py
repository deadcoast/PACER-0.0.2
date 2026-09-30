"""Harness adapter: stdin event JSON in, frame text or decision JSON out."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

from filelock import FileLock, Timeout

PATCH_FILE = re.compile(r"^\*\*\* (?:Update|Add) File: (.+)$", re.MULTILINE)
EVENTS = {
    "session-start": "SessionStart",
    "prompt": "UserPromptSubmit",
    "pre-edit": "PreToolUse",
    "post-edit": "PostToolUse",
    "stop": "Stop",
}


def find_root(cwd: Path) -> Path | None:
    """The nearest ancestor holding a todo register; None means PACER does not govern here."""
    for candidate in (cwd.resolve(), *cwd.resolve().parents):
        if (candidate / "todo.PACER.csv").is_file():
            return candidate
    return None


def edit_path(tool_name: str, tool_input: dict, root: Path) -> str | None:
    """Repo-relative POSIX path for Claude Edit/Write/NotebookEdit or Codex apply_patch."""
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw and tool_name == "apply_patch":
        text = tool_input.get("command") or tool_input.get("patch") or tool_input.get("input") or ""
        match = PATCH_FILE.search(str(text))
        raw = match.group(1).strip() if match else None
    if not raw:
        return None
    path = Path(raw)
    try:
        rel = path.resolve().relative_to(root.resolve()) if path.is_absolute() else path
    except ValueError:
        return None
    return rel.as_posix()


def hook_output(event_name: str, context: str, *, deny: str = "", block: bool = False) -> str:
    """SessionStart is plain stdout; others use hookSpecificOutput; never emits allow."""
    if event_name == "SessionStart":
        return context
    if event_name == "Stop":
        # A non-blocking stop stays silent: any Stop output re-prompts the model
        # and produces empty "no change" turns. The checkpoint is already written.
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


def worktree_changes(root: Path) -> list[str]:
    """Modified or untracked source paths, so shell-driven edits are still recorded."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    paths = []
    for line in out.stdout.splitlines():
        if len(line) < 4 or line[0] == "D" or line[1] == "D":
            continue
        rel = line[3:].split(" -> ")[-1].strip().strip('"')
        if rel.endswith(".PACER.csv") or rel.endswith(".PACER.jsonl") or rel.startswith(".pacer/"):
            continue
        if rel.endswith("/") or "/." in f"/{rel}":
            continue
        paths.append(rel)
    return sorted(set(paths))[:20]


DEDUPE_WINDOW = 3.0


def event_key(event: str, payload: dict) -> str:
    """Identity of one harness event; identical payloads from a second plugin copy collide."""
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


def seen_recently(root: Path, key: str, window: float = DEDUPE_WINDOW) -> bool:
    """Record the key under a lock; True when the same key was recorded inside the window.

    Two installed copies of the plugin, or a harness that fires an event twice, call the
    hook with the same payload within milliseconds; only the first delivers a frame.
    """
    state = root / ".pacer"
    try:
        state.mkdir(exist_ok=True)
        with FileLock(state / "hook.lock", timeout=2):
            path = state / "hook-seen.json"
            now = time.time()
            try:
                seen = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                seen = {}
            seen = {k: t for k, t in seen.items() if isinstance(t, int | float) and now - t < 60}
            duplicate = key in seen and now - seen[key] < window
            if not duplicate:
                seen[key] = now
            path.write_text(json.dumps(seen), encoding="utf-8")
            return duplicate
    except (OSError, Timeout):
        return False


def run(event: str, payload: dict) -> tuple[int, str]:
    """Dispatch one harness event; silent when the cwd is not governed or the event repeats."""
    root = find_root(Path(payload.get("cwd") or Path.cwd()))
    deduped = root is not None and seen_recently(root, event_key(event, payload))
    code, out = (0, "") if deduped else _run(event, payload)
    log = os.environ.get("PACER_HOOK_LOG")
    if log:
        try:
            with open(log, "a", encoding="utf-8") as stream:
                record = {
                    "event": event,
                    "cwd": payload.get("cwd"),
                    "tool": payload.get("tool_name"),
                    "source": payload.get("source"),
                    "deduped": deduped,
                    "exit": code,
                    "out": out,
                }
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass
    return code, out


def _run(event: str, payload: dict) -> tuple[int, str]:
    from pacer_mcp.service import Service

    if event not in EVENTS:
        return 2, f"unknown hook event {event}"
    root = find_root(Path(payload.get("cwd") or Path.cwd()))
    if root is None:
        return 0, ""
    service = Service(root)
    name = EVENTS[event]
    actor = "hook"
    if event == "session-start":
        return 0, hook_output(name, service.frame("session"))
    if event == "prompt":
        prompt = str(payload.get("prompt") or payload.get("user_prompt") or "")
        return 0, hook_output(name, service.frame("prompt", focus=prompt))
    if event in {"pre-edit", "post-edit"}:
        tool = str(payload.get("tool_name", ""))
        path = edit_path(tool, payload.get("tool_input") or {}, root)
        if event == "pre-edit":
            if not path:
                return 0, ""
            decision = service.edit_decision(path)
            deny = decision["reason"] if decision["deny"] else ""
            return 0, hook_output(name, service.frame("edit", focus=path), deny=deny)
        paths = [path] if path else (worktree_changes(root) if tool == "Bash" else [])
        lines = [service.touch(p, actor) for p in paths]
        return 0, hook_output(name, "\n".join(line for line in lines if line))
    result = service.stop(actor)
    return 0, hook_output(name, result["text"], block=result["block"])
