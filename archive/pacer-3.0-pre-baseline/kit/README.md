# PACER 3 kit

Everything a project needs to be governed by PACER 3: the agent plugin (Claude Code and Codex), a CLI, and the project files. Nothing here needs an API key or makes model calls. Register data stays in your project.

## What you get

```
PACER3-KIT-<version>/
  INSTALL.ps1  install.sh     one-time machine setup: plugin into Claude Code and/or Codex, `pacer` CLI on PATH
  marketplace/                the plugin as a local marketplace (both hosts read it)
  project/                    files to copy into a project: .MIVIM.spec, AGENTS.md, first-pace.json, gitignore
  docs/FORMAT.md              the format: registers, cards, frames, gate matrix, migration
  docs/CARDS.md               the card grammar and write lexicon (same text the agent's skill carries)
```

Prerequisites: `uv` (https://docs.astral.sh/uv/), Python 3.11+, and the agent CLI you use (`claude` and/or `codex`).

## 1. Install once per machine

```powershell
.\INSTALL.ps1                # both hosts it finds; -Agent Claude or -Agent Codex to pick one; -NoTool skips the CLI
```

```bash
./install.sh                 # same on macOS/Linux
```

This registers `marketplace/` as a local marketplace named `pacer3`, installs the `pacer` plugin, and puts the `pacer` command on your PATH with `uv tool install`. Start a new agent session afterwards.

## 2. Initialize a project

```powershell
cd <your project>
Copy-Item <kit>\project\.MIVIM.spec .          # edit name and tier
Copy-Item <kit>\project\AGENTS.md .            # or merge into an existing AGENTS.md
Get-Content <kit>\project\gitignore.snippet >> .gitignore
pacer --root . initialize                      # five empty registers, the ledger, and OVR-001 = README.md (OVR-002 = AGENTS.md)
pacer --root . write --file <kit>\project\first-pace.json --actor me   # optional worked area/phase/pace bound to OVR-001; edit the text first
pacer --root . frame session                   # what the agent will receive
```

Or ask the agent: "initialize PACER here and pace <your request>". It has `pacer_initialize` and `pacer_write`.

## 3. Work

Frames arrive by hook. Nothing to invoke:

| Moment | Hook | The agent receives |
|---|---|---|
| session start, resume, after compaction | SessionStart | active area, phase and pace; bound requirements with evidence state; latches and lessons |
| a prompt mentions an ID, path or `#tag` | UserPromptSubmit | those cards |
| before Edit / Write / apply_patch | PreToolUse | the file's card, its requirements, its latches, its dependents, `OFF-PACE` if outside the active pace |
| after an edit (or a Bash that changed files) | PostToolUse | touched paths recorded; unknown files registered `#unpurposed` |
| the agent tries to stop | Stop | blocks only per the tier matrix; writes the checkpoint |

Human commands mirror the agent's tools:

```
pacer --root . frame session|edit --focus <path>|prompt --focus "<text>"|stop
pacer --root . q <ID|path|#tag|register|register:STATUS>
pacer --root . write --file ops.json --actor <you>      # add set link move status latch pace absorb
pacer --root . probe OGM-004                            # run a requirement's Probe, record Evidence
pacer --root . tree                                     # indented plan view
pacer --root . validate
pacer --root . log [ID]
```

## Migrating

Profile 0.5 registers (`todo/overlord/organism/nodule.PACER.csv` with Notes columns): `pacer --root . migrate --from 0.5` previews; add `--apply` to publish. Old files move to `archive/pacer-0.5/`; every dropped cell lands in `ledger.PACER.jsonl`.

v2.0.0 plans (`todo.PACER` text): `pacer --root . migrate --from v2 --apply`.

## Tiers

`.MIVIM.spec` sets the project's default tier. `sketch`, `prototype` and `playable` never block. `integrated` blocks a stop when a bound probe FAILED. `release` blocks on FAILED or STALE. `protected` denies edits to a file unless a USER latch covers it. A PHASE row can raise the tier for its paces; an OVR row can raise it for one file.

## Uninstall

```powershell
claude plugin uninstall pacer@pacer3 ; claude plugin marketplace remove pacer3
codex plugin remove pacer@pacer3    ; codex plugin marketplace remove pacer3
uv tool uninstall pacer-mcp
```
