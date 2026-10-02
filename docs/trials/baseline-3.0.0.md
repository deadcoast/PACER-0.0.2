# Trials for the 3.0.0 baseline

2026-10-02. Windows 11, uv 0.9.5, git 2.53.0, Claude Code 2.1.287, Codex CLI 0.160.0. Everything below was run; where something was not, it says so at the end.

## 1. Test suite

`python scripts/check.py --matrix`

| Check | Result |
|---|---|
| ruff check, ruff format | clean |
| mypy on `src/pacer`, `scripts/`, `install.py` | clean |
| pytest, development interpreter | 91 passed |
| pytest on Python 3.11, 3.12, 3.13, 3.14 | 91 passed on each |
| `claude plugin validate` on the plugin and on the marketplace | passed |
| kit matches sources | 39 files |

The suite includes a hook started on an isolated base interpreter (`python -I`), a probe over a real stdio MCP session, lock exclusion across processes, and every migration source.

## 2. Hook start

Best of five, session frame of this repository:

| Command | Wall time |
|---|---|
| `uv run --no-project --no-python-downloads --python ">=3.11" <plugin>/src/pacer/__main__.py hook session-start` | 0.198 s |
| `python <plugin>/src/pacer/__main__.py hook session-start` | 0.206 s |

uv adds nothing measurable; the time is interpreter start and import. No environment is created.

Which interpreter uv picks, checked in a directory holding a Python 3.11 `.venv`:

| Request | Interpreter used | The `.venv` |
|---|---|---|
| `--python ">=3.11"` | the `.venv`'s 3.11 | unchanged |
| `--python ">=3.13"` | a 3.13 from outside | unchanged |

## 3. Claude Code, live session

Scratch project at tier `integrated` with one area, phase, pace, requirement, latch and asset. One headless turn (`claude -p`) asked for an edit, a `pacer_q` and a `pacer_probe`. Hook calls traced through `PACER_HOOK_LOG`:

| Event | Payload keys of note | Output |
|---|---|---|
| session-start | `source=startup` | the session frame, 7 cards |
| prompt | `prompt` | the OGM card the prompt named |
| pre-edit | `tool_name=Edit`, `tool_input`, `tool_use_id` | the edit frame for `src/a.py`: asset, bound requirement, latch, active pace |
| post-edit | `tool_response` | `pacer: touched src/a.py` |
| stop | `stop_hook_active` | nothing; `Next` written as `integrate` |

The MCP server started from a new environment in the plugin data directory. `pacer_probe` recorded `exit:0`, state CURRENT. The ledger shows `touch` (hook), `probe` (the agent), `checkpoint` (hook), in that order. Whole turn: 24 s.

`hooks.json` carries a `commandWindows` key for Codex on every hook. Claude Code ran all five with it present.

Observed later in an interactive session, with the plugin also enabled at project scope and this checkout registered as the marketplace: Claude Code started the MCP server with `--project <checkout>/plugins/pacer`, the working tree, not its cache copy. The environment was still the one in the plugin data directory. `claude plugin list` then shows `pacer@mivim` once per scope, both pointing at the same installed copy.

## 4. Codex, live sessions

Codex was run with `codex exec --enable hooks --dangerously-bypass-hook-trust`: hooks are disabled in this machine's configuration and a plugin's hooks otherwise wait for review, so both were overridden for these invocations only.

### 4.1 Which manifest layout loads what

Each row is one live session against the installed copy, with a diagnostic hook that writes a file when it runs.

| Layout | Hooks registered | `${PLUGIN_ROOT}` resolved in MCP config |
|---|---|---|
| root `plugin.json` with `extensions.com.openai.hooks` | no | yes |
| root `plugin.json` without extensions, plus `.codex-plugin/plugin.json` | no | yes |
| `.codex-plugin/plugin.json` only, `mcpServers` to a file using `${PLUGIN_ROOT}` | yes | no, passed literally |
| `.claude-plugin/plugin.json`, `.mcp.json`, `hooks/hooks.json` only | yes | no, passed literally |
| **shipped:** `.codex-plugin/plugin.json`, MCP entry with `cwd: "."` | yes | not needed; `cwd` resolves to the plugin root |

With a root `plugin.json` present, Codex reported two hooks per event (both from another installed plugin and the user's own hook file) and never PACER's. It gave no warning.

### 4.2 How Codex runs a hook on Windows

From the diagnostic hook's output:

| Question | Observed |
|---|---|
| Shell | PowerShell: `$env:ComSpec` expanded, `%COMSPEC%` did not |
| `command` or `commandWindows` | `commandWindows` |
| Plugin root | `$env:PLUGIN_ROOT` set to the installed copy |
| Placeholders in the command string | not substituted |
| Parent environment | a variable set for `codex exec` (`PACER_HOOK_LOG`) was not visible to the hook |

### 4.3 End to end

Installed with `install.py`, same scratch project, one turn asking for an edit and a `pacer_probe`:

- Codex started three hooks per event; PACER's was among them.
- The agent quoted the first line it was given at session start, `PACER trial tier=integrated pace=PAC-003`, and the line after its edit, `pacer: touched src/a.py`.
- Ledger: `touch` by the hook after `apply_patch`, `probe` by the agent with `exit:0` and state CURRENT, `checkpoint` by the hook at stop.

## 5. Installer

`uv run install.py` on a machine holding an earlier install:

```
Claude Code   removed pacer@personal, removed marketplace pacer3, removed marketplace personal, installed pacer@mivim
Codex         removed pacer@mivim, installed pacer@mivim, reported that hooks are disabled
pacer command installed with `uv tool install`
```

`uv run install.py --status` afterwards: exactly `pacer@mivim 3.0.0` in each host, marketplace `mivim` pointing at this directory, exit 0.

Removing the earlier Codex copy failed once while two MCP servers from it were still running inside an open Codex session: on Windows a running interpreter locks its directory. Stopping those processes let the removal through.

## 6. Migrations

Run on shadow copies: the PACER files copied, every other tracked file present as an empty placeholder, since a migration only checks that asset paths exist. The projects themselves were not touched.

| Project | Source | Before | After | Rows live | Rows archived | Apply |
|---|---|---|---|---|---|---|
| image-riposte | 0.5 | 14.3 MB in four registers | 0.45 MB live, 48 KB archived | 57 PAC, 2,530 OVR, 30 OGM, 80 DEC | 6 OVR (file gone), 29 NDL | 1.3 s |
| tag-replicata | 2.0 | 10.9 KB plan | 11.8 KB | 53 PAC, 41 OVR, 1 DEC | none | 0.2 s |
| this repository | 3.0-root | 178 KB in five root registers, 19 nodule files, 3.8 MB ledger | 191 KB with the nodule archive | 47 PAC, 598 OVR, 33 OGM, 82 DEC | 19 NDL | under 1 s |

All three validated with no errors. Session frame afterwards: 0.17 s for image-riposte's 2,530 assets, 0.12 s for tag-replicata.

The tag-replicata result exposed a defect that was then fixed: every open pace there is INTEGRATED, and the frame reported "no open work" because only TODO counted as upcoming.

This repository's registers were then brought to the baseline with the runtime's own operations: 15 `repath` calls followed the reorganisation, one `archive` retired 716 rows (46 work rows of the legacy area and the first PACER 3 phase, 33 superseded requirements, 79 decisions about them, and 558 assets that were gone, moved into the archive, or symbol-level), and the baseline work was paced with two requirements and ten decisions.

## Not verified

| Item | Why |
|---|---|
| Either host on macOS or Linux | no such machine here. On those systems Codex runs `command` in a POSIX shell with `CLAUDE_PLUGIN_ROOT` exported, per its documentation; that path is unexercised |
| Codex's hook review flow (`/hooks`) | interactive; the trust requirement was bypassed for the trial runs |
| Frame re-delivery after a real compaction | not exercised live on any build. `SessionStart` with `source=compact` takes the same code path as `startup`, which was |
| The denied edit at `protected` tier in a live host | covered by tests at the hook boundary, not by a live session |
