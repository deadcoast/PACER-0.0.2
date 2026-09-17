"""Readable, stateless, byte-bounded delivery of one complete compact context packet."""

from __future__ import annotations

import re
from copy import deepcopy

from pacer_mcp.semantics import canonical, fingerprint


def _size(value):
    return len(canonical(value).encode("utf-8"))


def _entries(value, path, budget):
    entry = {"path": path, "value": value}
    if _size(entry) <= budget:
        yield entry
    elif isinstance(value, (dict, list)):
        empty = {} if isinstance(value, dict) else []
        marker = {"path": path, "value": empty}
        if _size(marker) > budget:
            raise ValueError("Context path exceeds page budget")
        yield marker
        items = value.items() if isinstance(value, dict) else enumerate(value)
        for key, child in items:
            yield from _entries(child, [*path, key], budget)
    elif isinstance(value, str):
        if _size({"path": path, "value": ""}) > budget:
            raise ValueError("Context path exceeds page budget")
        yield {"path": path, "value": ""}
        start = 0
        while start < len(value):
            low, high = 0, len(value) - start
            while low < high:
                middle = (low + high + 1) // 2
                if _size({"path": path, "append": value[start : start + middle]}) <= budget:
                    low = middle
                else:
                    high = middle - 1
            if not low:
                raise ValueError("Context character exceeds page budget")
            yield {"path": path, "append": value[start : start + low]}
            start += low
    else:
        raise ValueError("Context value exceeds page budget")


def _envelope(packet, digest, entries, offset, end, total, max_bytes):
    last = end == total
    return {
        "format": "pacer-context-page/1",
        "task": packet["task"],
        "packet_digest": digest,
        "max_bytes": max_bytes,
        "offset": offset,
        "entries": entries,
        "next_cursor": "" if last else f"{digest}:{end}:{max_bytes}",
        "complete": last,
        "receipt": packet["receipt"] if last else None,
    }


def context_page(packet: dict, *, cursor: str = "", max_bytes: int = 8_000) -> dict:
    """Page exact JSON values by path; expose the freshness receipt only on the final page.

    Cursors bind the complete packet and page size, survive process restarts, and
    confer no authority or proof of reading. The caller must consume every page.
    The byte bound covers canonical UTF-8 JSON, excluding transport envelopes.
    """
    if type(max_bytes) is not int or not 2048 <= max_bytes <= 32_000:
        raise ValueError("Page max_bytes must be 2048..32000")
    if not packet.get("complete") or not packet.get("receipt"):
        raise ValueError(
            "Incomplete context cannot be paged: " + canonical(packet.get("diagnostics", []))
        )
    digest = fingerprint(packet)
    offset = 0
    if cursor:
        match = re.fullmatch(r"([0-9a-f]{64}):([1-9][0-9]{0,8}):([0-9]{4,5})", cursor)
        if match is None:
            raise ValueError("Invalid context page cursor")
        if match[1] != digest or int(match[3]) != max_bytes:
            raise ValueError("Stale context page; restart retrieval with an empty cursor")
        offset = int(match[2])
    # Reserve both the longest cursor and final receipt, plus bounded integer growth.
    shell = _envelope(packet, digest, [], 999999999, 999999999, 1000000000, max_bytes)
    shell["receipt"] = packet["receipt"]
    budget = max_bytes - _size(shell) - 16
    if budget < 64:
        raise ValueError("Context metadata exceeds page budget")
    entries = []
    for key, value in packet.items():
        if key != "receipt":
            entries.extend(_entries(value, [key], budget))
    if offset >= len(entries):
        raise ValueError("Invalid context page offset")
    end = offset
    while end < len(entries):
        candidate = _envelope(
            packet, digest, entries[offset : end + 1], offset, end + 1, len(entries), max_bytes
        )
        if _size(candidate) > max_bytes:
            break
        end += 1
    if end == offset:
        raise ValueError("Context entry exceeds page budget")
    return _envelope(packet, digest, entries[offset:end], offset, end, len(entries), max_bytes)


def assemble_context_pages(pages: list[dict]) -> dict:
    """Reconstruct and validate every page, its order and the exact original packet hash.

    This verifies delivery integrity, not current source state or human authority;
    Service.apply still checks the reconstructed receipt against live source.
    """
    if not pages or len(pages) > 100_000:
        raise ValueError("Complete ordered context pages required")
    packet: dict = {}
    try:
        for page in pages:
            for entry in page["entries"]:
                path = entry["path"]
                if not isinstance(path, list) or not path:
                    raise ValueError("Invalid context entry path")
                parent = packet
                for key in path[:-1]:
                    parent = parent[key]
                key = path[-1]
                if set(entry) == {"path", "append"}:
                    if not isinstance(parent[key], str) or not isinstance(entry["append"], str):
                        raise ValueError("Invalid string continuation")
                    parent[key] += entry["append"]
                elif set(entry) == {"path", "value"}:
                    if isinstance(parent, list):
                        if type(key) is not int or key != len(parent):
                            raise ValueError("Out of order list entry")
                        parent.append(deepcopy(entry["value"]))
                    elif isinstance(parent, dict) and isinstance(key, str) and key not in parent:
                        parent[key] = deepcopy(entry["value"])
                    else:
                        raise ValueError("Duplicate context entry")
                else:
                    raise ValueError("Invalid context entry")
        packet["receipt"] = pages[-1]["receipt"]
        if fingerprint(packet) != pages[0]["packet_digest"]:
            raise ValueError("Context packet digest mismatch")
        cursor = ""
        for number, page in enumerate(pages):
            expected = context_page(packet, cursor=cursor, max_bytes=pages[0]["max_bytes"])
            if canonical(page) != canonical(expected):
                raise ValueError("Incomplete, reordered or altered context page")
            cursor = expected["next_cursor"]
            if not cursor and number != len(pages) - 1:
                raise ValueError("Extra context pages")
        if cursor or not pages[-1]["complete"]:
            raise ValueError("Missing context pages")
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError("Invalid context page stream") from exc
    return packet
