"""Bounded delivery preserves context and refuses partial or inconsistent reconstruction."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pacer_mcp.pages import assemble_context_pages
from pacer_mcp.semantics import canonical
from pacer_mcp.service import Service


def collect(service, *, max_bytes=2048):
    pages, cursor = [], ""
    while True:
        page = service.context_page("PAC-001", cursor=cursor, max_bytes=max_bytes)
        assert len(canonical(page).encode()) <= max_bytes
        pages.append(page)
        if not page["next_cursor"]:
            return pages
        assert page["receipt"] is None and not page["complete"]
        cursor = page["next_cursor"]


def test_paged_context_roundtrip_and_guarded_write(operational):
    packet = operational.context("PAC-001", max_bytes=1_000_000)
    pages = collect(operational)
    assert len(pages) > 1
    assert assemble_context_pages(pages) == packet
    assert pages[-1]["receipt"] == packet["receipt"]
    state = operational.onboard()
    operational.apply(
        [{"op": "checkpoint", "id": "PAC-001", "next_action": "verify"}],
        actor="paged-test",
        revision=state["revision"],
        onboarding=state["onboarding"],
        context=pages[-1]["receipt"],
    )
    assert Service(operational.store.root).context("PAC-001")["next_action"] == "verify"


def test_long_unicode_and_escaped_values_roundtrip(operational, operate):
    value = '  :MIVIM::⡀++\n"literal"\\路径😀e\u0301\t' * 1800
    operate({"op": "set", "id": "PAC-001", "fields": {"Instructions": value}})
    pages = collect(operational)
    packet = assemble_context_pages(pages)
    assert packet == operational.context("PAC-001", max_bytes=1_000_000)
    assert any("append" in entry for page in pages for entry in page["entries"])


@pytest.mark.parametrize("change", ["source", "authority", "row", "checkpoint"])
def test_continuation_rejects_changed_packet(operational, operate, change):
    page = operational.context_page("PAC-001", max_bytes=2048)
    assert page["next_cursor"]
    if change in {"source", "authority"}:
        file = "settings.json" if change == "source" else "README.md"
        path = operational.store.root / file
        path.write_text(path.read_text() + " ", encoding="utf-8")
    elif change == "row":
        operate({"op": "set", "id": "PAC-001", "fields": {"Instructions": "Changed guidance"}})
    else:
        operate({"op": "checkpoint", "id": "PAC-001", "next_action": "verify"})
    with pytest.raises(ValueError, match="Stale context page"):
        Service(operational.store.root).context_page(
            "PAC-001", cursor=page["next_cursor"], max_bytes=2048
        )


@pytest.mark.parametrize("mutation", ["missing", "reordered", "altered", "duplicate", "receipt"])
def test_reconstruction_rejects_incomplete_or_altered_delivery(operational, mutation):
    pages = deepcopy(collect(operational))
    if mutation == "missing":
        pages.pop()
    elif mutation == "reordered":
        pages.reverse()
    elif mutation == "duplicate":
        pages.insert(1, deepcopy(pages[0]))
    elif mutation == "receipt":
        pages[-1]["receipt"]["basis"] = "0" * 64
    else:
        pages[0]["entries"][0]["value"] = "tampered"
    with pytest.raises(ValueError):
        assemble_context_pages(pages)


def test_paging_errors_never_issue_receipts(operational):
    for cursor in ("broken", "0" * 64 + ":999999:2048", "0" * 64 + ":-1:2048"):
        with pytest.raises(ValueError):
            operational.context_page("PAC-001", cursor=cursor, max_bytes=2048)
    with pytest.raises(ValueError):
        operational.context_page("PAC-001", max_bytes=256)
    (operational.store.root / "settings.json").unlink()
    with pytest.raises(ValueError, match="Incomplete context"):
        operational.context_page("PAC-001")


def test_cli_page_canonical_bound(operational):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pacer_mcp.cli",
            "--root",
            str(operational.store.root),
            "context-page",
            "PAC-001",
            "--max-bytes",
            "2048",
        ],
        capture_output=True,
        check=True,
    )
    assert len(result.stdout.rstrip(b"\r\n")) <= 2048
    assert json.loads(result.stdout)["format"] == "pacer-context-page/1"


async def test_mcp_page_stream_matches_service(operational):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pacer_mcp.cli", "serve", "--root", str(operational.store.root)],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert tools["pacer_context_page"].annotations.readOnlyHint
            pages, cursor = [], ""
            while True:
                response = await client.call_tool(
                    "pacer_context_page",
                    {
                        "root": str(operational.store.root),
                        "id": "PAC-001",
                        "max_bytes": 2048,
                        "cursor": cursor,
                    },
                )
                assert not response.isError
                page = response.structuredContent
                assert json.loads(response.content[0].text) == page
                assert len(response.content[0].text.encode()) <= 2048
                pages.append(page)
                cursor = page["next_cursor"]
                if not cursor:
                    break
            assert assemble_context_pages(pages) == operational.context(
                "PAC-001", max_bytes=1_000_000
            )


@pytest.mark.parametrize("mutation", ["none", "no_onboard", "root", "task", "budget", "tool"])
def test_native_proof_checks_actual_workflow(operational, monkeypatch, mutation):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    from prove_context_delivery import inspect_delivery

    root = str(operational.store.root)
    packet = operational.context("PAC-001", max_bytes=1_000_000)

    def event(tool, arguments, result):
        return {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "tool": tool,
                "arguments": arguments,
                "status": "completed",
                "result": {
                    "structured_content": result,
                    "content": [{"type": "text", "text": canonical(result)}],
                },
            },
        }

    events = [event("pacer_onboard", {"root": root}, operational.onboard())]
    cursor = ""
    for page in collect(operational):
        events.append(
            event(
                "pacer_context_page",
                {
                    "root": root,
                    "id": "PAC-001",
                    "cursor": cursor,
                    "max_bytes": 2048,
                },
                page,
            )
        )
        cursor = page["next_cursor"]
    if mutation == "none":
        assert inspect_delivery(events, packet, checkpoint=False)["exact_roundtrip"]
        return
    if mutation == "no_onboard":
        events.pop(0)
    elif mutation == "root":
        del events[1]["item"]["arguments"]["root"]
    elif mutation == "task":
        events[1]["item"]["arguments"]["id"] = "PAC-002"
    elif mutation == "budget":
        events[1]["item"]["arguments"]["max_bytes"] = 4096
    else:
        events.append({"type": "item.completed", "item": {"type": "command_execution"}})
    with pytest.raises(ValueError):
        inspect_delivery(events, packet, checkpoint=False)


def test_final_page_receipt_still_requires_live_source(operational):
    pages = collect(operational)
    state = operational.onboard()
    (operational.store.root / "settings.json").write_text('{"retries":1}', encoding="utf-8")
    assert assemble_context_pages(pages)["receipt"] == pages[-1]["receipt"]
    with pytest.raises(ValueError, match="Stale context"):
        operational.apply(
            [{"op": "checkpoint", "id": "PAC-001", "next_action": "verify"}],
            actor="paged-test",
            revision=state["revision"],
            onboarding=state["onboarding"],
            context=pages[-1]["receipt"],
        )


@pytest.mark.parametrize("failure", ["launch", "truncated"])
def test_native_attempt_finalizes_failed_launch_and_truncated_events(
    operational, monkeypatch, tmp_path, failure
):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    import prove_context_delivery as proof

    class BrokenProcess:
        returncode = 1

        def __init__(self, *args, **kwargs):
            if failure == "launch":
                raise OSError("simulated launch failure")
            kwargs["stdout"].write(b'{"type":"incomplete')

        def communicate(self, *args, **kwargs):
            return None, None

    monkeypatch.setattr(proof.subprocess, "Popen", BrokenProcess)
    attempt = proof.run_turn(
        "unused",
        tmp_path,
        operational.store.root,
        tmp_path / "attempt",
        str(tmp_path),
        "test-model",
        "test-effort",
        checkpoint=True,
    )
    persisted = json.loads((tmp_path / "attempt/attempt.json").read_text())
    assert attempt == persisted and attempt["status"] == "failed"
    assert attempt["error"] and "returncode" in attempt
