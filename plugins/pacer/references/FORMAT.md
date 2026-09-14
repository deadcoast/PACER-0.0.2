# PACER executable profile 0.2

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

Rows supplied to `pace` have explicit IDs. Use `next_ids` to suggest unused
numbers, then rely on the revision precondition to detect competing allocations.
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
