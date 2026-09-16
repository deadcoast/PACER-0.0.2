# AGENTS.md — Operating Inside a PACER Repository

Binding rules. If a rule here conflicts with your inclination, the rule wins. If a rule conflicts with the user's explicit instruction, the user wins — log the exception as a Note on the affected row.

## 0. Session start protocol

1. Read `README.md` (what PACER is), then this file.
2. Query state — do not read files whole. Standard opening queries:
   - Ready work: todo rows with `Status=TODO` and all hard `BlockedBy` DONE.
   - Health map: organism rows by status (`SCAFFOLD` / `PACED_REQUIREMENT` counts).
   - Active growth: nodule rows with `Status=ACTIVE`.
3. Before touching any source file, query overlord for its row(s) by `Path`. If none exists, the file is off-register: create the OVR row as part of your change, or refuse the change and flag it.

## 1. File roles and write rights

| File | You may | You may never |
|---|---|---|
| `todo.PACER.csv` | Add PACs; transition status; append Notes/LearningNotes/PreviousAttempts; set fields per lexicon | Delete rows; weaken a DoD to force a DONE; renumber IDs |
| `overlord.PACER.csv` | Add/update rows for assets you touch, same commit as the code change | Let it drift from source reality; delete rows for deleted code (mark `Tags` `#dead` + Note, prune only at milestone audits) |
| `organism.PACER.csv` | Advance statuses with evidence; add rows via nodule absorption; update refs | Set `VALIDATED_COMPLETE` without `AcceptanceEvidence`; delete requirements |
| `nodule.PACER.csv` | Create when pacing a user request; update status; absorb | Run two ACTIVE nodules in one lane; delete an unabsorbed nodule |

One canonical copy of each register. Atomic writes (write temp, validate, move). Multi-agent mutation goes through the command lexicon with a single applying writer; filtered views are read-only handouts.

## 2. Todo lifecycle (unchanged PACER core)

- Transitions: `TODO→DOING`, `DOING→REVIEW`, `DOING→TODO`, `REVIEW→DONE`, `REVIEW→DOING`. Nothing else.
- `StartedAt` on entering DOING, `DoneAt` on entering DONE (UTC ISO 8601).
- Dependency gate: DONE only if every **hard** `BlockedBy` is DONE. Soft/optional never gate.
- ≤3 rows in DOING per agent. >48h in DOING → split (`PAC-123A/B`) with narrower DoDs; parent blocks on children.
- Every significant change: one-line Note. Every completed task that taught you something: LearningNotes. Every failed approach: PreviousAttempts — the next agent must not repeat you.

## 3. Overlord discipline (the map must match the territory)

- Code change and OVR update are **one commit**. A merged change with a stale overlord is a defect.
- Row granularity: FILE always; MODULE/CLASS/FUNCTION/METHOD rows for anything exported, imported across files, or referenced by an OGM requirement. Internal helpers do not get rows.
- `Requires`/`RequiredBy` are OVR-to-OVR edges and must be symmetric: if OVR-003 Requires OVR-002, OVR-002 lists OVR-003 in RequiredBy. Asymmetry fails validation.
- `Exports`/`Imports` are the literal symbols/paths — this is what lets an agent answer "what breaks if I change this signature" from three greps.

## 4. Organism discipline (design truth with statuses)

- Statuses: `VALIDATED_COMPLETE` | `PACED_REQUIREMENT` | `SCAFFOLD` — exactly one, definitions per README.
- `SCAFFOLD → PACED_REQUIREMENT`: the moment the incompleteness is *because of* an unbuilt reference — record what blocks it (`BlockedByOGM`, `PACRefs`).
- `→ VALIDATED_COMPLETE`: requires `AcceptanceEvidence` (test run, audit, dated verification). No evidence, no status.
- Regression rule: if landed code breaks a VALIDATED_COMPLETE requirement, demote it immediately with a Note naming the offending commit/PAC. The organism never flatters the codebase.
- The organism is also the changelog: status transitions + Notes + `UpdatedAt` ARE the project history. Do not create a separate changelog.

## 5. Nodule protocol (the only door for new scope)

1. **Pace it out.** User request → one nodule row: `Intent`, `TargetOVR` (existing assets touched), `NewAssets` (paths/symbols to create), `OGMTargets` (requirements added or advanced), `AbsorptionCriteria`.
2. **Spawn.** Create the nodule's PACs in the todo (`NDLRefs`/`RelatedWork` link back). Status → `ACTIVE`.
3. **Build** under todo rules; overlord updates ride each commit.
4. **Absorb** when criteria are met: advance the OGM targets, verify every new asset has an OVR row, verify all cross-refs resolve, set `AbsorbedAt`, status → `ABSORBED`, move the file to `archive/` (or delete if the project archives via VCS history). The lane is now clear for the next nodule.
- One ACTIVE nodule per lane. Parallel lanes are allowed only when their `TargetOVR` sets are disjoint.
- Scope discovered mid-build that exceeds the nodule's Intent: new nodule. Never silently grow an active one.

## 6. Referencing rules

- IDs immutable, never reused. Multi-refs semicolon-separated. Tags `#lowercase`, shared vocabulary across all four files — check existing tags before minting a new one.
- Every reference must resolve to a live row. Broken refs are validation failures, fixed before commit.
- When you add any row, wire it both ways: the things it references gain back-references where a back-reference column exists.

## 7. Validation (run before every commit that touches a register)

- CSV parses; required columns present; no duplicate IDs.
- Todo: legal statuses/transitions, dependency refs exist, no cycles, no DONE with open hard blockers.
- Overlord: `Requires`/`RequiredBy` symmetry; paths exist in the repo (or `#dead`-tagged).
- Organism: valid status; VALIDATED_COMPLETE rows have evidence.
- Nodule: ACTIVE nodules have ≥1 spawned PAC; ABSORBED nodules have `AbsorbedAt` and satisfied criteria.
- Cross-file: every `PAC-`/`OVR-`/`OGM-`/`NDL-` reference resolves.

## 8. Refusals (respond with the literal string, then stop)

- `REFUSAL: Blocked by {ids}` — DONE attempted with open hard blockers.
- `REFUSAL: Illegal transition {from}->{to}`.
- `REFUSAL: Unknown ID {id}`.
- `REFUSAL: Circular dependency detected`.
- `REFUSAL: Evidence required` — VALIDATED_COMPLETE without AcceptanceEvidence.
- `REFUSAL: Off-register asset` — source change requested for a path with no OVR row and no permission to create one.
- `REFUSAL: Nodule lane occupied` — second ACTIVE nodule on overlapping TargetOVR.

## 9. Prime directives

1. The registers are the single source of truth. If code and register disagree, stopping to reconcile IS the work.
2. Query, don't read. Load rows, not files. Follow references only as deep as the task requires.
3. Leave the web stronger: every touch adds references, evidence, or learning — never orphans.
4. Everything connects. Everything works together or it dies.

## 10. Executable profile and this repository

Use `plugins/pacer/references/FORMAT.md` for profile 0.5's additive columns and
command lexicon. These clarify the original format while retaining its purposes:

- New OGM targets enter at pace time with `NDLRefs` so forward references resolve;
  `AbsorbedFromNDL` is added only after verified absorption.
- A nodule's sole canonical row moves to `archive/nodules/<ID>.PACER.csv` when
  absorbed. Root nodule keeps active rows and its header. Archive rows remain
  resolvable, and IDs are never reused. Historical acceptance permits later
  truthful organism regression; absorption criteria are checked at transition.
- Admitted scope and original DoDs cannot be removed or weakened through generic
  updates. Append new assets within Intent; pace distinct scope separately.
- All CLI/MCP writes use the shared applying writer, current revision and current
  authority digest. Readers refuse a pending transaction until explicit recovery.
  No conflicting external changes may be overwritten by recovery.
- New operational nodules preserve `UserRequest` and use `ContextPolicy=REQUIRED`.
  Pace alone, then use `pacer_context` for the task. Its typed rows and rules are
  the primary working representation. A budget refusal never omits required rows.
- Preserve user wording in `OriginText`; distinguish USER, OBSERVED, INFERRED,
  UNRESOLVED and LEGACY authority. Use the executable rule vocabulary from schema.
  Migration never invents rules or changes historical acceptance into current proof.
- After changes, retrieve fresh context and `refresh` as a separate batch. Source
  drift requires renewed verification; demonstrated failure requires demotion.
  Use `verify` for operational acceptance and `checkpoint` for durable next actions.
- Proposals awaiting a user decision use `Phase=PROPOSAL` or `ApprovalState=PENDING`.
  Record existing user authorization with `approval`; then admit the same IDs through
  nodule `SpawnedPACs`. Preserve the wording and approval history. Do not request
  authorization again when the user already granted it. LEGACY is compatibility,
  not proof of consent. Apply the format's approval and split rules.
- Compact context edges index `required_ids` and `relations.kinds`; consult schema
  or request `encoding=expanded` if needed. Required closure and receipts are identical.
- For bounded delivery, use `pacer_context_page` and read every page in order with
  unchanged `max_bytes`. Restart with an empty cursor after source or context drift.
  Only the final page carries a receipt; it proves freshness, not reading or
  comprehension. Resolve missing sources or packet-limit failures before acting.

The root `pyproject.toml` defines the uv workspace and development dependencies;
`plugins/pacer/pyproject.toml` defines the installable runtime package. Repository
commands share root `.venv` and `uv.lock`, including `--project plugins/pacer`.
Use uv and existing Python; do not install through pip or recreate a member `.venv`.
Run `uv run --project plugins/pacer --locked python scripts/check.py` before commits.
Keep the root and plugin default `dev` groups aligned; uv selects groups per project.
Build with `uv build --package pacer-mcp`. The plugin's `uv.lock` is
for copies installed outside the workspace; regenerate it from a standalone copy
when runtime dependencies change, alongside the root workspace lock.
`scripts/maintain.py --task <PAC> --nodule <NDL> [--paths <changed-paths>]`
previews the admitted source index; add `--apply` to publish. It
never advances acceptance. Query an OVR path before source edits and include
the matching register changes in the same commit. The evidence report is a test
artifact; the organism remains the design history and changelog.
