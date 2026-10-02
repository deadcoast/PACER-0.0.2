---
name: pacer
description: PACER card grammar and write operations. Use when a PACER frame or card (PAC, OVR, OGM, DEC, NDL) is in context, when a project has a .pacer/ directory, or when pacing new scope, recording a decision, proving a requirement, or archiving finished work.
---

Frames arrive by hook at session start, before and after edits, and at stop. Nothing is fetched to begin. Every line is one card:

    PAC PAC-041 A2.P3.05 ACTIVE prototype | Produce: … | In: OVR-012 | Out: src/x.py:Foo | Binds: OGM-004 | Probe: … | Next: implement
    OVR OVR-012 src/a.py:S integrated | Purpose: … | bound-by: OGM-004 | latch: DEC-003 | used-by: src/main.py (+3)
    OGM OGM-004 PACED_REQUIREMENT USER release | Requirement: … | Probe: pytest -q | Evidence: rev:a1b2c3d exit:0 at:2026-09-20 STALE(src/a.py)
    DEC DEC-003 LATCH USER latched | Subject: OVR-012 | Chosen: … | Why: …
    NDL NDL-019 ACTIVE lane=auth | Intent: … | Targets: OGM-004 | Spawned: PAC-040;PAC-041 | Exit: …

Head tokens are positional: PAC `Pos Status Tier`; OVR `path[:symbol] Tier`; OGM `Status Authority Tier`; DEC `Kind Authority latched|open`; NDL `Status lane=`. `Capitalised:` fields are stored cells. `lowercase:` fields are derived when the card is rendered and cannot be written. Bare trailing words are flags: `OFF-PACE` (the path is outside the active pace's In/Out), `missing` (the asset's file is gone), `archived`.

## Read

`pacer_q(root, query)` returns cards. `query` is an ID (with its neighbours within distance 2), a project path, a `#tag`, a register name (`todo overlord organism nodule decision`), or `register:STATUS`.

## Write

`pacer_write(root, operations, actor)` applies a batch atomically; all succeed or none do.

| op | fields | effect |
|---|---|---|
| `add` | `register`, `row` | new row; `ID` assigned when omitted |
| `set` | `id`, `fields` | change cells; not ID, Kind, Status, Pos, Path, Evidence, Latched |
| `link` | `id`, `field`, `target`, `remove?` | add or drop one reference |
| `move` | `id`, `pos` | re-position a PAC row (`A1`, `A1.P2`, `A1.P2.03`) |
| `status` | `id`, `status` | PAC `TODO ACTIVE INTEGRATED DONE`; OGM `SCAFFOLD PACED_REQUIREMENT VALIDATED_COMPLETE` |
| `latch` | `id`, `latched`, `evidence?` | record the user's answer on a DEC LATCH |
| `pace` | `nodule`, `tasks`, `requirements`, `decisions` | admit new scope in one batch |
| `absorb` | `id` | close a nodule whose exit holds |
| `archive` | `ids`, `cascade?` | retire finished rows from the live registers |
| `repath` | `from`, `to` | follow a moved file, or a directory when both end in `/` |

`pacer_probe(root, id, actor)` runs a requirement's `Probe` and writes its `Evidence`. `VALIDATED_COMPLETE` needs `exit:0` and CURRENT evidence; editing a bound file makes it STALE.

## Operate

- Continue through paces. Tests, research, tuning and refactors are yours to resolve.
- A `DEC … LATCH … open` card is the one reason to ask the user. Ask once, then record the answer with `latch`.
- New scope enters through `pace`: the nodule carries the user's literal `Request`; each PACE carries an imperative `Produce`.
- Record a choice, a failed approach or a lesson as a DEC bound to its `Subject`. It is delivered again whenever that subject is in frame.
- `OFF-PACE` means decide: pace the path into the active work, or leave it.
- Give every `#unpurposed` asset a one-line `Purpose` before its phase exits.
- When a phase is finished, `archive` it. Live registers hold current work; history stays queryable by ID.

Tiers: `sketch`, `prototype` and `playable` never block. `integrated` blocks a stop on a FAILED probe. `release` blocks on FAILED or STALE. `protected` denies edits without a USER latch.

Columns, limits, validation rules, frame composition and migration: `references/format.md`.
