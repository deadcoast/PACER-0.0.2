"""Compare matched facts through real Codex turns; retain inputs and every attempt.

Official method: https://learn.chatgpt.com/docs/non-interactive-mode
This is a small serialization experiment, not proof of long-term agent accuracy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from pacer_mcp.context import expand_context
from pacer_mcp.semantics import canonical
from pacer_mcp.service import Service

ROOT = Path(__file__).resolve().parents[1]
INSTRUCTIONS = """Closed-book PACER decision task. Use only the supplied facts. Do not call tools.
All serializations contain equivalent facts. A columnar table has columns and matching row cells.
Decide whether the indicated task may transition REVIEW to DONE now. Report blockers as exact IDs:
include each task's non-DONE hard dependency and each applicable rule whose result is not PASS,
freshness is not CURRENT, or requirement status is not VALIDATED_COMPLETE. Soft dependencies do
not block. Choose next_action by precedence: UNRESOLVED rule => resolve; FAIL => implement;
otherwise stale/unbound acceptance => verify; otherwise open hard task dependency => resolve;
otherwise review. impacted_assets must equal the supplied impacted set. Do not invent blockers.
Return only the requested JSON decision. Facts follow:
"""
ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "may_complete": {"type": "boolean"},
        "blockers": {"type": "array", "items": {"type": "string"}},
        "next_action": {"type": "string", "enum": ["resolve", "implement", "verify", "review"]},
        "impacted_assets": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["may_complete", "blockers", "next_action", "impacted_assets"],
}


def render_formats(packet: dict) -> dict[str, str]:
    """Render identical facts as columnar JSON, row objects and ordinary Markdown tables."""
    expanded = expand_context(packet)
    row_tables = {
        name: [dict(zip(table["columns"], row, strict=True)) for row in table["rows"]]
        for name, table in expanded["tables"].items()
    }
    metadata = {key: value for key, value in expanded.items() if key != "tables"}
    markdown = ["# Task context", "", "```json", canonical(metadata), "```", ""]
    for name, table in packet["tables"].items():
        markdown.extend(
            [
                f"## {name}",
                "",
                "| " + " | ".join(table["columns"]) + " |",
                "| " + " | ".join("---" for _ in table["columns"]) + " |",
            ]
        )
        for row in table["rows"]:
            cells = [canonical(value).replace("|", "&#124;") for value in row]
            markdown.append("| " + " | ".join(cells) + " |")
        markdown.append("")
    return {
        "operational": canonical(packet),
        "row_json": canonical({**metadata, "tables": row_tables}),
        "markdown": "\n".join(markdown),
    }


def score_answer(answer: dict, expected: dict) -> dict:
    """Score decisions independently of array ordering while rejecting extra or missing facts."""
    if not isinstance(answer, dict):
        return {"correct": False, "fields": {}}
    fields = {
        key: (
            sorted(answer.get(key, [])) == sorted(value)
            if isinstance(value, list) and isinstance(answer.get(key), list)
            else answer.get(key) == value
        )
        for key, value in expected.items()
    }
    return {"correct": all(fields.values()) and set(answer) == set(expected), "fields": fields}


def prepare_cases(parent: Path) -> list[dict]:
    """Construct four executable states, including a current positive control and hard blocker."""
    cases = []
    for name in ("current", "stale", "regressed", "unresolved"):
        root = parent / name
        root.mkdir(parents=True)
        (root / "README.md").write_text("Retry service; source wording governs.", encoding="utf-8")
        (root / "AGENTS.md").write_text("Use PACER; verify before DONE.", encoding="utf-8")
        (root / "settings.json").write_text('{"retries":3}', encoding="utf-8")
        service = Service(root)
        service.initialize()

        def apply(operations, *, intake=False, service=service):
            receipt = service.onboard()
            service.apply(
                operations,
                actor="evaluation",
                revision=receipt["revision"],
                onboarding=receipt["onboarding"],
                context=(
                    None if intake else service.context("PAC-001", max_bytes=100_000)["receipt"]
                ),
            )

        apply(
            [
                {
                    "op": "add",
                    "register": "overlord",
                    "row": {
                        "ID": "OVR-007",
                        "AssetType": "FILE",
                        "Path": "settings.json",
                        "Purpose": "Retry settings",
                    },
                }
            ],
            intake=True,
        )
        tasks = [
            {
                "ID": "PAC-001",
                "Title": "Maintain retries",
                "DoD": "Current verified retry contract",
                "OVRRefs": "OVR-007",
                "Instructions": "Preserve original requirement wording.",
            }
        ]
        if name == "regressed":
            tasks[0].update(BlockedBy="PAC-002", DependencyType="hard")
            tasks.append({"ID": "PAC-002", "Title": "Review caller", "DoD": "Caller inspected"})
        apply(
            [
                {
                    "op": "pace",
                    "nodule": {
                        "ID": "NDL-001",
                        "NoduleName": "retry",
                        "Lane": "main",
                        "Intent": "Maintain retry contract",
                        "TargetOVR": "OVR-007",
                        "ContextPolicy": "REQUIRED",
                        "UserRequest": "Retries must be at least 2.",
                        "AbsorptionCriteria": "Tasks and current rule verified",
                    },
                    "tasks": tasks,
                    "requirements": [
                        {
                            "ID": "OGM-001",
                            "Title": "Lower bound",
                            "Requirement": "Retries must be at least 2.",
                            "Authority": "UNRESOLVED" if name == "unresolved" else "USER",
                            "OriginText": "Retries must be at least 2.",
                            "RuleType": "json_ge",
                            "RuleSubject": "OVR-007",
                            "RuleSelector": "/retries",
                            "RuleValue": "2",
                            "OVRRefs": "OVR-007",
                        }
                    ],
                }
            ],
            intake=True,
        )
        if name != "unresolved":
            apply([{"op": "verify", "id": "OGM-001", "evidence": "Fixture rule evaluated"}])
        apply(
            [
                {"op": "transition", "id": "PAC-001", "status": "DOING"},
                {"op": "transition", "id": "PAC-001", "status": "REVIEW"},
                {"op": "checkpoint", "id": "PAC-001", "next_action": "review"},
            ]
        )
        if name in {"stale", "regressed"}:
            (root / "settings.json").write_text(
                '{"retries":' + ("4" if name == "stale" else "0") + "}", encoding="utf-8"
            )
        packet = service.context("PAC-001", max_bytes=100_000)
        assert packet["complete"]
        # Exclude write receipts, byte-accounting and checkpoint hashes uniformly.
        packet = {
            key: value
            for key, value in packet.items()
            if key not in {"receipt", "required_bytes", "delta"}
        }
        expected = {
            "may_complete": name == "current",
            "blockers": []
            if name == "current"
            else (["OGM-001", "PAC-002"] if name == "regressed" else ["OGM-001"]),
            "next_action": {
                "current": "review",
                "stale": "verify",
                "regressed": "implement",
                "unresolved": "resolve",
            }[name],
            "impacted_assets": ["OVR-007"],
        }
        cases.append({"name": name, "packet": packet, "expected": expected})
    return cases


def run_trial(
    executable: str,
    prompt: str,
    directory: Path,
    cwd: str,
    model: str,
    effort: str,
    *,
    answer_schema: dict | None = None,
) -> dict:
    """Run one recorded attempt; retain failures and never retry an ambiguous model request."""
    directory.mkdir()
    (directory / "input.txt").write_text(prompt, encoding="utf-8")
    schema = directory / "schema.json"
    schema.write_text(
        canonical(ANSWER_SCHEMA if answer_schema is None else answer_schema), encoding="utf-8"
    )
    output = directory / "answer.json"
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
        f"model_reasoning_effort={effort}",
        "--output-schema",
        str(schema),
        "-o",
        str(output),
        "-",
    ]
    attempt = {
        "status": "started",
        "command": command,
        "input_bytes": len(prompt.encode("utf-8")),
        "input_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }
    (directory / "attempt.json").write_text(canonical(attempt), encoding="utf-8")
    started = time.monotonic()
    with (
        (directory / "events.jsonl").open("wb") as stdout,
        (directory / "stderr.log").open("wb") as stderr,
    ):
        process = subprocess.Popen(
            command, cwd=cwd, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr
        )
        try:
            process.communicate(prompt.encode("utf-8"), timeout=180)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                process.kill()
            process.wait()
            attempt["status"] = "timeout"
    events = []
    for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    tools = [
        event
        for event in events
        if event.get("item", {}).get("type")
        in {"command_execution", "mcp_tool_call", "web_search", "file_change"}
    ]
    usage = [event["usage"] for event in events if event.get("type") == "turn.completed"]
    answer = None
    if output.is_file():
        try:
            answer = json.loads(output.read_text(encoding="utf-8"))
        except ValueError:
            pass
    attempt.update(
        returncode=process.returncode,
        seconds=round(time.monotonic() - started, 3),
        usage=usage,
        tool_events=len(tools),
        answer=answer,
    )
    if attempt["status"] == "started":
        attempt["status"] = (
            "completed" if process.returncode == 0 and answer is not None else "failed"
        )
    (directory / "attempt.json").write_text(canonical(attempt), encoding="utf-8")
    return attempt


def main() -> None:
    """Freeze matched cases, randomize order and report observed accuracy, bytes and usage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--repetitions", type=int, default=2, choices=range(1, 6))
    args = parser.parse_args()
    executable = shutil.which("codex.cmd" if os.name == "nt" else "codex")
    if not executable:
        raise RuntimeError("Existing Codex CLI required")
    trial = ROOT / ".cache/e" / uuid4().hex[:8]
    trial.mkdir(parents=True)
    cases = prepare_cases(trial / "fixtures")
    (trial / "cases.json").write_text(canonical(cases), encoding="utf-8")
    queue = [
        (case, arm, text, repeat)
        for case in cases
        for arm, text in render_formats(case["packet"]).items()
        for repeat in range(args.repetitions)
    ]
    random.Random(314159).shuffle(queue)
    report = {
        "model": args.model,
        "effort": args.effort,
        "repetitions": args.repetitions,
        "method": "matched facts and instructions; randomized serialization order seed 314159",
        "limitations": [
            "Four synthetic states; not long-term development or a population estimate.",
            "Row JSON and Markdown are equivalent-fact renditions, not historical v0.2 behavior.",
            "Full input usage includes constant Codex overhead and may contain cache effects.",
        ],
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "results": [],
    }
    print(str(trial), flush=True)
    with tempfile.TemporaryDirectory(prefix="pacer-eval-") as cwd:
        for number, (case, arm, text, repeat) in enumerate(queue, 1):
            label = f"{number:02d}-{case['name']}-{arm}-{repeat}"
            print("start " + label, flush=True)
            result = run_trial(
                executable, INSTRUCTIONS + text, trial / label, cwd, args.model, args.effort
            )
            result.update(
                case=case["name"],
                arm=arm,
                repetition=repeat,
                score=score_answer(result["answer"], case["expected"]),
            )
            report["results"].append(result)
            (trial / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(
                f"{label}: {result['status']} correct={result['score']['correct']} "
                f"tools={result['tool_events']}",
                flush=True,
            )
            if result["status"] != "completed":
                raise RuntimeError(
                    "Evaluation stopped after failed/ambiguous request; retained evidence, no retry"
                )
    print("report " + str(trial / "report.json"), flush=True)


if __name__ == "__main__":
    main()
