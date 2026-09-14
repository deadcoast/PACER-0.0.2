"""Exercise the actual stdio boundary rather than calling tool functions directly."""

import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_stdio_tools_resources_and_prompt(project):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pacer_mcp.cli", "serve", "--root", str(project.store.root)],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            initialized = await client.initialize()
            assert "PACER" in initialized.instructions
            catalog = await client.list_tools()
            names = {tool.name for tool in catalog.tools}
            assert {"pacer_onboard", "pacer_query", "pacer_apply", "pacer_validate"} <= names
            tools = {tool.name: tool for tool in catalog.tools}
            assert tools["pacer_query"].annotations.readOnlyHint
            assert not tools["pacer_apply"].annotations.readOnlyHint
            result = await client.call_tool("pacer_onboard", {"root": str(project.store.root)})
            assert not result.isError
            receipt = result.structuredContent
            assert receipt["validation"]["valid"]
            mutation = await client.call_tool(
                "pacer_apply",
                {
                    "root": str(project.store.root),
                    "actor": "mcp-test",
                    "revision": receipt["revision"],
                    "onboarding": receipt["onboarding"],
                    "operations": [
                        {
                            "op": "pace",
                            "nodule": {
                                "ID": "NDL-001",
                                "NoduleName": "mcp-test",
                                "Intent": "Prove MCP writes",
                                "AbsorptionCriteria": "Real request persisted",
                                "Lane": "main",
                            },
                            "tasks": [
                                {"ID": "PAC-001", "Title": "Protocol proof", "DoD": "Persisted"}
                            ],
                            "requirements": [],
                        }
                    ],
                },
            )
            assert not mutation.isError
            query = await client.call_tool(
                "pacer_query",
                {
                    "root": str(project.store.root),
                    "register": "todo",
                    "fields": ["ID", "Status"],
                    "ready": True,
                },
            )
            assert query.structuredContent["rows"] == [{"ID": "PAC-001", "Status": "TODO"}]
            stale = await client.call_tool(
                "pacer_apply",
                {
                    "root": str(project.store.root),
                    "actor": "mcp-test",
                    "revision": receipt["revision"],
                    "onboarding": receipt["onboarding"],
                    "operations": [{"op": "transition", "id": "PAC-001", "status": "DOING"}],
                },
            )
            assert stale.isError
            resources = await client.list_resources()
            assert "pacer://schema" in {str(r.uri) for r in resources.resources}
            schema = await client.read_resource("pacer://schema")
            assert "BlockedBy" in schema.contents[0].text
            prompt = await client.get_prompt("pacer_onboarding", {"root": str(project.store.root)})
            assert "README.md" in prompt.messages[0].content.text
            escaped = await client.call_tool(
                "pacer_onboard", {"root": str(project.store.root.parent)}
            )
            assert escaped.isError
            receipt = (
                await client.call_tool("pacer_onboard", {"root": str(project.store.root)})
            ).structuredContent
            result = await client.call_tool(
                "pacer_apply",
                {
                    "root": str(project.store.root),
                    "actor": "mcp-test",
                    "revision": receipt["revision"],
                    "onboarding": receipt["onboarding"],
                    "operations": [
                        *[
                            {
                                "op": "transition",
                                "id": "PAC-001",
                                "status": status,
                                "evidence": "Protocol persistence verified",
                            }
                            for status in ("DOING", "REVIEW", "DONE")
                        ],
                        {
                            "op": "absorb",
                            "id": "NDL-001",
                            "evidence": "Actual MCP lifecycle passed",
                        },
                    ],
                },
            )
            assert not result.isError, json.dumps(result.model_dump(), default=str)
            compact = await client.call_tool(
                "pacer_context", {"root": str(project.store.root), "id": "PAC-001"}
            )
            expanded = await client.call_tool(
                "pacer_context",
                {"root": str(project.store.root), "id": "PAC-001", "encoding": "expanded"},
            )
            assert compact.structuredContent["encoding"] == "pacer-context/2"
            assert isinstance(expanded.structuredContent["relations"], list)
            receipt = (
                await client.call_tool("pacer_onboard", {"root": str(project.store.root)})
            ).structuredContent
            approved = await client.call_tool(
                "pacer_apply",
                {
                    "root": str(project.store.root),
                    "actor": "mcp-test",
                    "revision": receipt["revision"],
                    "onboarding": receipt["onboarding"],
                    "operations": [
                        {
                            "op": "add",
                            "register": "todo",
                            "row": {
                                "ID": "PAC-002",
                                "Title": "Proposal",
                                "DoD": "Checked",
                                "Phase": "PROPOSAL",
                            },
                        },
                        {
                            "op": "approval",
                            "id": "PAC-002",
                            "state": "APPROVED",
                            "evidence": "User: approve proposal.",
                        },
                    ],
                },
            )
            assert not approved.isError
            query = await client.call_tool(
                "pacer_query",
                {
                    "root": str(project.store.root),
                    "register": "todo",
                    "ready": True,
                    "fields": ["ID", "ApprovalState"],
                },
            )
            assert query.structuredContent["rows"] == [
                {"ID": "PAC-002", "ApprovalState": "APPROVED"}
            ]
    assert project.validate()["valid"]
