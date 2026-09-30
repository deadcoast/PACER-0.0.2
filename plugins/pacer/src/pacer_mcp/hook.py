"""Harness adapter: stdin event JSON in, frame text or decision JSON out."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

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
    specific: dict = {"hookEventName": event_name}
    if deny:
        specific["permissionDecision"] = "deny"
        specific["permissionDecisionReason"] = deny
    if context:
        specific["additionalContext"] = context
    return json.dumps({"hookSpecificOutput": specific})


def run(event: str, payload: dict) -> tuple[int, str]:
    """Dispatch one harness event; silent when the cwd is not PACER-governed."""
    code, out = _run(event, payload)
    log = os.environ.get("PACER_HOOK_LOG")
    if log:
        try:
            with open(log, "a", encoding="utf-8") as stream:
                record = {
                    "event": event,
                    "cwd": payload.get("cwd"),
                    "tool": payload.get("tool_name"),
                    "source": payload.get("source"),
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
        path = edit_path(str(payload.get("tool_name", "")), payload.get("tool_input") or {}, root)
        if not path:
            return 0, ""
        if event == "pre-edit":
            decision = service.edit_decision(path)
            deny = decision["reason"] if decision["deny"] else ""
            return 0, hook_output(name, service.frame("edit", focus=path), deny=deny)
        return 0, hook_output(name, service.touch(path, actor))
    result = service.stop(actor)
    return 0, hook_output(name, result["text"], block=result["block"])
