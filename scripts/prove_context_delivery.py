"""Retain two real Codex MCP turns: paged checkpoint and fresh-thread regression retrieval.

Uses documented codex exec JSONL/output-schema and explicit stdio configuration.
The existing authenticated CLI and uv environment are required. Each attempt is
written before execution; failures and timeouts stop the proof without retries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from evaluate_context import prepare_cases
from pacer_mcp.pages import assemble_context_pages
from pacer_mcp.semantics import canonical
from pacer_mcp.service import Service

ROOT = Path(__file__).resolve().parents[1]
ANSWER = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "checkpointed": {"type": "boolean"},
        "next_action": {"type": "string"},
        "rule_result": {"type": "string"},
        "freshness": {"type": "string"},
        "may_complete": {"type": "boolean"},
        "changed_sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "checkpointed",
        "next_action",
        "rule_result",
        "freshness",
        "may_complete",
        "changed_sources",
    ],
}


def inspect_delivery(events: list[dict], expected: dict, *, checkpoint: bool) -> dict:
    """Verify actual ordered tool outputs and the receipt submitted to the writer."""
    for event in events:
        if event.get("type") == "item.completed" and event.get("item", {}).get("type") not in {
            "agent_message",
            "reasoning",
            "mcp_tool_call",
        }:
            raise ValueError("Native model used a tool outside the declared proof")
    calls = [
        e["item"]
        for e in events
        if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "mcp_tool_call"
    ]
    if not calls or calls[0]["tool"] != "pacer_onboard":
        raise ValueError("Native workflow must start with onboarding")
    pages: list[dict] = []
    applies: list[dict] = []
    onboard: dict | None = None
    for call in calls:
        if call["tool"] not in {"pacer_onboard", "pacer_context_page", "pacer_apply"}:
            raise ValueError("Native model used an undeclared MCP tool")
        if call.get("status") != "completed" or call.get("error"):
            raise ValueError("Native MCP call failed")
        result = call.get("result") or {}
        if result.get("isError"):
            raise ValueError("Native MCP result is an error")
        arguments = call["arguments"]
        if arguments.get("root") != expected["receipt"]["root"]:
            raise ValueError("Native tool used the wrong project root")
        if call["tool"] == "pacer_onboard":
            onboard = result.get("structured_content") or result.get("structuredContent")
            if not onboard:
                onboard = json.loads(
                    next(i["text"] for i in result["content"] if i["type"] == "text")
                )
            if (
                not onboard["validation"]["valid"]
                or not onboard["revision"]
                or not onboard["onboarding"]
            ):
                raise ValueError("Native onboarding is invalid")
        if call["tool"] == "pacer_context_page":
            if arguments.get("id") != expected["task"] or arguments.get("max_bytes") != 2048:
                raise ValueError("Native page used the wrong task or page budget")
            payload = result.get("structured_content") or result.get("structuredContent")
            text = next(item["text"] for item in result["content"] if item["type"] == "text")
            payload = payload or json.loads(text)
            if json.loads(text) != payload or len(text.encode()) > 2048:
                raise ValueError("Native page text failed its delivery bound")
            wanted = pages[-1]["next_cursor"] if pages else ""
            if call["arguments"].get("cursor", "") != wanted:
                raise ValueError("Native model skipped or repeated a cursor")
            pages.append(payload)
        elif call["tool"] == "pacer_apply":
            if (
                onboard is None
                or any(arguments.get(key) != onboard[key] for key in ("revision", "onboarding"))
                or arguments.get("actor") != "native-delivery"
            ):
                raise ValueError("Native writer did not use current onboarding and actor")
            applies.append(call)
            if not pages or not pages[-1]["complete"]:
                raise ValueError("Native model wrote before complete retrieval")
    packet = assemble_context_pages(pages)
    if packet != expected or len(pages) < 2:
        raise ValueError("Native stream did not reconstruct the frozen complete packet")
    if checkpoint:
        if (
            len(applies) != 1
            or applies[0]["arguments"]["operations"]
            != [{"op": "checkpoint", "id": "PAC-001", "next_action": "verify"}]
            or applies[0]["arguments"]["context"] != packet["receipt"]
        ):
            raise ValueError("Native checkpoint did not submit the issued current receipt")
    elif applies:
        raise ValueError("Read-only resumption unexpectedly wrote state")
    return {
        "pages": len(pages),
        "packet_digest": pages[0]["packet_digest"],
        "page_bytes": [len(canonical(p).encode()) for p in pages],
        "tool_calls": [c["tool"] for c in calls],
        "exact_roundtrip": True,
    }


def run_turn(
    executable: str,
    plugin: Path,
    root: Path,
    directory: Path,
    cwd: str,
    model: str,
    effort: str,
    *,
    checkpoint: bool,
) -> dict:
    """Run one bounded authenticated CLI attempt and preserve outputs even on failure."""
    directory.mkdir()
    expected = Service(root).context("PAC-001", max_bytes=1_000_000)
    action = (
        "After reading every page, submit exactly one pacer_apply operation: "
        '{"op":"checkpoint","id":"PAC-001","next_action":"verify"}. '
        'Use actor="native-delivery", current onboarding/revision, and the final page receipt. '
        'Report checkpointed=true and next_action="verify" after success.'
        if checkpoint
        else "This is a fresh thread. Read only: do not call any mutation tool. "
        "Report the persisted "
        "next_action and current rule result/freshness and delta. Set checkpointed=false."
    )
    prompt = (
        f"Exercise the real PACER tools for task PAC-001 in project {root}. "
        "Use only pacer_onboard, pacer_context_page and (when requested) pacer_apply. "
        "Do not use shell, web, other tools or direct context retrieval. "
        "Call pacer_onboard then pacer_context_page with max_bytes=2048 and empty cursor. "
        "Follow every next_cursor with the same root/id/max_bytes until complete=true. "
        "Entries carry JSON paths: value sets that path; append continues a string at that path. "
        "Read all entries; no receipt is available on partial pages. "
        + action
        + " Report OGM-001 rule_result and freshness from the retrieved packet; "
        "may_complete requires PASS/CURRENT, VALIDATED_COMPLETE and no hard blockers. "
        "Report changed_sources from that packet delta exactly. "
        "Do not complete or absorb anything. "
        "Authority files supplied verbatim below:\n"
        + "\n".join(
            f"{name}:\n{(root / name).read_text(encoding='utf-8')}"
            for name in ("README.md", "AGENTS.md")
        )
    )
    (directory / "prompt.txt").write_text(prompt, encoding="utf-8")
    (directory / "schema.json").write_text(canonical(ANSWER), encoding="utf-8")
    (directory / "expected.json").write_text(canonical(expected), encoding="utf-8")
    command = [
        executable,
        "exec",
        "--ignore-user-config",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--json",
        "--model",
        model,
        "-c",
        f"model_reasoning_effort={json.dumps(effort)}",
        "-c",
        f"mcp_servers.pacer.command={json.dumps(sys.executable)}",
        "-c",
        "mcp_servers.pacer.args="
        + json.dumps(["-m", "pacer_mcp.cli", "serve", "--root", str(root)]),
        "-c",
        "mcp_servers.pacer.env={PYTHONPATH=" + json.dumps(str(plugin / "src")) + "}",
        "-c",
        "mcp_servers.pacer.required=true",
        "-c",
        'mcp_servers.pacer.enabled_tools=["pacer_onboard","pacer_context_page","pacer_apply"]',
        "--output-schema",
        str(directory / "schema.json"),
        "-o",
        str(directory / "answer.json"),
        "-",
    ]
    attempt = {
        "status": "started",
        "command": command,
        "model": model,
        "effort": effort,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "prompt_bytes": len(prompt.encode()),
    }
    (directory / "attempt.json").write_text(canonical(attempt), encoding="utf-8")
    started = time.monotonic()
    process = None
    try:
        with (
            (directory / "events.jsonl").open("wb") as stdout,
            (directory / "stderr.log").open("wb") as stderr,
        ):
            process = subprocess.Popen(
                command, cwd=cwd, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr
            )
            try:
                process.communicate(prompt.encode(), timeout=300)
            except subprocess.TimeoutExpired:
                attempt["status"] = "timeout"
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                    )
                else:
                    process.kill()
                process.wait()
        attempt.update(returncode=process.returncode, seconds=round(time.monotonic() - started, 3))
        events = [
            json.loads(line)
            for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        attempt["usage"] = [e["usage"] for e in events if e.get("type") == "turn.completed"]
        if process.returncode or attempt["status"] == "timeout":
            raise ValueError("Codex turn did not complete")
        attempt["delivery"] = inspect_delivery(events, expected, checkpoint=checkpoint)
        answer = json.loads((directory / "answer.json").read_text(encoding="utf-8"))
        rule = next(r for r in expected["rules"] if r["id"] == "OGM-001")
        wanted = {
            "checkpointed": checkpoint,
            "next_action": "verify",
            "rule_result": rule["result"],
            "freshness": rule["freshness"],
            "may_complete": checkpoint,
            "changed_sources": expected["delta"]["changed_sources"],
        }
        if answer != wanted:
            raise ValueError("Native answer mismatched observed state")
        attempt.update(status="passed", answer=answer)
    except (ValueError, KeyError, TypeError, StopIteration, OSError) as exc:
        attempt.update(
            status="failed" if attempt["status"] != "timeout" else "timeout", error=str(exc)
        )
    finally:
        attempt.update(
            returncode=process.returncode if process else None,
            seconds=round(time.monotonic() - started, 3),
        )
        (directory / "attempt.json").write_text(canonical(attempt), encoding="utf-8")
    return attempt


def main() -> None:
    """Freeze fixture state, prove actual checkpoint persistence, then start a new model thread."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    args = parser.parse_args()
    executable = shutil.which("codex.cmd" if os.name == "nt" else "codex")
    if not executable:
        raise RuntimeError("Installed Codex CLI required")
    trial = ROOT / ".cache/p" / uuid4().hex[:8]
    trial.mkdir(parents=True)
    prepare_cases(trial / "fixtures")
    root = trial / "fixtures/current"
    attempts: list[dict] = []
    report = {
        "trial": str(trial),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "plugin": str(args.plugin.resolve()),
        "attempts": attempts,
        "passed": False,
        "limitations": [
            "Two instructed native tool-use turns in one synthetic fixture; "
            "not autonomous development or a population accuracy estimate.",
            "Fresh Codex thread and MCP process recover durable PACER state; "
            "no long-conversation or long-term retention advantage measured.",
            "Explicit documented stdio configuration points to installed plugin source; "
            "ordinary installed plugin discovery is checked separately.",
        ],
    }
    print(str(trial), flush=True)
    with tempfile.TemporaryDirectory(prefix="pacer-delivery-") as cwd:
        for number, checkpoint in enumerate((True, False), 1):
            attempt = run_turn(
                executable,
                args.plugin.resolve(),
                root,
                trial / f"{number:02d}",
                cwd,
                args.model,
                args.effort,
                checkpoint=checkpoint,
            )
            attempts.append(attempt)
            (trial / "report.json").write_text(canonical(report), encoding="utf-8")
            print(
                json.dumps(
                    {"stage": number, "status": attempt["status"], "error": attempt.get("error")}
                ),
                flush=True,
            )
            if attempt["status"] != "passed":
                raise RuntimeError("Native delivery proof failed; attempt retained, no retry")
            service = Service(root)
            assert service.query("todo", where={"ID": "PAC-001"}, fields=["Status", "NextAction"])[
                "rows"
            ] == [{"Status": "REVIEW", "NextAction": "verify"}]
            if checkpoint:
                report["checkpoint_snapshot"] = json.loads(
                    service.query("todo", where={"ID": "PAC-001"}, fields=["ContextCheckpoint"])[
                        "rows"
                    ][0]["ContextCheckpoint"]
                )
                (root / "settings.json").write_text('{"retries":0}', encoding="utf-8")
                assert service.evaluate("OGM-001")["result"] == "FAIL"
        report["passed"] = True
        (trial / "report.json").write_text(canonical(report), encoding="utf-8")
    print(json.dumps({"passed": True, "report": str(trial / "report.json")}), flush=True)


if __name__ == "__main__":
    main()
