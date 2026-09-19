# PACER v2.0.0 — Agent Continuity Framework

PACER is a compact project-development syntax and context-routing system for agents. It exists to help an agent **keep developing coherently**, not to force every small implementation through a user approval ceremony.

v2 is a breaking operational correction: PACER changes from a micro-task gate machine into a **modulated continuity system**.

## Core doctrine

- Global project context is retained in `.MIVIM.spec` and OVERLORD state.
- `todo.PACER` expresses integrated development phases and their paces.
- A pace is not a mandatory user checkpoint.
- The agent continues through related paces until a coherent operational state is reached or a true authority blocker exists.
- Testing, research, documentation, sub-agents, and local experiments are agent tools inside the loop—not reasons to hand trivial work back to the user.
- User approval/skip is latched. Do not re-ask unless the approved object or its governing assumptions materially change.
- Guardrails tighten with maturity. Prototype work is autonomous; release/protected content can carry strict gates.

## The compression model

Avoid this:

```text
1:1:1:1:1:1:1:1:1:1
1:1:1:1:1:1:1:1:1:1
...
```

Prefer modulated global work:

```text
50[10]X[5]:(1:1:1:1:1:1:1:1:1:1)
```

The exact numbers are a planning descriptor, not a second task database. The point is that the agent receives the same task information **inside a global structure**: development area → phase → pace → source/context → loop.

## Package map

- `AGENT_START.md` — zero-memory agent entry point.
- `PREPROMPT.txt` — short operational reminder.
- `.MIVIM.spec` — package/project authority and global context.
- `todo.PACER` — canonical development flow.
- `rules.overlord.rs` — parent workflow semantics.
- `map.overlord.toml` — file-role and authority map.
- `task.overlord.md` — OVERLORD task counterpart.
- `grammar/` — compact syntax grammar.
- `contract/` — behavioral contract.
- `api/` — command/API semantics.
- `commands/commands.jsonl` — machine-readable command vocabulary.
- `machine/` — JSON authority model plus YAML mirror.
- `schema/` — JSON schema for machine representation.
- `docs/` — doctrine and operating guides.
- `templates/` — clean project bootstrap files.
- `examples/` — anti-pattern, corrected pattern, and REPLICATA M01–M18 mapping.
- `pacer/` — zero-dependency parser/auditor/theatre compiler.

## Quick start

```bash
python -m pacer audit todo.PACER
python -m pacer theatre todo.PACER
python -m pacer theatre todo.PACER --phase P05
```

`audit` reports continuity problems; it does **not** block development. A warning is advisory unless the project itself marks the condition as a true authority gate.

## Operating loop

```text
ORIENT → BUILD → INTEGRATE → SELF-CHECK → ABSORB → :loop⠁: → CONTINUE
                                      ↘ USER only for true authority blockers
```

See `docs/OPERATING_GUIDE.md` and `docs/GUARDRAIL_DOCTRINE.md`.
