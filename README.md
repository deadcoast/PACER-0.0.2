# PACER 3 — delivered context

PACER is the project's knowledge substrate for coding agents. It does not ask the agent to onboard, fetch, or operate a database. The harness delivers the relevant slice of project state as fixed-grammar cards at the moments that matter: session start, after compaction, before and after every edit, and when the agent tries to stop.

```
registers   five CSV files, current state only, bounded cells   +  ledger.PACER.jsonl (append-only history)
compiler    pacer frame <session|edit|prompt|stop>   ranks rows by typed-edge distance, fills a byte budget
adapters    hooks/hooks.json for Claude Code and Codex; MCP tools for explicit query and write
```

## Registers

| File | Prefix | One row per | Carries |
|---|---|---|---|
| `todo.PACER.csv` | PAC | AREA, PHASE or PACE | position `A1.P2.03`, status, tier, Produce, In/Out assets, Binds, Needs, Probe, Exit, Next, Latch |
| `overlord.PACER.csv` | OVR | source asset | path, symbol, kind, Purpose, tier, Binds, Latch. Imports and dependents are derived from code, never stored |
| `organism.PACER.csv` | OGM | requirement | status, authority, literal Origin, Requirement, Binds, Probe command, one-cell Evidence, tier |
| `nodule.PACER.csv` | NDL | scoped intake | lane, literal Request, Intent, In/Out, Targets, Spawned, Exit |
| `decision.PACER.csv` | DEC | choice, latch, lesson or failed approach | Subject, Question, Chosen, Rejected, Why, authority, Latched |

Statuses: PAC `TODO ACTIVE INTEGRATED DONE`; OGM `SCAFFOLD PACED_REQUIREMENT VALIDATED_COMPLETE`; NDL `ACTIVE ABSORBED`. Tiers: `sketch prototype playable integrated release protected`.

## Cards

```
PAC PAC-041 A2.P3.05 ACTIVE prototype | Produce: … | In: OVR-012 | Out: src/x.py:Foo | Binds: OGM-004 | Probe: pytest -q | Next: implement
OVR OVR-012 src/a.py:S integrated | Purpose: … | Binds: OGM-004 | Latch: DEC-003 | used-by: src/main.py (+3)
OGM OGM-004 PACED_REQUIREMENT USER release | Requirement: … | Probe: pytest -q | Evidence: rev:a1b2c3d exit:0 at:2026-09-20 STALE(src/a.py)
DEC DEC-003 LATCH USER latched | Subject: OVR-012 | Chosen: keep sync API | Why: …
NDL NDL-019 ACTIVE lane=auth | Intent: … | Targets: OGM-004 | Spawned: PAC-040;PAC-041 | Exit: …
```

One grammar everywhere: frames, query results, MCP tool output. Evidence is a probe run (`rev src exit out at`); staleness is computed from the bound files, so an uncommitted edit counts.

## Install and use

```powershell
./install.ps1                                   # installs the plugin into Claude Code and Codex
uv run --locked pacer --root . frame session    # what a session receives
uv run --locked pacer --root . q OGM-004        # cards for an ID, path, #tag, register or register:STATUS
uv run --locked pacer --root . write --file ops.json --actor me
uv run --locked pacer --root . probe OGM-004
uv run --locked pacer --root . validate
uv run --locked pacer --root . tree             # indented plan view
uv run --locked pacer --root . migrate --from 0.5 [--apply]   # or --from v2
uv run --locked python scripts/check.py         # ruff, pytest, validation
```

`.MIVIM.spec` at the project root sets the project name, default tier, structure provider and frame budgets. The format, ranking, gate matrix and migration are specified in [plugins/pacer/references/FORMAT.md](plugins/pacer/references/FORMAT.md). Operating rules for agents are in [AGENTS.md](AGENTS.md). Development history of this repository lives in `ledger.PACER.jsonl` and git.
