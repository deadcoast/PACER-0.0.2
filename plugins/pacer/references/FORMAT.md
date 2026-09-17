# PACER executable profile 0.5

PACER is an agent's connected working memory for a project. The human states
intent. The agent paces it into a nodule and tasks, maps the code in overlord,
and records the design's actual state in organism. CSV remains authoritative.
The runtime enforces mechanics; the agent must still understand the request,
inspect source, judge definitions of done, and supply honest evidence.

The original README and AGENTS.md define the four organs and their meanings.
This profile makes missing mechanics executable without changing those meanings.
Design and development history live in organism and todo, not this reference.

## Explicit format decisions

- Retain every original column. Append `OVRRefs`, `OGMRefs`, `NDLRefs`, `Tags`,
  `UpdatedAt` to todo; `NDLRefs` to organism; `Lane`, `AcceptanceEvidence` to nodule.
  Extra project columns survive reading, migration and writes.
- IDs match `(PAC|OVR|OGM|NDL)-[0-9]{3,}[A-Z]*`. Split children use distinct IDs
  such as `PAC-123A` and `PAC-123B`; IDs never recycle, including archived nodules.
- Reference columns contain semicolon-separated IDs. Tags are whitespace-separated
  `#lowercase` tokens, allowing digits and hyphens after the first letter.
- `BlockedBy` and `DependencyType`: an empty type means hard; a single `hard`,
  `soft`, or `optional` applies to all blockers. A semicolon list of types must
  have exactly one entry per blocker in the same order. This is a new explicit
  mixed-dependency encoding; legacy uniform types retain their meaning.
- `RelatedWork` remains free text containing resolvable IDs and tags. Migration
  extracts its IDs into the added typed reference columns and keeps original text.
- A planned requirement enters organism at pace time with `NDLRefs`, without
  `AbsorbedFromNDL`. This resolves the original forward-reference contradiction:
  nodule targets must exist before absorption. It is `SCAFFOLD` until its
  incompleteness is caused by a named unbuilt reference, then `PACED_REQUIREMENT`.
- Nodule states are `ACTIVE` and `ABSORBED`. Pacing creates tasks and targets in
  the same transaction as activation. A named lane admits one active nodule;
  different lanes additionally require disjoint `TargetOVR` and `NewAssets`.
- Absorption moves the row to `archive/nodules/<NDL-ID>.PACER.csv`. That file is
  its sole canonical location; the root nodule register contains active rows
  and keeps its header when empty. Archived rows remain resolvable live records
  of absorbed scope. Deleting history is not the default in this implementation.
- Completion evidence is a nonempty, dated test/audit reference describing what
  was checked. The runtime can verify presence and state dependencies, not the
  truth of arbitrary human assertions. Test reports should identify their source
  revision or digest and exact command.
- `set` cannot change IDs, workflow state, timestamps, history or a task's DoD.
  Scope refinement uses narrower split children and leaves the parent DoD intact.
  `append` preserves Notes, LearningNotes and PreviousAttempts. Each mutation
  adds a dated actor Note; workflow transitions set their UTC timestamps.
  DOING work older than 48 hours must use `split`; returning it to TODO cannot
  reset the clock to bypass this requirement.
- Nodule intent and absorption criteria cannot be rewritten by `set`. Admitted
  tasks, requirements, target assets and new assets cannot be removed from scope,
  including by clearing reciprocal NDLRefs. New assets can be added within Intent.
  Material edits to a validated requirement require demotion before editing.
- Absorption criteria are checked at absorption time. The archived event and
  its evidence remain historical when a later source change regresses a target.

## Command lexicon

The CLI and MCP share one operation representation. Apply a bounded JSON array
as a transaction, with the current revision and onboarding digest from `onboard`.
`preview` executes the same validation without publishing. Failed batches leave
the canonical files unchanged. Use freshly queried revision values after changes.

| Operation | Fields | Purpose |
|---|---|---|
| `add` | `register`, `row` | Register an asset or task; new design/scope uses pace |
| `set` | `id`, `fields` | Correct mutable row metadata with automatic backrefs |
| `append` | `id`, `field`, `text` | Retain a note, learning or failed approach |
| `link` | `id`, `field`, `target`, optional `remove` | Maintain symmetric typed edges |
| `transition` | `id`, `status`, optional `evidence` | Execute a legal task/organism transition |
| `pace` | `nodule`, `tasks`, `requirements` | Admit scoped work with all refs in one batch |
| `split` | `id`, `children` | Return stale work to TODO; add narrower children and hard gates |
| `absorb` | `id`, `evidence` | Check all tasks, requirements, assets and refs; archive the nodule |
| `checkpoint` | task `id`, `next_action` | Persist task context basis and next action |
| `verify` | OGM `id`, `evidence`, optional artifact OVR `artifact` | Evaluate and bind acceptance to current meaning/source |
| `refresh` | task `id` | Record stale evidence and demote demonstrated failures and affected dependents |
| `approval` | task `id`, `state`, `evidence` | Attest APPROVED or WITHDRAWN on TODO work; retain exact decision history |
| `correct_assets` | active NDL `id`, exact `expected`, `replacements`, `evidence` | Normalize reviewed legacy NewAssets prose/IDs to admitted live asset identities |

Rows supplied to `pace` have explicit IDs. Use `next_ids` to suggest unused
numbers, then rely on the revision precondition to detect competing allocations.

`correct_assets` is a narrow, explicit legacy correction. `expected` must equal the
current complete `NewAssets` text. `replacements` maps every malformed entry to a
nonempty list of existing live OVR IDs already in that nodule's `TargetOVR`. An OVR
token must map to itself; the command derives its exact `path[:symbol]`. Existing
identities and files remain literal, as do planned paths with a slash, backslash,
colon or extension, and tokens without whitespace (except OVR IDs). Only remaining
descriptive prose can receive a reviewed mapping. Ambiguous path-like text is
refused rather than guessed. The caller must judge that prose mappings preserve
meaning; the runtime cannot establish semantic equivalence from prose.

All literal entries survive, including unbuilt paths. The command records exact
before/after text, mappings and review evidence in dated actor Notes. It changes
no task, requirement or acceptance state. Ordinary scope-removal guards, context
and revision checks, preview rollback and absorption criteria still apply.

## Approval without replacing lifecycle state

Todo adds `ApprovalState`, `ApprovalEvidence`, `ApprovalActor`, `ApprovedAt`,
`ApprovalBasis` and `ApprovalHistory`. States are LEGACY, PENDING, APPROVED and
WITHDRAWN. A proposal created with `Phase=PROPOSAL` becomes PENDING; changing its
phase cannot erase that gate. Explicit PENDING also opts in independently of phase.
Record a user's existing authorization using `approval`; do not ask again merely
to populate a receipt. Evidence is exact attributable wording, and prior decisions
remain in the protected literal JSON history. Quoted IDs create no reference edges.

Approval binds ID, Title and the immutable DoD. Generic metadata cannot forge or
erase it. A title change requires withdrawal and re-approval on TODO work. Source
index maintenance is within the admitted intent and does not invalidate approval.
The agent still judges whether new scope needs another nodule. This is a workflow
attestation, not authentication of a human or permission for an external action.

Ready selection, advancement and newly admitted nodule tasks require approval for
opted-in work. Withdrawal requires TODO: return active work through legal lifecycle
transitions first. `pace` may admit existing TODO IDs via `SpawnedPACs` with an empty
`tasks` list, or combine them with genuinely new tasks. Splitting approved work
derives each narrower child's approval from the parent's preserved evidence,
independent of phase. The writer cannot prove that a child DoD is truly narrower;
review that claim. New scope must never be disguised as a split.

Migration marks ungated historical tasks LEGACY and historical proposals PENDING.
LEGACY preserves compatibility and does not claim user consent. Unspecified new
tasks retain this compatibility mode; use PENDING/PROPOSAL for work awaiting a
decision. Migration never creates an approval, rule, or current acceptance proof.

## Lossless context encoding

`context` defaults to `encoding=compact`, marked `encoding: pacer-context/2`.
Columnar tables and all required facts remain unchanged. Directed relations use
`relations: {kinds: [...], edges: [[source, kind, target], ...]}`. Source and target
are zero-based indexes into `required_ids`; kind indexes `relations.kinds`.
Order, direction, relation names, Unicode and exact field values round-trip through
`pacer_mcp.context.expand_context`. Unknown versions or invalid indexes fail.

CLI `--encoding expanded` and MCP `encoding="expanded"` return the earlier explicit
edge objects. Both variants retain the same receipt, mandatory closure, source
freshness and checkpoint delta. Byte budgeting happens after encoding and still
refuses rather than truncates. This compacts representation, not meaning or history.
Custom/audit fields omitted by the context projection remain queryable in CSV;
losslessness applies to the complete projected packet, not every register column.
Task rows begin TODO. New requirements begin SCAFFOLD or PACED_REQUIREMENT.
Source files are created by the coding agent and registered in the same change;
PACER does not execute arbitrary shell commands or modify source through MCP.

A minimal command file for a freshly initialized project (choose unused IDs in
an existing project):

```json
[
  {
    "op": "pace",
    "nodule": {
      "ID": "NDL-001",
      "NoduleName": "authority-audit",
      "Intent": "Verify the project's existing README authority",
      "Lane": "main",
      "TargetOVR": "OVR-001",
      "AbsorptionCriteria": "README inspected and authority requirement verified"
    },
    "tasks": [
      {"ID": "PAC-001", "Title": "Inspect README", "DoD": "README inspected against the request"}
    ],
    "requirements": [
      {"ID": "OGM-001", "Title": "Project authority", "Status": "SCAFFOLD", "Requirement": "README explains this project's purpose"}
    ]
  }
]
```

Save it outside source or register the command artifact if retaining it. Run
`pacer --root <project> onboard` to obtain fresh digests, then
`pacer --root <project> preview --file <commands.json> --actor <agent-name>
--revision <revision> --onboarding <onboarding>` and the same command with
`apply` when ready. `pacer schema` returns both columns and command JSON schemas.
The runtime records fresh UTC timestamps; do not manufacture completion dates.

`initialize` creates empty current-profile registers without copying worked
examples. It requires an existing project README and AGENTS.md. `migrate`
adds missing profile columns to live legacy registers, preserves all values and
extra columns, and repairs reciprocal typed refs. It refuses invalid data rather
than guessing at incomplete requirements, deleting examples or inventing evidence.

## Operational representation

Storage and delivery have different jobs. The four CSV registers retain canonical
meaning and history. `context` compiles their relevant rows into columnar JSON
with directed, named relations and evaluated rules. JSON is MCP's transport; it
is not a fifth project register. Required SKILL.md files provide discovery and
the operating bootstrap. They do not duplicate the project's design state.

Profile 0.3 appends these fields without removing original/custom columns:

| Organ | Additions | Purpose |
|---|---|---|
| todo | `NextAction`, `ContextCheckpoint` | Durable operational resumption |
| overlord | `EvidenceFor` | Reciprocal reference from report artifact to requirement |
| organism | `Authority`, `OriginText`, `RuleType`, `RuleSubject`, `RuleSelector`, `RuleValue`, `EvidenceBindings`, `EvidenceArtifact` | Explicit meaning, observation and source-bound acceptance |
| nodule | `ContextPolicy`, `UserRequest` | Declare operational workflow and preserve original request |

`USER` attributes a requirement to original user wording. `OBSERVED` identifies
source or measured behavior. `INFERRED` labels an agent's interpretation;
`UNRESOLVED` cannot be accepted. `LEGACY` preserves historical rows pending explicit
adoption. Migration assigns LEGACY where authority was absent, invents no rule,
and preserves old statuses. A historical VALIDATED_COMPLETE row is not thereby
current operational proof. Adopt rules deliberately before operational completion.

`OriginText` and `UserRequest` preserve literal language, including apparent IDs
that are quotations rather than links. Only typed reference columns create graph
edges. Other historical reference mentions remain checked for existence but do
not expand a graph. This separates attribution, rules, evidence and connections.

New nodules use `ContextPolicy=REQUIRED` and submit `pace` as a separate intake
batch. Retrieve `pacer_context(root, id=<PAC>, max_bytes=32000)` afterwards. Its
receipt is passed as `context` to preview/apply; CLI uses `--context-file` containing
the receipt object. A receipt binds the project root, authority bytes, required
rows and source files. It is a freshness precondition, not proof of understanding
or a security credential. Direct filesystem edits remain possible and are audited.

Context closes hard work dependencies, admitted nodule targets, requirement and
source dependencies, and affected consumers/dependent requirements. It includes
operative task guidance and original wording; source hashes identify files that
still need inspection. Audit Notes and raw evidence bindings remain available by
projected query. `complete=false` returns no receipt; exceeding the byte budget
never silently truncates mandatory rows. Increase the explicit budget or split
the work into independently sufficient scopes. `max_bytes` is UTF-8 bytes, not
model tokens. Unknown custom column semantics require explicit queries/adoption.

`checkpoint` stores the current row/source basis plus a declared next action:
inspect, implement, verify, review, absorb or resolve. A fresh process reconstructs
the packet and reports changed/removed rows and sources relative to that basis.
It preserves external work state, not private model reasoning.

## Rules, evidence and regression

Use `pacer_schema` or `pacer schema` for the machine-readable vocabulary:

| RuleType | Subject / selector / value |
|---|---|
| `json_eq` | OVR source / RFC 6901 JSON pointer / exact canonical JSON value |
| `json_ge`, `json_le` | OVR source / JSON pointer / finite number lower or upper bound |
| `row_eq` | OVR row / overlord column / JSON string |
| `file_sha256` | OVR source / empty selector / lowercase SHA-256 JSON string |
| `manual` | OVRRefs source basis / empty predicate fields / separate registered report |

RuleSubject must also be in OVRRefs. Booleans and strings are not numbers.
Canonical equality preserves JSON types and numeric spelling after JSON parsing:
`2` and `2.0` differ, object key order does not. No rule executes arbitrary code.
Canonical register files use row rules rather than recursively hashing their own
evidence bytes. Source dependencies bind their OVR metadata and file digests.

An explicit requirement example, after registering settings.json as OVR-007:

```json
{"ID":"OGM-001","Title":"Retry lower bound","Requirement":"Retries must be at least 2.","Authority":"USER","OriginText":"Retries must be at least 2.","RuleType":"json_ge","RuleSubject":"OVR-007","RuleSelector":"/retries","RuleValue":"2","OVRRefs":"OVR-007"}
```

`evaluate` returns observed PASS/FAIL/UNRESOLVED independently of accepted evidence
CURRENT/STALE/UNBOUND. `verify` requires PASS, records bindings produced by the
runtime, and checks current dependency acceptance transitively. Requirements with
explicit rules cannot be accepted by merely supplying evidence text. DONE and
absorb recheck their current rule evidence against the final transaction candidate.

For manual checks, first evaluate the requirement to obtain `meaning` and `sources`.
Run its actual test/audit. Write a separate JSON report and register its FILE OVR:

```json
{"requirement":"OGM-001","meaning":"<evaluated SHA-256>","sources":{"settings.json":"<evaluated SHA-256>"},"result":"PASS","command":["python","check_settings.py"]}
```

Pass that artifact OVR to verify. The artifact must not be part of its own source
basis. The runtime checks its exact requirement, meaning, source map and result,
then binds the artifact bytes. It cannot prove that a report's author ran its
command: retain actual execution output and have a reviewer assess the assertion.

After source changes, refresh in its own task-context batch. A changed hash makes
accepted evidence stale; passing-but-stale rules require re-verification. Failed
rules and affected dependent claims are demoted with previous acceptance retained.
Refresh can cross a lane boundary only for these context-covered regression
updates; unrelated lanes are untouched. OGM status definitions remain the README's
definitions. Freshness is an additional observation, not a fourth organism status.

## Measured comparison

`scripts/evaluate_context.py --model <model> --effort <effort> --repetitions 2`
runs matched Codex CLI trials with schema-constrained answers and JSONL usage.
Four synthetic states cover current evidence, passing-but-stale evidence,
regression plus a hard blocker, and unresolved authority. Each arm receives the
same frozen facts and instructions; Markdown and row JSON are renditions of those
facts, not historical version behavior. Receipts, byte accounting and checkpoint
hashes are excluded uniformly from this decision exercise.

The initial 24 trials all answered correctly. They establish a small baseline,
not an accuracy or long-term retention advantage. Input bytes and model usage are
reported separately; fixed Codex overhead and cache effects limit conclusions.
The evaluator retains every prompt, answer, event stream and failed attempt,
randomizes arm order with a fixed seed, detects tool use, and never automatically
retries ambiguous requests. The organism links the retained execution evidence.

`scripts/evaluate_development.py --model <model> --effort <effort>` extends the
comparison to five bounded development states: code edits, dependency regression,
ambiguous intent, cold context reconstruction and a subsequent nodule. Models
receive equivalent frozen facts and propose structured candidates. The host checks
bounded code behavior, applies only the allowed file to a disposable copy, verifies
evidence and executes the real lifecycle through a fresh Service. Record decision
correctness, exact constraint preservation, replay outcomes and native CLI usage
separately. This does not measure autonomous tool selection, long conversations,
or long-term retention. Results and failures belong in registered evidence.

## Bounded context delivery

`pacer_context_page(root, id, cursor="", max_bytes=8000)` and CLI
`context-page <PAC-ID> --cursor <cursor> --max-bytes 8000` deliver the complete
compact packet as readable `pacer-context-page/1` JSON. Page size is 2048..32000
canonical UTF-8 bytes. Ordinary `pacer_context` remains compatible; use pages
when its complete response would exceed a practical tool response budget.

Each page contains `task`, `packet_digest`, `max_bytes`, `offset`, `entries`,
`next_cursor`, `complete` and `receipt`. Entries have a JSON `path` array and
`value` to set that path. Oversized containers start with an empty container,
followed by child paths. Oversized strings start empty, followed by `append`
entries at the same path. Append in order without normalizing Unicode, whitespace
or escapes. This is transport segmentation, not a new requirement language.

Start with an empty cursor. Read every entry, then pass `next_cursor` unchanged
with the same task, root and byte limit until `complete=true`. Partial pages have
`receipt=null`. The final page has an empty cursor and the normal freshness
receipt. `pacer_mcp.pages.assemble_context_pages(pages)` validates the order,
complete stream, exact packet digest and canonical page layout, reconstructing
the identical compact packet including receipt and byte accounting.

Continuation re-reads the locked register snapshot and source basis. Changes to
source, authority or any delivered packet fact invalidate the cursor: restart
from an empty cursor. A cursor is an opaque continuation value, not a secret or
proof of reading. Final receipt checks still run at apply time; a caller fetching
only the final page has not followed the workflow. Receipt validity never proves
model comprehension or human approval. No server delivery sessions are stored,
so continuation works after a server restart if the complete packet is unchanged.

Missing sources, original packet sizes above 1000000 bytes, or indivisible path
metadata above the page limit refuse without a receipt. Paging preserves the
whole required closure; it does not lower total context size. Custom/audit fields
outside the original packet projection remain in the registers for targeted queries.

The bound covers canonical JSON text, also supplied as MCP `structuredContent`.
MCP envelopes and escaping add bytes; Codex applies a separate token budget and
may truncate tool output. Choose a smaller page or the documented per-tool
`output_token_limit` when needed. This plugin does not change user configuration.
The SDK 1.x `CallToolResult` path supplies identical canonical text and structured
values; stdio tests check both channels. The native proof uses official `codex
exec` JSONL and explicit MCP configuration pointing to installed plugin source.
It retains sequential model-selected page calls, a guarded checkpoint, and a
fresh-thread source-regression read. That bounded instructed workflow does not
establish autonomous development performance or long-term retention.

## Atomicity, scope and recovery

One OS-backed repository lock serializes readers and the applying writer across
CLI/MCP processes. Every write validates its expected revision and current
onboarding authority digest, builds the complete candidate web in memory, then
validates serialized temporary CSVs before publication. A transient journal with
before/after digests supports roll-forward after interruption. Multi-file rename
is not a filesystem atomic transaction: PACER readers refuse pending recovery,
and `recover` finishes only if every file still matches its recorded old/new
digest, including unchanged registers, then validates the reconstructed complete
candidate. Unknown edits stop recovery. The journal is not a fifth design register.

All register, archive and OVR paths are repository-relative and resolve inside
the chosen project root. Symlink escapes and alternate canonical copies fail.
The MCP server uses an explicit absolute project root supplied to each tool,
restricted by optional `--root` when running a project-bound server. A plugin
server can serve multiple projects explicitly; installed plugin cwd is not
silently treated as the user's project.

## Official integration references (fetched 2026-09-14)

- [Codex customization](https://learn.chatgpt.com/docs/customization/overview):
  AGENTS guidance, skills, MCP and plugin roles.
- [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp): stdio, configuration,
  server instructions, tools and startup policy.
- [Build skills](https://learn.chatgpt.com/docs/build-skills): SKILL.md discovery,
  progressive disclosure and optional agents/openai.yaml.
- [Package plugins](https://developers.openai.com/plugins/build/plugins):
  portable root manifests, supported compatibility layout and local marketplaces.
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk):
  queried through Context7; implementation pins the 1.x API and verifies installed
  signatures because indexed main examples also describe the developing 2.x API.
- [Codex portable MCP parser](https://github.com/openai/codex/blob/main/codex-rs/codex-mcp/src/agent_plugin_config.rs)
  and [compatibility parser](https://github.com/openai/codex/blob/main/codex-rs/codex-mcp/src/plugin_config.rs):
  source checks supplement official docs; installed CLI behavior is the acceptance
  check. Hook variable expansion must not be assumed for compatibility MCP args.
- [Codex app-server](https://learn.chatgpt.com/docs/app-server): documented JSONL
  initialization, native plugin/skill discovery and MCP calls. The verification
  script follows the JSON schemas generated by installed Codex 0.154.0.
- [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode#create-structured-outputs-with-a-schema):
  official `codex exec --output-schema`, `-o`, `--json` and usage event methodology
  used by the matched comparison. `openaiDeveloperDocs` supplied this reference.
