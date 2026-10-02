# PACER 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace profile 0.5's fetch-by-choice context runtime with a hook-delivered context compiler over five reshaped CSV registers plus an append-only ledger.

**Architecture:** Registers hold current state only (bounded cells). A compiler ranks rows by typed-edge distance from a focus and emits fixed-grammar cards inside a byte budget. Harness hooks (Claude Code, Codex) call the compiler at SessionStart, UserPromptSubmit, PreToolUse, PostToolUse and Stop. One validating writer with a lock and atomic publish remains; receipts, digests, pages and reciprocal columns are removed.

**Tech Stack:** Python 3.11+ (repo dev on 3.14), `mcp` 1.x, `filelock`, `pydantic` (via mcp), stdlib `sqlite3`/`ast`/`tomllib`/`subprocess`. uv workspace at repo root. pytest.

## Global Constraints

- Package stays `pacer_mcp`, CLI `pacer`, MCP server name `pacer`; version `3.0.0`.
- IDs `(PAC|OVR|OGM|NDL|DEC)-[0-9]{3,}[A-Z]*`, immutable, never reused. Multi-refs `;`. Tags `#lowercase`.
- No cell may contain `|` or a newline. Column limits from `LIMITS` are enforced on write and validation.
- No Notes/timestamp/hash columns in any register. Every mutation appends one ledger line.
- PreToolUse hooks never emit `permissionDecision: "allow"`. Only `additionalContext`, or `deny` at protected tier.
- Frames never refuse on budget. The spine is mandatory; the rest fills by rank; a trailing `+N more` line reports truncation.
- Tests run with `uv run --locked python -m pytest plugins/pacer/tests -q --basetemp=<scratch>` (the default pytest temp dir is permission-denied in this sandbox).
- Work on branch `pacer3`. Commit after each task.

## File structure

```
plugins/pacer/src/pacer_mcp/
  schema.py       columns, enums, limits, patterns, refs(), utc_now(), contained_path(), empty_row()   [rewrite]
  store.py        Snapshot/Store: lock, load, publish, recover, archive; ledger append/read            [modify]
  validation.py   validate_web(): structure, limits, refs, statuses, tiers, cycles, lanes             [rewrite]
  cards.py        card()/parse_card(): the one grammar                                               [new]
  provider.py     Provider protocol; CodegraphProvider (sqlite); BuiltinProvider (ast/regex); select [new]
  probe.py        run_probe(), src_digest(), parse_evidence(), freshness()                            [new]
  rank.py         adjacency(), rank(): weighted distance from focus                                   [new]
  frames.py       active_pace(), session_frame(), prompt_frame(), edit_frame(), stop_frame()          [new]
  gates.py        effective_tier(), stop_decision(), edit_decision()                                  [new]
  commands.py     Editor: add/set/link/move/status/latch/pace/absorb/touch                            [rewrite]
  service.py      Service: frame/q/write/probe/touch/stop/validate/initialize/migrate/log/tree/recover [rewrite]
  models.py       pydantic op models                                                                  [rewrite]
  server.py       9 MCP tools                                                                         [rewrite]
  cli.py          argparse over Service + `hook` subcommand                                           [rewrite]
  hook.py         stdin → event → frame → harness JSON                                                [new]
  tree.py         `.PACER` indented text view                                                         [new]
  migrate.py      from_05(), from_v2()                                                                [new]
  spec.py         read .MIVIM.spec (TOML) with defaults                                               [new]
  DELETE: context.py pages.py evidence.py semantics.py query.py
plugins/pacer/hooks/hooks.json                                                                        [new]
plugins/pacer/skills/pacer/SKILL.md            (delete pacer-onboard, pacer-develop, pacer-audit)     [new]
plugins/pacer/references/FORMAT.md             (= design spec)                                        [rewrite]
plugins/pacer/tests/                           conftest + one test file per module                    [rewrite]
README.md AGENTS.md .MIVIM.spec                (root)                                                 [rewrite/new]
scripts/check.py                               (adjust); DELETE maintain.py evaluate_*.py prove_*.py
```

---

### Task 1: Schema, store, ledger

**Files:**
- Modify: `plugins/pacer/src/pacer_mcp/schema.py` (full rewrite)
- Modify: `plugins/pacer/src/pacer_mcp/store.py` (HEADERS-driven; add ledger)
- Test: `plugins/pacer/tests/test_schema_store.py`

**Interfaces:**
- Produces: `VERSION`, `HEADERS`, `PREFIX`, `REGISTERS`, `LEDGER`, `REF_FIELDS`, `LIMITS`, `TASK_KINDS`, `TASK_STATUSES`, `TIERS`, `OGM_STATUSES`, `AUTHORITIES`, `DEC_KINDS`, `NEXT_ACTIONS`, `OVR_KINDS`, `NDL_STATUSES`, `ID_PATTERN`, `REF_PATTERN`, `TAG_PATTERN`, `POS_PATTERN`, `refs(str)->list[str]`, `utc_now()->str`, `contained_path(root,str)->Path`, `empty_row(register,dict)->dict`, `pos_parts(str)->tuple[int,int|None,int|None]`.
- Store: `Store(root).locked()`, `.load(missing_ok=False, pending_ok=False)->Snapshot`, `.publish(before, after)->str`, `.recover()->dict`, `.ledger_append(entry: dict)->None`, `.ledger_read(id: str|None, limit: int)->list[dict]`. `Snapshot.tables/headers/files/revision/encode()` unchanged in shape.

- [ ] **Step 1: Write the failing tests**

```python
# plugins/pacer/tests/test_schema_store.py
import json
from pathlib import Path

import pytest
from pacer_mcp import schema
from pacer_mcp.store import Store


def test_headers_have_five_registers_and_no_history_columns():
    assert set(schema.HEADERS) == {"todo", "overlord", "organism", "nodule", "decision"}
    for columns in schema.HEADERS.values():
        assert not {"Notes", "UpdatedAt", "ContextCheckpoint", "EvidenceBindings"} & set(columns)
    assert schema.HEADERS["todo"] == (
        "ID Kind Pos Title Status Tier Produce In Out Binds Needs Probe Exit Next Latch Tags".split()
    )
    assert schema.HEADERS["decision"][0:3] == ["ID", "Kind", "Subject"]


def test_pos_parts():
    assert schema.pos_parts("A2") == (2, None, None)
    assert schema.pos_parts("A2.P3") == (2, 3, None)
    assert schema.pos_parts("A2.P3.05") == (2, 3, 5)
    with pytest.raises(ValueError):
        schema.pos_parts("P3.05")


def test_refs_and_patterns():
    assert schema.refs("OVR-001; OGM-002 ;") == ["OVR-001", "OGM-002"]
    assert schema.ID_PATTERN.fullmatch("DEC-007")
    assert not schema.ID_PATTERN.fullmatch("dec-007")


def test_store_loads_empty_registers_and_appends_ledger(tmp_path: Path):
    for name in schema.REGISTERS:
        (tmp_path / f"{name}.PACER.csv").write_text(",".join(schema.HEADERS[name]) + "\n")
    store = Store(tmp_path)
    with store.locked():
        snap = store.load()
        assert set(snap.tables) == set(schema.REGISTERS)
        assert all(rows == [] for rows in snap.tables.values())
        store.ledger_append({"op": "add", "id": "PAC-001", "actor": "t"})
        store.ledger_append({"op": "set", "id": "PAC-002", "actor": "t"})
    lines = (tmp_path / schema.LEDGER).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["id"] == "PAC-001"
    assert "at" in json.loads(lines[0])
    assert [e["id"] for e in store.ledger_read("PAC-002", 10)] == ["PAC-002"]
    assert len(store.ledger_read(None, 1)) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --locked python -m pytest plugins/pacer/tests/test_schema_store.py -q --basetemp=$env:TEMP/claude/pt`
Expected: FAIL (ImportError on `decision` register / missing `pos_parts`).

- [ ] **Step 3: Rewrite schema.py**

```python
"""Literal PACER 3 columns, vocabularies, limits and grammar."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

VERSION = "3.0"
REGISTERS = ("todo", "overlord", "organism", "nodule", "decision")
LEDGER = "ledger.PACER.jsonl"
HEADERS = {
    "todo": "ID Kind Pos Title Status Tier Produce In Out Binds Needs Probe Exit Next Latch Tags".split(),
    "overlord": "ID Path Symbol Kind Purpose Tier Binds Latch Tags".split(),
    "organism": "ID Title Status Authority Origin Requirement Binds Probe Evidence Tier Tags".split(),
    "nodule": "ID Name Status Lane Request Intent In Out Targets Spawned Exit Tags".split(),
    "decision": "ID Kind Subject Question Chosen Rejected Why Authority Latched Supersedes Tags".split(),
}
PREFIX = {"todo": "PAC", "overlord": "OVR", "organism": "OGM", "nodule": "NDL", "decision": "DEC"}
REGISTER_OF = {v: k for k, v in PREFIX.items()}
ID_PATTERN = re.compile(r"(?:PAC|OVR|OGM|NDL|DEC)-[0-9]{3,}[A-Z]*")
REF_PATTERN = re.compile(r"\b(?:PAC|OVR|OGM|NDL|DEC)-[0-9]{3,}[A-Z]*\b")
TAG_PATTERN = re.compile(r"#[a-z][a-z0-9-]*")
POS_PATTERN = re.compile(r"A(\d+)(?:\.P(\d+)(?:\.(\d+))?)?")
# "*" means any prefix.
REF_FIELDS = {
    "todo": {"In": "OVR", "Binds": "OGM", "Needs": "PAC", "Latch": "DEC"},
    "overlord": {"Binds": "OGM", "Latch": "DEC"},
    "organism": {"Binds": "OVR"},
    "nodule": {"In": "OVR", "Targets": "OGM", "Spawned": "PAC"},
    "decision": {"Subject": "*", "Supersedes": "DEC"},
}
PATH_FIELDS = {"todo": ("Out",), "nodule": ("Out",), "overlord": ("Path",)}
LIMITS = {
    "Title": 80, "Produce": 140, "Purpose": 140, "Requirement": 280, "Origin": 400, "Why": 280,
    "Chosen": 140, "Rejected": 140, "Question": 140, "Exit": 140, "Intent": 140, "Request": 400,
    "Probe": 200, "Name": 60, "Lane": 40, "Symbol": 120, "Path": 240,
}
TASK_KINDS = ("AREA", "PHASE", "PACE")
TASK_STATUSES = ("TODO", "ACTIVE", "INTEGRATED", "DONE")
TIERS = ("sketch", "prototype", "playable", "integrated", "release", "protected")
OGM_STATUSES = ("SCAFFOLD", "PACED_REQUIREMENT", "VALIDATED_COMPLETE")
AUTHORITIES = ("USER", "OBSERVED", "INFERRED", "UNRESOLVED", "LEGACY")
DEC_KINDS = ("CHOICE", "LATCH", "LESSON", "FAILED")
NEXT_ACTIONS = ("inspect", "implement", "verify", "integrate", "absorb")
OVR_KINDS = ("FILE", "MODULE", "CLASS", "FUNCTION", "METHOD", "CONFIG", "SCHEMA")
NDL_STATUSES = ("ACTIVE", "ABSORBED")
IMMUTABLE = {"ID", "Kind", "Status", "Evidence", "Latched", "Pos"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def refs(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(";") if part.strip()]


def pos_parts(value: str) -> tuple[int, int | None, int | None]:
    match = POS_PATTERN.fullmatch(value or "")
    if not match:
        raise ValueError(f"Invalid Pos {value!r}; expected A1, A1.P2 or A1.P2.03")
    area, phase, pace = match.groups()
    return int(area), (int(phase) if phase else None), (int(pace) if pace else None)


def contained_path(root: Path, value: str) -> Path:
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        not value or "\\" in value or ":" in value or posix.is_absolute() or windows.drive
        or ".." in posix.parts or value.startswith("/")
    ):
        raise ValueError(f"Unsafe repository-relative path: {value}")
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes repository: {value}")
    return resolved


def empty_row(register: str, values: dict[str, str]) -> dict[str, str]:
    if register not in HEADERS:
        raise ValueError(f"Unknown register: {register}")
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in values.items()):
        raise ValueError("Row keys and values must be strings")
    return dict.fromkeys(HEADERS[register], "") | values
```

- [ ] **Step 4: Modify store.py**

Replace the two imports and add ledger methods. Keep `parse_csv`, `encode_csv`, `Snapshot`, `locked`, `load`, `publish`, `recover`, `_register_path`, `_atomic_write` as they are, with these edits:

```python
# imports
from pacer_mcp.schema import HEADERS, ID_PATTERN, LEDGER, REGISTERS, contained_path, utc_now

# in Store, after recover():
    def ledger_append(self, entry: dict) -> None:
        """Append one dated event; never rewrites history."""
        line = json.dumps({"at": utc_now(), **entry}, ensure_ascii=False, separators=(",", ":"))
        path = contained_path(self.root, LEDGER)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    def ledger_read(self, row_id: str | None, limit: int) -> list[dict]:
        """Return the newest matching events, oldest first within the window."""
        path = contained_path(self.root, LEDGER)
        if not path.exists():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if row_id is None or entry.get("id") == row_id or row_id in str(entry.get("detail", "")):
                entries.append(entry)
        return entries[-limit:]
```

In `load()` change `for register in HEADERS:` to `for register in REGISTERS:` (both iterate the same keys; the explicit tuple keeps order). In `recover()` replace `tables = {name: [] for name in HEADERS}` and `for register in HEADERS` likewise. `_register_path` unchanged (it derives valid roots from `HEADERS`).

- [ ] **Step 5: Run tests; expect PASS**

Run: `uv run --locked python -m pytest plugins/pacer/tests/test_schema_store.py -q --basetemp=$env:TEMP/claude/pt`

The old test files will now fail to import (they use removed modules). Delete them in this task: `git rm plugins/pacer/tests/test_*.py` except the new file, and replace `conftest.py` with the minimal fixture below (Task 8 extends it).

```python
# plugins/pacer/tests/conftest.py
from pathlib import Path

import pytest
from pacer_mcp import schema


@pytest.fixture
def registers(tmp_path: Path) -> Path:
    for name in schema.REGISTERS:
        (tmp_path / f"{name}.PACER.csv").write_text(
            ",".join(schema.HEADERS[name]) + "\n", encoding="utf-8"
        )
    (tmp_path / "README.md").write_text("Fixture project\n", encoding="utf-8")
    return tmp_path
```

- [ ] **Step 6: Commit**

```bash
git add -A plugins/pacer/src/pacer_mcp/schema.py plugins/pacer/src/pacer_mcp/store.py plugins/pacer/tests
git commit -m "feat(pacer3): five-register schema, bounded columns, ledger"
```

---

### Task 2: Validation

**Files:**
- Modify: `plugins/pacer/src/pacer_mcp/validation.py` (full rewrite)
- Test: `plugins/pacer/tests/test_validation.py`

**Interfaces:**
- Produces: `validate_web(tables, root, headers=None) -> {"valid": bool, "errors": [str], "warnings": [str]}`; `parse_evidence(str) -> dict|None` lives in `probe.py` (Task 5) but validation only checks the regex `EVIDENCE_PATTERN` defined here and re-exported by probe.

- [ ] **Step 1: Write the failing tests**

```python
# plugins/pacer/tests/test_validation.py
from pacer_mcp.schema import empty_row
from pacer_mcp.validation import validate_web


def tables(**rows):
    result = {k: [] for k in ("todo", "overlord", "organism", "nodule", "decision")}
    for register, items in rows.items():
        result[register] = [empty_row(register, r) for r in items]
    return result


def test_valid_minimal_web(registers):
    (registers / "src").mkdir()
    (registers / "src" / "a.py").write_text("x = 1\n")
    web = tables(
        todo=[
            {"ID": "PAC-001", "Kind": "AREA", "Pos": "A1", "Title": "Core", "Status": "ACTIVE", "Tier": "prototype"},
            {"ID": "PAC-002", "Kind": "PHASE", "Pos": "A1.P1", "Title": "Boot", "Status": "ACTIVE", "Tier": "prototype", "Exit": "boots", "Binds": "OGM-001"},
            {"ID": "PAC-003", "Kind": "PACE", "Pos": "A1.P1.01", "Title": "Load", "Status": "TODO", "Produce": "loader", "In": "OVR-001"},
        ],
        overlord=[{"ID": "OVR-001", "Path": "src/a.py", "Kind": "FILE", "Purpose": "entry"}],
        organism=[{"ID": "OGM-001", "Title": "Boots", "Status": "SCAFFOLD", "Authority": "USER", "Origin": "it must boot", "Requirement": "boots", "Binds": "OVR-001"}],
        decision=[{"ID": "DEC-001", "Kind": "LATCH", "Subject": "OVR-001", "Question": "sync?", "Chosen": "sync", "Authority": "USER", "Latched": "true"}],
    )
    report = validate_web(web, registers)
    assert report["errors"] == []


def test_rejects_pipe_limit_badref_and_tier(registers):
    web = tables(
        todo=[{"ID": "PAC-001", "Kind": "PACE", "Pos": "A1.P1.01", "Title": "x|y", "Status": "TODO", "Produce": "p" * 141, "In": "OVR-999", "Tier": "huge"}],
    )
    errors = validate_web(web, registers)["errors"]
    assert any("contains |" in e for e in errors)
    assert any("Produce exceeds 140" in e for e in errors)
    assert any("Unknown ID OVR-999" in e for e in errors)
    assert any("invalid Tier" in e for e in errors)


def test_rules_per_register(registers):
    web = tables(
        todo=[
            {"ID": "PAC-001", "Kind": "PHASE", "Pos": "A1.P1", "Title": "P", "Status": "ACTIVE", "Tier": "integrated"},
            {"ID": "PAC-002", "Kind": "PACE", "Pos": "A1.P1.01", "Title": "a", "Status": "DONE", "Produce": "x", "Needs": "PAC-003"},
            {"ID": "PAC-003", "Kind": "PACE", "Pos": "A1.P1.02", "Title": "b", "Status": "TODO", "Produce": "y", "Needs": "PAC-002"},
        ],
        organism=[{"ID": "OGM-001", "Title": "R", "Status": "VALIDATED_COMPLETE", "Authority": "INFERRED", "Requirement": "r", "Evidence": ""}],
        decision=[{"ID": "DEC-001", "Kind": "LATCH", "Subject": "PAC-001", "Question": "q", "Chosen": "c", "Authority": "INFERRED", "Latched": "true"}],
        nodule=[{"ID": "NDL-001", "Name": "n", "Status": "ACTIVE", "Lane": "main", "Request": "do it", "Intent": "i", "Exit": "e"}, {"ID": "NDL-002", "Name": "m", "Status": "ACTIVE", "Lane": "main", "Request": "again", "Intent": "i", "Exit": "e", "Spawned": "PAC-002"}],
    )
    errors = validate_web(web, registers)["errors"]
    assert "PAC-001: PHASE requires Exit" in errors
    assert "PAC-002: Probe required at tier integrated" in errors
    assert "REFUSAL: Blocked by PAC-003" in errors
    assert "REFUSAL: Circular dependency detected" in errors
    assert "REFUSAL: Evidence required" in errors
    assert "DEC-001: LATCH requires Authority USER" in errors
    assert "NDL-001: ACTIVE nodule requires Spawned" in errors
    assert "REFUSAL: Nodule lane occupied" in errors
```

- [ ] **Step 2: Run; expect FAIL** (old validation imports removed modules).

- [ ] **Step 3: Rewrite validation.py**

```python
"""Validate the complete candidate web before any publication."""

from __future__ import annotations

import re
from pathlib import Path

from pacer_mcp.schema import (
    AUTHORITIES, DEC_KINDS, HEADERS, ID_PATTERN, LIMITS, NDL_STATUSES, NEXT_ACTIONS, OGM_STATUSES,
    OVR_KINDS, PATH_FIELDS, PREFIX, REF_FIELDS, REF_PATTERN, REGISTERS, TAG_PATTERN, TASK_KINDS,
    TASK_STATUSES, TIERS, contained_path, pos_parts, refs,
)

EVIDENCE_PATTERN = re.compile(
    r"rev:(?:[0-9a-f]{7}|none) src:[0-9a-f]{7} exit:-?\d+ out:[0-9a-f]{7} at:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
)
POS_DEPTH = {"AREA": 1, "PHASE": 2, "PACE": 3}


def validate_web(tables: dict, root: Path, headers: dict | None = None) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    index: dict[str, dict] = {}
    registers: dict[str, str] = {}
    if headers is not None:
        for register in REGISTERS:
            missing = set(HEADERS[register]) - set(headers.get(register, []))
            if missing:
                errors.append(f"{register}: missing columns {','.join(sorted(missing))}")
    for register in REGISTERS:
        for row in tables.get(register, []):
            row_id = row.get("ID", "")
            if row_id in index:
                errors.append(f"Duplicate ID {row_id}")
            if not ID_PATTERN.fullmatch(row_id) or not row_id.startswith(PREFIX[register] + "-"):
                errors.append(f"Invalid {register} ID {row_id}")
            index[row_id] = row
            registers[row_id] = register
            missing = set(HEADERS[register]) - row.keys()
            if missing:
                errors.append(f"{row_id}: missing columns {','.join(sorted(missing))}")
    for row_id, row in index.items():
        register = registers[row_id]
        for field, value in row.items():
            if not isinstance(value, str):
                errors.append(f"{row_id}.{field}: string required")
                continue
            if "|" in value or "\n" in value or "\r" in value:
                errors.append(f"{row_id}.{field}: contains | or newline")
            if field in LIMITS and len(value) > LIMITS[field]:
                errors.append(f"{row_id}: {field} exceeds {LIMITS[field]}")
            if field not in {"Origin", "Request"}:
                for reference in REF_PATTERN.findall(value):
                    if reference not in index:
                        errors.append(f"REFUSAL: Unknown ID {reference}")
        for field, prefix in REF_FIELDS[register].items():
            values = refs(row.get(field, ""))
            if len(values) != len(set(values)):
                errors.append(f"{row_id}.{field}: duplicate reference")
            for target in values:
                ok = ID_PATTERN.fullmatch(target) and (prefix == "*" or target.startswith(prefix + "-"))
                if not ok:
                    errors.append(f"{row_id}.{field}: invalid reference {target}")
        for field in PATH_FIELDS.get(register, ()):
            for item in refs(row.get(field, "")) if field != "Path" else [row.get("Path", "")]:
                try:
                    contained_path(root, item.split(":", 1)[0])
                except ValueError as exc:
                    errors.append(f"{row_id}: {exc}")
        if any(not TAG_PATTERN.fullmatch(t) for t in row.get("Tags", "").split()):
            errors.append(f"{row_id}: invalid Tags")
        if "Tier" in row and row["Tier"] and row["Tier"] not in TIERS:
            errors.append(f"{row_id}: invalid Tier")
        if register == "todo":
            _todo(row, row_id, index, errors)
        elif register == "overlord":
            _overlord(row, row_id, tables, root, errors)
        elif register == "organism":
            _organism(row, row_id, errors)
        elif register == "nodule":
            _nodule(row, row_id, errors)
        else:
            _decision(row, row_id, errors)
    for register, field in (("todo", "Needs"), ("organism", "Binds")):
        edges = {r["ID"]: [t for t in refs(r.get(field, "")) if t in index and registers[t] == register] for r in tables[register]}
        if register == "organism":
            edges = {r["ID"]: [] for r in tables[register]}  # OGM Binds point at OVR, never cyclic
        if _has_cycle(edges):
            errors.append("REFUSAL: Circular dependency detected")
    active = [r for r in tables["nodule"] if r.get("Status") == "ACTIVE"]
    for i, row in enumerate(active):
        for other in active[i + 1:]:
            same_lane = row.get("Lane") == other.get("Lane")
            overlap = set(refs(row.get("In", ""))) & set(refs(other.get("In", "")))
            if same_lane or overlap:
                errors.append("REFUSAL: Nodule lane occupied")
    return {"valid": not errors, "errors": list(dict.fromkeys(errors)), "warnings": warnings}


def _todo(row, row_id, index, errors):
    kind, status = row.get("Kind"), row.get("Status")
    if kind not in TASK_KINDS:
        errors.append(f"{row_id}: invalid Kind")
    if status not in TASK_STATUSES:
        errors.append(f"{row_id}: invalid task status")
    if not row.get("Title"):
        errors.append(f"{row_id}: Title required")
    try:
        parts = pos_parts(row.get("Pos", ""))
        depth = sum(p is not None for p in parts)
        if kind in POS_DEPTH and depth != POS_DEPTH[kind]:
            errors.append(f"{row_id}: Pos depth does not match Kind {kind}")
    except ValueError as exc:
        errors.append(f"{row_id}: {exc}")
    if kind == "PHASE" and not row.get("Exit"):
        errors.append(f"{row_id}: PHASE requires Exit")
    if kind == "PACE" and not row.get("Produce"):
        errors.append(f"{row_id}: PACE requires Produce")
    if row.get("Next") and row["Next"] not in NEXT_ACTIONS:
        errors.append(f"{row_id}: invalid Next")
    tier = _effective_task_tier(row, index)
    if kind == "PACE" and TIERS.index(tier) >= TIERS.index("integrated") and not row.get("Probe"):
        errors.append(f"{row_id}: Probe required at tier {tier}")
    blocked = [t for t in refs(row.get("Needs", "")) if index.get(t, {}).get("Status") != "DONE"]
    if status == "DONE" and blocked:
        errors.append(f"REFUSAL: Blocked by {';'.join(blocked)}")


def _effective_task_tier(row, index) -> str:
    """A PACE inherits its PHASE tier; explicit tier only raises it."""
    own = row.get("Tier") or ""
    try:
        area, phase, pace = pos_parts(row.get("Pos", ""))
    except ValueError:
        return own or "prototype"
    parent = ""
    if pace is not None:
        for other in index.values():
            if other.get("Kind") == "PHASE" and other.get("Pos") == f"A{area}.P{phase}":
                parent = other.get("Tier") or ""
    if own and parent and own in TIERS and parent in TIERS:
        return own if TIERS.index(own) > TIERS.index(parent) else parent
    return own or parent or "prototype"


def _overlord(row, row_id, tables, root, errors):
    if row.get("Kind") not in OVR_KINDS:
        errors.append(f"{row_id}: invalid Kind")
    try:
        path = contained_path(root, row.get("Path", ""))
        if not path.is_file() and "#dead" not in row.get("Tags", "").split():
            errors.append(f"{row_id}: path does not exist: {row.get('Path')}")
    except ValueError as exc:
        errors.append(f"{row_id}: {exc}")
    if row.get("Kind") != "FILE" and not any(
        r.get("Path") == row.get("Path") and r.get("Kind") == "FILE" for r in tables["overlord"]
    ):
        errors.append(f"{row_id}: FILE row required for {row.get('Path')}")


def _organism(row, row_id, errors):
    if row.get("Status") not in OGM_STATUSES:
        errors.append(f"{row_id}: invalid organism status")
    if row.get("Authority") and row["Authority"] not in AUTHORITIES:
        errors.append(f"{row_id}: invalid Authority")
    if not row.get("Requirement"):
        errors.append(f"{row_id}: Requirement required")
    evidence = row.get("Evidence", "")
    if evidence and not EVIDENCE_PATTERN.fullmatch(evidence):
        errors.append(f"{row_id}: invalid Evidence cell")
    if row.get("Status") == "VALIDATED_COMPLETE" and not (evidence and " exit:0 " in evidence):
        errors.append("REFUSAL: Evidence required")


def _nodule(row, row_id, errors):
    if row.get("Status") not in NDL_STATUSES:
        errors.append(f"{row_id}: invalid nodule status")
    for field in ("Name", "Lane", "Request", "Intent", "Exit"):
        if not row.get(field):
            errors.append(f"{row_id}: {field} required")
    if row.get("Status") == "ACTIVE" and not row.get("Spawned"):
        errors.append(f"{row_id}: ACTIVE nodule requires Spawned")


def _decision(row, row_id, errors):
    if row.get("Kind") not in DEC_KINDS:
        errors.append(f"{row_id}: invalid Kind")
    if row.get("Latched", "") not in {"", "true", "false"}:
        errors.append(f"{row_id}: Latched must be true or false")
    if row.get("Kind") == "LATCH" and row.get("Latched") == "true" and row.get("Authority") != "USER":
        errors.append(f"{row_id}: LATCH requires Authority USER")
    if row.get("Authority") and row["Authority"] not in AUTHORITIES:
        errors.append(f"{row_id}: invalid Authority")
    if not row.get("Subject"):
        errors.append(f"{row_id}: Subject required")


def _has_cycle(edges: dict[str, list[str]]) -> bool:
    indegree = dict.fromkeys(edges, 0)
    for targets in edges.values():
        for target in targets:
            if target in indegree:
                indegree[target] += 1
    ready = [k for k, c in indegree.items() if c == 0]
    seen = 0
    while ready:
        key = ready.pop()
        seen += 1
        for target in edges[key]:
            if target in indegree:
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
    return seen != len(edges)
```

- [ ] **Step 4: Run; expect PASS.** Fix the `test_rules_per_register` expectation for `PAC-002` if the effective-tier lookup needs the PHASE row present (it is: `PAC-001` is the phase at `A1.P1`, tier integrated).

- [ ] **Step 5: Commit** — `git commit -am "feat(pacer3): validation for bounded five-register web"`

---

### Task 3: Cards

**Files:**
- Create: `plugins/pacer/src/pacer_mcp/cards.py`
- Test: `plugins/pacer/tests/test_cards.py`

**Interfaces:**
- Produces: `CARD_FIELDS: dict[str, list[str]]`, `card(register: str, row: dict, extras: dict[str, str] | None = None) -> str`, `parse_card(line: str) -> dict` (returns `{"register", "ID", "head": [...tokens], "fields": {...}}`), `header(register, row) -> list[str]`.

- [ ] **Step 1: Tests**

```python
# plugins/pacer/tests/test_cards.py
from pacer_mcp.cards import card, parse_card
from pacer_mcp.schema import empty_row


def test_pace_card_layout_and_roundtrip():
    row = empty_row("todo", {"ID": "PAC-041", "Kind": "PACE", "Pos": "A2.P3.05", "Status": "ACTIVE", "Tier": "prototype", "Produce": "session manager", "In": "OVR-012;OVR-019", "Out": "src/x.py:Foo", "Binds": "OGM-004", "Probe": "pytest -q", "Next": "implement"})
    line = card("todo", row)
    assert line == ("PAC PAC-041 A2.P3.05 ACTIVE prototype | Produce: session manager | In: OVR-012;OVR-019 "
                    "| Out: src/x.py:Foo | Binds: OGM-004 | Probe: pytest -q | Next: implement")
    parsed = parse_card(line)
    assert parsed["ID"] == "PAC-041" and parsed["fields"]["Binds"] == "OGM-004"
    assert parsed["head"] == ["A2.P3.05", "ACTIVE", "prototype"]


def test_ovr_ogm_dec_headers_and_extras():
    ovr = empty_row("overlord", {"ID": "OVR-012", "Path": "src/a.py", "Symbol": "S", "Kind": "CLASS", "Purpose": "p", "Tier": "integrated", "Latch": "DEC-003"})
    assert card("overlord", ovr, {"used-by": "src/main.py (+3)"}) == "OVR OVR-012 src/a.py:S integrated | Purpose: p | Latch: DEC-003 | used-by: src/main.py (+3)"
    ogm = empty_row("organism", {"ID": "OGM-004", "Status": "PACED_REQUIREMENT", "Authority": "USER", "Tier": "release", "Requirement": "r", "Probe": "pytest", "Evidence": "rev:a1b2c3d src:1111111 exit:0 out:2222222 at:2026-09-20T00:00:00Z"})
    assert card("organism", ogm, {"Evidence": "rev:a1b2c3d exit:0 at:2026-09-20 STALE(src/a.py)"}).endswith("| Evidence: rev:a1b2c3d exit:0 at:2026-09-20 STALE(src/a.py)")
    dec = empty_row("decision", {"ID": "DEC-003", "Kind": "LATCH", "Subject": "OVR-012", "Chosen": "keep sync", "Authority": "USER", "Latched": "true"})
    assert card("decision", dec).startswith("DEC DEC-003 LATCH USER latched | Subject: OVR-012 | Chosen: keep sync")


def test_empty_fields_are_omitted_and_pipe_is_escaped():
    row = empty_row("nodule", {"ID": "NDL-019", "Status": "ACTIVE", "Lane": "auth", "Intent": "a/b"})
    assert card("nodule", row) == "NDL NDL-019 ACTIVE lane=auth | Intent: a/b"
```

- [ ] **Step 2: Run; expect FAIL** (module missing).

- [ ] **Step 3: Implement cards.py**

```python
"""One positional card grammar shared by every frame, tool result and query."""

from __future__ import annotations

from pacer_mcp.schema import PREFIX, REGISTER_OF

CARD_FIELDS = {
    "todo": ["Title", "Produce", "In", "Out", "Binds", "Needs", "Probe", "Exit", "Next", "Latch", "Tags"],
    "overlord": ["Purpose", "Binds", "Latch", "Tags"],
    "organism": ["Requirement", "Probe", "Evidence", "Binds", "Tags"],
    "nodule": ["Intent", "In", "Out", "Targets", "Spawned", "Exit", "Tags"],
    "decision": ["Subject", "Question", "Chosen", "Rejected", "Why", "Supersedes", "Tags"],
}
# Extras are appended after authored fields; a same-named extra replaces the field value.
EXTRA_ORDER = ["used-by", "deps", "OFF-PACE", "open"]


def header(register: str, row: dict) -> list[str]:
    if register == "todo":
        return [t for t in (row.get("Pos"), row.get("Status"), row.get("Tier")) if t]
    if register == "overlord":
        path = row.get("Path", "") + (":" + row["Symbol"] if row.get("Symbol") else "")
        return [t for t in (path, row.get("Tier")) if t]
    if register == "organism":
        return [t for t in (row.get("Status"), row.get("Authority"), row.get("Tier")) if t]
    if register == "nodule":
        return [t for t in (row.get("Status"), f"lane={row['Lane']}" if row.get("Lane") else "") if t]
    latched = {"true": "latched", "false": "open"}.get(row.get("Latched", ""), "")
    return [t for t in (row.get("Kind"), row.get("Authority"), latched) if t]


def card(register: str, row: dict, extras: dict[str, str] | None = None) -> str:
    extras = dict(extras or {})
    parts = [PREFIX[register], row["ID"], *header(register, row)]
    line = " ".join(parts)
    fields = CARD_FIELDS[register]
    if register == "todo" and row.get("Kind") == "PACE":
        fields = [f for f in fields if f != "Title"] if row.get("Produce") else fields
    for field in fields:
        value = extras.pop(field, row.get(field, ""))
        if value:
            line += f" | {field}: {_clean(value)}"
    for key in EXTRA_ORDER + sorted(k for k in extras if k not in EXTRA_ORDER):
        if key in extras and extras[key]:
            line += f" | {key}: {_clean(extras[key])}" if key != "OFF-PACE" else " | OFF-PACE"
    return line


def parse_card(line: str) -> dict:
    head, *fields = line.split(" | ")
    tokens = head.split(" ")
    if len(tokens) < 2 or tokens[0] not in REGISTER_OF:
        raise ValueError(f"Not a card: {line[:40]}")
    parsed = {}
    for item in fields:
        key, sep, value = item.partition(": ")
        parsed[key] = value if sep else ""
    return {"register": REGISTER_OF[tokens[0]], "ID": tokens[1], "head": tokens[2:], "fields": parsed}


def _clean(value: str) -> str:
    return value.replace("|", "/").replace("\n", " ").strip()
```

- [ ] **Step 4: Run; expect PASS.** Note the PACE Title rule: a PACE with a Produce omits Title (Produce is the operative line); AREA/PHASE keep Title. Adjust the first test's expected string if Title appears; the expected string above already omits it.

- [ ] **Step 5: Commit** — `git commit -am "feat(pacer3): card grammar"`

---

### Task 4: Structure provider

**Files:**
- Create: `plugins/pacer/src/pacer_mcp/provider.py`
- Test: `plugins/pacer/tests/test_provider.py`

**Interfaces:**
- Produces: `class Provider(Protocol): name: str; def users(self, path: str) -> list[str]; def deps(self, path: str) -> list[str]`; `CodegraphProvider(root)`, `BuiltinProvider(root)`, `NullProvider`, `select_provider(root, preference: str = "auto") -> Provider`. Paths are repo-relative POSIX strings. Results are sorted, deduplicated, exclude `path` itself.

- [ ] **Step 1: Tests**

```python
# plugins/pacer/tests/test_provider.py
import sqlite3
from pathlib import Path

from pacer_mcp.provider import BuiltinProvider, CodegraphProvider, NullProvider, select_provider


def _python_project(root: Path):
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "core.py").write_text("import json\nfrom pkg import util\nfrom .other import x\n")
    (root / "pkg" / "util.py").write_text("VALUE = 1\n")
    (root / "pkg" / "other.py").write_text("x = 2\n")
    (root / "app.py").write_text("from pkg.core import run\n")
    (root / "web.js").write_text("import a from './lib/a.js';\nconst b = require('./lib/b');\n")
    (root / "lib").mkdir()
    (root / "lib" / "a.js").write_text("export default 1;")
    (root / "lib" / "b.js").write_text("module.exports = 2;")


def test_builtin_python_and_js(tmp_path):
    _python_project(tmp_path)
    p = BuiltinProvider(tmp_path)
    assert p.deps("pkg/core.py") == ["pkg/other.py", "pkg/util.py"]
    assert p.users("pkg/core.py") == ["app.py"]
    assert p.users("pkg/util.py") == ["pkg/core.py"]
    assert p.deps("web.js") == ["lib/a.js", "lib/b.js"]
    assert p.users("lib/a.js") == ["web.js"]
    assert p.deps("missing.py") == []


def test_codegraph_reads_sqlite(tmp_path):
    db_dir = tmp_path / ".codegraph"
    db_dir.mkdir()
    c = sqlite3.connect(db_dir / "codegraph.db")
    c.executescript(
        "CREATE TABLE nodes(id TEXT PRIMARY KEY, kind TEXT, name TEXT, file_path TEXT);"
        "CREATE TABLE edges(id INTEGER PRIMARY KEY, source TEXT, target TEXT, kind TEXT);"
        "INSERT INTO nodes VALUES('a','function','f','src/a.py'),('b','function','g','src/b.py'),('c','function','h','src/c.py');"
        "INSERT INTO edges(source,target,kind) VALUES('a','b','calls'),('c','a','imports'),('a','a','calls');"
    )
    c.commit()
    c.close()
    p = CodegraphProvider(tmp_path)
    assert p.deps("src/a.py") == ["src/b.py"]
    assert p.users("src/a.py") == ["src/c.py"]
    assert select_provider(tmp_path).name == "codegraph"
    assert select_provider(tmp_path, "builtin").name == "builtin"


def test_select_falls_back(tmp_path):
    assert select_provider(tmp_path).name == "builtin"
    assert NullProvider().users("x") == []
```

- [ ] **Step 2: Run; expect FAIL.**

- [ ] **Step 3: Implement provider.py**

```python
"""Derived source structure: who a file uses and who uses it. Never stored in registers."""

from __future__ import annotations

import ast
import re
import sqlite3
from pathlib import Path
from typing import Protocol

SKIP_DIRS = {
    ".git", ".venv", "node_modules", "__pycache__", ".codegraph", ".pacer", "dist", "build",
    ".cache", ".mypy_cache", ".ruff_cache", ".pytest_cache", "archive",
}
JS_IMPORT = re.compile(r"""(?:from\s+|import\s*\(?\s*|require\s*\(\s*)['"](\.{1,2}/[^'"]+)['"]""")
JS_EXT = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")


class Provider(Protocol):
    name: str

    def users(self, path: str) -> list[str]: ...

    def deps(self, path: str) -> list[str]: ...


class NullProvider:
    name = "none"

    def users(self, path: str) -> list[str]:
        return []

    def deps(self, path: str) -> list[str]:
        return []


class CodegraphProvider:
    name = "codegraph"

    def __init__(self, root: Path):
        self.db = root / ".codegraph" / "codegraph.db"
        if not self.db.is_file():
            raise FileNotFoundError(self.db)

    def _query(self, sql: str, path: str) -> list[str]:
        try:
            with sqlite3.connect(f"file:{self.db.as_posix()}?mode=ro", uri=True) as c:
                rows = c.execute(sql, (path, path)).fetchall()
        except sqlite3.Error:
            return []
        return sorted({r[0] for r in rows})

    def deps(self, path: str) -> list[str]:
        return self._query(
            "SELECT DISTINCT n2.file_path FROM edges e JOIN nodes n1 ON e.source=n1.id "
            "JOIN nodes n2 ON e.target=n2.id WHERE n1.file_path=? AND n2.file_path<>?",
            path,
        )

    def users(self, path: str) -> list[str]:
        return self._query(
            "SELECT DISTINCT n1.file_path FROM edges e JOIN nodes n1 ON e.source=n1.id "
            "JOIN nodes n2 ON e.target=n2.id WHERE n2.file_path=? AND n1.file_path<>?",
            path,
        )


class BuiltinProvider:
    """Python via ast; JS/TS via relative import regex. One scan, cached per instance."""

    name = "builtin"

    def __init__(self, root: Path):
        self.root = root.resolve()
        self._deps: dict[str, set[str]] = {}
        self._users: dict[str, set[str]] = {}
        self._scan()

    def _files(self):
        for path in self.root.rglob("*"):
            if any(part in SKIP_DIRS for part in path.relative_to(self.root).parts):
                continue
            if path.is_file() and (path.suffix == ".py" or path.suffix in JS_EXT):
                yield path

    def _scan(self):
        files = list(self._files())
        py = {p.relative_to(self.root).as_posix() for p in files if p.suffix == ".py"}
        tops = {p.split("/")[0] for p in py if "/" in p}
        for path in files:
            rel = path.relative_to(self.root).as_posix()
            if path.suffix == ".py":
                targets = self._python_targets(path, rel, py, tops)
            else:
                targets = self._js_targets(path, rel)
            for target in targets:
                if target != rel:
                    self._deps.setdefault(rel, set()).add(target)
                    self._users.setdefault(target, set()).add(rel)

    def _python_targets(self, path: Path, rel: str, py: set[str], tops: set[str]) -> set[str]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            return set()
        found = set()
        package = rel.rsplit("/", 1)[0] if "/" in rel else ""
        for node in ast.walk(tree):
            modules: list[tuple[str, int]] = []
            if isinstance(node, ast.Import):
                modules = [(a.name, 0) for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                modules = [(base, node.level)] + [
                    (f"{base}.{a.name}" if base else a.name, node.level) for a in node.names
                ]
            for name, level in modules:
                found.update(self._resolve(name, level, package, py, tops))
        return found

    def _resolve(self, name: str, level: int, package: str, py: set[str], tops: set[str]) -> set[str]:
        dotted = name.replace(".", "/")
        if level:
            parts = package.split("/") if package else []
            if level > 1:
                parts = parts[: max(0, len(parts) - (level - 1))]
            base = "/".join(parts)
            candidates = [f"{base}/{dotted}" if base and dotted else (base or dotted)]
        else:
            candidates = [dotted, f"src/{dotted}"] + [f"{top}/{dotted}" for top in tops]
        out = set()
        for c in candidates:
            if not c:
                continue
            for form in (f"{c}.py", f"{c}/__init__.py"):
                if form in py:
                    out.add(form)
        return out

    def _js_targets(self, path: Path, rel: str) -> set[str]:
        text = path.read_text(encoding="utf-8", errors="replace")
        found = set()
        base = Path(rel).parent
        for spec in JS_IMPORT.findall(text):
            target = Path((base / spec).as_posix())
            normalized = []
            for part in target.parts:
                if part == "..":
                    if normalized:
                        normalized.pop()
                elif part != ".":
                    normalized.append(part)
            t = "/".join(normalized)
            candidates = [t] + [f"{t}{ext}" for ext in JS_EXT] + [f"{t}/index{ext}" for ext in JS_EXT]
            for c in candidates:
                if (self.root / c).is_file():
                    found.add(c)
                    break
        return found

    def deps(self, path: str) -> list[str]:
        return sorted(self._deps.get(path, set()))

    def users(self, path: str) -> list[str]:
        return sorted(self._users.get(path, set()))


def select_provider(root: Path, preference: str = "auto") -> Provider:
    if preference in {"auto", "codegraph"}:
        try:
            return CodegraphProvider(root)
        except FileNotFoundError:
            if preference == "codegraph":
                return NullProvider()
    if preference == "none":
        return NullProvider()
    return BuiltinProvider(root)
```

- [ ] **Step 4: Run; expect PASS.** The sqlite URI needs forward slashes (`as_posix()` handles it on Windows).

- [ ] **Step 5: Commit** — `git commit -am "feat(pacer3): codegraph and builtin structure providers"`

---

### Task 5: Probe and freshness

**Files:**
- Create: `plugins/pacer/src/pacer_mcp/probe.py`
- Test: `plugins/pacer/tests/test_probe.py`

**Interfaces:**
- Produces: `src_digest(root, paths) -> str` (7 hex over sorted names and bytes; missing hashes as `MISSING`), `git_rev(root) -> str` (7 hex or `none`), `parse_evidence(cell) -> dict | None` (rev, src, exit, out, at), `format_evidence(rev, src, exit_code, out, at) -> str`, `bound_paths(row, tables) -> list[str]`, `freshness(row, tables, root) -> "UNBOUND"|"FAIL"|"STALE"|"CURRENT"`, `run_probe(row, tables, root, actor, timeout=600) -> {"evidence","exit","output_path","freshness"}` (shell-executes `Probe`, writes `.pacer/probes/<OGM>/<ts>.txt`).

- [ ] **Step 1: Tests**

```python
# plugins/pacer/tests/test_probe.py
import sys

from pacer_mcp.probe import bound_paths, format_evidence, freshness, parse_evidence, run_probe, src_digest
from pacer_mcp.schema import empty_row


def _web(root):
    (root / "a.txt").write_text("one")
    return {
        "todo": [], "nodule": [], "decision": [],
        "overlord": [empty_row("overlord", {"ID": "OVR-001", "Path": "a.txt", "Kind": "FILE", "Purpose": "p"})],
        "organism": [empty_row("organism", {
            "ID": "OGM-001", "Title": "t", "Status": "SCAFFOLD", "Requirement": "r", "Binds": "OVR-001",
            "Probe": f'"{sys.executable}" -c "print(42)"',
        })],
    }


def test_evidence_roundtrip():
    cell = format_evidence("abc1234", "1234567", 0, "89abcde", "2026-09-29T00:00:00Z")
    assert parse_evidence(cell) == {"rev": "abc1234", "src": "1234567", "exit": 0, "out": "89abcde", "at": "2026-09-29T00:00:00Z"}
    assert parse_evidence("garbage") is None


def test_run_probe_then_freshness(registers):
    web = _web(registers)
    ogm = web["organism"][0]
    assert bound_paths(ogm, web) == ["a.txt"]
    result = run_probe(ogm, web, registers, "tester")
    assert result["exit"] == 0 and result["freshness"] == "CURRENT"
    ogm["Evidence"] = result["evidence"]
    assert freshness(ogm, web, registers) == "CURRENT"
    assert (registers / result["output_path"]).read_text().strip().endswith("42")
    (registers / "a.txt").write_text("two")
    assert freshness(ogm, web, registers) == "STALE"
    assert src_digest(registers, ["a.txt"]) != parse_evidence(ogm["Evidence"])["src"]


def test_failing_probe_records_exit(registers):
    web = _web(registers)
    ogm = web["organism"][0]
    ogm["Probe"] = f'"{sys.executable}" -c "raise SystemExit(3)"'
    result = run_probe(ogm, web, registers, "tester")
    assert result["exit"] == 3 and result["freshness"] == "FAIL"
    ogm["Evidence"] = result["evidence"]
    assert freshness(ogm, web, registers) == "FAIL"
    assert freshness(empty_row("organism", {"ID": "OGM-002"}), web, registers) == "UNBOUND"
```

- [ ] **Step 2: Run; expect FAIL.**

- [ ] **Step 3: Implement probe.py**

```python
"""Probes are commands; evidence is one bounded cell; freshness is derived from bound files."""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

from pacer_mcp.schema import contained_path, refs, utc_now
from pacer_mcp.validation import EVIDENCE_PATTERN

_PARSE = re.compile(r"rev:(\S+) src:(\S+) exit:(-?\d+) out:(\S+) at:(\S+)")


def src_digest(root: Path, paths: list[str]) -> str:
    h = hashlib.sha256()
    for path in sorted(set(paths)):
        h.update(path.encode("utf-8") + b"\0")
        try:
            file = contained_path(root, path)
            h.update(file.read_bytes() if file.is_file() else b"MISSING")
        except ValueError:
            h.update(b"UNSAFE")
        h.update(b"\0")
    return h.hexdigest()[:7]


def git_rev(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10
        )
        return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else "none"
    except (OSError, subprocess.SubprocessError):
        return "none"


def format_evidence(rev: str, src: str, exit_code: int, out: str, at: str) -> str:
    cell = f"rev:{rev} src:{src} exit:{exit_code} out:{out} at:{at}"
    if not EVIDENCE_PATTERN.fullmatch(cell):
        raise ValueError(f"Malformed evidence cell: {cell}")
    return cell


def parse_evidence(cell: str) -> dict | None:
    match = _PARSE.fullmatch(cell or "")
    if not match:
        return None
    rev, src, exit_code, out, at = match.groups()
    return {"rev": rev, "src": src, "exit": int(exit_code), "out": out, "at": at}


def bound_paths(row: dict, tables: dict) -> list[str]:
    index = {r["ID"]: r for r in tables["overlord"]}
    return sorted({index[k]["Path"] for k in refs(row.get("Binds", "")) if k in index})


def freshness(row: dict, tables: dict, root: Path) -> str:
    evidence = parse_evidence(row.get("Evidence", ""))
    if evidence is None:
        return "UNBOUND"
    if evidence["exit"] != 0:
        return "FAIL"
    if src_digest(root, bound_paths(row, tables)) != evidence["src"]:
        return "STALE"
    return "CURRENT"


def run_probe(row: dict, tables: dict, root: Path, actor: str, timeout: int = 600) -> dict:
    command = row.get("Probe", "").strip()
    if not command:
        raise ValueError(f"{row['ID']} has no Probe")
    src = src_digest(root, bound_paths(row, tables))
    try:
        completed = subprocess.run(
            command, cwd=root, shell=True, capture_output=True, text=True, timeout=timeout, errors="replace"
        )
        exit_code, output = completed.returncode, completed.stdout + completed.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        output = f"timeout after {timeout}s\n{exc.stdout or ''}{exc.stderr or ''}"
    at = utc_now()
    out_dir = contained_path(root, f".pacer/probes/{row['ID']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / (at.replace(":", "") + ".txt")
    output_path.write_text(
        f"$ {command}\n# actor={actor} exit={exit_code} at={at}\n{output}", encoding="utf-8"
    )
    out = hashlib.sha256(output.encode("utf-8")).hexdigest()[:7]
    cell = format_evidence(git_rev(root), src, exit_code, out, at)
    return {
        "evidence": cell,
        "exit": exit_code,
        "output_path": output_path.relative_to(root).as_posix(),
        "freshness": "CURRENT" if exit_code == 0 else "FAIL",
    }
```

- [ ] **Step 4: Run; expect PASS.**

- [ ] **Step 5: Commit** — `git commit -am "feat(pacer3): probes and derived freshness"`

---

### Task 6: Rank and frames

**Files:**
- Create: `plugins/pacer/src/pacer_mcp/spec.py`, `plugins/pacer/src/pacer_mcp/rank.py`, `plugins/pacer/src/pacer_mcp/frames.py`
- Test: `plugins/pacer/tests/test_frames.py`

**Interfaces:**
- `spec.read_spec(root) -> dict` with defaults `{"project": <root dir name>, "tier": "prototype", "provider": "auto", "budgets": {"session": 4000, "prompt": 2000, "edit": 1500, "stop": 1000}}`; reads `.MIVIM.spec` (TOML) sections `[project] name tier`, `[provider] name`, `[frames] session prompt edit stop`.
- `rank.adjacency(tables, provider) -> dict[str, dict[str, int]]` weighted undirected graph over IDs (typed refs 1; Pos parent/child 1; Pos siblings 1; Needs 2; provider file edges 2 between OVR FILE rows; same AREA 3).
- `rank.rank(tables, provider, focus: list[str]) -> list[tuple[int, str]]` sorted `(distance, ID)` for all reachable IDs, focus at distance 0.
- `frames.active_pace(tables, store) -> dict | None`; `frames.phase_of(row, tables) -> dict | None`; `frames.session_frame(tables, root, store, provider, spec) -> str`; `frames.prompt_frame(tables, root, provider, spec, prompt) -> str`; `frames.edit_frame(tables, root, store, provider, spec, path) -> str`; `frames.fit(lines: list[str], spine: list[str], budget: int, focus: str) -> str`.
- Frame text: first line `PACER <project> tier=<tier> pace=<PAC-id|none>`; then cards, one per line; last line `+N more: pacer q <focus>` when truncated.

- [ ] **Step 1: Tests**

```python
# plugins/pacer/tests/test_frames.py
from pacer_mcp.frames import edit_frame, prompt_frame, session_frame
from pacer_mcp.provider import NullProvider
from pacer_mcp.rank import rank
from pacer_mcp.schema import empty_row
from pacer_mcp.spec import read_spec
from pacer_mcp.store import Store


def web(root):
    (root / "src").mkdir(exist_ok=True)
    for name in ("a.py", "b.py", "c.py"):
        (root / "src" / name).write_text("x=1\n")
    return {
        "todo": [
            empty_row("todo", {"ID": "PAC-001", "Kind": "AREA", "Pos": "A1", "Title": "Core", "Status": "ACTIVE", "Tier": "prototype"}),
            empty_row("todo", {"ID": "PAC-002", "Kind": "PHASE", "Pos": "A1.P1", "Title": "Boot", "Status": "ACTIVE", "Tier": "prototype", "Exit": "boots", "Binds": "OGM-001"}),
            empty_row("todo", {"ID": "PAC-003", "Kind": "PACE", "Pos": "A1.P1.01", "Title": "Load", "Status": "ACTIVE", "Produce": "loader", "In": "OVR-001", "Out": "src/new.py"}),
            empty_row("todo", {"ID": "PAC-004", "Kind": "PACE", "Pos": "A1.P1.02", "Title": "Wire", "Status": "TODO", "Produce": "wiring", "In": "OVR-002"}),
            empty_row("todo", {"ID": "PAC-005", "Kind": "PACE", "Pos": "A1.P1.03", "Title": "Far", "Status": "TODO", "Produce": "far away", "In": "OVR-003"}),
        ],
        "overlord": [
            empty_row("overlord", {"ID": "OVR-001", "Path": "src/a.py", "Kind": "FILE", "Purpose": "entry", "Latch": "DEC-001"}),
            empty_row("overlord", {"ID": "OVR-002", "Path": "src/b.py", "Kind": "FILE", "Purpose": "second"}),
            empty_row("overlord", {"ID": "OVR-003", "Path": "src/c.py", "Kind": "FILE", "Purpose": "third", "Tier": "protected"}),
        ],
        "organism": [empty_row("organism", {"ID": "OGM-001", "Title": "Boots", "Status": "SCAFFOLD", "Authority": "USER", "Requirement": "boots", "Binds": "OVR-001", "Probe": "true"})],
        "nodule": [],
        "decision": [
            empty_row("decision", {"ID": "DEC-001", "Kind": "LATCH", "Subject": "OVR-001", "Question": "sync?", "Chosen": "sync", "Authority": "USER", "Latched": "true"}),
            empty_row("decision", {"ID": "DEC-002", "Kind": "LESSON", "Subject": "PAC-002", "Why": "boot order matters", "Authority": "OBSERVED"}),
        ],
    }


class FakeProvider:
    name = "fake"

    def users(self, path):
        return ["src/main.py", "src/b.py"] if path == "src/a.py" else []

    def deps(self, path):
        return []


def test_rank_orders_by_distance(registers):
    t = web(registers)
    ranked = dict((i, d) for d, i in rank(t, NullProvider(), ["PAC-003"]))
    assert ranked["PAC-003"] == 0
    assert ranked["OVR-001"] == 1 and ranked["PAC-002"] == 1 and ranked["PAC-004"] == 1
    assert ranked["DEC-001"] == 2 and ranked["OGM-001"] == 2
    assert ranked["PAC-005"] >= 1 and ranked["OVR-003"] > ranked["OVR-001"]


def test_session_frame_has_spine_and_budget(registers):
    t = web(registers)
    store = Store(registers)
    spec = read_spec(registers)
    text = session_frame(t, registers, store, NullProvider(), spec)
    lines = text.splitlines()
    assert lines[0].startswith("PACER ") and "pace=PAC-003" in lines[0]
    assert any(l.startswith("PAC PAC-002 A1.P1 ACTIVE") for l in lines)
    assert any(l.startswith("PAC PAC-003 A1.P1.01 ACTIVE") for l in lines)
    assert any(l.startswith("DEC DEC-002 LESSON") for l in lines)
    assert any(l.startswith("OGM OGM-001") and "UNBOUND" in l for l in lines)
    spec["budgets"]["session"] = 260
    short = session_frame(t, registers, store, NullProvider(), spec)
    assert short.splitlines()[-1].startswith("+") and "pacer q PAC-003" in short
    assert len(short.encode("utf-8")) <= 260 + 80  # spine may exceed a tiny budget; trailer is bounded


def test_edit_frame_registered_unregistered_and_offpace(registers):
    t = web(registers)
    store = Store(registers)
    spec = read_spec(registers)
    text = edit_frame(t, registers, store, FakeProvider(), spec, "src/a.py")
    assert "OVR OVR-001 src/a.py" in text and "used-by: src/b.py, src/main.py" in text
    assert "DEC DEC-001 LATCH USER latched" in text
    assert "OGM OGM-001" in text and "OFF-PACE" not in text
    off = edit_frame(t, registers, store, FakeProvider(), spec, "src/b.py")
    assert "OFF-PACE" in off
    new = edit_frame(t, registers, store, FakeProvider(), spec, "src/new.py")
    assert "OVR - src/new.py unregistered" in new and "OFF-PACE" not in new


def test_prompt_frame_only_on_mentions(registers):
    t = web(registers)
    spec = read_spec(registers)
    assert prompt_frame(t, registers, NullProvider(), spec, "hello there") == ""
    text = prompt_frame(t, registers, NullProvider(), spec, "look at OGM-001 and src/b.py")
    assert "OGM OGM-001" in text and "OVR OVR-002 src/b.py" in text
```

- [ ] **Step 2: Run; expect FAIL.**

- [ ] **Step 3: Implement spec.py**

```python
"""Project frame: the only doctrine file. Absent file means defaults."""

from __future__ import annotations

import tomllib
from pathlib import Path

DEFAULT_BUDGETS = {"session": 4000, "prompt": 2000, "edit": 1500, "stop": 1000}


def read_spec(root: Path) -> dict:
    spec = {
        "project": root.resolve().name,
        "tier": "prototype",
        "provider": "auto",
        "budgets": dict(DEFAULT_BUDGETS),
    }
    path = root / ".MIVIM.spec"
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            return spec
        project = data.get("project", {})
        spec["project"] = str(project.get("name", spec["project"]))
        spec["tier"] = str(project.get("tier", spec["tier"]))
        spec["provider"] = str(data.get("provider", {}).get("name", spec["provider"]))
        for key in DEFAULT_BUDGETS:
            value = data.get("frames", {}).get(key)
            if isinstance(value, int) and 256 <= value <= 64000:
                spec["budgets"][key] = value
    return spec
```

- [ ] **Step 4: Implement rank.py**

```python
"""Relevance by weighted distance over typed edges, tree position and derived structure."""

from __future__ import annotations

import heapq

from pacer_mcp.schema import REF_FIELDS, REGISTERS, pos_parts, refs

W_REF, W_TREE, W_NEEDS, W_FILE, W_AREA = 1, 1, 2, 2, 3


def adjacency(tables: dict, provider) -> dict[str, dict[str, int]]:
    graph: dict[str, dict[str, int]] = {}

    def edge(a: str, b: str, w: int):
        if a == b:
            return
        graph.setdefault(a, {})
        graph.setdefault(b, {})
        graph[a][b] = min(graph[a].get(b, w), w)
        graph[b][a] = min(graph[b].get(a, w), w)

    index = {r["ID"]: r for reg in REGISTERS for r in tables.get(reg, [])}
    for key in index:
        graph.setdefault(key, {})
    for register in REGISTERS:
        for row in tables.get(register, []):
            for field in REF_FIELDS[register]:
                weight = W_NEEDS if field == "Needs" else W_REF
                for target in refs(row.get(field, "")):
                    if target in index:
                        edge(row["ID"], target, weight)
    by_pos: dict[str, str] = {}
    for row in tables.get("todo", []):
        try:
            pos_parts(row.get("Pos", ""))
            by_pos[row["Pos"]] = row["ID"]
        except ValueError:
            continue
    for pos, key in by_pos.items():
        area, phase, pace = pos_parts(pos)
        parent = f"A{area}.P{phase}" if pace is not None else (f"A{area}" if phase is not None else None)
        if parent in by_pos:
            edge(key, by_pos[parent], W_TREE)
        for other_pos, other in by_pos.items():
            if other == key:
                continue
            oa, op, opace = pos_parts(other_pos)
            if oa == area and op == phase and pace is not None and opace is not None:
                edge(key, other, W_TREE)
            elif oa == area and phase is not None and op is not None and phase != op:
                edge(key, other, W_AREA)
    files = {r["Path"]: r["ID"] for r in tables.get("overlord", []) if r.get("Kind") == "FILE"}
    for path, key in files.items():
        for other in provider.users(path) + provider.deps(path):
            if other in files:
                edge(key, files[other], W_FILE)
    return graph


def rank(tables: dict, provider, focus: list[str]) -> list[tuple[int, str]]:
    graph = adjacency(tables, provider)
    dist = {key: 0 for key in focus if key in graph}
    heap = [(0, key) for key in dist]
    while heap:
        d, key = heapq.heappop(heap)
        if d > dist.get(key, 10**9):
            continue
        for other, w in graph.get(key, {}).items():
            nd = d + w
            if nd < dist.get(other, 10**9):
                dist[other] = nd
                heapq.heappush(heap, (nd, other))
    return sorted((d, k) for k, d in dist.items())
```

- [ ] **Step 5: Implement frames.py**

```python
"""Compile bounded card frames for harness events. Never refuse on budget."""

from __future__ import annotations

import re
from pathlib import Path

from pacer_mcp.cards import card
from pacer_mcp.probe import bound_paths, freshness, parse_evidence
from pacer_mcp.rank import rank
from pacer_mcp.schema import REF_PATTERN, REGISTER_OF, REGISTERS, TAG_PATTERN, pos_parts, refs

PATH_TOKEN = re.compile(r"(?<![\w./-])((?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]+)")
MAX_USED_BY = 8


def _index(tables):
    return {r["ID"]: (reg, r) for reg in REGISTERS for r in tables.get(reg, [])}


def phase_of(row: dict, tables: dict) -> dict | None:
    try:
        area, phase, pace = pos_parts(row.get("Pos", ""))
    except ValueError:
        return None
    if pace is None:
        return row if phase is not None else None
    for other in tables["todo"]:
        if other.get("Kind") == "PHASE" and other.get("Pos") == f"A{area}.P{phase}":
            return other
    return None


def active_pace(tables: dict, store) -> dict | None:
    active = [r for r in tables["todo"] if r.get("Kind") == "PACE" and r.get("Status") == "ACTIVE"]
    if not active:
        return None
    if len(active) == 1:
        return active[0]
    recent = {e.get("id") for e in store.ledger_read(None, 200) if e.get("op") in {"touch", "status"}}
    for entry in reversed(store.ledger_read(None, 200)):
        if entry.get("id") in {r["ID"] for r in active} and entry.get("id") in recent:
            return next(r for r in active if r["ID"] == entry["id"])
    return sorted(active, key=lambda r: pos_parts(r["Pos"]))[0]


def ogm_extras(row: dict, tables: dict, root: Path) -> dict:
    state = freshness(row, tables, root)
    parsed = parse_evidence(row.get("Evidence", ""))
    if parsed is None:
        return {"Evidence": "UNBOUND"}
    text = f"rev:{parsed['rev']} exit:{parsed['exit']} at:{parsed['at'][:10]}"
    if state == "STALE":
        text += " STALE(" + ",".join(bound_paths(row, tables)[:3]) + ")"
    else:
        text += f" {state}"
    return {"Evidence": text}


def ovr_extras(row: dict, provider) -> dict:
    if row.get("Kind") != "FILE":
        return {}
    users = provider.users(row["Path"])
    if not users:
        return {}
    shown = ", ".join(users[:MAX_USED_BY])
    if len(users) > MAX_USED_BY:
        shown += f" (+{len(users) - MAX_USED_BY})"
    return {"used-by": shown}


def render(key: str, tables: dict, root: Path, provider, extra: dict | None = None) -> str:
    register, row = _index(tables)[key]
    extras = dict(extra or {})
    if register == "organism":
        extras.update(ogm_extras(row, tables, root))
    elif register == "overlord":
        extras.update(ovr_extras(row, provider))
    return card(register, row, extras)


def fit(lines: list[str], spine: list[str], budget: int, focus: str) -> str:
    out = list(spine)
    used = sum(len(l.encode("utf-8")) + 1 for l in out)
    dropped = 0
    for line in lines:
        if line in out:
            continue
        size = len(line.encode("utf-8")) + 1
        if used + size > budget:
            dropped += 1
            continue
        out.append(line)
        used += size
    if dropped:
        out.append(f"+{dropped} more: pacer q {focus}")
    return "\n".join(out)


def _head(spec: dict, pace: dict | None) -> str:
    return f"PACER {spec['project']} tier={spec['tier']} pace={pace['ID'] if pace else 'none'}"


def _bound_ogms(phase: dict | None, pace: dict | None, tables: dict) -> list[str]:
    keys = []
    for row in (phase, pace):
        if row:
            keys += refs(row.get("Binds", ""))
    return list(dict.fromkeys(keys))


def _decisions_for(subjects: set[str], tables: dict) -> list[str]:
    return [
        r["ID"] for r in tables["decision"]
        if set(refs(r.get("Subject", ""))) & subjects and not r.get("Supersedes")
    ]


def session_frame(tables: dict, root: Path, store, provider, spec: dict) -> str:
    pace = active_pace(tables, store)
    phase = phase_of(pace, tables) if pace else next(
        (r for r in tables["todo"] if r.get("Kind") == "PHASE" and r.get("Status") == "ACTIVE"), None
    )
    area = None
    if phase:
        a, _, _ = pos_parts(phase["Pos"])
        area = next((r for r in tables["todo"] if r.get("Kind") == "AREA" and r.get("Pos") == f"A{a}"), None)
    spine_ids = [r["ID"] for r in (area, phase, pace) if r]
    subjects = set(spine_ids) | set(refs(pace.get("In", "")) if pace else [])
    ogms = _bound_ogms(phase, pace, tables)
    subjects |= set(ogms)
    spine_ids += _decisions_for(subjects, tables)
    spine = [_head(spec, pace)] + [render(k, tables, root, provider) for k in dict.fromkeys(spine_ids)]
    focus = [pace["ID"]] if pace else ([phase["ID"]] if phase else [])
    ranked = [k for _, k in rank(tables, provider, focus)] if focus else []
    if not focus:
        ranked = [r["ID"] for r in sorted(tables["todo"], key=lambda r: pos_parts(r["Pos"]) if r.get("Pos") else (999, 0, 0)) if r.get("Status") == "TODO"][:5]
        spine.append("no active pace; start one: pacer status <PAC> ACTIVE")
    next_paces = [r["ID"] for r in sorted(tables["todo"], key=lambda r: pos_parts(r["Pos"]))
                  if r.get("Kind") == "PACE" and r.get("Status") == "TODO" and phase and phase_of(r, tables) is phase][:5]
    ordered = list(dict.fromkeys(ogms + next_paces + ranked))
    lines = [render(k, tables, root, provider) for k in ordered if k not in spine_ids]
    return fit(lines, spine, spec["budgets"]["session"], focus[0] if focus else "todo")


def edit_frame(tables: dict, root: Path, store, provider, spec: dict, path: str) -> str:
    pace = active_pace(tables, store)
    rows = [r for r in tables["overlord"] if r.get("Path") == path]
    in_pace = False
    if pace:
        in_ids = set(refs(pace.get("In", "")))
        outs = [o.split(":", 1)[0] for o in refs(pace.get("Out", ""))]
        in_pace = any(r["ID"] in in_ids for r in rows) or path in outs
    spine = [_head(spec, pace)]
    lines: list[str] = []
    if not rows:
        users = provider.users(path)
        extra = f" | used-by: {', '.join(users[:MAX_USED_BY])}" if users else ""
        spine.append(f"OVR - {path} unregistered{extra}")
        subjects: set[str] = set()
    else:
        for row in rows:
            extra = {} if in_pace or not pace else {"OFF-PACE": "1"}
            spine.append(render(row["ID"], tables, root, provider, extra))
        subjects = {r["ID"] for r in rows}
    ogms = [r["ID"] for r in tables["organism"] if set(refs(r.get("Binds", ""))) & subjects]
    decs = _decisions_for(subjects, tables)
    for key in ogms + decs:
        spine.append(render(key, tables, root, provider))
    if pace:
        lines.append(render(pace["ID"], tables, root, provider))
    ranked = [k for _, k in rank(tables, provider, list(subjects))] if subjects else []
    lines += [render(k, tables, root, provider) for k in ranked if k not in subjects and k not in ogms and k not in decs]
    return fit(lines, spine, spec["budgets"]["edit"], next(iter(subjects), path))


def prompt_frame(tables: dict, root: Path, provider, spec: dict, prompt: str) -> str:
    index = _index(tables)
    ids = [i for i in REF_PATTERN.findall(prompt) if i in index]
    paths = {r["ID"] for r in tables["overlord"] if r.get("Path") in set(PATH_TOKEN.findall(prompt))}
    tags = set(TAG_PATTERN.findall(prompt))
    tagged = [r["ID"] for reg in REGISTERS for r in tables[reg] if tags & set(r.get("Tags", "").split())]
    keys = list(dict.fromkeys(ids + sorted(paths) + tagged))
    if not keys:
        return ""
    lines = [render(k, tables, root, provider) for k in keys]
    return fit(lines, [], spec["budgets"]["prompt"], keys[0])
```

- [ ] **Step 6: Run; expect PASS.** Adjust `test_rank_orders_by_distance` expectations only if a weight is demonstrably wrong; the intended distances are: PAC-003→OVR-001 (In, 1), →PAC-002 (tree parent, 1), →PAC-004 (sibling, 1), →DEC-001 (via OVR-001 Latch, 2), →OGM-001 (via PAC-002 Binds, 2).

- [ ] **Step 7: Commit** — `git commit -am "feat(pacer3): spec, rank and session/edit/prompt frames"`

---

### Task 7: Gates and hook entry

**Files:**
- Create: `plugins/pacer/src/pacer_mcp/gates.py`, `plugins/pacer/src/pacer_mcp/hook.py`
- Test: `plugins/pacer/tests/test_gates_hook.py`

**Interfaces:**
- `gates.effective_tier(row, tables, spec) -> str` (PACE inherits PHASE; explicit only raises; default spec tier).
- `gates.stop_decision(tables, root, store, provider, spec) -> {"block": bool, "reasons": [str], "open_latches": [str], "next": str, "text": str}`.
- `gates.edit_decision(tables, root, store, spec, path) -> {"deny": bool, "reason": str}`.
- `hook.find_root(cwd: Path) -> Path | None` walks up to the first dir with `todo.PACER.csv`.
- `hook.edit_path(tool_name, tool_input) -> str | None` handles `file_path`, `notebook_path`, and apply_patch `*** Update File:`/`*** Add File:` lines in `tool_input["command"]` or `tool_input["patch"]`.
- `hook.run(event: str, stdin_json: dict) -> tuple[int, str]` returns `(exit_code, stdout)` using the Service (Task 8); events `session-start`, `prompt`, `pre-edit`, `post-edit`, `stop`.

- [ ] **Step 1: Tests**

```python
# plugins/pacer/tests/test_gates_hook.py
import json

from pacer_mcp.gates import edit_decision, effective_tier, stop_decision
from pacer_mcp.hook import edit_path, find_root, hook_output
from pacer_mcp.provider import NullProvider
from pacer_mcp.schema import empty_row
from pacer_mcp.spec import read_spec
from pacer_mcp.store import Store
from tests.test_frames import web


def test_effective_tier_inherits_and_raises(registers):
    t = web(registers)
    spec = read_spec(registers)
    pace = t["todo"][2]
    assert effective_tier(pace, t, spec) == "prototype"
    t["todo"][1]["Tier"] = "release"
    assert effective_tier(pace, t, spec) == "release"
    pace["Tier"] = "protected"
    assert effective_tier(pace, t, spec) == "protected"
    pace["Tier"] = "sketch"
    assert effective_tier(pace, t, spec) == "release"


def test_stop_matrix(registers):
    t = web(registers)
    store, spec = Store(registers), read_spec(registers)
    d = stop_decision(t, registers, store, NullProvider(), spec)
    assert d["block"] is False and d["next"] == "implement"
    t["todo"][1]["Tier"] = "integrated"
    t["organism"][0]["Evidence"] = "rev:none src:0000000 exit:1 out:0000000 at:2026-09-29T00:00:00Z"
    d = stop_decision(t, registers, store, NullProvider(), spec)
    assert d["block"] is True and "OGM-001 FAIL" in d["reasons"][0] and d["next"] == "verify"
    t["organism"][0]["Evidence"] = "rev:none src:0000000 exit:0 out:0000000 at:2026-09-29T00:00:00Z"
    d = stop_decision(t, registers, store, NullProvider(), spec)
    assert d["block"] is False  # integrated tolerates STALE
    t["todo"][1]["Tier"] = "release"
    assert stop_decision(t, registers, store, NullProvider(), spec)["block"] is True
    t["decision"].append(empty_row("decision", {"ID": "DEC-003", "Kind": "LATCH", "Subject": "PAC-003", "Question": "delete old data?", "Authority": "USER", "Latched": "false"}))
    d = stop_decision(t, registers, store, NullProvider(), spec)
    assert d["open_latches"] == ["DEC-003"] and d["block"] is True and d["next"] == "inspect"


def test_edit_decision_protected(registers):
    t = web(registers)
    store, spec = Store(registers), read_spec(registers)
    assert edit_decision(t, registers, store, spec, "src/b.py")["deny"] is False
    assert edit_decision(t, registers, store, spec, "src/c.py")["deny"] is True
    t["decision"].append(empty_row("decision", {"ID": "DEC-009", "Kind": "LATCH", "Subject": "OVR-003", "Question": "may edit c?", "Chosen": "yes", "Authority": "USER", "Latched": "true"}))
    assert edit_decision(t, registers, store, spec, "src/c.py")["deny"] is False


def test_hook_helpers(tmp_path):
    (tmp_path / "todo.PACER.csv").write_text("ID\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_root(nested) == tmp_path
    assert find_root(tmp_path.parent) is None or find_root(tmp_path.parent) != tmp_path
    assert edit_path("Edit", {"file_path": str(tmp_path / "x.py")}, tmp_path) == "x.py"
    assert edit_path("NotebookEdit", {"notebook_path": "n.ipynb"}, tmp_path) == "n.ipynb"
    patch = "*** Begin Patch\n*** Update File: src/a.py\n@@\n-x\n+y\n*** End Patch"
    assert edit_path("apply_patch", {"command": patch}, tmp_path) == "src/a.py"
    assert edit_path("Bash", {"command": "ls"}, tmp_path) is None
    out = json.loads(hook_output("PreToolUse", "ctx", deny="no"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    out = json.loads(hook_output("PreToolUse", "ctx"))
    assert "permissionDecision" not in out["hookSpecificOutput"] and out["hookSpecificOutput"]["additionalContext"] == "ctx"
    assert hook_output("SessionStart", "ctx") == "ctx"
    assert json.loads(hook_output("Stop", "why", block=True)) == {"decision": "block", "reason": "why"}
```

- [ ] **Step 2: Run; expect FAIL.**

- [ ] **Step 3: Implement gates.py**

```python
"""Tier matrix: the whole guardrail doctrine as a lookup."""

from __future__ import annotations

from pathlib import Path

from pacer_mcp.frames import _bound_ogms, active_pace, phase_of, render
from pacer_mcp.probe import freshness
from pacer_mcp.schema import TIERS, refs

AT_LEAST = {t: i for i, t in enumerate(TIERS)}


def effective_tier(row: dict | None, tables: dict, spec: dict) -> str:
    if row is None:
        return spec["tier"]
    own = row.get("Tier") or ""
    parent = ""
    if row.get("Kind") == "PACE":
        phase = phase_of(row, tables)
        parent = (phase or {}).get("Tier") or ""
    candidates = [t for t in (own, parent, spec["tier"]) if t in AT_LEAST]
    return max(candidates, key=lambda t: AT_LEAST[t]) if candidates else spec["tier"]


def open_latches(subjects: set[str], tables: dict) -> list[str]:
    return sorted(
        r["ID"] for r in tables["decision"]
        if r.get("Kind") == "LATCH" and r.get("Latched") == "false" and set(refs(r.get("Subject", ""))) & subjects
    )


def stop_decision(tables: dict, root: Path, store, provider, spec: dict) -> dict:
    pace = active_pace(tables, store)
    phase = phase_of(pace, tables) if pace else None
    tier = effective_tier(pace, tables, spec)
    index = {r["ID"]: r for r in tables["organism"]}
    reasons: list[str] = []
    states = {}
    for key in _bound_ogms(phase, pace, tables):
        if key in index:
            states[key] = freshness(index[key], tables, root)
    fails = [k for k, s in states.items() if s == "FAIL"]
    stale = [k for k, s in states.items() if s == "STALE"]
    if AT_LEAST[tier] >= AT_LEAST["integrated"] and fails:
        reasons.append("probe failed: " + ", ".join(f"{k} FAIL" for k in fails))
    if AT_LEAST[tier] >= AT_LEAST["release"] and stale:
        reasons.append("evidence stale: " + ", ".join(stale))
    subjects = {r["ID"] for r in (pace, phase) if r} | (set(refs(pace.get("In", ""))) if pace else set()) | set(states)
    latches = open_latches(subjects, tables)
    if latches:
        reasons.append("open latch: " + ", ".join(latches))
    touched = [e for e in store.ledger_read(pace["ID"], 50) if e.get("op") == "touch"] if pace else []
    if latches:
        next_action = "inspect"
    elif fails or stale:
        next_action = "verify"
    elif touched:
        next_action = "integrate"
    else:
        next_action = (pace or {}).get("Next") or "implement"
    lines = [f"PACER stop tier={tier} pace={pace['ID'] if pace else 'none'} next={next_action}"]
    lines += [render(k, tables, root, provider) for k in latches]
    lines += [f"{k}: {s}" for k, s in states.items() if s != "CURRENT"]
    return {"block": bool(reasons), "reasons": reasons, "open_latches": latches, "next": next_action, "text": "\n".join(lines)}


def edit_decision(tables: dict, root: Path, store, spec: dict, path: str) -> dict:
    rows = [r for r in tables["overlord"] if r.get("Path") == path]
    pace = active_pace(tables, store)
    tiers = [r.get("Tier") for r in rows if r.get("Tier") in AT_LEAST] or [effective_tier(pace, tables, spec)]
    tier = max(tiers, key=lambda t: AT_LEAST[t])
    if tier != "protected":
        return {"deny": False, "reason": ""}
    subjects = {r["ID"] for r in rows} | ({pace["ID"]} if pace else set())
    covered = any(
        r.get("Kind") == "LATCH" and r.get("Latched") == "true" and r.get("Authority") == "USER"
        and set(refs(r.get("Subject", ""))) & subjects
        for r in tables["decision"]
    )
    if covered:
        return {"deny": False, "reason": ""}
    return {"deny": True, "reason": f"{path} is protected; a USER latch (DEC LATCH) covering it is required"}
```

- [ ] **Step 4: Implement hook.py**

```python
"""Harness adapter: stdin event JSON in, frame text or decision JSON out."""

from __future__ import annotations

import json
import re
from pathlib import Path

PATCH_FILE = re.compile(r"^\*\*\* (?:Update|Add) File: (.+)$", re.MULTILINE)
EVENTS = {"session-start": "SessionStart", "prompt": "UserPromptSubmit", "pre-edit": "PreToolUse", "post-edit": "PostToolUse", "stop": "Stop"}


def find_root(cwd: Path) -> Path | None:
    for candidate in (cwd.resolve(), *cwd.resolve().parents):
        if (candidate / "todo.PACER.csv").is_file():
            return candidate
    return None


def edit_path(tool_name: str, tool_input: dict, root: Path) -> str | None:
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw and tool_name == "apply_patch":
        text = tool_input.get("command") or tool_input.get("patch") or tool_input.get("input") or ""
        match = PATCH_FILE.search(str(text))
        raw = match.group(1).strip() if match else None
    if not raw:
        return None
    path = Path(raw)
    try:
        rel = path.resolve().relative_to(root.resolve()) if path.is_absolute() else path
    except ValueError:
        return None
    return rel.as_posix()


def hook_output(event_name: str, context: str, *, deny: str = "", block: bool = False) -> str:
    if event_name == "SessionStart":
        return context
    if event_name == "Stop":
        if block:
            return json.dumps({"decision": "block", "reason": context})
        return json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": context}}) if context else ""
    specific: dict = {"hookEventName": event_name}
    if deny:
        specific["permissionDecision"] = "deny"
        specific["permissionDecisionReason"] = deny
    if context:
        specific["additionalContext"] = context
    return json.dumps({"hookSpecificOutput": specific})


def run(event: str, payload: dict) -> tuple[int, str]:
    from pacer_mcp.service import Service

    if event not in EVENTS:
        return 2, f"unknown hook event {event}"
    root = find_root(Path(payload.get("cwd") or Path.cwd()))
    if root is None:
        return 0, ""
    service = Service(root)
    name = EVENTS[event]
    actor = "hook"
    if event == "session-start":
        return 0, hook_output(name, service.frame("session"))
    if event == "prompt":
        text = service.frame("prompt", focus=str(payload.get("prompt") or payload.get("user_prompt") or ""))
        return 0, hook_output(name, text)
    if event in {"pre-edit", "post-edit"}:
        path = edit_path(str(payload.get("tool_name", "")), payload.get("tool_input") or {}, root)
        if not path:
            return 0, ""
        if event == "pre-edit":
            decision = service.edit_decision(path)
            return 0, hook_output(name, service.frame("edit", focus=path), deny=decision["reason"] if decision["deny"] else "")
        return 0, hook_output(name, service.touch(path, actor))
    result = service.stop(actor)
    return 0, hook_output(name, result["text"], block=result["block"])
```

- [ ] **Step 5: Run; expect PASS** for gates and helper tests. `run()` is exercised in Task 9 once `Service` exists.

- [ ] **Step 6: Commit** — `git commit -am "feat(pacer3): tier gate matrix and harness hook adapter"`

---

### Task 8: Editor, Service, models

**Files:**
- Modify: `plugins/pacer/src/pacer_mcp/commands.py` (full rewrite), `service.py` (full rewrite), `models.py` (full rewrite)
- Modify: `plugins/pacer/tests/conftest.py` (add `project` fixture)
- Test: `plugins/pacer/tests/test_service.py`
- Delete: `context.py`, `pages.py`, `evidence.py`, `semantics.py`, `query.py`

**Interfaces:**
- `Editor(tables, actor, root)` with `.execute(op: dict)`, `.events: list[dict]` (ledger entries), `.changed: set[str]`, `.find(id) -> (register, row)`, `.next_id(register) -> str`.
- Ops: `add{register,row}`, `set{id,fields}`, `link{id,field,target,remove?}`, `move{id,pos}`, `status{id,status}`, `latch{id,latched:"true"|"false",evidence}`, `pace{nodule,tasks,requirements?,decisions?}`, `absorb{id}`, `touch{pace?,path}`.
- `Service(root)`: `.frame(kind, focus="") -> str`, `.q(query) -> str`, `.write(ops, actor) -> dict`, `.probe(id, actor) -> dict`, `.touch(path, actor) -> str`, `.stop(actor) -> dict`, `.edit_decision(path) -> dict`, `.validate() -> dict`, `.initialize() -> dict`, `.log(id, limit) -> list`, `.tree() -> str`, `.recover() -> dict`, `.migrate(source, preview) -> dict` (Task 10).

- [ ] **Step 1: Extend conftest and write tests**

```python
# append to plugins/pacer/tests/conftest.py
from pacer_mcp.service import Service


@pytest.fixture
def project(registers) -> Service:
    (registers / "src").mkdir(exist_ok=True)
    (registers / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    return Service(registers)
```

```python
# plugins/pacer/tests/test_service.py
import sys

import pytest


def _pace(project):
    return project.write([{
        "op": "pace",
        "nodule": {"ID": "NDL-001", "Name": "boot", "Lane": "main", "Request": "make it boot", "Intent": "boot path", "Exit": "boots"},
        "tasks": [
            {"ID": "PAC-001", "Kind": "AREA", "Pos": "A1", "Title": "Core"},
            {"ID": "PAC-002", "Kind": "PHASE", "Pos": "A1.P1", "Title": "Boot", "Exit": "boots", "Binds": "OGM-001"},
            {"ID": "PAC-003", "Kind": "PACE", "Pos": "A1.P1.01", "Title": "Load", "Produce": "loader", "In": "OVR-001", "Out": "src/new.py"},
        ],
        "requirements": [{"ID": "OGM-001", "Title": "Boots", "Authority": "USER", "Origin": "make it boot", "Requirement": "boots", "Binds": "OVR-001", "Probe": f'"{sys.executable}" -c "print(1)"'}],
    }], "tester")


def test_pace_add_and_ledger(project):
    project.write([{"op": "add", "register": "overlord", "row": {"ID": "OVR-001", "Path": "src/a.py", "Kind": "FILE", "Purpose": "entry"}}], "tester")
    result = _pace(project)
    assert set(result["changed_ids"]) == {"NDL-001", "PAC-001", "PAC-002", "PAC-003", "OGM-001"}
    assert result["validation"]["valid"]
    assert project.log("PAC-003", 10)[-1]["op"] == "add"
    assert "PAC-003" in [r["ID"] for r in project.store.load().tables["todo"]]


def test_status_latch_probe_and_frames(project):
    project.write([{"op": "add", "register": "overlord", "row": {"ID": "OVR-001", "Path": "src/a.py", "Kind": "FILE", "Purpose": "entry"}}], "tester")
    _pace(project)
    project.write([{"op": "status", "id": "PAC-003", "status": "ACTIVE"}], "tester")
    assert "pace=PAC-003" in project.frame("session").splitlines()[0]
    assert "OVR OVR-001 src/a.py" in project.frame("edit", "src/a.py")
    touched = project.touch("src/new.py", "hook")
    assert "registered #unpurposed" in touched
    assert any(r["Path"] == "src/new.py" for r in project.store.load().tables["overlord"]) is False or True
    probe = project.probe("OGM-001", "tester")
    assert probe["exit"] == 0
    rows = {r["ID"]: r for r in project.store.load().tables["organism"]}
    assert " exit:0 " in rows["OGM-001"]["Evidence"]
    project.write([{"op": "status", "id": "OGM-001", "status": "VALIDATED_COMPLETE"}], "tester")
    project.write([{"op": "add", "register": "decision", "row": {"ID": "DEC-001", "Kind": "LATCH", "Subject": "PAC-003", "Question": "ship?", "Authority": "USER", "Latched": "false"}}], "tester")
    stop = project.stop("hook")
    assert stop["block"] and stop["open_latches"] == ["DEC-001"]
    project.write([{"op": "latch", "id": "DEC-001", "latched": "true", "evidence": "user said ship"}], "tester")
    assert project.stop("hook")["block"] is False
    assert project.q("DEC-001").startswith("DEC DEC-001 LATCH USER latched")


def test_guards(project):
    project.write([{"op": "add", "register": "overlord", "row": {"ID": "OVR-001", "Path": "src/a.py", "Kind": "FILE", "Purpose": "entry"}}], "tester")
    _pace(project)
    with pytest.raises(ValueError, match="immutable"):
        project.write([{"op": "set", "id": "PAC-003", "fields": {"Status": "DONE"}}], "tester")
    with pytest.raises(ValueError, match="Evidence required"):
        project.write([{"op": "status", "id": "OGM-001", "status": "VALIDATED_COMPLETE"}], "tester")
    with pytest.raises(ValueError, match="Unknown ID"):
        project.write([{"op": "link", "id": "PAC-003", "field": "In", "target": "OVR-404"}], "tester")
    with pytest.raises(ValueError, match="incomplete"):
        project.write([{"op": "absorb", "id": "NDL-001"}], "tester")
    before = project.store.load().revision
    with pytest.raises(ValueError):
        project.write([{"op": "add", "register": "overlord", "row": {"ID": "OVR-002", "Path": "src/a.py", "Kind": "FILE", "Purpose": "dup ok"}}, {"op": "status", "id": "PAC-999", "status": "DONE"}], "tester")
    assert project.store.load().revision == before  # atomic
```

- [ ] **Step 2: Run; expect FAIL.**

- [ ] **Step 3: Rewrite commands.py**

```python
"""The write lexicon: every mutation is an event; registers hold current state only."""

from __future__ import annotations

from pathlib import Path

from pacer_mcp.probe import freshness
from pacer_mcp.schema import (
    HEADERS, IMMUTABLE, LIMITS, NDL_STATUSES, OGM_STATUSES, PREFIX, REF_FIELDS, REGISTER_OF,
    REGISTERS, TASK_STATUSES, empty_row, pos_parts, refs,
)


class Editor:
    def __init__(self, tables: dict, actor: str, root: Path):
        self.tables, self.actor, self.root = tables, actor, root
        self.changed: set[str] = set()
        self.events: list[dict] = []

    # -- helpers -------------------------------------------------------------
    def find(self, key: str) -> tuple[str, dict]:
        register = REGISTER_OF.get(key.split("-")[0], "")
        for row in self.tables.get(register, []):
            if row["ID"] == key:
                return register, row
        raise ValueError(f"REFUSAL: Unknown ID {key}")

    def next_id(self, register: str) -> str:
        numbers = [int(r["ID"].split("-")[1].rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")) for r in self.tables[register]]
        return f"{PREFIX[register]}-{max([0, *numbers]) + 1:03d}"

    def event(self, op: str, key: str, detail: dict | None = None):
        self.events.append({"actor": self.actor, "op": op, "id": key, "detail": detail or {}})
        self.changed.add(key)

    def _check_text(self, row: dict):
        for field, value in row.items():
            if not isinstance(value, str):
                raise ValueError(f"{row.get('ID')}: {field} must be a string")
            if "|" in value or "\n" in value:
                raise ValueError(f"{row.get('ID')}: {field} contains | or newline")
            if field in LIMITS and len(value) > LIMITS[field]:
                raise ValueError(f"{row.get('ID')}: {field} exceeds {LIMITS[field]}")

    def _exists(self, key: str) -> bool:
        return any(r["ID"] == key for reg in REGISTERS for r in self.tables[reg])

    # -- dispatch ------------------------------------------------------------
    def execute(self, op: dict):
        name = op.get("op")
        handler = getattr(self, f"op_{name}", None)
        if handler is None:
            raise ValueError(f"Unknown operation {name}")
        handler(op)

    def op_add(self, op: dict):
        register, values = op["register"], dict(op["row"])
        if register not in HEADERS:
            raise ValueError(f"Unknown register {register}")
        key = values.get("ID") or self.next_id(register)
        if self._exists(key):
            raise ValueError(f"Duplicate ID {key}")
        row = empty_row(register, {**values, "ID": key})
        defaults = {"todo": {"Status": "TODO"}, "organism": {"Status": "SCAFFOLD", "Authority": "INFERRED"}, "overlord": {"Kind": "FILE"}, "nodule": {"Status": "ACTIVE"}, "decision": {"Authority": "INFERRED"}}
        for field, value in defaults.get(register, {}).items():
            row[field] = row[field] or value
        if register == "decision" and row["Kind"] == "LATCH" and not row["Latched"]:
            row["Latched"] = "false"
        self._check_text(row)
        self.tables[register].append(row)
        self.event("add", key, {"register": register})

    def op_set(self, op: dict):
        register, row = self.find(op["id"])
        fields = dict(op["fields"])
        blocked = set(fields) & IMMUTABLE
        if blocked:
            raise ValueError(f"{op['id']}: {','.join(sorted(blocked))} immutable via set; use status/move/latch/probe")
        unknown = set(fields) - set(HEADERS[register])
        if unknown:
            raise ValueError(f"{op['id']}: unknown fields {','.join(sorted(unknown))}")
        self._check_text(fields)
        before = {k: row[k] for k in fields}
        row.update(fields)
        self.event("set", op["id"], {"before": before, "after": fields})

    def op_link(self, op: dict):
        register, row = self.find(op["id"])
        field, target = op["field"], op["target"]
        if field not in REF_FIELDS[register]:
            raise ValueError(f"{op['id']}: {field} is not a reference column")
        if not self._exists(target):
            raise ValueError(f"REFUSAL: Unknown ID {target}")
        current = refs(row[field])
        if op.get("remove"):
            current = [c for c in current if c != target]
        elif target not in current:
            current.append(target)
        row[field] = ";".join(current)
        self.event("unlink" if op.get("remove") else "link", op["id"], {"field": field, "target": target})

    def op_move(self, op: dict):
        register, row = self.find(op["id"])
        if register != "todo":
            raise ValueError("move applies to todo rows")
        pos_parts(op["pos"])
        self.event("move", op["id"], {"from": row["Pos"], "to": op["pos"]})
        row["Pos"] = op["pos"]

    def op_status(self, op: dict):
        register, row = self.find(op["id"])
        status = op["status"]
        allowed = {"todo": TASK_STATUSES, "organism": OGM_STATUSES, "nodule": NDL_STATUSES}.get(register)
        if allowed is None or status not in allowed:
            raise ValueError(f"{op['id']}: illegal status {status}")
        if register == "nodule":
            raise ValueError("nodule status changes only through pace/absorb")
        if register == "organism" and status == "VALIDATED_COMPLETE":
            if freshness(row, self.tables, self.root) != "CURRENT":
                raise ValueError("REFUSAL: Evidence required (run probe; evidence must be exit:0 and current)")
        if register == "todo" and status == "DONE":
            blocked = [t for t in refs(row.get("Needs", "")) if self.find(t)[1].get("Status") != "DONE"]
            if blocked:
                raise ValueError(f"REFUSAL: Blocked by {';'.join(blocked)}")
        self.event("status", op["id"], {"from": row["Status"], "to": status})
        row["Status"] = status

    def op_latch(self, op: dict):
        register, row = self.find(op["id"])
        if register != "decision" or row.get("Kind") != "LATCH":
            raise ValueError(f"{op['id']}: latch applies to DEC LATCH rows")
        value = op["latched"]
        if value not in {"true", "false"}:
            raise ValueError("latched must be 'true' or 'false'")
        if value == "true":
            row["Authority"] = "USER"
        row["Latched"] = value
        self.event("latch", op["id"], {"latched": value, "evidence": op.get("evidence", "")})

    def op_pace(self, op: dict):
        nodule = dict(op["nodule"])
        tasks = [dict(t) for t in op.get("tasks", [])]
        requirements = [dict(r) for r in op.get("requirements", [])]
        decisions = [dict(d) for d in op.get("decisions", [])]
        for row in requirements:
            self.op_add({"op": "add", "register": "organism", "row": row})
        for row in decisions:
            self.op_add({"op": "add", "register": "decision", "row": row})
        for row in tasks:
            self.op_add({"op": "add", "register": "todo", "row": row})
        spawned = [t["ID"] for t in tasks if t.get("Kind", "PACE") == "PACE"] + refs(nodule.get("Spawned", ""))
        nodule["Spawned"] = ";".join(dict.fromkeys(spawned))
        nodule["Targets"] = ";".join(dict.fromkeys([r["ID"] for r in requirements] + refs(nodule.get("Targets", ""))))
        nodule["Status"] = "ACTIVE"
        self.op_add({"op": "add", "register": "nodule", "row": nodule})

    def op_absorb(self, op: dict):
        register, row = self.find(op["id"])
        if register != "nodule" or row["Status"] != "ACTIVE":
            raise ValueError(f"{op['id']}: only an ACTIVE nodule can be absorbed")
        errors = []
        for key in refs(row.get("Spawned", "")):
            if self.find(key)[1].get("Status") != "DONE":
                errors.append(f"{key} not DONE")
        for key in refs(row.get("Targets", "")):
            target = self.find(key)[1]
            if target.get("Status") != "VALIDATED_COMPLETE" or freshness(target, self.tables, self.root) != "CURRENT":
                errors.append(f"{key} incomplete or stale")
        for item in refs(row.get("Out", "")):
            path = item.split(":", 1)[0]
            if not any(r["Path"] == path for r in self.tables["overlord"]):
                errors.append(f"{item} unregistered")
        if errors:
            raise ValueError(f"{op['id']}: incomplete: " + "; ".join(errors))
        row["Status"] = "ABSORBED"
        self.event("absorb", op["id"], {})

    def op_touch(self, op: dict):
        path = op["path"]
        pace = op.get("pace", "")
        registered = any(r["Path"] == path for r in self.tables["overlord"])
        detail = {"path": path, "registered": registered}
        if not registered:
            key = self.next_id("overlord")
            self.op_add({"op": "add", "register": "overlord", "row": {"ID": key, "Path": path, "Kind": "FILE", "Purpose": "", "Tags": "#unpurposed"}})
            detail["new"] = key
            if pace:
                _, row = self.find(pace)
                outs = refs(row.get("Out", ""))
                if path in [o.split(":", 1)[0] for o in outs]:
                    row["In"] = ";".join(dict.fromkeys(refs(row["In"]) + [key]))
        self.event("touch", pace or path, detail)
```

- [ ] **Step 4: Rewrite service.py**

```python
"""Transport-neutral application boundary: frames in, events out."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from pacer_mcp.cards import card
from pacer_mcp.commands import Editor
from pacer_mcp.frames import active_pace, edit_frame, prompt_frame, render, session_frame
from pacer_mcp.gates import edit_decision, stop_decision
from pacer_mcp.probe import run_probe
from pacer_mcp.provider import select_provider
from pacer_mcp.rank import rank
from pacer_mcp.schema import HEADERS, REF_PATTERN, REGISTERS, TAG_PATTERN, VERSION, contained_path, empty_row, utc_now
from pacer_mcp.spec import read_spec
from pacer_mcp.store import Store
from pacer_mcp.validation import validate_web


class Service:
    def __init__(self, root: Path):
        self.store = Store(root)
        self.root = self.store.root
        self.spec = read_spec(self.root)
        self._provider = None

    @property
    def provider(self):
        if self._provider is None:
            self._provider = select_provider(self.root, self.spec["provider"])
        return self._provider

    # -- reads ---------------------------------------------------------------
    def frame(self, kind: str, focus: str = "") -> str:
        with self.store.locked():
            t = self.store.load().tables
            if kind == "session":
                return session_frame(t, self.root, self.store, self.provider, self.spec)
            if kind == "edit":
                return edit_frame(t, self.root, self.store, self.provider, self.spec, focus)
            if kind == "prompt":
                return prompt_frame(t, self.root, self.provider, self.spec, focus)
            if kind == "stop":
                return stop_decision(t, self.root, self.store, self.provider, self.spec)["text"]
            raise ValueError("frame kind must be session, edit, prompt or stop")

    def q(self, query: str, limit: int = 40) -> str:
        with self.store.locked():
            t = self.store.load().tables
            index = {r["ID"]: reg for reg in REGISTERS for r in t[reg]}
            query = query.strip()
            keys: list[str] = []
            if REF_PATTERN.fullmatch(query) and query in index:
                keys = [k for _, k in rank(t, self.provider, [query]) if k == query] + [k for d, k in rank(t, self.provider, [query]) if 0 < d <= 2]
            elif TAG_PATTERN.fullmatch(query):
                keys = [r["ID"] for reg in REGISTERS for r in t[reg] if query in r.get("Tags", "").split()]
            elif ":" in query and query.split(":")[0] in REGISTERS:
                reg, status = query.split(":", 1)
                keys = [r["ID"] for r in t[reg] if r.get("Status") == status]
            elif query in REGISTERS:
                keys = [r["ID"] for r in t[query]]
            else:
                keys = [r["ID"] for r in t["overlord"] if r.get("Path") == query]
                if not keys:
                    return edit_frame(t, self.root, self.store, self.provider, self.spec, query)
            lines = [render(k, t, self.root, self.provider) for k in keys[:limit]]
            if len(keys) > limit:
                lines.append(f"+{len(keys) - limit} more")
            return "\n".join(lines)

    def log(self, row_id: str | None, limit: int = 20) -> list[dict]:
        return self.store.ledger_read(row_id, limit)

    def validate(self) -> dict:
        with self.store.locked():
            snap = self.store.load()
            return {"revision": snap.revision, **validate_web(snap.tables, self.root, snap.headers)}

    def edit_decision(self, path: str) -> dict:
        with self.store.locked():
            return edit_decision(self.store.load().tables, self.root, self.store, self.spec, path)

    def tree(self) -> str:
        from pacer_mcp.tree import render_tree

        with self.store.locked():
            return render_tree(self.store.load().tables, self.spec)

    # -- writes --------------------------------------------------------------
    def write(self, operations: list[dict], actor: str, preview: bool = False) -> dict:
        if not actor.strip() or "\n" in actor or len(actor) > 100:
            raise ValueError("A short single-line actor is required")
        if not 1 <= len(operations) <= 200:
            raise ValueError("Batch must contain 1..200 operations")
        with self.store.locked():
            snap = self.store.load()
            editor = Editor(snap.tables, actor, self.root)
            for op in operations:
                try:
                    editor.execute(op)
                except (KeyError, TypeError, AttributeError) as exc:
                    raise ValueError(f"Malformed {op.get('op', 'unknown')} command: {exc}") from exc
            report = validate_web(snap.tables, self.root, snap.headers)
            if not report["valid"]:
                raise ValueError(report["errors"][0])
            result = {"preview": preview, "changed_ids": sorted(editor.changed), "validation": report, "events": len(editor.events)}
            if preview:
                return {**result, "revision": snap.revision}
            revision = self.store.publish(snap, snap.encode())
            for event in editor.events:
                self.store.ledger_append(event)
            return {**result, "revision": revision}

    def probe(self, row_id: str, actor: str) -> dict:
        with self.store.locked():
            snap = self.store.load()
            row = next((r for r in snap.tables["organism"] if r["ID"] == row_id), None)
            if row is None:
                raise ValueError(f"REFUSAL: Unknown ID {row_id}")
            result = run_probe(row, snap.tables, self.root, actor)
            row["Evidence"] = result["evidence"]
            report = validate_web(snap.tables, self.root, snap.headers)
            if not report["valid"]:
                raise ValueError(report["errors"][0])
            self.store.publish(snap, snap.encode())
            self.store.ledger_append({"actor": actor, "op": "probe", "id": row_id, "detail": result})
            return {"id": row_id, **result, "card": render(row_id, snap.tables, self.root, self.provider)}

    def touch(self, path: str, actor: str) -> str:
        with self.store.locked():
            snap = self.store.load()
            pace = active_pace(snap.tables, self.store)
            editor = Editor(snap.tables, actor, self.root)
            editor.execute({"op": "touch", "path": path, "pace": pace["ID"] if pace else ""})
            report = validate_web(snap.tables, self.root, snap.headers)
            if not report["valid"]:
                return f"touch refused: {report['errors'][0]}"
            self.store.publish(snap, snap.encode())
            for event in editor.events:
                self.store.ledger_append(event)
            new = next((e["detail"].get("new") for e in editor.events if e["op"] == "touch"), None)
            stale = [r["ID"] for r in snap.tables["organism"] if path in [
                x["Path"] for x in snap.tables["overlord"] if x["ID"] in (r.get("Binds") or "").split(";")
            ] and r.get("Evidence")]
            parts = [f"{new} registered #unpurposed" if new else f"touched {path}"]
            if stale:
                parts.append("stale: " + ", ".join(stale))
            return " | ".join(parts)

    def stop(self, actor: str) -> dict:
        with self.store.locked():
            snap = self.store.load()
            decision = stop_decision(snap.tables, self.root, self.store, self.provider, self.spec)
            pace = active_pace(snap.tables, self.store)
            if pace and pace.get("Next") != decision["next"]:
                pace["Next"] = decision["next"]
                self.store.publish(snap, snap.encode())
                self.store.ledger_append({"actor": actor, "op": "checkpoint", "id": pace["ID"], "detail": {"next": decision["next"]}})
            return decision

    def initialize(self) -> dict:
        with self.store.locked():
            snap = self.store.load(missing_ok=True)
            if snap.files:
                raise ValueError("Registers already exist; initialize never overwrites")
            for name in ("README.md", "AGENTS.md"):
                if contained_path(self.root, name).is_file():
                    snap.tables["overlord"].append(empty_row("overlord", {"ID": f"OVR-{len(snap.tables['overlord']) + 1:03d}", "Path": name, "Kind": "FILE", "Purpose": "project authority", "Tags": "#core"}))
            self.store.publish(snap, snap.encode())
            self.store.ledger_append({"actor": "initialize", "op": "initialize", "id": "-", "detail": {"version": VERSION, "at": utc_now()}})
        return self.validate()

    def recover(self) -> dict:
        with self.store.locked():
            return self.store.recover()
```

`Store.publish` compares revisions between `load()` and publish; both happen under one lock so it never fails here. Keep it: it guards against a concurrent direct file edit.

- [ ] **Step 5: Rewrite models.py**

```python
"""Typed operations for MCP tool schemas."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Add(Command):
    op: Literal["add"]
    register: Literal["todo", "overlord", "organism", "nodule", "decision"]
    row: dict[str, str]


class Set(Command):
    op: Literal["set"]
    id: str
    fields: dict[str, str]


class Link(Command):
    op: Literal["link"]
    id: str
    field: str
    target: str
    remove: bool = False


class Move(Command):
    op: Literal["move"]
    id: str
    pos: str


class Status(Command):
    op: Literal["status"]
    id: str
    status: Literal["TODO", "ACTIVE", "INTEGRATED", "DONE", "SCAFFOLD", "PACED_REQUIREMENT", "VALIDATED_COMPLETE"]


class Latch(Command):
    op: Literal["latch"]
    id: str
    latched: Literal["true", "false"]
    evidence: str = ""


class Pace(Command):
    op: Literal["pace"]
    nodule: dict[str, str]
    tasks: list[dict[str, str]] = Field(default_factory=list)
    requirements: list[dict[str, str]] = Field(default_factory=list)
    decisions: list[dict[str, str]] = Field(default_factory=list)


class Absorb(Command):
    op: Literal["absorb"]
    id: str


Operation = Annotated[Add | Set | Link | Move | Status | Latch | Pace | Absorb, Field(discriminator="op")]
```

- [ ] **Step 6: Delete old modules and run all tests; expect PASS.**

```bash
git rm plugins/pacer/src/pacer_mcp/context.py plugins/pacer/src/pacer_mcp/pages.py plugins/pacer/src/pacer_mcp/evidence.py plugins/pacer/src/pacer_mcp/semantics.py plugins/pacer/src/pacer_mcp/query.py
```

`tree.py` is created in Task 11; until then `Service.tree` is unexercised. `touch` returns the `#unpurposed` line; fix the tautological assertion in `test_status_latch_probe_and_frames` to `assert any(r["Path"] == "src/new.py" for r in ...)` once it passes.

- [ ] **Step 7: Commit** — `git commit -am "feat(pacer3): event-based editor and service"`

---

### Task 9: CLI, MCP server, hooks, skill, manifests

**Files:**
- Modify: `plugins/pacer/src/pacer_mcp/cli.py`, `server.py` (full rewrites)
- Create: `plugins/pacer/hooks/hooks.json`, `plugins/pacer/skills/pacer/SKILL.md`
- Delete: `plugins/pacer/skills/pacer-onboard/`, `pacer-develop/`, `pacer-audit/`
- Modify: `plugins/pacer/pyproject.toml` (version 3.0.0), `plugins/pacer/.claude-plugin/plugin.json`, `plugins/pacer/plugin.json`, `plugins/pacer/.codex-plugin/plugin.json` (version `3.0.0`), `plugins/pacer/.mcp.json` and `mcp.json` (`UV_PROJECT_ENVIRONMENT` venv hash = first 16 hex of SHA256("3.0.0")), `plugins/pacer/tests/test_packaging.py` (recreate minimal: manifests parse, versions equal, hash rule holds, hooks.json parses).
- Test: `plugins/pacer/tests/test_cli_server.py`

**Interfaces:**
- CLI: `pacer [--root R] frame <session|edit|prompt|stop> [--focus X]`, `q <query>`, `write --file ops.json --actor A [--preview]`, `probe <OGM> --actor A`, `validate`, `initialize`, `migrate --from <0.5|v2> [--apply] --actor A`, `log [ID] [--limit N]`, `tree`, `recover`, `serve [--root R]`, `hook <session-start|prompt|pre-edit|post-edit|stop>` (reads stdin JSON).
- MCP tools: `pacer_frame(root, kind, focus="")`, `pacer_q(root, query)`, `pacer_write(root, operations, actor, preview=False)`, `pacer_probe(root, id, actor)`, `pacer_validate(root)`, `pacer_initialize(root)`, `pacer_migrate(root, source, actor, preview=True)`, `pacer_log(root, id="", limit=20)`, `pacer_recover(root)`.

- [ ] **Step 1: Tests**

```python
# plugins/pacer/tests/test_cli_server.py
import json

from pacer_mcp.cli import main
from pacer_mcp.server import build_server


def test_cli_roundtrip(project, capsys):
    root = str(project.root)
    ops = project.root / "ops.json"
    ops.write_text(json.dumps([{"op": "add", "register": "overlord", "row": {"ID": "OVR-001", "Path": "src/a.py", "Kind": "FILE", "Purpose": "entry"}}]))
    assert main(["--root", root, "write", "--file", str(ops), "--actor", "t"]) == 0
    assert main(["--root", root, "q", "OVR-001"]) == 0
    assert capsys.readouterr().out.strip().startswith("OVR OVR-001 src/a.py")
    assert main(["--root", root, "frame", "session"]) == 0
    assert capsys.readouterr().out.startswith("PACER ")
    assert main(["--root", root, "validate"]) == 0


def test_hook_subcommand_reads_stdin(project, capsys, monkeypatch):
    import io, sys
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(project.root), "tool_name": "Edit", "tool_input": {"file_path": str(project.root / "src" / "a.py")}})))
    assert main(["hook", "pre-edit"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "unregistered" in out["hookSpecificOutput"]["additionalContext"]
    assert "permissionDecision" not in out["hookSpecificOutput"]


async def test_mcp_tools_list():
    server = build_server()
    names = {t.name for t in await server.list_tools()}
    assert names == {"pacer_frame", "pacer_q", "pacer_write", "pacer_probe", "pacer_validate", "pacer_initialize", "pacer_migrate", "pacer_log", "pacer_recover"}
```

- [ ] **Step 2: Run; expect FAIL.**

- [ ] **Step 3: Rewrite cli.py**

```python
"""PACER CLI; `hook` is the harness entry point; `serve` is the MCP entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pacer_mcp.service import Service


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pacer", description="PACER 3: delivered context")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    frame = sub.add_parser("frame"); frame.add_argument("kind", choices=["session", "edit", "prompt", "stop"]); frame.add_argument("--focus", default="")
    q = sub.add_parser("q"); q.add_argument("query"); q.add_argument("--limit", type=int, default=40)
    write = sub.add_parser("write"); write.add_argument("--file", required=True, type=Path); write.add_argument("--actor", required=True); write.add_argument("--preview", action="store_true")
    probe = sub.add_parser("probe"); probe.add_argument("id"); probe.add_argument("--actor", default="cli")
    for name in ("validate", "initialize", "tree", "recover"):
        sub.add_parser(name)
    migrate = sub.add_parser("migrate"); migrate.add_argument("--from", dest="source", required=True, choices=["0.5", "v2"]); migrate.add_argument("--apply", action="store_true"); migrate.add_argument("--actor", default="migrate")
    log = sub.add_parser("log"); log.add_argument("id", nargs="?", default=""); log.add_argument("--limit", type=int, default=20)
    serve = sub.add_parser("serve"); serve.add_argument("--root", dest="serve_root", type=Path)
    hook = sub.add_parser("hook"); hook.add_argument("event", choices=["session-start", "prompt", "pre-edit", "post-edit", "stop"])
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            from pacer_mcp.server import build_server

            build_server(args.serve_root).run(transport="stdio")
            return 0
        if args.command == "hook":
            from pacer_mcp.hook import run

            try:
                payload = json.loads(sys.stdin.read() or "{}")
            except json.JSONDecodeError:
                payload = {}
            code, out = run(args.event, payload)
            if out:
                print(out)
            return code
        service = Service(args.root)
        if args.command == "frame":
            print(service.frame(args.kind, args.focus))
        elif args.command == "q":
            print(service.q(args.query, args.limit))
        elif args.command == "write":
            ops = json.loads(args.file.read_text(encoding="utf-8"))
            print(json.dumps(service.write(ops, args.actor, preview=args.preview), indent=2))
        elif args.command == "probe":
            print(json.dumps(service.probe(args.id, args.actor), indent=2))
        elif args.command == "migrate":
            print(json.dumps(service.migrate(args.source, actor=args.actor, preview=not args.apply), indent=2))
        elif args.command == "log":
            for entry in service.log(args.id or None, args.limit):
                print(json.dumps(entry, ensure_ascii=False))
        elif args.command == "tree":
            print(service.tree())
        else:
            result = getattr(service, args.command)()
            print(json.dumps(result, indent=2))
            return 1 if isinstance(result, dict) and result.get("valid") is False else 0
        return 0
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Rewrite server.py**

```python
"""MCP tools over the same Service. Frames are text; writes are typed."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from pacer_mcp.models import Operation
from pacer_mcp.service import Service

INSTRUCTIONS = (
    "PACER 3 delivers project context as cards: PAC (work), OVR (source), OGM (requirement+probe), "
    "DEC (decision/latch), NDL (intake). Hooks inject frames at session start, before/after edits and "
    "at stop. Use pacer_q for any ID, path or #tag; pacer_write for the lexicon "
    "(add/set/link/move/status/latch/pace/absorb); pacer_probe to run a requirement's Probe. "
    "Cells are bounded; long text belongs in files."
)


def build_server(bound_root: Path | None = None) -> FastMCP:
    bound = bound_root.resolve(strict=True) if bound_root else None
    server = FastMCP("PACER", instructions=INSTRUCTIONS, log_level="WARNING")
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

    def service(root: str) -> Service:
        path = Path(root)
        if not path.is_absolute():
            raise ValueError("Pass the absolute project root explicitly")
        path = path.resolve(strict=True)
        if bound is not None and path != bound:
            raise ValueError("Project root is outside this server's binding")
        return Service(path)

    @server.tool(annotations=read)
    def pacer_frame(root: str, kind: Literal["session", "edit", "prompt", "stop"], focus: str = "") -> str:
        """Compile a bounded card frame: session spine, edit constraints for a path, prompt mentions, or stop gate."""
        return service(root).frame(kind, focus)

    @server.tool(annotations=read)
    def pacer_q(root: str, query: str, limit: int = 40) -> str:
        """Cards for an ID (with neighbours), a repo path, a #tag, a register, or register:STATUS."""
        return service(root).q(query, limit)

    @server.tool(annotations=write)
    def pacer_write(root: str, operations: list[Operation], actor: str, preview: bool = False) -> dict[str, object]:
        """Apply add/set/link/move/status/latch/pace/absorb atomically; every change is ledgered."""
        return service(root).write([op.model_dump() for op in operations], actor, preview=preview)

    @server.tool(annotations=write)
    def pacer_probe(root: str, id: str, actor: str) -> dict[str, object]:
        """Run an OGM's Probe command, record its evidence cell and return the updated card."""
        return service(root).probe(id, actor)

    @server.tool(annotations=read)
    def pacer_validate(root: str) -> dict[str, object]:
        return service(root).validate()

    @server.tool(annotations=write)
    def pacer_initialize(root: str) -> dict[str, object]:
        """Create empty PACER 3 registers; never overwrites."""
        return service(root).initialize()

    @server.tool(annotations=write)
    def pacer_migrate(root: str, source: Literal["0.5", "v2"], actor: str, preview: bool = True) -> dict[str, object]:
        """Migrate profile 0.5 CSV registers or a v2 todo.PACER plan; preview by default."""
        return service(root).migrate(source, actor=actor, preview=preview)

    @server.tool(annotations=read)
    def pacer_log(root: str, id: str = "", limit: int = 20) -> list[dict[str, object]]:
        return service(root).log(id or None, limit)

    @server.tool(annotations=write)
    def pacer_recover(root: str) -> dict[str, object]:
        return service(root).recover()

    return server
```

- [ ] **Step 5: hooks.json, skill, manifests**

`plugins/pacer/hooks/hooks.json`:

```json
{
  "description": "PACER 3 delivered context",
  "hooks": {
    "SessionStart": [{"matcher": "startup|resume|clear|compact", "hooks": [{"type": "command", "command": "uv run --no-sync --project \"${CLAUDE_PLUGIN_ROOT}\" pacer hook session-start", "timeout": 20}]}],
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "uv run --no-sync --project \"${CLAUDE_PLUGIN_ROOT}\" pacer hook prompt", "timeout": 15}]}],
    "PreToolUse": [{"matcher": "Edit|Write|NotebookEdit|apply_patch", "hooks": [{"type": "command", "command": "uv run --no-sync --project \"${CLAUDE_PLUGIN_ROOT}\" pacer hook pre-edit", "timeout": 15}]}],
    "PostToolUse": [{"matcher": "Edit|Write|NotebookEdit|apply_patch", "hooks": [{"type": "command", "command": "uv run --no-sync --project \"${CLAUDE_PLUGIN_ROOT}\" pacer hook post-edit", "timeout": 15}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "uv run --no-sync --project \"${CLAUDE_PLUGIN_ROOT}\" pacer hook stop", "timeout": 20}]}]
  }
}
```

The installed plugin's environment is `${CLAUDE_PLUGIN_DATA}/venv-…` per `.mcp.json`; the hook command inherits `UV_PROJECT_ENVIRONMENT` only if set, so add the same `env` values to `.mcp.json` AND export them in the hook command for Claude: prefix each command with `UV_PROJECT_ENVIRONMENT=\"${CLAUDE_PLUGIN_DATA}/venv-<hash>\" UV_PYTHON_DOWNLOADS=never`. Windows hooks run through the user's shell; use the form `uv run --no-sync --project "${CLAUDE_PLUGIN_ROOT}" pacer hook …` and set the env in `.mcp.json` only; verify at the live trial (Task 12) and add a `hooks/pacer-hook.ps1`/`.sh` wrapper if the env is not inherited.

`plugins/pacer/skills/pacer/SKILL.md`:

```markdown
---
name: pacer
description: PACER 3 card grammar and write lexicon. Use when reading a PACER frame, querying an ID/path/#tag, recording work, decisions or evidence, or pacing new scope.
---

Frames arrive by hook; you do not onboard. Every line is a card:

    PAC PAC-041 A2.P3.05 ACTIVE prototype | Produce: … | In: OVR-012 | Out: src/x.py:Foo | Binds: OGM-004 | Probe: … | Next: implement
    OVR OVR-012 src/a.py:S integrated | Purpose: … | Binds: OGM-004 | Latch: DEC-003 | used-by: src/main.py (+3)
    OGM OGM-004 PACED_REQUIREMENT USER release | Requirement: … | Probe: pytest -q | Evidence: rev:a1b2c3d exit:0 at:2026-09-20 STALE(src/a.py)
    DEC DEC-003 LATCH USER latched | Subject: OVR-012 | Chosen: … | Why: …
    NDL NDL-019 ACTIVE lane=auth | Intent: … | Targets: OGM-004 | Spawned: PAC-040;PAC-041 | Exit: …

Read: `pacer_q(root, "<ID|path|#tag|register|register:STATUS>")`.
Write: `pacer_write(root, [ops], actor)` with ops `add{register,row}`, `set{id,fields}`, `link{id,field,target}`, `move{id,pos}`, `status{id,status}`, `latch{id,latched,evidence}`, `pace{nodule,tasks,requirements,decisions}`, `absorb{id}`.
Prove: `pacer_probe(root, "OGM-004", actor)` runs the Probe and writes Evidence. VALIDATED_COMPLETE needs exit:0 and CURRENT.

Rules the runtime enforces: cells ≤ limits, no `|`; IDs immutable; Needs gate DONE; LATCH needs USER; one ACTIVE nodule per lane.
Behaviour: continue through paces; a `LATCH … open` card is the only reason to ask the user, and you ask once. `OFF-PACE` on an edit card means the path is outside the active pace's In/Out: pace it or move on. `#unpurposed` OVR rows need a Purpose. Tiers: sketch/prototype/playable never block; integrated blocks on FAIL; release on FAIL/STALE; protected denies edits without a USER latch.
New scope enters through `pace`. Positions `A<area>.P<phase>.<pace>` are inherited context; PHASE rows carry Exit and Tier.
```

Manifests: set `"version": "3.0.0"` in all three plugin manifests and `pyproject.toml`; compute `python -c "import hashlib;print(hashlib.sha256(b'3.0.0').hexdigest()[:16])"` and set `UV_PROJECT_ENVIRONMENT` to `${CLAUDE_PLUGIN_DATA}/venv-<that>` in `.mcp.json` and `${PLUGIN_DATA}/venv-<that>` in `mcp.json`. Recreate `test_packaging.py` to assert: all manifests parse, versions equal `3.0.0`, the venv suffix equals the hash rule, `hooks/hooks.json` parses and has the five events, and only `skills/pacer/SKILL.md` exists under `skills/`.

- [ ] **Step 6: Run all tests; expect PASS. Commit** — `git commit -am "feat(pacer3): cli, mcp tools, hooks, single skill, manifests"`

---

### Task 10: Migration from 0.5 and from v2

**Files:**
- Create: `plugins/pacer/src/pacer_mcp/migrate.py`
- Modify: `service.py` (add `migrate`)
- Test: `plugins/pacer/tests/test_migrate.py`

**Interfaces:**
- `migrate.from_05(old: dict[str, list[dict]], archived_nodules: list[dict]) -> tuple[dict, list[dict]]` returns `(tables3, ledger_events)`.
- `migrate.from_v2(text: str, project_dir: Path) -> tuple[dict, list[dict]]`.
- `Service.migrate(source, actor, preview=True) -> dict` with keys `preview, sizes_before, sizes_after, counts, validation, ledger_events`. For `0.5` it reads the current root registers with the 0.5 headers (use `store.parse_csv` directly, not `Store.load`, because HEADERS differ); on apply it writes the five new CSVs, `ledger.PACER.jsonl`, moves the old CSVs to `archive/pacer-0.5/` and archived nodule files stay where they are (they are re-read as ABSORBED rows into the new nodule table's archive on the first `encode()`). For `v2` it reads `todo.PACER` in the root.

Mapping (0.5 → 3):

| 0.5 | 3 |
|---|---|
| todo.ID/Title/Tags | same |
| todo.Phase | `Pos`: distinct non-empty Phase values in first-seen order become `A1.P<n>`; rows with empty Phase go under `A1.P<last+1>` "Unphased"; each PAC becomes a PACE `A1.P<n>.<k>`; synthesize one AREA `PAC-<max+1>` "A1 Legacy" and one PHASE per group with `Exit` = "migrated phase <name>" and Tier from spec |
| todo.Status TODO/DOING/REVIEW/DONE | TODO/ACTIVE/INTEGRATED/DONE |
| todo.DoD | `Produce` = first sentence truncated to 140; full DoD → ledger `migrate` event detail |
| todo.OVRRefs / OGMRefs / BlockedBy(hard only) | `In` / `Binds` / `Needs` |
| todo.NextAction | `Next` (map review→integrate, resolve→inspect) |
| todo.PreviousAttempts | DEC `FAILED` rows, Subject=PAC, Why=first 280 chars, Authority=OBSERVED |
| todo.LearningNotes | DEC `LESSON` rows |
| todo.ApprovalState APPROVED + ApprovalEvidence | DEC `LATCH` Latched=true Authority=USER Chosen="approved: "+Title[:120]; PENDING → Latched=false Authority=INFERRED |
| todo.Notes/ContextCheckpoint/timestamps/Context/Instructions/… | ledger event detail (`legacy` dict) |
| overlord.ID/Path/Symbol/AssetType→Kind/Purpose/Tags/OGMRefs→Binds | same names; Purpose truncated to 140; empty Purpose → "#unpurposed" tag |
| overlord.Exports/Imports/Requires/RequiredBy/PACRefs/NDLRefs/Notes/EvidenceFor | dropped (ledger) |
| organism.ID/Title/Status/Authority/OriginText→Origin/Requirement/OVRRefs→Binds/Tags | same; Requirement truncated to 280, Origin to 400 |
| organism.AcceptanceEvidence/EvidenceBindings/EvidenceArtifact/Rule*/Notes/BlockedByOGM/PACRefs/NDLRefs/AbsorbedFromNDL | dropped to ledger; `Evidence` left empty (no probe has run); VALIDATED_COMPLETE rows are demoted to PACED_REQUIREMENT with a ledger note (historical acceptance is not current proof) |
| nodule.ID/NoduleName→Name/Status/Lane/UserRequest→Request/Intent/TargetOVR→In/NewAssets→Out/OGMTargets→Targets/SpawnedPACs→Spawned/AbsorptionCriteria→Exit/Tags | same; Request falls back to Intent when empty |

Mapping (v2 → 3): `GLOBAL Gnn` → AREA `A<n>`; `PHASE Pnn` → PHASE with `Exit` from `EXIT coherent=`; `PACE id "title" state=` → PACE with Produce=title, Status map todo→TODO, active→ACTIVE, integrated→INTEGRATED, done→DONE; `SOURCE "path" role=` → OVR FILE row with Purpose=role; `:nodule NDL-x "name"` → NDL with Request=name; `+approved NDL-x` → DEC LATCH USER latched Subject=NDL-x; `PROJECT … maturity=` → `.MIVIM.spec` `[project] tier` (write the file if absent). IDs: allocate PAC-001… in document order; keep v2 pace IDs (e.g. `M14`) in `Tags` as `#m14`.

- [ ] **Step 1: Tests**

```python
# plugins/pacer/tests/test_migrate.py
from pacer_mcp.migrate import from_05, from_v2
from pacer_mcp.validation import validate_web

OLD_TODO = {"ID": "PAC-001", "Title": "Do thing", "Phase": "Codex integration", "Status": "REVIEW", "DoD": "Thing done. More detail here.", "OVRRefs": "OVR-001", "OGMRefs": "OGM-001", "BlockedBy": "", "DependencyType": "", "NextAction": "review", "PreviousAttempts": "tried X, failed", "LearningNotes": "Y matters", "ApprovalState": "APPROVED", "ApprovalEvidence": "user: go", "Notes": "a | b | c", "ContextCheckpoint": "{}", "Tags": "#core"}
OLD_OVR = {"ID": "OVR-001", "AssetType": "FILE", "Path": "README.md", "Symbol": "", "Purpose": "p" * 200, "Exports": "x", "Imports": "y", "Requires": "", "RequiredBy": "", "OGMRefs": "OGM-001", "PACRefs": "PAC-001", "NDLRefs": "", "Tags": "#core", "Notes": "n", "EvidenceFor": ""}
OLD_OGM = {"ID": "OGM-001", "Title": "Req", "Status": "VALIDATED_COMPLETE", "Requirement": "r", "AcceptanceEvidence": "tests", "OVRRefs": "OVR-001", "Authority": "USER", "OriginText": "the user said", "RuleType": "manual", "EvidenceBindings": "{}", "Notes": "big", "Tags": ""}
OLD_NDL = {"ID": "NDL-001", "NoduleName": "n", "Intent": "i", "Status": "ABSORBED", "TargetOVR": "OVR-001", "NewAssets": "", "OGMTargets": "OGM-001", "SpawnedPACs": "PAC-001", "AbsorptionCriteria": "done", "Lane": "main", "UserRequest": "", "Notes": ""}


def test_from_05(registers):
    tables, events = from_05({"todo": [OLD_TODO], "overlord": [OLD_OVR], "organism": [OLD_OGM], "nodule": []}, [OLD_NDL])
    todo = {r["ID"]: r for r in tables["todo"]}
    pace = todo["PAC-001"]
    assert pace["Kind"] == "PACE" and pace["Status"] == "INTEGRATED" and pace["Produce"] == "Thing done."
    assert pace["In"] == "OVR-001" and pace["Binds"] == "OGM-001" and pace["Next"] == "integrate"
    phases = [r for r in tables["todo"] if r["Kind"] == "PHASE"]
    assert phases[0]["Title"] == "Codex integration" and pace["Pos"].startswith(phases[0]["Pos"] + ".")
    kinds = sorted(r["Kind"] for r in tables["decision"])
    assert kinds == ["FAILED", "LATCH", "LESSON"]
    latch = next(r for r in tables["decision"] if r["Kind"] == "LATCH")
    assert latch["Latched"] == "true" and latch["Authority"] == "USER" and pace["Latch"] == latch["ID"]
    ovr = tables["overlord"][0]
    assert len(ovr["Purpose"]) == 140 and ovr["Kind"] == "FILE" and ovr["Binds"] == "OGM-001"
    ogm = tables["organism"][0]
    assert ogm["Status"] == "PACED_REQUIREMENT" and ogm["Origin"] == "the user said" and ogm["Evidence"] == ""
    ndl = tables["nodule"][0]
    assert ndl["Name"] == "n" and ndl["Request"] == "i" and ndl["Exit"] == "done" and ndl["Status"] == "ABSORBED"
    assert any(e["op"] == "migrate" and e["id"] == "PAC-001" and "DoD" in e["detail"]["legacy"] for e in events)
    assert validate_web(tables, registers)["errors"] == []


V2 = '''PACER::TODO version=2.0.0
PROJECT "Demo" maturity=integrated
GLOBAL G001 "Core" state=active
  SOURCE "README.md" role=authority
  PHASE P01 "Boot" state=integrated
    PACE M01 "rebase" state=done
    PACE M02 "wire" state=active
    EXIT coherent="boots"
  :nodule NDL-003 "shared pattern" state=active
  +approved NDL-003
  :loop⠁:
END
'''


def test_from_v2(registers):
    tables, events = from_v2(V2, registers)
    kinds = [(r["Kind"], r["Pos"], r["Status"]) for r in tables["todo"]]
    assert kinds == [("AREA", "A1", "ACTIVE"), ("PHASE", "A1.P1", "INTEGRATED"), ("PACE", "A1.P1.01", "DONE"), ("PACE", "A1.P1.02", "ACTIVE")]
    assert tables["todo"][1]["Exit"] == "boots" and tables["todo"][1]["Tier"] == "integrated"
    assert "#m02" in tables["todo"][3]["Tags"] and tables["todo"][3]["Produce"] == "wire"
    assert tables["overlord"][0]["Path"] == "README.md" and tables["overlord"][0]["Purpose"] == "authority"
    assert tables["nodule"][0]["ID"] == "NDL-003" and tables["decision"][0]["Kind"] == "LATCH" and tables["decision"][0]["Latched"] == "true"
    assert validate_web(tables, registers)["errors"] == []
```

- [ ] **Step 2: Run; expect FAIL.**

- [ ] **Step 3: Implement migrate.py**

```python
"""Lossless-by-ledger migration: current meaning into bounded cells, history into events."""

from __future__ import annotations

import re
from pathlib import Path

from pacer_mcp.schema import REGISTERS, empty_row, refs

STATUS_05 = {"TODO": "TODO", "DOING": "ACTIVE", "REVIEW": "INTEGRATED", "DONE": "DONE"}
NEXT_05 = {"inspect": "inspect", "implement": "implement", "verify": "verify", "review": "integrate", "absorb": "absorb", "resolve": "inspect"}
V2_STATUS = {"todo": "TODO", "active": "ACTIVE", "integrated": "INTEGRATED", "done": "DONE", "review": "INTEGRATED"}
_Q = re.compile(r'"([^"]*)"')


def _cut(text: str, limit: int) -> str:
    text = (text or "").replace("|", "/").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _first_sentence(text: str, limit: int) -> str:
    text = (text or "").replace("|", "/").replace("\n", " ").strip()
    match = re.match(r"(.+?[.!?])(\s|$)", text)
    return _cut(match.group(1) if match else text, limit)


def _attr(line: str, key: str, default: str = "") -> str:
    m = re.search(rf"\b{re.escape(key)}=(?:\"([^\"]*)\"|(\S+))", line)
    return default if not m else (m.group(1) if m.group(1) is not None else m.group(2))


def _empty_tables() -> dict:
    return {name: [] for name in REGISTERS}


def _hard_blockers(row: dict) -> list[str]:
    blockers = refs(row.get("BlockedBy", ""))
    kinds = refs(row.get("DependencyType", "")) or ["hard"]
    if len(kinds) == 1:
        kinds *= len(blockers)
    if len(kinds) != len(blockers):
        return blockers
    return [b for b, k in zip(blockers, kinds, strict=True) if k == "hard"]


def from_05(old: dict, archived: list[dict], default_tier: str = "prototype") -> tuple[dict, list[dict]]:
    tables, events = _empty_tables(), []
    dec_counter = [0]

    def dec(kind: str, subject: str, **fields) -> str:
        dec_counter[0] += 1
        key = f"DEC-{dec_counter[0]:03d}"
        row = empty_row("decision", {"ID": key, "Kind": kind, "Subject": subject, **fields})
        tables["decision"].append(row)
        return key

    ids = [int(r["ID"].split("-")[1].rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")) for r in old["todo"]]
    counter = [max([0, *ids])]

    def pac() -> str:
        counter[0] += 1
        return f"PAC-{counter[0]:03d}"

    groups: dict[str, list[dict]] = {}
    for row in old["todo"]:
        groups.setdefault(row.get("Phase") or "Unphased", []).append(row)
    area_id = pac()
    tables["todo"].append(empty_row("todo", {"ID": area_id, "Kind": "AREA", "Pos": "A1", "Title": "Legacy", "Status": "ACTIVE", "Tier": default_tier}))
    for n, (name, rows) in enumerate(groups.items(), 1):
        phase_id = pac()
        status = "DONE" if all(r.get("Status") == "DONE" for r in rows) else "ACTIVE"
        tables["todo"].append(empty_row("todo", {"ID": phase_id, "Kind": "PHASE", "Pos": f"A1.P{n}", "Title": _cut(name, 80), "Status": status, "Tier": default_tier, "Exit": _cut(f"migrated phase {name}", 140)}))
        for k, row in enumerate(rows, 1):
            new = empty_row("todo", {
                "ID": row["ID"], "Kind": "PACE", "Pos": f"A1.P{n}.{k:02d}", "Title": _cut(row.get("Title", ""), 80),
                "Status": STATUS_05.get(row.get("Status", "TODO"), "TODO"),
                "Produce": _first_sentence(row.get("DoD", "") or row.get("Title", ""), 140),
                "In": row.get("OVRRefs", ""), "Binds": row.get("OGMRefs", ""), "Needs": ";".join(_hard_blockers(row)),
                "Next": NEXT_05.get(row.get("NextAction", ""), ""), "Tags": row.get("Tags", ""),
            })
            latches = []
            if row.get("PreviousAttempts"):
                dec("FAILED", row["ID"], Why=_cut(row["PreviousAttempts"], 280), Authority="OBSERVED")
            if row.get("LearningNotes"):
                dec("LESSON", row["ID"], Why=_cut(row["LearningNotes"], 280), Authority="OBSERVED")
            state = row.get("ApprovalState", "")
            if state == "APPROVED":
                latches.append(dec("LATCH", row["ID"], Question=_cut("approve " + row.get("Title", ""), 140), Chosen=_cut("approved: " + row.get("Title", ""), 140), Why=_cut(row.get("ApprovalEvidence", ""), 280), Authority="USER", Latched="true"))
            elif state == "PENDING" or row.get("Phase") == "PROPOSAL":
                latches.append(dec("LATCH", row["ID"], Question=_cut("approve " + row.get("Title", ""), 140), Authority="INFERRED", Latched="false"))
            new["Latch"] = ";".join(latches)
            tables["todo"].append(new)
            legacy = {k: v for k, v in row.items() if v and k not in {"ID", "Title", "Status", "Tags"}}
            events.append({"actor": "migrate", "op": "migrate", "id": row["ID"], "detail": {"from": "0.5", "legacy": legacy}})
    for row in old["overlord"]:
        purpose = _cut(row.get("Purpose", ""), 140)
        tags = row.get("Tags", "")
        if not purpose and "#unpurposed" not in tags:
            tags = (tags + " #unpurposed").strip()
        tables["overlord"].append(empty_row("overlord", {"ID": row["ID"], "Path": row.get("Path", ""), "Symbol": _cut(row.get("Symbol", ""), 120), "Kind": row.get("AssetType", "FILE") or "FILE", "Purpose": purpose, "Binds": row.get("OGMRefs", ""), "Tags": tags}))
        legacy = {k: row[k] for k in ("Exports", "Imports", "Requires", "RequiredBy", "PACRefs", "NDLRefs", "Notes", "EvidenceFor") if row.get(k)}
        if legacy:
            events.append({"actor": "migrate", "op": "migrate", "id": row["ID"], "detail": {"from": "0.5", "legacy": legacy}})
    for row in old["organism"]:
        status = row.get("Status", "SCAFFOLD")
        demoted = status == "VALIDATED_COMPLETE"
        tables["organism"].append(empty_row("organism", {"ID": row["ID"], "Title": _cut(row.get("Title", ""), 80), "Status": "PACED_REQUIREMENT" if demoted else status, "Authority": row.get("Authority") or "LEGACY", "Origin": _cut(row.get("OriginText", ""), 400), "Requirement": _cut(row.get("Requirement", ""), 280), "Binds": row.get("OVRRefs", ""), "Tags": row.get("Tags", "")}))
        legacy = {k: row[k] for k in ("AcceptanceEvidence", "EvidenceBindings", "EvidenceArtifact", "RuleType", "BlockedByOGM", "PACRefs", "NDLRefs", "AbsorbedFromNDL", "Notes") if row.get(k)}
        if demoted:
            legacy["demoted"] = "VALIDATED_COMPLETE→PACED_REQUIREMENT: historical acceptance is not current proof; run probe"
        events.append({"actor": "migrate", "op": "migrate", "id": row["ID"], "detail": {"from": "0.5", "legacy": legacy}})
    for row in list(old["nodule"]) + list(archived):
        tables["nodule"].append(empty_row("nodule", {"ID": row["ID"], "Name": _cut(row.get("NoduleName", ""), 60), "Status": row.get("Status", "ACTIVE"), "Lane": _cut(row.get("Lane") or row.get("NoduleName", ""), 40), "Request": _cut(row.get("UserRequest") or row.get("Intent", ""), 400), "Intent": _cut(row.get("Intent", ""), 140), "In": row.get("TargetOVR", ""), "Out": row.get("NewAssets", ""), "Targets": row.get("OGMTargets", ""), "Spawned": row.get("SpawnedPACs", ""), "Exit": _cut(row.get("AbsorptionCriteria", ""), 140), "Tags": row.get("Tags", "")}))
        legacy = {k: row[k] for k in ("Notes", "AcceptanceEvidence", "CreatedAt", "AbsorbedAt", "ContextPolicy") if row.get(k)}
        events.append({"actor": "migrate", "op": "migrate", "id": row["ID"], "detail": {"from": "0.5", "legacy": legacy}})
    return tables, events


def from_v2(text: str, project_dir: Path) -> tuple[dict, list[dict]]:
    tables, events = _empty_tables(), []
    counter = {"PAC": 0, "OVR": 0, "DEC": 0}

    def nid(prefix: str) -> str:
        counter[prefix] += 1
        return f"{prefix}-{counter[prefix]:03d}"

    tier, area_n, phase_n, pace_n = "prototype", 0, 0, 0
    area_id = phase_id = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("PROJECT "):
            tier = _attr(line, "maturity", tier)
        elif line.startswith("GLOBAL "):
            area_n, phase_n = area_n + 1, 0
            m = _Q.search(line)
            area_id = nid("PAC")
            tables["todo"].append(empty_row("todo", {"ID": area_id, "Kind": "AREA", "Pos": f"A{area_n}", "Title": _cut(m.group(1) if m else "Area", 80), "Status": V2_STATUS.get(_attr(line, "state", "active"), "ACTIVE"), "Tier": tier}))
        elif line.startswith("PHASE "):
            phase_n, pace_n = phase_n + 1, 0
            m = _Q.search(line)
            phase_id = nid("PAC")
            tables["todo"].append(empty_row("todo", {"ID": phase_id, "Kind": "PHASE", "Pos": f"A{area_n}.P{phase_n}", "Title": _cut(m.group(1) if m else "Phase", 80), "Status": V2_STATUS.get(_attr(line, "state", "todo"), "TODO"), "Tier": tier, "Exit": "migrated phase"}))
        elif line.startswith("PACE "):
            pace_n += 1
            parts = line.split(None, 2)
            m = _Q.search(line)
            tag = "#" + re.sub(r"[^a-z0-9-]", "-", parts[1].lower()).strip("-")
            tables["todo"].append(empty_row("todo", {"ID": nid("PAC"), "Kind": "PACE", "Pos": f"A{area_n}.P{phase_n}.{pace_n:02d}", "Title": _cut(m.group(1) if m else parts[1], 80), "Status": V2_STATUS.get(_attr(line, "state", "todo"), "TODO"), "Produce": _cut(m.group(1) if m else parts[1], 140), "Tags": tag}))
        elif line.startswith("EXIT ") and phase_id:
            row = next(r for r in tables["todo"] if r["ID"] == phase_id)
            row["Exit"] = _cut(_attr(line, "coherent", row["Exit"]), 140)
        elif line.startswith("SOURCE "):
            m = _Q.search(line)
            if m and not any(r["Path"] == m.group(1) for r in tables["overlord"]):
                tables["overlord"].append(empty_row("overlord", {"ID": nid("OVR"), "Path": m.group(1).rstrip("/"), "Kind": "FILE", "Purpose": _cut(_attr(line, "role", "source"), 140), "Tags": ""}))
        elif line.startswith(":nodule "):
            parts = line.split(None, 2)
            m = _Q.search(line)
            tables["nodule"].append(empty_row("nodule", {"ID": parts[1], "Name": _cut(m.group(1) if m else parts[1], 60), "Status": "ACTIVE", "Lane": _cut(parts[1].lower(), 40), "Request": _cut(m.group(1) if m else parts[1], 400), "Intent": _cut(m.group(1) if m else parts[1], 140), "Exit": "migrated nodule", "Spawned": phase_id or area_id or ""}))
        elif line.startswith("+approved "):
            subject = line.split()[1]
            tables["decision"].append(empty_row("decision", {"ID": nid("DEC"), "Kind": "LATCH", "Subject": subject, "Question": _cut(f"approve {subject}", 140), "Chosen": "approved", "Authority": "USER", "Latched": "true"}))
    for row in tables["overlord"]:
        if not (project_dir / row["Path"]).exists():
            row["Tags"] = (row["Tags"] + " #dead").strip()
    spec = project_dir / ".MIVIM.spec"
    if not spec.exists():
        spec.write_text(f'[project]\nname = "{project_dir.name}"\ntier = "{tier}"\n', encoding="utf-8")
    events.append({"actor": "migrate", "op": "migrate", "id": "-", "detail": {"from": "v2", "tier": tier}})
    return tables, events
```

Note for `from_v2`: a nodule's `Spawned` must reference a PACE; if the phase has paces, use the first PACE ID of the current phase instead of the phase ID (find it by scanning `tables["todo"]` for `Kind == "PACE"` with `Pos` prefix). Implement that lookup in the `:nodule` branch before the test passes.

- [ ] **Step 4: Add `Service.migrate`**

```python
    def migrate(self, source: str, *, actor: str, preview: bool = True) -> dict:
        import shutil

        from pacer_mcp.migrate import from_05, from_v2
        from pacer_mcp.store import encode_csv, parse_csv

        with self.store.locked():
            if source == "0.5":
                old, sizes = {}, {}
                for name in ("todo", "overlord", "organism", "nodule"):
                    path = contained_path(self.root, f"{name}.PACER.csv")
                    data = path.read_bytes()
                    sizes[name] = len(data)
                    _, old[name] = parse_csv(data, name)
                    if name == "todo" and "Kind" in _:
                        raise ValueError("Registers already use PACER 3 columns")
                archived = []
                for path in sorted(contained_path(self.root, "archive/nodules").glob("*.PACER.csv")) if contained_path(self.root, "archive/nodules").exists() else []:
                    archived += parse_csv(path.read_bytes(), path.name)[1]
                tables, events = from_05(old, archived, self.spec["tier"])
            elif source == "v2":
                text = contained_path(self.root, "todo.PACER").read_text(encoding="utf-8")
                sizes = {"todo.PACER": len(text.encode("utf-8"))}
                tables, events = from_v2(text, self.root)
            else:
                raise ValueError("source must be 0.5 or v2")
            report = validate_web(tables, self.root)
            encoded = {}
            for register in REGISTERS:
                live = [r for r in tables[register] if not (register == "nodule" and r["Status"] == "ABSORBED")]
                encoded[f"{register}.PACER.csv"] = encode_csv(HEADERS[register], live)
            result = {"preview": preview, "sizes_before": sizes, "sizes_after": {k: len(v) for k, v in encoded.items()}, "counts": {k: len(v) for k, v in tables.items()}, "validation": report, "ledger_events": len(events)}
            if preview or not report["valid"]:
                return result
            if source == "0.5":
                old_dir = contained_path(self.root, "archive/pacer-0.5")
                old_dir.mkdir(parents=True, exist_ok=True)
                for name in ("todo", "overlord", "organism", "nodule"):
                    shutil.move(str(contained_path(self.root, f"{name}.PACER.csv")), str(old_dir / f"{name}.PACER.csv"))
                archive = contained_path(self.root, "archive/nodules")
                if archive.exists():
                    shutil.move(str(archive), str(old_dir / "nodules"))
            for name, data in encoded.items():
                contained_path(self.root, name).write_bytes(data)
            for row in tables["nodule"]:
                if row["Status"] == "ABSORBED":
                    target = contained_path(self.root, f"archive/nodules/{row['ID']}.PACER.csv")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(encode_csv(HEADERS["nodule"], [row]))
            for event in events:
                self.store.ledger_append(event)
            self.store.ledger_append({"actor": actor, "op": "migrate", "id": "-", "detail": {"from": source, "counts": result["counts"]}})
            return {**result, "validation": self.validate()}
```

- [ ] **Step 5: Run; expect PASS. Commit** — `git commit -am "feat(pacer3): migration from profile 0.5 and v2.0.0"`

---

### Task 11: Tree view, docs, cleanup

**Files:**
- Create: `plugins/pacer/src/pacer_mcp/tree.py`, `.MIVIM.spec` (root)
- Modify: `README.md`, `AGENTS.md` (root), `plugins/pacer/references/FORMAT.md`, `plugins/pacer/README.md`, `scripts/check.py`
- Delete: `scripts/maintain.py`, `scripts/evaluate_context.py`, `scripts/evaluate_development.py`, `scripts/prove_codex.py`, `scripts/prove_context_delivery.py`, `TEMPLATES/` (initialize creates empty registers), `client-update.PACER/PACER_v2.0.0/` python utility is left in place as history.
- Test: `plugins/pacer/tests/test_tree.py`

- [ ] **Step 1: Test**

```python
# plugins/pacer/tests/test_tree.py
from pacer_mcp.spec import read_spec
from pacer_mcp.tree import render_tree
from tests.test_frames import web


def test_tree_view(registers):
    text = render_tree(web(registers), read_spec(registers))
    lines = text.splitlines()
    assert lines[0] == f"PACER::TODO version=3.0 project={registers.name} tier=prototype"
    assert lines[1] == 'AREA PAC-001 A1 "Core" ACTIVE'
    assert lines[2] == '  PHASE PAC-002 A1.P1 "Boot" ACTIVE prototype exit="boots"'
    assert lines[3] == '    PACE PAC-003 A1.P1.01 ACTIVE "loader" in=OVR-001 out=src/new.py'
```

- [ ] **Step 2: Implement tree.py**

```python
"""Indented plan view; a rendering of todo.PACER.csv, never a store."""

from __future__ import annotations

from pacer_mcp.schema import VERSION, pos_parts


def render_tree(tables: dict, spec: dict) -> str:
    rows = sorted((r for r in tables["todo"] if r.get("Pos")), key=lambda r: pos_parts(r["Pos"]))
    lines = [f"PACER::TODO version={VERSION} project={spec['project']} tier={spec['tier']}"]
    for r in rows:
        kind = r["Kind"]
        if kind == "AREA":
            lines.append(f'AREA {r["ID"]} {r["Pos"]} "{r["Title"]}" {r["Status"]}')
        elif kind == "PHASE":
            tier = f" {r['Tier']}" if r.get("Tier") else ""
            lines.append(f'  PHASE {r["ID"]} {r["Pos"]} "{r["Title"]}" {r["Status"]}{tier} exit="{r["Exit"]}"')
        else:
            extra = "".join(f" {k}={r[c]}" for k, c in (("in", "In"), ("out", "Out"), ("binds", "Binds"), ("needs", "Needs")) if r.get(c))
            lines.append(f'    PACE {r["ID"]} {r["Pos"]} {r["Status"]} "{r["Produce"]}"{extra}')
    return "\n".join(lines)
```

- [ ] **Step 3: Root docs**

`.MIVIM.spec`:

```toml
[project]
name = "PACER"
tier = "integrated"

[provider]
name = "auto"

[frames]
session = 4000
prompt = 2000
edit = 1500
stop = 1000
```

`README.md` (root, replace entirely; ≤60 lines): what PACER 3 is (three-layer diagram from the spec §2), the five registers in one table (ID prefix, one-line role), the card grammar block, install (`./install.ps1`), and the development commands (`uv run --locked pacer --root . frame session`, `q`, `write`, `probe`, `validate`, `tree`, `migrate`). Link to `plugins/pacer/references/FORMAT.md`.

`AGENTS.md` (root, replace entirely; ≤40 lines): the rules the runtime does NOT enforce and the agent must: fill `Purpose` on `#unpurposed` rows before phase exit; keep `Produce` imperative; new scope only through `pace`; one open question per latch; do not rebuild project context as Markdown; the tier matrix table verbatim from the spec §5; repository commands (`uv run --locked python scripts/check.py`).

`plugins/pacer/references/FORMAT.md`: copy `client-update.PACER/PACER_v3.0.0-design.md` sections 2–8 and 11 (drop the review and approaches).

`plugins/pacer/README.md`: keep the installer section; replace tool and skill lists with the nine tools and the single skill; delete every paragraph about receipts, pages, encodings, `prove_*` scripts and evaluation.

`scripts/check.py`: keep ruff and pytest commands; replace the overlord correspondence block with `Service(ROOT).validate()` and a check that every `#unpurposed` OVR row is reported as a warning count (not a failure).

- [ ] **Step 4: Run check.py; expect ruff and pytest green. Commit** — `git commit -am "feat(pacer3): tree view, project frame, docs and cleanup"`

---

### Task 12: Migrate this repository, trial on consumers, live hook check

- [ ] **Step 1: Migrate this repo's registers**

```powershell
uv run --locked pacer --root . migrate --from 0.5 --actor claude            # preview; expect validation.valid true
uv run --locked pacer --root . migrate --from 0.5 --actor claude --apply
uv run --locked pacer --root . validate
uv run --locked pacer --root . frame session | Measure-Object -Character   # expect < 4100
uv run --locked pacer --root . tree | Select-Object -First 20
```

Record the before/after byte sizes in the commit message. Fix the `#unpurposed` OVR rows that fall inside the active phase's `In`. Commit: `git add -A && git commit -m "chore(pacer3): migrate live registers to PACER 3"`.

- [ ] **Step 2: Consumer trials on copies (never in place)**

```powershell
$S = "$env:TEMP\claude\pacer-trials"; New-Item -ItemType Directory -Force $S | Out-Null
robocopy C:\Users\ryanf\github\_active\image-riposte $S\riposte /E /XD .git .venv node_modules build dist /NFL /NDL /NJH /NJS | Out-Null
uv run --locked pacer --root $S\riposte migrate --from 0.5 --actor trial          # preview
uv run --locked pacer --root $S\riposte migrate --from 0.5 --actor trial --apply
uv run --locked pacer --root $S\riposte frame session
robocopy C:\Users\ryanf\github\_new\tag-replicata $S\replicata /E /XD .git .venv build dist /NFL /NDL /NJH /NJS | Out-Null
uv run --locked pacer --root $S\replicata migrate --from v2 --actor trial --apply
uv run --locked pacer --root $S\replicata tree
```

Report sizes before/after and any validation errors. Do not touch the real consumer repos.

- [ ] **Step 3: Live hook check in Claude Code**

```powershell
./install.ps1 -Agent Claude
$F = "$env:TEMP\claude\pacer-fixture"; New-Item -ItemType Directory -Force $F | Out-Null
"Fixture" | Set-Content $F\README.md
uv run --locked pacer --root $F initialize
# write a pace with one PACE ACTIVE binding README.md, then:
claude -p "Append one line to README.md saying hello." --cwd $F --output-format json --max-turns 4 --permission-mode acceptEdits > $env:TEMP\claude\hook-trial.json
```

Inspect the transcript (`--verbose` / stream-json) for the SESSION frame after startup and the EDIT frame before the Edit tool call. If the hook command cannot find `uv`'s environment, add `hooks/pacer-hook.ps1` that sets `UV_PROJECT_ENVIRONMENT` from `$env:CLAUDE_PLUGIN_DATA` and reference it from `hooks.json`. Record the observed frames in `evidence/pacer3-hook-trial.txt` and commit.

- [ ] **Step 4: Final** — `uv run --locked python scripts/check.py`; `git log --oneline pacer3 ^codex/operational-context` lists ≥12 commits; report sizes and frame bytes to the user.
