"""pacer_probe must complete through a real stdio MCP server.

Regression: the probe child once inherited the server's stdin (the JSON-RPC pipe)
and deadlocked the transport on Windows. This drives the installed entry point
exactly as a harness does, with a hard timeout.
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PLUGIN = Path(__file__).resolve().parents[1]


async def test_probe_through_stdio_server(project):
    project.write(
        [
            {
                "op": "add",
                "register": "overlord",
                "row": {"ID": "OVR-001", "Path": "src/a.py", "Kind": "FILE", "Purpose": "entry"},
            },
            {
                "op": "add",
                "register": "organism",
                "row": {
                    "ID": "OGM-001",
                    "Title": "Runs",
                    "Requirement": "interpreter answers",
                    "Binds": "OVR-001",
                    "Probe": f'"{sys.executable}" -c "print(7)"',
                },
            },
        ],
        "tester",
    )
    env = dict(os.environ, PYTHONPATH=str(PLUGIN / "src"))
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "pacer_mcp.cli", "serve"], cwd=str(PLUGIN), env=env
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await asyncio.wait_for(client.initialize(), 60)
            try:
                result = await asyncio.wait_for(
                    client.call_tool(
                        "pacer_probe", {"root": str(project.root), "id": "OGM-001", "actor": "t"}
                    ),
                    45,
                )
            except asyncio.TimeoutError:
                pytest.fail("pacer_probe hung inside the stdio MCP server")
            assert not result.isError
            assert result.structuredContent["exit"] == 0
            assert result.structuredContent["freshness"] == "CURRENT"
