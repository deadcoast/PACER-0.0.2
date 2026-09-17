"""Measure matched candidate edits and PACER resumption through documented Codex CLI turns."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from evaluate_context import render_formats, run_trial, score_answer
from pacer_mcp.semantics import canonical
from pacer_mcp.service import Service

ROOT = Path(__file__).resolve().parents[1]
CODE = "def scale(value):\n    return value * 2\n"
REQUIREMENT = "scale(value) returns value multiplied by 2; preserve exported name and argument."
INSTRUCTIONS = """Closed-book bounded development task. Use only supplied facts; do not call tools.
Return a candidate that the host will check and apply to a disposable copy of the frozen project.
All formats carry equivalent facts. Columnar rows follow columns. In pacer-context/2, each relations
edge is [source index, kind index, target index]. Source/target index required_ids;
kind indexes relations.kinds.
Return action: resolve for unresolved intent; implement for broken behavior; verify for correct
behavior with stale/unbound acceptance; review when evidence is current. Respect exact user wording.
Return replacement and path only when implementing: the entire allowed file, no Markdown fences.
For calculator.py preserve scale(value), multiply by 2; add no imports, calls or other definitions.
For settings.json restore minimum to 2. Otherwise path and replacement must both be empty strings.
requirement must copy the operative OGM-001 Requirement exactly. impacted_assets and changed_sources
must copy packet.impacted and packet.delta.changed_sources exactly. may_complete means REVIEW->DONE
is permitted BEFORE your candidate: only if all rules PASS/CURRENT and intent is resolved.
Source hashes indicate freshness; inspect supplied source for actual behavior. A manual report that
is stale does not by itself mean the source behavior is wrong. The host separately executes checks,
re-verifies source evidence and reconstructs workflow in a fresh Service. Facts follow:
"""
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {"type": "string", "enum": ["resolve", "implement", "verify", "review"]},
        "path": {"type": "string"},
        "replacement": {"type": "string"},
        "requirement": {"type": "string"},
        "may_complete": {"type": "boolean"},
        "impacted_assets": {"type": "array", "items": {"type": "string"}},
        "changed_sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "action",
        "path",
        "replacement",
        "requirement",
        "may_complete",
        "impacted_assets",
        "changed_sources",
    ],
}


def apply_commands(
    service: Service, operations: list[dict], task: str = "PAC-001", *, intake: bool = False
) -> dict:
    """Execute fixture/replay mutations through current onboarding and context receipts."""
    state = service.onboard()
    return service.apply(
        operations,
        actor="evaluation",
        revision=state["revision"],
        onboarding=state["onboarding"],
        context=None if intake else service.context(task, max_bytes=1_000_000)["receipt"],
    )


def check_code(code: str) -> bool:
    """Execute only a bounded arithmetic AST with no calls/imports or external side effects."""
    if len(code) > 4096:
        return False
    try:
        tree = ast.parse(code)
        allowed = (
            ast.Module,
            ast.FunctionDef,
            ast.arguments,
            ast.arg,
            ast.Return,
            ast.BinOp,
            ast.Mult,
            ast.Name,
            ast.Load,
            ast.Constant,
        )
        if any(not isinstance(node, allowed) for node in ast.walk(tree)) or len(tree.body) != 1:
            return False
        function = tree.body[0]
        if (
            not isinstance(function, ast.FunctionDef)
            or function.name != "scale"
            or len(function.body) != 1
        ):
            return False
        if (
            len(function.args.args) != 1
            or function.args.args[0].arg != "value"
            or function.args.defaults
            or function.decorator_list
            or function.args.posonlyargs
            or function.args.kwonlyargs
            or function.args.vararg
            or function.args.kwarg
            or function.args.kw_defaults
            or function.returns
            or function.args.args[0].annotation
        ):
            return False
        if any(
            not isinstance(node.value, (int, float))
            or isinstance(node.value, bool)
            or abs(node.value) > 100
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
        ):
            return False
        namespace: dict[str, object] = {"__builtins__": {}}
        exec(compile(tree, "<bounded candidate>", "exec"), namespace)
        scale = namespace["scale"]
        return callable(scale) and all(scale(value) == value * 2 for value in (-7, 0, 1, 4, 1.5))
    except (SyntaxError, ValueError, TypeError, AttributeError, NameError, OverflowError):
        return False


def cold_read(root: Path, task: str) -> dict:
    """Reconstruct persisted context and validation in an actual fresh Python process."""
    program = (
        "import json,os,sys; from pathlib import Path; from pacer_mcp.service import Service; "
        "s=Service(Path(sys.argv[1])); print(json.dumps({'pid':os.getpid(),"
        "'context':s.context(sys.argv[2],max_bytes=1000000),'validation':s.validate()}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", program, str(root.resolve()), task],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=30,
    )
    observation = json.loads(result.stdout)
    if observation["pid"] == os.getpid():
        raise ValueError("Cold reconstruction did not cross a process boundary")
    return observation


def verify_behavior(service: Service, task: str = "PAC-001") -> None:
    """Run real source behavior checks and bind a separately registered report before acceptance."""
    root = service.store.root
    if not check_code((root / "calculator.py").read_text(encoding="utf-8")):
        raise ValueError("Candidate violates scale behavior or exported interface")
    if json.loads((root / "settings.json").read_text()) != {"minimum": 2}:
        raise ValueError("Candidate violates dependency contract")
    apply_commands(
        service,
        [{"op": "verify", "id": "OGM-002", "evidence": "Dependency predicate executed"}],
        task,
    )
    observation = service.evaluate("OGM-001")
    report = {
        "requirement": "OGM-001",
        "meaning": observation["meaning"],
        "sources": observation["sources"],
        "result": "PASS",
        "command": ["evaluate_development.py", "check_code"],
        "tested_values": [-7, 0, 1, 4, 1.5],
    }
    (root / "audit.json").write_text(canonical(report), encoding="utf-8")
    apply_commands(
        service,
        [
            {
                "op": "verify",
                "id": "OGM-001",
                "artifact": "OVR-010",
                "evidence": "Bounded source code executed across five values",
            }
        ],
        task,
    )


def prepare_development_cases(parent: Path) -> list[dict]:
    """Freeze edits, dependency failure, ambiguous intent, cold resume and successor scope."""
    cases = []
    for name in (
        "code_edit",
        "dependency_regression",
        "ambiguous_intent",
        "cold_resume",
        "subsequent_nodule",
    ):
        root = parent / name
        root.mkdir(parents=True)
        for path, content in {
            "README.md": "Scale service; preserve user meaning.",
            "AGENTS.md": "Use PACER; inspect source; verify before DONE.",
            "calculator.py": CODE,
            "caller.py": "from calculator import scale\n",
            "settings.json": '{"minimum":2}',
            "audit.json": "{}",
        }.items():
            (root / path).write_text(content, encoding="utf-8")
        service = Service(root)
        service.initialize()
        assets = [
            {
                "ID": "OVR-007",
                "Path": "calculator.py",
                "AssetType": "FILE",
                "Purpose": "Scaling implementation",
                "Exports": "scale",
            },
            {
                "ID": "OVR-008",
                "Path": "calculator.py",
                "AssetType": "FUNCTION",
                "Symbol": "scale",
                "Purpose": "Scale value",
                "Exports": "scale",
                "Requires": "OVR-007",
            },
            {
                "ID": "OVR-009",
                "Path": "caller.py",
                "AssetType": "FILE",
                "Purpose": "Consumer",
                "Imports": "calculator.scale",
                "Requires": "OVR-008",
            },
            {
                "ID": "OVR-010",
                "Path": "audit.json",
                "AssetType": "FILE",
                "Purpose": "Separate measured report",
            },
            {
                "ID": "OVR-011",
                "Path": "settings.json",
                "AssetType": "FILE",
                "Purpose": "Dependency contract",
            },
        ]
        apply_commands(
            service,
            [{"op": "add", "register": "overlord", "row": row} for row in assets],
            intake=True,
        )
        apply_commands(
            service,
            [
                {
                    "op": "pace",
                    "nodule": {
                        "ID": "NDL-001",
                        "Intent": "Maintain scaling and dependency contracts",
                        "Lane": "main",
                        "ContextPolicy": "REQUIRED",
                        "UserRequest": REQUIREMENT + " Minimum must equal 2.",
                        "TargetOVR": "OVR-007;OVR-008;OVR-009;OVR-010;OVR-011",
                        "AbsorptionCriteria": "Both requirements verified",
                    },
                    "tasks": [
                        {
                            "ID": "PAC-001",
                            "Title": "Maintain scaling",
                            "DoD": "Both contracts hold with current evidence",
                            "OVRRefs": "OVR-007;OVR-011",
                        }
                    ],
                    "requirements": [
                        {
                            "ID": "OGM-001",
                            "Title": "Scaling contract",
                            "Requirement": REQUIREMENT,
                            "Authority": "USER",
                            "OriginText": REQUIREMENT,
                            "RuleType": "manual",
                            "OVRRefs": "OVR-007;OVR-008;OVR-009",
                            "BlockedByOGM": "OGM-002",
                        },
                        {
                            "ID": "OGM-002",
                            "Title": "Dependency contract",
                            "Requirement": "Minimum must equal 2.",
                            "Authority": "USER",
                            "OriginText": "Minimum must equal 2.",
                            "RuleType": "json_eq",
                            "RuleSubject": "OVR-011",
                            "RuleSelector": "/minimum",
                            "RuleValue": "2",
                            "OVRRefs": "OVR-011",
                        },
                    ],
                }
            ],
            intake=True,
        )
        verify_behavior(service)
        apply_commands(
            service,
            [
                {"op": "transition", "id": "PAC-001", "status": "DOING"},
                {"op": "transition", "id": "PAC-001", "status": "REVIEW"},
                {"op": "checkpoint", "id": "PAC-001", "next_action": "verify"},
            ],
        )
        task, requirement, path, replacement, action = "PAC-001", REQUIREMENT, "", "", "verify"
        if name == "code_edit":
            (root / "calculator.py").write_text(CODE.replace("* 2", "* 3"), encoding="utf-8")
            path, replacement, action = "calculator.py", CODE, "implement"
        elif name == "dependency_regression":
            (root / "settings.json").write_text('{"minimum":0}', encoding="utf-8")
            path, replacement, action = "settings.json", '{"minimum":2}', "implement"
        elif name == "ambiguous_intent":
            requirement, action = "Make scale smarter.", "resolve"
            apply_commands(
                service,
                [
                    {
                        "op": "transition",
                        "id": "OGM-001",
                        "status": "SCAFFOLD",
                        "evidence": "New ambiguous intent needs resolution",
                    },
                    {
                        "op": "set",
                        "id": "OGM-001",
                        "fields": {
                            "Authority": "UNRESOLVED",
                            "Requirement": requirement,
                            "OriginText": requirement,
                        },
                    },
                ],
            )
        elif name == "cold_resume":
            (root / "calculator.py").write_text(CODE + "\n", encoding="utf-8")
        else:
            apply_commands(
                service,
                [
                    {
                        "op": "transition",
                        "id": "PAC-001",
                        "status": "DONE",
                        "evidence": "Both contracts checked",
                    },
                    {"op": "absorb", "id": "NDL-001", "evidence": "First growth completed"},
                ],
            )
            apply_commands(
                service,
                [
                    {
                        "op": "add",
                        "register": "todo",
                        "row": {
                            "ID": "PAC-002",
                            "Title": "Successor verification",
                            "Phase": "PROPOSAL",
                            "DoD": "Verify unchanged contracts in a new growth lane",
                        },
                    }
                ],
                intake=True,
            )
            apply_commands(
                service,
                [
                    {
                        "op": "approval",
                        "id": "PAC-002",
                        "state": "APPROVED",
                        "evidence": "Fixture user: approve successor verification.",
                    }
                ],
                intake=True,
            )
            apply_commands(
                service,
                [
                    {
                        "op": "pace",
                        "nodule": {
                            "ID": "NDL-002",
                            "Intent": "Verify the existing contracts again",
                            "UserRequest": "Verify the existing contracts again.",
                            "ContextPolicy": "REQUIRED",
                            "Lane": "main",
                            "TargetOVR": "OVR-007;OVR-008;OVR-009;OVR-010;OVR-011",
                            "OGMTargets": "OGM-001;OGM-002",
                            "SpawnedPACs": "PAC-002",
                            "AbsorptionCriteria": "Current acceptance retained",
                        },
                        "tasks": [],
                    }
                ],
                intake=True,
            )
            task, action = "PAC-002", "review"
            apply_commands(
                service,
                [
                    {"op": "set", "id": task, "fields": {"OGMRefs": "OGM-001;OGM-002"}},
                    {"op": "transition", "id": task, "status": "DOING"},
                    {"op": "transition", "id": task, "status": "REVIEW"},
                    {"op": "checkpoint", "id": task, "next_action": "review"},
                ],
                task,
            )
        cold = cold_read(root, task)
        packet = cold["context"]
        assert packet["complete"]
        packet = {k: v for k, v in packet.items() if k not in {"receipt", "required_bytes"}}
        expected = {
            "action": action,
            "path": path,
            "replacement": replacement,
            "requirement": requirement,
            "may_complete": name == "subsequent_nodule",
            "impacted_assets": packet["impacted"],
            "changed_sources": packet["delta"]["changed_sources"],
        }
        cases.append(
            {
                "name": name,
                "root": str(root.resolve()),
                "packet": packet,
                "expected": expected,
                "source": {
                    p: (root / p).read_text(encoding="utf-8")
                    for p in ("calculator.py", "caller.py", "settings.json")
                },
                "allowed_edit": path,
                "cold_process": {"host_pid": os.getpid(), "reader_pid": cold["pid"]},
            }
        )
    return cases


def replay_candidate(case: dict, answer: dict | None, root: Path) -> dict:
    """Apply the declared candidate to a disposable copy and recover its lifecycle."""
    shutil.copytree(case["root"], root, ignore=shutil.ignore_patterns(".pacer"))
    service, task = Service(root), case["packet"]["task"]
    try:
        if not isinstance(answer, dict):
            raise ValueError("No structured answer")
        if answer.get("path") != case["allowed_edit"] or (
            not case["allowed_edit"] and answer.get("replacement") != ""
        ):
            raise ValueError("Candidate exceeds allowed edit")
        if case["name"] == "ambiguous_intent":
            assert answer.get("action") == "resolve"
            assert service.evaluate("OGM-001")["result"] == "UNRESOLVED"
            return {
                "passed": True,
                "status": "UNRESOLVED",
                "validation": service.validate()["valid"],
            }
        if case["allowed_edit"]:
            replacement = answer.get("replacement")
            if not isinstance(replacement, str) or len(replacement) > 4096:
                raise ValueError("Invalid bounded replacement")
            apply_commands(service, [{"op": "transition", "id": task, "status": "DOING"}], task)
            (root / case["allowed_edit"]).write_text(replacement, encoding="utf-8")
            apply_commands(service, [{"op": "transition", "id": task, "status": "REVIEW"}], task)
        verify_behavior(service, task)
        apply_commands(
            service,
            [
                {
                    "op": "transition",
                    "id": task,
                    "status": "DONE",
                    "evidence": "Candidate checks executed",
                },
                {
                    "op": "absorb",
                    "id": "NDL-002" if case["name"] == "subsequent_nodule" else "NDL-001",
                    "evidence": "Candidate replay verified",
                },
            ],
            task,
        )
        fresh = Service(root)
        cold = cold_read(root, task)
        report = cold["validation"]
        assert report["valid"] and not report["stale_evidence"]
        assert fresh.query("todo", where={"ID": task})["rows"][0]["Status"] == "DONE"
        return {
            "passed": True,
            "status": "ABSORBED",
            "validation": True,
            "code_checks": 5,
            "cold_process": {"host_pid": os.getpid(), "reader_pid": cold["pid"]},
            "rule_freshness": {
                key: fresh.evaluate(key)["freshness"] for key in ("OGM-001", "OGM-002")
            },
        }
    except (ValueError, AssertionError, TypeError, KeyError) as exc:
        return {"passed": False, "status": "FAILED", "error": str(exc)}


def score_candidate(
    answer: dict | None, expected: dict, replay: dict, *, tool_events: int = 0
) -> dict:
    """Score decisions, exact meaning/constraints and executed candidate behavior separately."""
    if not isinstance(answer, dict):
        return {"correct": False, "fields": {}, "executed": replay["passed"]}
    # Executed checks accept equivalent arithmetic/JSON spellings.
    score = score_answer(
        {k: v for k, v in answer.items() if k != "replacement"},
        {k: v for k, v in expected.items() if k != "replacement"},
    )
    return score | {
        "correct": score["correct"] and replay["passed"] and tool_events == 0,
        "executed": replay["passed"],
        "closed_book": tool_events == 0,
    }


def main() -> None:
    """Run a bounded randomized matrix and retain every prompt, attempt, candidate and replay."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--repetitions", type=int, default=1, choices=range(1, 4))
    args = parser.parse_args()
    executable = shutil.which("codex.cmd" if os.name == "nt" else "codex")
    if not executable:
        raise RuntimeError("Existing Codex CLI required")
    trial = ROOT / ".cache/d" / uuid4().hex[:8]
    trial.mkdir(parents=True)
    cases = prepare_development_cases(trial / "fixtures")
    (trial / "cases.json").write_text(canonical(cases), encoding="utf-8")
    queue = [
        (case, arm, text, repeat)
        for case in cases
        for arm, text in render_formats(case["packet"]).items()
        for repeat in range(args.repetitions)
    ]
    random.Random(161819).shuffle(queue)
    report = {
        "model": args.model,
        "effort": args.effort,
        "repetitions": args.repetitions,
        "method": "Equivalent frozen facts; seed 161819; schema-constrained candidates; "
        "host executes bounded edits and PACER lifecycle in fresh copies",
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limitations": [
            "Five small development scenarios; not a long-term or population estimate.",
            "Models propose candidates without tools; the host performs edits and lifecycle.",
            "Cold resumption crosses a process boundary; not a long conversation measurement.",
            "Native CLI token usage includes fixed harness overhead and caching.",
        ],
        "results": [],
    }
    print(trial, flush=True)
    with tempfile.TemporaryDirectory(prefix="pacer-development-") as cwd:
        for number, (case, arm, text, repeat) in enumerate(queue, 1):
            label = f"{number:02d}-{case['name']}-{arm}-{repeat}"
            prompt = (
                INSTRUCTIONS
                + canonical({"source": case["source"], "allowed_edit": case["allowed_edit"]})
                + "\n"
                + text
            )
            print("start " + label, flush=True)
            result = run_trial(
                executable,
                prompt,
                trial / label,
                cwd,
                args.model,
                args.effort,
                answer_schema=SCHEMA,
            )
            replay = replay_candidate(case, result["answer"], trial / "replays" / label)
            result.update(
                case=case["name"],
                arm=arm,
                repetition=repeat,
                replay=replay,
                score=score_candidate(
                    result["answer"], case["expected"], replay, tool_events=result["tool_events"]
                ),
            )
            report["results"].append(result)
            (trial / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(
                f"{label}: {result['status']} correct={result['score']['correct']} "
                f"replay={replay['status']}",
                flush=True,
            )
            if result["status"] != "completed":
                raise RuntimeError(
                    "Stopped after failed/ambiguous request; retained attempt, no retry"
                )
    print("report " + str(trial / "report.json"), flush=True)


if __name__ == "__main__":
    main()
