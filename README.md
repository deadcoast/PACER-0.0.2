# PACER — Project Actions, Constraints & Evidence Register

You are an agent reading this because a PACER repository governs the project you are about to work on. This file tells you what PACER is. `AGENTS.md` tells you how to operate inside it. Read both before touching anything.

## What PACER is

PACER is the project's central nervous system, built for agents. It converts what the user asks for in natural language into structured, cross-referenced development data: what the source code contains, what connects where, what requires what, what exports and imports what, and what state every piece is in. It replaces bloated design markdown and loose JSON with row-addressable CSV — you never load a document, you load a query result. `grep` an ID or a `#tag` and you receive exactly the rows that matter, with references that cascade outward only as far as you follow them. That is the anti-context-bloat contract: rigid IDs, rigid columns, targeted retrieval.

Everything connects. Everything works together or it dies. The registers live beside the source code and update with it — a living system, not documentation that rots.

## The four organs

| File | Alias | State | Role |
|---|---|---|---|
| `todo.PACER.csv` | — | PERSISTENT | The task register. Actions, dependencies, definitions of done, AI-First guidance columns |
| `overlord.PACER.csv` | OVR | PERSISTENT | The MOC index. One row per source-code asset (file, module, class, function, config, schema): purpose, exports, imports, what it requires, what requires it |
| `organism.PACER.csv` | OGM | PERSISTENT | The global design map. One row per design requirement, each carrying a live status. This is the project's design doc AND its changelog — requirements enter, evolve, and reach validated completion here |
| `nodule.PACER.csv` | NDL | VOLATILE | A targeted addition plan. Temporary growth lane for a scoped source-code change; spawns tasks into the todo, then is absorbed into the organism and cleared |

**PERSISTENT** files are never removed or replaced — constantly updated, core to the project.
**VOLATILE** files are short-lived context injectors — absorbed by the system, then safely deleted (archived per `AGENTS.md`).

## The organism status vocabulary

Every organism row carries exactly one status:

- `VALIDATED_COMPLETE` — thoroughly developed; no traces of incomplete, dead, or scaffolded code; complete per the live PACER spec.
- `PACED_REQUIREMENT` — incomplete **because** it references, requires, imports, or exports to another part of the source code that is not yet developed. The blocking references live in `BlockedByOGM` / `OVRRefs` / `PACRefs` — follow them and you have the full dependency picture.
- `SCAFFOLD` — incomplete because it has not been developed past initial scaffolding.

Search these statuses and you get an instant project health map. Search a `#tag` across all four files and you get the cascading, contextually rich web around any asset — its design intent (OGM), its code reality (OVR), its pending work (PAC), and any active growth touching it (NDL).

## The lifecycle (user request → shipped code)

1. **User speaks** — an organic request in natural language.
2. **An agent PACES IT OUT** — the request becomes a `nodule`: intent, target assets (OVR refs), new assets to create, organism rows to add or update, spawned tasks.
3. **The nodule spawns PACs** into the todo. Work proceeds under todo lifecycle rules (`AGENTS.md`).
4. **Code lands.** Overlord rows are created/updated for every touched asset — exports, imports, connections, always current.
5. **Absorption.** When the nodule's criteria are met, its organism targets are updated (statuses advance toward `VALIDATED_COMPLETE`), its rows are absorbed, and the nodule is cleared — making room for the next targeted growth.

## The referencing grammar (rigid, everywhere)

- IDs: `PAC-###`, `OVR-###`, `OGM-###`, `NDL-###`. Unique within their file, never reused, never renumbered.
- Multi-refs within a cell: semicolon-separated (`OVR-002;OGM-003`). Commas are reserved for CSV.
- Tags: `#lowercase` freeform, shared across all four files — the cross-file search keys.
- A reference must resolve. A row pointing at an ID that does not exist is a broken synapse and fails validation.

## This package

```
PACER/
|-- TEMPLATES/
|   |-- todo.PACER.csv
|   |-- overlord.PACER.csv
|   |-- organism.PACER.csv
|   `-- nodule.PACER.csv
|-- AGENTS.md
`-- README.md
```

Templates ship with worked example rows demonstrating the cross-reference web (tagged `#template-example`, plus neutral rows showing a config/auth dependency chain). On instantiating a new project: copy `TEMPLATES/` contents to the repository root, keep the example rows until your first real rows exist if you need the pattern in front of you, then purge every example row before first commit. `AGENTS.md` governs everything after that.

## Executable PACER and agent integration

PACER is in active development. This repository now develops its own format and
Codex and Claude Code integration under its live root registers. Query them for design state and
work history; the examples in `TEMPLATES/` are never the project's actual status.

The [executable format profile](plugins/pacer/references/FORMAT.md) specifies
additive columns, the command lexicon, mixed dependency types and canonical
nodule archives. It records the rationale for resolving ambiguities in the
original templates. The four organs and their status meanings remain authoritative.

[PACER for Codex and Claude Code](plugins/pacer/README.md) contains the runtime and usage guide.
The installable plugin provides an official stdio MCP server, typed tools, schema
resources, an onboarding prompt and three skills: onboard, develop and audit.
The CLI and MCP use the same validating writer. The server requires explicit
project roots and does not substitute its installed directory for your project.

For this repository, the root uv workspace owns `.venv`, `uv.lock` and development
dependencies. Its `pacer-mcp` member is the package in `plugins/pacer`. Use the
existing Python 3.14 selected by `.python-version`:

```powershell
./install.ps1
uv sync --locked
uv run --locked pacer --root . onboard
uv run --locked pacer --root . query todo --ready
uv run --locked pacer --root . validate
uv run --locked python scripts/check.py
uv build --package pacer-mcp
```

Commands run inside `plugins/pacer` or with `--project plugins/pacer` also use
the root environment. Do not activate or recreate `plugins/pacer/.venv`.
The root is a development project; build the named `pacer-mcp` package as above.
Keep the root and member `dev` groups aligned so syncing either project retains
the development tools. The plugin retains its own lock for standalone Codex/Claude installs;
uv ignores that member lock inside this workspace. After runtime dependency changes,
refresh the root lock and regenerate the plugin lock from a copy outside the workspace.

For a new project, `pacer initialize` creates empty real registers and indexes
the project's existing README.md and AGENTS.md. This is preferable to copying
worked example data into live state. Migration preserves existing rows and extra
project columns; it previews before publishing and refuses unresolved evidence
or reference errors.

Run `./install.ps1` again after source changes to refresh both live CLI plugins.
It shows file progress and retains full logs under `.cache/install/logs/`.
After installing, start a new agent session and invoke `$pacer:pacer-onboard`
in Codex or `/pacer:pacer-onboard` in Claude Code.
The plugin's [usage guide](plugins/pacer/README.md) includes native installation
verification and the boundary between structural validation and agent judgment.

Profile 0.5 makes PACER the shared operational representation between the user's
wording and the agent's development work. It preserves that wording, assigns
explicit authority to requirements, evaluates bounded rules, retrieves sufficient
task context, and binds acceptance to source and dependency freshness. Durable
checkpoints reconstruct the next action and changed context in a fresh process.
The four registers remain canonical; MCP serves compiled views and applies the
command lexicon. Required Markdown entry points bootstrap discovery and explain
the format; project meaning and lifecycle state live in PACER.

Use `pacer context <PAC-ID>` for work context and `pacer evaluate <OGM-ID>` to
inspect a rule. New scope uses `ContextPolicy=REQUIRED`, then current context
receipts accompany changes. A source change can make evidence stale even while
the rule still passes. The [format reference](plugins/pacer/references/FORMAT.md)
defines the distinction and the measured comparison's limits.

Approval-pending proposals now have an explicit gate independent of task status.
The context wire encoding shares IDs and relation kinds without dropping required
facts; an expanded compatibility view remains available. Migration preserves
historical meaning and evidence while leaving current verification explicit.

Large packets can be retrieved through `pacer context-page <PAC-ID>` or
`pacer_context_page`. Follow every cursor to receive the complete context and
final receipt. Pages preserve readable values and reject continuation after
source or context changes. This bounds individual JSON responses; it does not
reduce the full required context or establish a model accuracy advantage.
