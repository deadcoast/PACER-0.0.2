# PACER format 3.0

Normative reference for a PACER project: the files on disk, the card grammar, what each frame carries, the write operations and the gates. The runtime in `src/pacer/` implements exactly this.

## 1. Layout

All PACER state for a project lives in one tracked directory at the project root.

```
.pacer/
  project.pacer.toml        project frame; its presence marks a governed project
  todo.pacer.csv            PAC  work tree: areas, phases, paces
  overlord.pacer.csv        OVR  source assets
  organism.pacer.csv        OGM  requirements with probes
  nodule.pacer.csv          NDL  scoped intake
  decision.pacer.csv        DEC  choices, latches, lessons, failed approaches
  ledger.pacer.jsonl        append-only history; never compiled into a frame
  archive/<register>.pacer.csv   retired rows, same columns; created with the first retired row
  .gitignore                ignores run/
  .gitattributes            `* -text`: no end-of-line conversion, so state is byte-exact in every clone
  run/                      machine-local: lock, write journal, hook memory, provider cache, probe output
```

Everything except `run/` is committed. File and directory names are lowercase; `PACER` is capitalised only as a name in prose. The project root is the nearest ancestor directory holding `.pacer/project.pacer.toml`.

## 2. Project frame

`project.pacer.toml`. Every key is optional.

```toml
format = "3.0"

[project]
name = "my-project"          # default: directory name
tier = "prototype"           # default tier; see section 9

[provider]
name = "auto"                # auto | codegraph | builtin | none
exclude = []                 # directories the builtin scanner skips

[frames]                     # byte budget per frame, 256..64000
session = 4000
prompt = 2000
edit = 1500
stop = 1000

[probe]
timeout = 120              # seconds before a Probe is stopped, 1..3600
```

`auto` uses the CodeGraph index when `.codegraph/` exists, otherwise the builtin scanner (Python `ast`, import patterns for JS/TS). The provider supplies `used-by` and file-to-file distance; nothing it derives is stored.

## 3. Registers

CSV, UTF-8, LF, header row, current state only. IDs are `PAC|OVR|OGM|NDL|DEC-<3+ digits>`, immutable, never reused, including after archiving. Multi-reference cells are `;`-separated. Tags are space-separated `#lowercase-words`. No cell contains `|` or a newline. Length limits are enforced on write, so a card is bounded by construction.

Each relation is stored once, in one direction. The reverse view is derived when a card is rendered.

### todo — PAC

| Column | Values | Limit | Meaning |
|---|---|---|---|
| ID | `PAC-###` | | |
| Kind | AREA, PHASE, PACE | | one tree, three levels |
| Pos | `A1`, `A1.P2`, `A1.P2.03` | | position; unique; depth matches Kind; changed only by `move` |
| Title | text | 80 | required |
| Status | TODO, ACTIVE, INTEGRATED, DONE | | changed only by `status` |
| Tier | section 9 | | set on a PHASE; a PACE inherits it; explicit tiers only raise |
| Produce | imperative text | 140 | what the row makes true; required on a PACE |
| In | OVR refs | | assets the work reads or edits |
| Out | `path[:symbol]` list | | assets the work will create |
| Binds | OGM refs | | requirements that constrain the row; a PACE also inherits its PHASE's |
| Needs | PAC refs | | hard dependencies; gate DONE; no cycles |
| Probe | command | 200 | proves the row; warned when absent on an open PACE at tier integrated or above |
| Exit | text | 140 | required on a PHASE: its coherence condition |
| Next | inspect, implement, verify, integrate, absorb | | durable next action; written at stop |
| Tags | | | |

### overlord — OVR

| Column | Values | Limit | Meaning |
|---|---|---|---|
| ID | `OVR-###` | | |
| Path | project-relative, `/` separators | 240 | changed only by `repath`; never inside `.pacer/` |
| Symbol | name | 120 | empty for a file row |
| Kind | FILE, MODULE, CLASS, FUNCTION, METHOD, CONFIG, SCHEMA | | a symbol row requires the FILE row of its path |
| Purpose | text | 140 | the one thing code analysis cannot derive |
| Tier | section 9 | | raises protection for this asset |
| Tags | | | `#unpurposed` until Purpose is written |

`(Path, Symbol)` is unique. A file that no longer exists is a warning and a `missing` flag on the card, never an error.

### organism — OGM

| Column | Values | Limit | Meaning |
|---|---|---|---|
| ID | `OGM-###` | | |
| Title | text | 80 | |
| Status | SCAFFOLD, PACED_REQUIREMENT, VALIDATED_COMPLETE | | changed only by `status` |
| Authority | USER, OBSERVED, INFERRED, UNRESOLVED, LEGACY | | LEGACY only from migration |
| Origin | literal user wording | 400 | |
| Requirement | normalised statement | 280 | required |
| Binds | OVR refs | | the assets the requirement constrains |
| Probe | command | 200 | exit 0 passes |
| Evidence | one cell, section 8 | | written only by `probe` |
| Tier | section 9 | | |
| Tags | | | |

### nodule — NDL

| Column | Values | Limit | Meaning |
|---|---|---|---|
| ID | `NDL-###` | | |
| Name | text | 60 | required |
| Status | ACTIVE | | ABSORBED rows live in the archive |
| Lane | text | 40 | required; ACTIVE nodules share neither a lane nor an In asset |
| Request | literal user wording | 400 | required |
| Intent | text | 140 | required |
| In | OVR refs | | |
| Out | `path[:symbol]` list | | |
| Targets | OGM refs | | |
| Spawned | PAC refs | | required while ACTIVE |
| Exit | text | 140 | required |
| Tags | | | |

### decision — DEC

| Column | Values | Limit | Meaning |
|---|---|---|---|
| ID | `DEC-###` | | |
| Kind | CHOICE, LATCH, LESSON, FAILED | | |
| Subject | refs to any register | | required; what the decision is about |
| Question | text | 140 | |
| Chosen | text | 140 | |
| Rejected | text | 140 | |
| Why | text | 280 | |
| Authority | USER, OBSERVED, INFERRED, UNRESOLVED, LEGACY | | a latched LATCH requires USER |
| Latched | `true`, `false`, empty | | LATCH only; `false` is an open question for the user; changed only by `latch` |
| Supersedes | DEC ref | | the superseded decision is no longer delivered |
| Tags | | | |

## 4. Archive

Live registers hold current work. `archive` and `absorb` move rows to `archive/<register>.pacer.csv`, unchanged.

- The live web is closed: a live row never references an archived one. Retiring a row strips it from every live reference cell. `decision.Supersedes` is the one exception and may point into the archive.
- Archiving an AREA or PHASE takes its subtree. A PACE that is not DONE refuses.
- A decision whose every Subject is retired retires with them. Requirements and assets never cascade.
- An archived ID stays taken. `pacer_q <ID>` returns its card with the `archived` flag.

## 5. Ledger

`ledger.pacer.jsonl`: one JSON object per line, `{"at": "<UTC>", "actor": "…", "op": "…", "id": "…", "detail": {…}}`. Every write appends; nothing is rewritten. Operations recorded: `init`, `migrate`, `add`, `set`, `link`, `move`, `status`, `latch`, `absorb`, `archive`, `repath`, `touch`, `probe`, `checkpoint`. A `probe` event keeps one digest per bound file, which is how a later STALE names the files that changed. Read with `pacer log [ID]`; never part of a frame.

## 6. Cards

One row, one line: `<KIND> <ID> <head tokens> | Field: value | …`. Field order is fixed; empty fields are omitted; `|` inside a value is rendered `/`.

| Kind | Head tokens | Stored fields, in order |
|---|---|---|
| PAC | `Pos Status Tier` | Title (AREA and PHASE only), Produce, In, Out, Binds, Needs, Probe, Exit, Next, Tags |
| OVR | `Path[:Symbol] Tier` | Purpose, Tags |
| OGM | `Status Authority Tier` | Requirement, Probe, Evidence, Binds, Tags |
| NDL | `Status lane=<Lane>` | Intent, In, Out, Targets, Spawned, Exit, Tags |
| DEC | `Kind Authority latched\|open` | Subject, Question, Chosen, Rejected, Why, Supersedes, Tags |

Derived fields follow the stored ones, in lowercase, and are never written back:

| Field | On | Meaning |
|---|---|---|
| `bound-by` | OVR | requirements whose Binds names the asset |
| `latch` | PAC, OVR | latched LATCH decisions whose Subject names the row |
| `used-by` | OVR | files that import the asset, from the provider; at most 8, then `(+N)` |

The OGM `Evidence` field is rendered as its state: `UNBOUND` when there is none, otherwise `rev:<sha7> exit:<n> at:<date>` followed by `CURRENT`, `FAIL`, or `STALE(<bound files changed since the probe ran>)`. At most three files are named, then `+N`.

Flags are bare trailing words, in this order: `missing`, `OFF-PACE`, `archived`.

## 7. Frames

A frame is a head line followed by cards. The spine always fits; remaining cards fill the byte budget in order; a trailer `+N more: pacer_q <focus>` counts what was left out. A superseded decision is never included.

Head line: `PACER <project> tier=<tier> pace=<active PAC or none>`.

| Frame | Delivered | Spine | Then, while budget lasts |
|---|---|---|---|
| session | session start, resume, clear, after compaction | active AREA, PHASE and PACE; decisions on them, on the pace's In assets and on the bound requirements | bound requirements; the next 5 TODO paces of the phase; everything else by distance from the pace |
| prompt | a prompt naming an ID, a registered path or a `#tag` | none | the named rows; empty when nothing is named |
| edit | before an edit to a path | the path's asset rows, the requirements that bind them, the decisions on either | the active pace, then rows by distance from the asset |
| stop | the agent stops | `PACER stop tier=… pace=… next=…`, open latches, requirements whose evidence is not CURRENT | |

The active pace is the first ACTIVE PACE in position order. With none active, the session frame says what to do instead: start a TODO pace, or pace new scope.

An unregistered path renders `OVR - <path> unregistered`. After a deliberate edit the file is registered as a FILE row tagged `#unpurposed`, and joins the active pace's In when the pace listed it in Out.

Distance is the shortest path over these edges: a reference cell 1; parent and child in the tree 1; paces of one phase 1; `Needs` 2; provider file dependency 2; phases of one area 3.

## 8. Evidence

`pacer_probe <OGM>` runs the requirement's Probe from the project root (no stdin; stopped at the configured timeout and recorded as exit 124). The project lock is not held while the command runs, so a probe may take minutes and may use PACER itself. It stores the full output under `run/probes/<OGM>/` and writes one cell:

```
rev:<git sha7|none> src:<sha7> exit:<n> out:<sha7> at:<UTC>
```

`src` digests the content of every file the requirement binds, with line endings normalised, so the same tree gives the same digest on every platform and uncommitted edits count. State is derived on every read:

| State | When |
|---|---|
| UNBOUND | no Evidence |
| FAIL | last exit was not 0 |
| STALE | the bound files' digest differs from `src` |
| CURRENT | exit 0 and the digest matches |

`VALIDATED_COMPLETE` requires CURRENT evidence at the transition. A bound file may change afterwards: the card then shows STALE, and at release tier a stop is blocked until the probe is run again. Validation never refuses a write over stale evidence.

## 9. Gates

| Tier | A stop is blocked when | An edit is denied when |
|---|---|---|
| sketch, prototype, playable | never | never |
| integrated | a requirement bound to the active phase or pace is FAIL | never |
| release | one is FAIL or STALE | never |
| protected | as release | no latched USER LATCH covers the asset or the active pace |

The effective tier of a pace is the highest of its own, its phase's and the project's. An asset's Tier raises protection for that file alone.

An open LATCH (`Latched = false`) whose Subject is the active pace, its phase, one of the pace's In assets or one of its bound requirements blocks a stop at every tier. It is the only question put to the user. The answer is recorded with `latch`, which sets Authority USER.

A stop that is not blocked emits nothing and writes the pace's `Next`.

## 10. Operations

A batch is 1 to 200 operations applied to an in-memory copy, validated as a whole, then published atomically under the project lock. Any refusal leaves disk and ledger untouched. An interrupted publication is finished by `pacer recover`.

| op | Fields | Rules |
|---|---|---|
| `add` | `register`, `row` | ID assigned when omitted; PAC defaults Kind PACE, Status TODO; OGM defaults SCAFFOLD |
| `set` | `id`, `fields` | not ID, Kind, Status, Pos, Path, Evidence, Latched |
| `link` | `id`, `field`, `target`, `remove` | reference columns only; target must be live and of the right register |
| `move` | `id`, `pos` | PAC rows; the position must be free and match the row's Kind |
| `status` | `id`, `status` | DONE requires every Needs DONE; VALIDATED_COMPLETE requires CURRENT evidence |
| `latch` | `id`, `latched`, `evidence` | DEC LATCH rows; `true` sets Authority USER; `evidence` goes to the ledger |
| `pace` | `nodule`, `tasks`, `requirements`, `decisions` | adds all rows; the nodule's Spawned and Targets are filled from them |
| `absorb` | `id` | every Spawned DONE, every Target VALIDATED_COMPLETE and CURRENT, every Out path registered; the nodule retires |
| `archive` | `ids`, `cascade` | section 4 |
| `repath` | `from`, `to` | rewrites `overlord.Path`, `todo.Out`, `nodule.Out`; both ending in `/` moves a directory |

Hooks follow renames on their own: a staged `git mv` is read from git, and an unstaged move is recognised when a deleted tracked file and a new file of the same name have identical content. `pacer sync` retires asset rows whose file is gone.

## 11. Validation

Errors refuse a write. Warnings never do.

Errors: malformed or duplicate ID; unknown column; a cell over its limit or containing `|` or a newline; a reference to an unknown, archived or wrong-register row; an unsafe path (absolute, `..`, backslash, drive, or inside `.pacer/`); invalid vocabulary value; duplicate Pos or asset; Pos depth not matching Kind; PHASE without Exit; PACE without Produce; DONE with open Needs; a Needs cycle; a symbol row without its FILE row; VALIDATED_COMPLETE without CURRENT evidence; malformed Evidence; two ACTIVE nodules in one lane or sharing an In asset; an ACTIVE nodule without Spawned; a latched LATCH without Authority USER; a decision without Subject.

Warnings: `missing <path>`; `#unpurposed`; `no Probe at tier <tier>`.

## 12. Surfaces

| MCP tool | CLI | |
|---|---|---|
| `pacer_frame` | `pacer frame <session\|edit\|prompt\|stop> [--focus]` | compile a frame |
| `pacer_q` | `pacer q <query>` | cards for an ID, path, `#tag`, register or `register:STATUS` |
| `pacer_write` | `pacer write --file ops.json --actor <name>` | apply operations |
| `pacer_probe` | `pacer probe <OGM>` | run a probe, record evidence |
| `pacer_validate` | `pacer validate` | errors and warnings |
| `pacer_sync` | `pacer sync [--apply]` | retire assets whose file is gone |
| `pacer_log` | `pacer log [ID]` | ledger events |
| `pacer_init` | `pacer init [--name] [--tier]` | create `.pacer/` |
| `pacer_migrate` | `pacer migrate [--from] [--apply]` | upgrade an older layout |
| `pacer_recover` | `pacer recover` | finish an interrupted write |
| | `pacer tree` | the work tree as indented PAC cards |
| | `pacer update [--check] [--notify on\|off]` | bring the installation to the latest version; report it; silence the notice |

Every MCP tool takes the absolute project root. The CLI finds it from the working directory, or takes `--root`.

Hook events, one entry point `pacer hook <event>` reading the harness JSON on stdin:

| Event | Harness hook | Output |
|---|---|---|
| `session-start` | SessionStart | the session frame |
| `prompt` | UserPromptSubmit | the prompt frame, or nothing |
| `pre-edit` | PreToolUse on Edit, Write, NotebookEdit, apply_patch | the edit frame; `deny` only at protected tier |
| `post-edit` | PostToolUse on the same tools and Bash | one line: paths touched, files registered, renames followed, evidence gone stale |
| `stop` | Stop | nothing, or a block with the stop frame |

A hook never grants permission, is silent outside a governed project, and answers a repeated event once.

## 13. Migration

`pacer migrate` detects what is in the project root, previews by default, and writes only when the result validates.

| Source | Recognised by | Result |
|---|---|---|
| `0.5` | `todo/overlord/organism/nodule.pacer.csv` with a `DoD` column | phases become `A1.P<n>`; DoD becomes Produce; approvals become LATCH decisions, attempts FAILED, notes LESSON; a completed requirement is demoted to PACED_REQUIREMENT because an old acceptance is not a probe result; assets whose file is gone and absorbed nodules go to the archive |
| `2.0` | `todo.pacer` text beginning `PACER::TODO` | GLOBAL becomes AREA, PHASE and PACE keep their kind, SOURCE becomes an asset, `+approved` a latched LATCH, `maturity` the project tier |
| `3.0-root` | five registers with a `Kind` column in the project root | files move into `.pacer/`; the reverse columns `overlord.Binds`, `overlord.Latch` and `todo.Latch` fold into `organism.Binds` and `decision.Subject`; absorbed nodules move to the archive; `.MIVIM.spec` becomes `project.pacer.toml` |

File names are matched without regard to case. Imported originals are kept verbatim under `.pacer/archive/import-<source>/`. A project still in an older layout gets one line at session start naming the upgrade.
