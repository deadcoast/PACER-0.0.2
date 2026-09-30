"""One positional card grammar shared by every frame, tool result and query."""

from __future__ import annotations

from pacer_mcp.schema import PREFIX, REGISTER_OF

CARD_FIELDS = {
    "todo": [
        "Title",
        "Produce",
        "In",
        "Out",
        "Binds",
        "Needs",
        "Probe",
        "Exit",
        "Next",
        "Latch",
        "Tags",
    ],
    "overlord": ["Purpose", "Binds", "Latch", "Tags"],
    "organism": ["Requirement", "Probe", "Evidence", "Binds", "Tags"],
    "nodule": ["Intent", "In", "Out", "Targets", "Spawned", "Exit", "Tags"],
    "decision": ["Subject", "Question", "Chosen", "Rejected", "Why", "Supersedes", "Tags"],
}
# Extras follow authored fields; a same-named extra replaces the field value.
EXTRA_ORDER = ["used-by", "deps", "OFF-PACE", "open"]


def header(register: str, row: dict) -> list[str]:
    """Positional tokens after the ID; empty tokens are dropped."""
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
    """Render one row as one line; a PACE with Produce omits its Title."""
    extras = dict(extras or {})
    line = " ".join([PREFIX[register], row["ID"], *header(register, row)])
    fields = CARD_FIELDS[register]
    if register == "todo" and row.get("Kind") == "PACE" and row.get("Produce"):
        fields = [f for f in fields if f != "Title"]
    for field in fields:
        value = extras.pop(field, row.get(field, ""))
        if value:
            line += f" | {field}: {_clean(value)}"
    for key in EXTRA_ORDER + sorted(k for k in extras if k not in EXTRA_ORDER):
        if key in extras and extras[key]:
            line += " | OFF-PACE" if key == "OFF-PACE" else f" | {key}: {_clean(extras[key])}"
    return line


def parse_card(line: str) -> dict:
    """Decode a card into register, ID, head tokens and fields."""
    head, *fields = line.split(" | ")
    tokens = head.split(" ")
    if len(tokens) < 2 or tokens[0] not in REGISTER_OF:
        raise ValueError(f"Not a card: {line[:40]}")
    parsed = {}
    for item in fields:
        key, sep, value = item.partition(": ")
        parsed[key] = value if sep else ""
    return {
        "register": REGISTER_OF[tokens[0]],
        "ID": tokens[1],
        "head": tokens[2:],
        "fields": parsed,
    }


def _clean(value: str) -> str:
    return value.replace("|", "/").replace("\n", " ").strip()
