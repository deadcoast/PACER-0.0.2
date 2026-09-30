# PACER plugin for Claude Code and Codex

The plugin ships one MCP server, one skill and one `hooks/hooks.json`. The hooks are the point: they call `pacer hook <event>` at SessionStart (including after compaction), UserPromptSubmit, PreToolUse and PostToolUse on edits, and Stop, and inject the compiled card frame. Nothing in the plugin needs an API key or makes model calls. Register data stays in the governed project.

## Install

Run `./install.ps1` from the PACER repository root. It needs an existing uv, the Python selected by `.python-version`, and the agent CLIs you want to target (`-Agent Codex` or `-Agent Claude` selects one). It syncs the root workspace, verifies imports resolve to this checkout, snapshots the plugin under `.cache/install/builds/`, and registers that local marketplace with each host CLI. Logs and a `result.json` land under `.cache/install/logs/`. Start a new agent session afterwards.

Installed plugin copies are standalone Python 3.11+ packages with their own `uv.lock`; the hook and MCP commands run `uv run --project <plugin root>` so they work from any project directory. `.mcp.json` pins `UV_PROJECT_ENVIRONMENT` to `${CLAUDE_PLUGIN_DATA}/venv-<first 16 hex of SHA256(version)>`; `mcp.json` does the same with `${PLUGIN_DATA}` for Codex. Packaging tests enforce that rule.

## Tools

| Tool | Purpose |
|---|---|
| `pacer_frame(root, kind, focus)` | `session`, `edit` (focus = path), `prompt` (focus = text) or `stop` frame |
| `pacer_q(root, query)` | cards for an ID and its neighbours, a path, a `#tag`, a register, or `register:STATUS` |
| `pacer_write(root, operations, actor, preview)` | `add set link move status latch pace absorb`, atomic, ledgered |
| `pacer_probe(root, id, actor)` | run an OGM's Probe and record its Evidence cell |
| `pacer_validate(root)` | structure, references, statuses, tiers, lanes |
| `pacer_initialize(root)` | create empty registers |
| `pacer_migrate(root, source, actor, preview)` | from profile `0.5` CSVs or a `v2` `todo.PACER` |
| `pacer_log(root, id, limit)` | ledger events |
| `pacer_recover(root)` | finish an interrupted publication |

Every tool takes the absolute project root. A server started with `pacer serve --root <project>` refuses other roots.

## Development

```powershell
uv run --locked pacer --root . frame session
uv run --locked pacer --root . q PAC-001
uv run --locked python scripts/check.py
uv build --package pacer-mcp
```

Repository development uses the root `.venv` and `uv.lock`. After a version or dependency change, run `uv lock` at the root and regenerate this plugin's `uv.lock` from a copy outside the workspace. The format is specified in [references/FORMAT.md](references/FORMAT.md).
