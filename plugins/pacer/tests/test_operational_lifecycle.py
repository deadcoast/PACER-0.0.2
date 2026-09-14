"""A real MCP client completes, resumes, repairs and absorbs operational work."""

import json
import subprocess
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_operational_lifecycle_through_stdio_and_fresh_session(operational):
    root = str(operational.store.root)
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "pacer_mcp.cli", "serve", "--root", root]
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            tools = {tool.name for tool in (await client.list_tools()).tools}
            assert {"pacer_context", "pacer_evaluate"} <= tools

            async def apply(*operations):
                receipt = (
                    await client.call_tool("pacer_onboard", {"root": root})
                ).structuredContent
                packet = (
                    await client.call_tool("pacer_context", {"root": root, "id": "PAC-001"})
                ).structuredContent
                result = await client.call_tool(
                    "pacer_apply",
                    {
                        "root": root,
                        "operations": list(operations),
                        "actor": "mcp-agent",
                        "revision": receipt["revision"],
                        "onboarding": receipt["onboarding"],
                        "context": packet["receipt"],
                    },
                )
                assert not result.isError, str(result)

            await apply({"op": "transition", "id": "PAC-001", "status": "DOING"})
            await apply(
                {"op": "verify", "id": "OGM-001", "evidence": "Actual settings checked"},
                {"op": "checkpoint", "id": "PAC-001", "next_action": "review"},
            )
    # A separate process reconstructs state solely from canonical PACER records.
    cold = subprocess.run(
        [sys.executable, "-m", "pacer_mcp.cli", "--root", root, "context", "PAC-001"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(cold.stdout)["next_action"] == "review"
    (operational.store.root / "settings.json").write_text('{"retries":0}', encoding="utf-8")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            # The helper's client binding now refers to this new MCP session.
            packet = (
                await client.call_tool("pacer_context", {"root": root, "id": "PAC-001"})
            ).structuredContent
            assert packet["rules"][0]["freshness"] == "STALE"
            await apply({"op": "refresh", "id": "PAC-001"})
            (operational.store.root / "settings.json").write_text('{"retries":4}', encoding="utf-8")
            await apply({"op": "verify", "id": "OGM-001", "evidence": "Repaired settings verified"})
            await apply({"op": "transition", "id": "PAC-001", "status": "REVIEW"})
            await apply(
                {
                    "op": "transition",
                    "id": "PAC-001",
                    "status": "DONE",
                    "evidence": "Lifecycle verified",
                },
                {"op": "absorb", "id": "NDL-001", "evidence": "All requirements current"},
            )
    assert operational.validate()["valid"]
    assert operational.onboard()["active"]["rows"] == []
    assert (operational.store.root / "archive/nodules/NDL-001.PACER.csv").is_file()
