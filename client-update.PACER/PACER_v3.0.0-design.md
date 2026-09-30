# PACER 3 — delivered context

Date: 2026-09-29. Status: DESIGN, awaiting approval. Supersedes profile 0.5 (`plugins/pacer`) and v2.0.0 (`client-update.PACER/PACER_v2.0.0`).

Thesis: the unit of PACER is not a row the agent reads. It is a card the harness delivers. PACER stops being a database the agent operates and becomes a context compiler wired into the agent's lifecycle events. Storage is reshaped so compiled cards are small, positional and dense. Writes are side effects of tool events, not ceremony.

## 1. Review of the two lineages

Measured on this repository's live registers, 2026-09-29.

| # | Finding | Evidence |
|---|---|---|
| D1 | Context packet is the whole project | `pacer context PAC-036`: 457 rows, 207,370 B compact, 477,959 B pretty. Default budget 32,000 B refuses outright. `required_closure` follows `RequiredBy` reverse-impact transitively and every OGM's `OVRRefs`; OGM-008 alone links 200+ OVRs |
| D2 | Runtime writes its own bloat into the knowledge | `Store.note()` appends a dated line on every link/set/transition. organism: 32 rows, 2,439,166 B; `Notes` avg 63,072 B, max 229,157 B (OGM-008, 265 segments, mostly `linked OVRRefs to OVR-###`). `EvidenceBindings` avg 8,776 B. todo `ContextCheckpoint` avg 18,797 B, max 51,618 B, stored in the row |
| D3 | Executable rules: zero real uses | 32/32 OGMs `RuleType=manual`; `RuleSubject/RuleSelector/RuleValue` empty in every row. `json_eq/json_ge/row_eq/file_sha256` cannot express a software requirement. The manual path is a 5-step ceremony (evaluate, run, write report with meaning+source hashes, register report OVR, verify) |
| D4 | Knowledge thin, ceremony thick | overlord `Purpose` avg 61 chars; `Notes` avg 409 chars of ledger. todo has 35 columns; `Context/Instructions/ExpectedOutput/ValidationCriteria` empty on 16–24 of 36 rows and on PAC-036. 6 approval columns, 4 timestamps, 1 checkpoint always populated |
| D5 | Adherence by instruction, not delivery | No hooks. The only automatic touchpoint is the 512-char MCP instruction string. Skills are ~90% tool ceremony (revision, digest, receipt, cursor, page, encoding), ~0% project knowledge. The agent must choose to call 5–8 tools in order. This is "running alongside" |
| D6 | Self-referential corpus | All 36 PAC, 18 NDL, 32 OGM rows are about building PACER (Codex, uv, installer, mypy). PACER has never governed a foreign codebase here. The 24-trial "all correct" measurement used synthetic states |
| D7 | Overlord hand-maintains what code analysis derives | 572 rows; `Exports/Imports/Requires/RequiredBy` typed by agents (`maintain.py` covers Python `ast` only). `.codegraph` already holds imports/callers for the repo with ~1 s lag. "Map must match territory in one commit" is a treadmill that competes with a better tool |
| D8 | v2.0.0 fixes behaviour and deletes the model | 58 KB package restates one doctrine in ~8 files (README, AGENT_START, PREPROMPT, .MIVIM.spec, machine.json, machine.yaml, contract, rules.rs, map.toml, GUARDRAIL_DOCTRINE). Format carries a title, a state and source paths per node. No requirements, no dependency graph, no evidence, no decisions. `:loop⠁:`, `->:absorb::nodule`, "intentionally non-compiling pseudo-Rust" are decoration. `theatre.py` prints the phase header because there is nothing else to compile |
| D9 | Shipping-team gates at proof-of-concept | Receipts bind to source hashes, so any edit stales the receipt and forces a 200 KB refetch before apply. 48 h DOING split rule. Approval gate independent of status. Absorb rechecks all rules transitively. This is the [A] `1:1:1:1…` pattern enforced by the runtime |

What survives, because it is right: four organs' meanings (work / source / design / scoped intake); immutable IDs; typed cross-refs; statuses that require evidence; nodule as the only door for scope; original wording preserved with USER/OBSERVED/INFERRED authority; atomic validated writes under a lock; freshness as an observation not a status. From v2: maturity tiers, authority-class gates, latching, WELL/THEATRE split, modulation as inherited position, continue-by-default.

## 2. Architecture

Three layers.

```
registers  (git-tracked CSV, current state only)  +  ledger.PACER.jsonl (append-only, never in context)
    │
compiler   pacer frame <kind> --focus <id|path|prompt> --budget <bytes>   → cards (fixed grammar)
    │            uses: registers + structure provider (codegraph | builtin ast) + git
adapters   Claude Code hooks.json / Codex hooks.json → call the compiler on lifecycle events
           MCP tools for explicit query/write (same cards, same writer)
```

The agent never onboards. The harness delivers the SESSION frame at start and after compaction, the EDIT frame before every edit, the RESULT frame after it, and the STOP frame when the agent tries to stop. Nothing is fetched by choice; the constraint field arrives at the moment of action.

## 3. Registers

Six files. IDs remain `PAC|OVR|OGM|NDL|DEC-###`, immutable, never reused. Multi-refs `;`-separated. Tags `#lowercase`. Column length limits are enforced by the writer so cards are bounded by construction.

### 3.1 todo.PACER.csv — work tree (16 columns)

| Col | Type | Limit | Meaning |
|---|---|---|---|
| ID | PAC-### | | |
| Kind | AREA·PHASE·PACE | | one tree, three levels |
| Pos | `A2.P3.05` | | modulation made a column; mutable (re-modulation), ID is not |
| Title | text | 80 | |
| Status | TODO·ACTIVE·INTEGRATED·DONE | | REVIEW is evidence, not a state |
| Tier | sketch·prototype·playable·integrated·release·protected | | set on PHASE; PACE inherits |
| Produce | imperative | 140 | what this node makes true |
| In | OVR refs | | assets read or edited |
| Out | `path[:symbol]` list | | assets to create; become OVR rows on first touch |
| Binds | OGM refs | | invariants that constrain this node; PACE inherits PHASE's |
| Needs | PAC refs | | hard deps only; position order is the default sequence |
| Probe | command | 200 | proves the pace; required at Tier ≥ integrated |
| Exit | text | 140 | PHASE only: coherence condition |
| Next | inspect·implement·verify·integrate·absorb | | durable next action; written by the STOP frame |
| Latch | DEC refs | | decisions that gate or authorise this node |
| Tags | | | |

Dropped from 0.5: DoD (→ Produce + Probe), Context/Instructions/ExpectedOutput/ValidationCriteria/ErrorHandling (→ inherited cards), PreviousAttempts/LearningNotes (→ DEC FAILED/LESSON), Notes/StartedAt/DoneAt/UpdatedAt/ContextCheckpoint (→ ledger), Approval×6 (→ DEC LATCH), Priority, Assignee, DependencyType/Reason/UnblockingStrategy, RelatedWork.

### 3.2 overlord.PACER.csv — authored source semantics (9 columns)

| Col | Limit | Meaning |
|---|---|---|
| ID, Path, Symbol, Kind(FILE·MODULE·CLASS·FUNCTION·CONFIG·SCHEMA) | | |
| Purpose | 140 | the one thing code analysis cannot derive |
| Tier | | protection level of this asset; overrides phase tier upward only |
| Binds | | OGM refs this asset must satisfy |
| Latch | | DEC refs in force on this asset |
| Tags | | |

`Exports/Imports/Requires/RequiredBy` are not stored. The structure provider computes imports, exporters, callers and callees at compile time: `codegraph` when `.codegraph/` exists, else the builtin provider (Python `ast`; import-regex for JS/TS; extensible). Drift between map and territory becomes impossible for the structural half. Rows auto-register on first touch with `Purpose=""` and tag `#unpurposed`; the EDIT card shows that until the agent fills it.

### 3.3 organism.PACER.csv — requirements with probes (11 columns)

| Col | Limit | Meaning |
|---|---|---|
| ID, Title(80), Status(SCAFFOLD·PACED_REQUIREMENT·VALIDATED_COMPLETE) | | unchanged vocabulary |
| Authority | USER·OBSERVED·INFERRED·UNRESOLVED | LEGACY only from migration |
| Origin | 400 | literal user wording |
| Requirement | 280 | normalised statement |
| Binds | | OVR refs the requirement constrains |
| Probe | 200 | command; exit 0 = PASS |
| Evidence | | `rev:<sha7> exit:<n> out:<sha7> at:<date>` — one cell |
| Tier | | gate posture for this requirement |
| Tags | | |

Freshness is derived at compile time, not stored: STALE when `git diff --name-only <Evidence.rev>..HEAD` intersects the paths of `Binds` or their one-hop provider dependents. FAIL when the last probe exit ≠ 0. `pacer probe OGM-004` runs the command, writes the Evidence cell, stores full output at `.pacer/probes/OGM-004/<ts>.txt`, appends the ledger. One command replaces the five-step manual-report ceremony. VALIDATED_COMPLETE requires `exit:0` and not STALE, same rule as before, one cell.

### 3.4 decision.PACER.csv — new (11 columns)

| Col | Limit | Meaning |
|---|---|---|
| ID | DEC-### | |
| Kind | CHOICE·LATCH·LESSON·FAILED | |
| Subject | refs (PAC/OVR/OGM/NDL) | what the decision binds |
| Question | 140 | |
| Chosen | 140 | |
| Rejected | 140 | |
| Why | 280 | |
| Authority | USER·OBSERVED·INFERRED | LATCH requires USER |
| Latched | true·false | false = open question awaiting the user |
| Supersedes | DEC ref | the only way to reopen |
| Tags | | |

This is where "why" lives and where approval/skip lives. A LATCH is delivered as a card whenever its Subject is in frame, so re-asking is structurally impossible: the agent sees `DEC-003 LATCH USER 2026-09-18 | Chosen: …` before it can form the question. FAILED and LESSON replace PreviousAttempts/LearningNotes and survive compaction because the SESSION frame re-delivers those bound to the active phase.

### 3.5 nodule.PACER.csv — intake (12 columns)

`ID, Name, Status(ACTIVE·ABSORBED), Lane, Request(literal wording, 400), Intent(140), In(OVR), Out(paths), Targets(OGM), Spawned(PAC), Exit(140), Tags`. Unchanged meaning: the only door for new scope; archived to `archive/nodules/<ID>.PACER.csv` on absorb.

### 3.6 ledger.PACER.jsonl — new

Append-only `{"at","actor","op","id","fields"|"path"|"probe"}`. All timestamps, link events, touched paths, probe runs, migrations. Never compiled into a frame. Queried only by `pacer log <id>`. Git history remains the second ledger.

## 4. Compiler

### 4.1 Card grammar

One line per card, pipe-delimited, three-letter kind, fixed field order. The same line is emitted by every frame, every MCP tool result and every CLI query. The agent sees it hundreds of times per session; the human reads the same line.

```
PAC PAC-041 A2.P3.05 ACTIVE prototype | Produce: … | In: OVR-012;OVR-019 | Out: src/x.py:Foo | Binds: OGM-004 | Needs: PAC-040 | Probe: pytest tests/test_x.py -q | Next: implement
OVR OVR-012 src/auth/session.py:SessionManager integrated | Purpose: … | Binds: OGM-004;OGM-007 | Latch: DEC-003 | used-by: src/main.py, src/api/login.py (+3)
OGM OGM-004 PACED_REQUIREMENT USER release | Requirement: … | Probe: pytest tests/test_session.py -q | Evidence: rev:a1b2c3d exit:0 at:2026-09-20 STALE(src/auth/session.py)
DEC DEC-003 LATCH USER latched | Subject: OVR-012 | Chosen: keep sync API; no async rewrite | Why: …
NDL NDL-019 ACTIVE lane=auth | Intent: … | Targets: OGM-004 | Spawned: PAC-040;PAC-041 | Exit: …
```

Empty fields are omitted, field order never changes.

### 4.2 Frames

| Frame | Trigger | Content | Budget |
|---|---|---|---|
| SESSION | SessionStart (startup, resume, clear, compact) | project line; active AREA + PHASE cards (Exit, Tier); ACTIVE and next ≤5 PACE cards; LATCH/LESSON/FAILED DECs bound to the phase; OGMs bound to the phase with status and freshness; OVR cards for the phase's `In` | 4,000 B |
| PROMPT | UserPromptSubmit | cards for any ID, path or `#tag` mentioned in the prompt; otherwise empty | 2,000 B |
| EDIT | PreToolUse on Edit·Write·NotebookEdit | the asset card for `tool_input.file_path`: OVR, its bound OGMs (with Probe), its DECs, provider dependents (≤8), and `OFF-PACE` if the path is in neither the active pace's `In` nor `Out` | 1,500 B |
| RESULT | PostToolUse on the same tools | writes: touched path → ledger under the active pace; unknown path → OVR row `#unpurposed`; returns ≤200 B: `OVR-612 registered #unpurposed` and/or `stale: OGM-004` | 200 B |
| STOP | Stop | gate matrix (§5) for the active phase; writes `Next` as the checkpoint; blocks only per matrix | 1,000 B |

Delivery channels, per the Claude Code hooks reference (checked 2026-09-29): SessionStart injects plain stdout and fires with `source` ∈ {startup, resume, clear, compact, fork}; UserPromptSubmit, PreToolUse and Stop inject `hookSpecificOutput.additionalContext`; PreToolUse `additionalContext` is combined across hooks. Two items to confirm at implementation: that PreToolUse accepts `permissionDecision: allow` together with `additionalContext` (implied, not stated), and PostToolUse's channel back to the model (fallback: fold staleness into the next EDIT or STOP frame; the RESULT frame's primary job is the write, not the message).

The SESSION frame on `source=compact` is the compaction-survival mechanism: the constraint field is re-delivered after every summarisation without the agent doing anything.

### 4.3 Relevance ranking replaces closure

`score(row) = 1 / (1 + d(focus,row))` with typed-edge distances: `Binds, In, Out, Latch, Subject` = 1; same PHASE = 1; `Needs`, provider `used-by` = 2; same AREA = 3. The spine is mandatory and always fits: focus card + its PHASE card + LATCH DECs on the focus (≤ ~1 KB by column limits). Remaining budget fills by score, ties by ID. The frame ends with `+N more: pacer q <focus>` when truncated. No refusal on budget. Completeness means "the spine and the top-K by relevance", which is what an engineer holds in working memory, not every reachable row.

### 4.4 Writer

Kept from 0.5: repository lock, validate-in-memory then atomic publish, path containment, `pace`, `absorb`. Dropped: revision precondition (git is the revision), onboarding digest, context receipt, pages/cursors, compact/expanded encodings, approval history JSON, `split`, `correct_assets`, `checkpoint` as a command (the STOP frame writes `Next`), `refresh`/`verify`/`evaluate` (→ `probe`, freshness derived), RuleType vocabulary.

CLI and MCP share one lexicon: `add · set · link · move · status · latch · probe · pace · absorb · q · frame · log · sync · migrate`. Every write appends to the ledger; no write touches a Notes cell because there are none.

## 5. Gates as data

Tier is a column; doctrine collapses to one matrix evaluated by the STOP and EDIT frames.

| Tier | STOP blocks when | EDIT denies when |
|---|---|---|
| sketch, prototype, playable | never | never |
| integrated | a phase-bound OGM probe FAILED | never |
| release | FAILED or STALE on a phase-bound OGM | never |
| protected | as release | path has no USER LATCH covering it |

User-authority classes (irreversible external action, missing secret, destructive change to protected content, mutually exclusive direction, user-reserved) are open LATCH rows (`Latched=false`). The STOP frame lists open latches once; the agent asks once; the answer sets `Latched=true` with Authority=USER. There is no other stop condition. Ordinary test failure, tuning values, style, refactors, research, sub-agent findings and absent playtesting never appear in the matrix, which is v2's doctrine expressed as a lookup instead of ten documents.

## 6. Harness adapters

`plugins/pacer/hooks/hooks.json` (Claude Code) and the Codex hooks equivalent, both calling `uv run pacer frame …` with the project root from the hook input. MCP tools remain for explicit query and write. Skills reduce to one short `pacer` skill that documents the card grammar and the lexicon; there is no onboarding skill because there is no onboarding.

Codex has SessionStart/PreToolUse/PostToolUse hooks (since v0.117; the installed CLI is 0.154), so both adapters deliver the same frames.

## 7. Migration

`pacer migrate --from 0.5` on this repository:

- PAC: `DoD`→`Produce` (first sentence; full text to ledger), `Phase`→`Pos` (A1.P<n>), `Approval*`→DEC LATCH, `PreviousAttempts`→DEC FAILED, `LearningNotes`→DEC LESSON, `Notes`+`ContextCheckpoint`→ledger, `Status REVIEW`→INTEGRATED, `DOING`→ACTIVE.
- OVR: authored columns kept; `Exports/Imports/Requires/RequiredBy/Notes/EvidenceFor` dropped (provider or ledger).
- OGM: `Requirement/Authority/OriginText(→Origin)` kept; `EvidenceBindings`→ledger; manual reports with a recoverable `command`→`Probe`, their result→`Evidence` with `rev` from the report date's commit.
- NDL: kept.
- `pacer migrate --from v2` maps GLOBAL→AREA, PHASE→PHASE (EXIT→Exit), PACE→PACE, SOURCE→OVR, `+approved`→DEC LATCH.

Expected sizes here after migration (measured columns, not estimates of prose): organism 2.4 MB → ≈40 KB; todo 903 KB → ≈30 KB; overlord 412 KB → ≈90 KB; the remainder lands in `ledger.PACER.jsonl` and is never delivered.

## 8. Deleted

`pages.py`, cursor logic, encodings, receipts, onboarding digest, revision preconditions, approval columns, split/48 h/≤3-DOING rules, `correct_assets`, `EvidenceBindings`, `ContextCheckpoint`, RuleType vocabulary, manual report ceremony, `Requires/RequiredBy` symmetry validation, `scripts/maintain.py` (→ `pacer sync` via provider). From v2: `rules.overlord.rs`, `machine.json/yaml`, `PREPROMPT.txt`, `contract/`, `api/`, `map.overlord.toml`, `task.overlord.md`, eight doctrine documents. The `.PACER` indented DSL survives as a view (`pacer tree`), not storage; CSV stays canonical because it is row-addressable and diffable.

`.MIVIM.spec` survives as the project frame: name, default tier, provider, frame budgets, lanes. Nothing else.

## 9. Approaches considered

**A. Hooks-first rebuild (recommended).** New `pacer_mcp` internals: reuse store/lock/validation; replace `context.py` with `frames.py`; add DEC register, ledger, provider, hooks. Only option that addresses D5, which is the actual complaint. Cost: largest change; migration on live data.

**B. Prune 0.5 in place.** Move Notes to a ledger, cap closure at distance 2, drop receipts, add hooks that call the existing `pacer_context`. Fixes D1/D2/D9, not D3/D4/D5/D7. The agent still receives JSON packets rather than cards, the 35-column todo remains, the dead rule vocabulary remains.

**C. Grow the v2 DSL into the canonical store.** Add requirements, decisions and probes to the grammar; compile from text. Pleasant for humans; not row-addressable; atomic multi-agent writes and validation must be reinvented; loses the 0.5 writer. Not recommended.

## 10. Verification

- Unit: card grammar round-trip; ranking determinism; budgets never split a card; gate matrix per tier; migration on this repository's live registers preserves every USER `Origin`, every latch, every ID.
- Integration: fixture project; `claude -p` with the plugin's hooks and `codex exec --json`; assert the EDIT frame precedes each edit and contains the OGM bound to the path; assert a SESSION frame follows compaction; assert a latched question is never asked twice across two sessions.
- Foreign project: run the same trial on a non-PACER repository to break D6. Metrics: bytes injected per session and per edit; OFF-PACE edits; repeated latch questions; probe pass/stale counts at phase exit.

## 11. Decisions

1. **CSV is canonical.** The indented `.PACER` text is a view (`pacer tree`). Reason: row addressing, diffability, and the existing lock/atomic-publish writer; a text DSL as storage would reinvent all three.
2. **Both adapters ship.** Codex plugins read the same `hooks/hooks.json` wrapper and support `hookSpecificOutput.additionalContext` on PreToolUse and PostToolUse (checked 2026-09-29 at learn.chatgpt.com/docs/hooks). One hook entry point, `pacer hook <event>`, reads stdin JSON from either harness; the edit matcher is `Edit|Write|NotebookEdit|apply_patch`, and for `apply_patch` the file path is parsed from `*** Update File:` / `*** Add File:` lines. Claude Code is verified live in a fixture; Codex by configuration.
3. **Migration subjects are real.** `C:/Users/ryanf/github/_active/image-riposte` runs profile 0.5 with the same pathology (organism 30 rows / 7.8 MB, overlord 2,536 rows / 1.7 MB, todo 49 rows / 4.8 MB) and is the `--from 0.5` subject and the live trial. `C:/Users/ryanf/github/_new/tag-replicata` runs v2.0.0 and is the `--from v2` subject. Neither repo is modified until its migration preview validates; the trial runs on a copy first.

Implementation notes fixed at plan time: the package stays `pacer_mcp` with CLI `pacer` and MCP server name `pacer` so the installer and manifests keep working; version 3.0.0. Evidence staleness is computed from a digest of the bound files (`src:<sha7>` in the Evidence cell) rather than from git alone, so uncommitted edits count. PreToolUse hooks never emit `permissionDecision: allow` (that would bypass the permission prompt); they emit only `additionalContext`, or `deny` at protected tier. The ledger lives at `ledger.PACER.jsonl` in the project root and is git-tracked.
