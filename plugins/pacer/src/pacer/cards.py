"""One positional card grammar shared by every frame, tool result and query.

    <KIND> <ID> <head tokens> | Field: value | Field: value ...

Head tokens are positional per register; fields keep a fixed order and are
omitted when empty, so a reader learns the layout once.
"""

from __future__ import annotations

from pacer.schema import PREFIX, REGISTER_OF

# Stored columns first, then views derived at render time (marked by the compiler).
CARD_FIELDS = {
    "todo": ["Title", "Produce", "In", "Out", "Binds", "Needs", "Probe", "Exit", "Next", "Tags"],
    "overlord": ["Purpose", "Tags"],
    "organism": ["Requirement", "Probe", "Evidence", "Binds", "Tags"],
    "nodule": ["Intent", "In", "Out", "Targets", "Spawned", "Exit", "Tags"],
    "decision": ["Subject", "Question", "Chosen", "Rejected", "Why", "Supersedes", "Tags"],
}
# Derived fields, appended after stored ones in this order.
DERIVED_ORDER = ["bound-by", "latch", "used-by"]
FLAGS = ("missing", "OFF-PACE", "archived")


def header(register: str, row: dict) -> list[str]:
    """Positional tokens after the ID; empty tokens are dropped."""
    tokens: tuple[str | None, ...]
    if register == "todo":
        tokens = (row.get("Pos"), row.get("Status"), row.get("Tier"))
    elif register == "overlord":
        path = row.get("Path", "") + (":" + row["Symbol"] if row.get("Symbol") else "")
        tokens = (path, row.get("Tier"))
    elif register == "organism":
        tokens = (row.get("Status"), row.get("Authority"), row.get("Tier"))
    elif register == "nodule":
        tokens = (row.get("Status"), f"lane={row['Lane']}" if row.get("Lane") else "")
    else:
        latched = {"true": "latched", "false": "open"}.get(row.get("Latched", ""), "")
        tokens = (row.get("Kind"), row.get("Authority"), latched)
    return [t for t in tokens if t]


def card(register: str, row: dict, extras: dict[str, str] | None = None) -> str:
    """Render one row as one line.

    `extras` may override a stored field (the compiler replaces `Evidence` with its
    freshness reading), add derived fields, or raise a flag such as `OFF-PACE`.
    A PACE that has a Produce omits its Title: Produce is the operative line.
    """
    extras = dict(extras or {})
    line = " ".join([PREFIX[register], row["ID"], *header(register, row)])
    fields = CARD_FIELDS[register]
    if register == "todo" and row.get("Kind") == "PACE" and row.get("Produce"):
        fields = [f for f in fields if f != "Title"]
    for field in fields:
        value = extras.pop(field, row.get(field, ""))
        if value:
            line += f" | {field}: {_clean(value)}"
    for key in DERIVED_ORDER:
        if extras.get(key):
            line += f" | {key}: {_clean(extras[key])}"
    for flag in FLAGS:
        if extras.get(flag):
            line += f" | {flag}"
    return line


def parse_card(line: str) -> dict:
    """Decode a card into register, ID, head tokens, fields and flags."""
    head, *parts = line.split(" | ")
    tokens = head.split(" ")
    if len(tokens) < 2 or tokens[0] not in REGISTER_OF:
        raise ValueError(f"Not a card: {line[:40]}")
    fields, flags = {}, []
    for part in parts:
        key, sep, value = part.partition(": ")
        if sep:
            fields[key] = value
        else:
            flags.append(part)
    return {
        "register": REGISTER_OF[tokens[0]],
        "ID": tokens[1],
        "head": tokens[2:],
        "fields": fields,
        "flags": flags,
    }


def _clean(value: str) -> str:
    return value.replace("|", "/").replace("\r", " ").replace("\n", " ").strip()
