"""Prove local plugin installation and discovery using the installed Codex CLI.

Uses a fresh isolated Codex home. No model turn, credentials or user configuration
are needed. The script leaves its report and isolated installation in .cache.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from evaluate_context import prepare_cases

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    """Install the package, inspect native discovery and call its MCP through Codex."""
    executable = shutil.which("codex.cmd" if os.name == "nt" else "codex")
    if executable is None:
        raise RuntimeError("Codex CLI must already be installed")
    # Keep dependency-cache paths below legacy Windows path limits.
    trial = ROOT / ".cache/c" / uuid4().hex[:8]
    trial.mkdir(parents=True)
    prepare_cases(trial / "fixtures")
    fixture_root = trial / "fixtures" / "stale"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--installed", action="store_true", help="Inspect the current Codex home without installing"
    )
    options = parser.parse_args()
    env = dict(os.environ, UV_CACHE_DIR=str(ROOT / ".cache/uv"), PYTHONDONTWRITEBYTECODE="1")
    if not options.installed:
        env["CODEX_HOME"] = str(trial / "home")
        Path(env["CODEX_HOME"]).mkdir()
    marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())["name"]
    report = {
        "trial": str(trial),
        "model_turns": 0,
        "marketplace": marketplace,
        "current_home": options.installed,
    }
    for label, arguments in [
        ("version", ["--version"]),
        ("marketplace_add", ["plugin", "marketplace", "add", str(ROOT)]),
        ("plugin_add", ["plugin", "add", f"pacer@{marketplace}", "--json"]),
        ("plugin_list", ["plugin", "list", "--marketplace", marketplace, "--json"]),
        ("mcp_list", ["mcp", "list", "--json"]),
    ]:
        if options.installed and label in {"marketplace_add", "plugin_add"}:
            continue
        result = subprocess.run(
            [executable, *arguments],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        report[label] = {
            "code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        print(label, result.returncode, flush=True)
        (trial / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"{label} failed: {result.stderr}")
    # Scope this process to PACER so unrelated user servers cannot stall the proof.
    listed_servers = json.loads(report["mcp_list"]["stdout"])
    overrides = []
    for server in listed_servers:
        if server["name"] != "pacer":
            overrides.extend(["-c", f"mcp_servers.{server['name']}.enabled=false"])
    # Use the documented JSONL app-server protocol to inspect installed skills/MCP.
    with (trial / "app-server.stderr.log").open("wb") as errors:
        process = await asyncio.create_subprocess_exec(
            executable,
            "app-server",
            "--stdio",
            *overrides,
            cwd=ROOT,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=errors,
            limit=8 * 1024 * 1024,
        )
        serial = 0

        async def request(method: str, params: dict) -> dict:
            nonlocal serial
            serial += 1
            process.stdin.write(
                (json.dumps({"id": serial, "method": method, "params": params}) + "\n").encode()
            )
            await process.stdin.drain()
            print("request", method, flush=True)
            async with asyncio.timeout(60):
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        raise RuntimeError("Codex app-server closed its stream")
                    message = json.loads(line)
                    if "method" in message and "id" in message:
                        raise RuntimeError(f"Unexpected server request: {message['method']}")
                    if message.get("id") == serial:
                        if "error" in message:
                            raise RuntimeError(f"{method}: {message['error']}")
                        return message["result"]

        try:
            report["initialize"] = await request(
                "initialize",
                {
                    "clientInfo": {"name": "pacer_integration_proof", "version": "0.3.0"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            process.stdin.write(b'{"method":"initialized","params":{}}\n')
            await process.stdin.drain()
            skills = await request("skills/list", {"cwds": [str(ROOT)], "forceReload": True})
            report["skills"] = skills
            names = {
                skill["name"]
                for item in skills["data"]
                for skill in item["skills"]
                if skill.get("pluginId") == f"pacer@{marketplace}"
            }
            if not {"pacer:pacer-onboard", "pacer:pacer-develop", "pacer:pacer-audit"} <= names:
                raise RuntimeError("Codex did not discover all bundled PACER skills")
            details = await request(
                "plugin/read",
                {
                    "pluginName": "pacer",
                    "marketplacePath": str(ROOT / ".agents/plugins/marketplace.json"),
                },
            )
            report["plugin_read"] = details
            status = await request("mcpServerStatus/list", {"limit": 100})
            report["mcp_status"] = status
            (trial / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            servers = [
                item
                for item in status.get("data", [])
                if item.get("pluginId") == f"pacer@{marketplace}"
                and "pacer_onboard" in item.get("tools", {})
                and not item.get("toolsError")
            ]
            if len(servers) != 1:
                raise RuntimeError("Codex did not initialize PACER's MCP tool inventory")
            if not {"pacer_context", "pacer_evaluate"} <= set(servers[0]["tools"]):
                raise RuntimeError("Installed PACER lacks operational context tools")
            thread = await request("thread/start", {"cwd": str(ROOT), "ephemeral": True})
            report["onboard"] = await request(
                "mcpServer/tool/call",
                {
                    "threadId": thread["thread"]["id"],
                    "server": servers[0]["name"],
                    "tool": "pacer_onboard",
                    "arguments": {"root": str(ROOT)},
                },
            )
            if report["onboard"].get("isError") or "onboarding" not in json.dumps(
                report["onboard"]
            ):
                raise RuntimeError("Codex could not call PACER onboarding")
            for tool, row_id in (("pacer_context", "PAC-001"), ("pacer_evaluate", "OGM-001")):
                result = await request(
                    "mcpServer/tool/call",
                    {
                        "threadId": thread["thread"]["id"],
                        "server": servers[0]["name"],
                        "tool": tool,
                        "arguments": {"root": str(fixture_root), "id": row_id},
                    },
                )
                report[tool] = result
                if result.get("isError"):
                    raise RuntimeError(f"Installed {tool} call failed")
                payload = result.get("structuredContent") or json.loads(
                    next(item["text"] for item in result["content"] if item["type"] == "text")
                )
                if tool == "pacer_context":
                    if not payload["complete"] or not payload["receipt"]:
                        raise RuntimeError("Installed context did not return a complete receipt")
                    observation = next(r for r in payload["rules"] if r["id"] == "OGM-001")
                else:
                    observation = payload
                if observation["result"] != "PASS" or observation["freshness"] != "STALE":
                    raise RuntimeError(
                        "Installed runtime conflated passing source with current evidence"
                    )
            report["passed"] = True
            print(
                json.dumps(
                    {
                        "passed": True,
                        "skills": sorted(names),
                        "servers": [s["name"] for s in servers],
                        "report": str(trial / "report.json"),
                    }
                ),
                flush=True,
            )
        finally:
            (trial / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), 10)
            except TimeoutError:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        timeout=10,
                        check=False,
                    )
                else:
                    process.kill()
                try:
                    await asyncio.wait_for(process.wait(), 10)
                except TimeoutError:
                    # A launcher can exit before descendants close inherited pipes.
                    process._transport.close()


if __name__ == "__main__":
    asyncio.run(main())
