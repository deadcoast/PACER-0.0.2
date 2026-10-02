# PACER plugin

One plugin for Claude Code and Codex: hooks that deliver card frames, an MCP server for explicit reads and writes, and one skill that carries the grammar. It makes no model calls and needs no API key. A project's state stays in that project's `.pacer/` directory.

## What is in this directory

| Path | Read by | Purpose |
|---|---|---|
| `.claude-plugin/plugin.json` | Claude Code | plugin manifest |
| `.mcp.json` | Claude Code | MCP server; paths through `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PLUGIN_DATA}` |
| `.codex-plugin/plugin.json` | Codex | plugin manifest; names the hooks, skills and MCP file |
| `.codex-plugin/mcp.json` | Codex | MCP server; `cwd` relative to the plugin root |
| `hooks/hooks.json` | both | five events, one entry point |
| `skills/pacer/` | both | card grammar and operations; `references/format.md` is the format reference |
| `src/pacer/` | | the runtime |
| `pyproject.toml`, `uv.lock` | uv | the MCP server's locked environment |
| `tests/` | | not part of the kit |

Each host reads one manifest and one MCP file; everything else is shared. There is deliberately no root `plugin.json`: Codex 0.160 stops loading a plugin's hooks when one is present (measured, `docs/trials/baseline-3.0.0.md`).

## How it starts

Hooks run on every edit, so they start without an environment:

```
uv run --no-project --no-python-downloads --python ">=3.11" "<plugin>/src/pacer/__main__.py" hook <event>
```

uv only picks the interpreter. Everything outside `server.py` and `models.py` uses the standard library alone, which a test enforces. A hook call takes about 0.2 s. Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}` into `command`. Codex substitutes nothing and exports the same variable instead: its POSIX shell expands it in `command`, and on Windows, where it runs hooks in PowerShell, it uses `commandWindows` with `$env:PLUGIN_ROOT`.

The MCP server is the one part with a dependency (`mcp`):

```
uv run --locked --no-dev --project <plugin> pacer serve
```

Its environment is built from `uv.lock` on first start, which needs network access: under Claude Code in the plugin data directory (`venv/`, kept across updates), under Codex in `.venv/` inside the installed copy. uv never downloads a Python: 3.11 or newer must already be installed.

## Prerequisites

uv, Python 3.11 or newer, git (for rename following and evidence revisions), and Claude Code or Codex. In Codex, hooks must be enabled (`codex features enable hooks`) and the plugin's hooks trusted once (`/hooks`).

## Working on the plugin

From the repository root:

```
python scripts/check.py              # lint, format, types, tests, manifests, registers, kit
python scripts/check.py --matrix     # tests on Python 3.11 to 3.14
claude --plugin-dir plugins/pacer    # run a session against the working tree, no install
python -B plugins/pacer/src/pacer/__main__.py frame session
```

`check.py` keeps the environment in `.venv/` at the repository root and every cache under `.cache/`: hosts copy this directory verbatim, so nothing may be generated inside it.
