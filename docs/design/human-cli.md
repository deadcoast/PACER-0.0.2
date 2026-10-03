# The human layer of the CLI: decisions

2026-10-03. Why `pacer update`, `pacer init` and `pacer doctor` ask, show and repair the way they do, what else was considered, and why.

## What was asked

The command line worked for agents: every subcommand takes its arguments, prints JSON or cards and never asks. A person uses three of those commands almost exclusively, and for them the request was a human layer: `update` asks where when no host is named, `init` asks for the path and the agent when they are missing, `doctor` finds what is wrong and fixes it; everything visual, nothing bland, and a polish pass on whatever is touched.

## Decisions

### 1. Two layers, one command, decided by the terminal

| Option | Outcome |
|---|---|
| Separate commands for people (`pacer-ui`, `pacer wizard`) | two vocabularies for one thing |
| A `--interactive` flag | people would have to know to type it |
| **The same command; a prompt only when both standard streams are a terminal** | chosen |

`pacer update` in a terminal asks where; `pacer update` in a hook, a pipe or an agent's shell takes every host. `pacer init` with nothing typed asks for the path and the agent in a terminal, and off one does exactly what it did before: `.pacer/` here, one JSON document. The agent contract is untouched and the person is never asked to opt in. `PACER_DISPLAY=plain` turns the prompts off in a terminal too, the same switch that already turns the Pace Line off.

### 2. Keys from the standard library

| Option | Outcome |
|---|---|
| `prompt_toolkit`, `questionary`, `rich` | a dependency on the hook path; the runtime is standard library only |
| `input()` with a numbered menu | no animation, no live scan, no rail |
| **`msvcrt` on Windows and `termios` cbreak elsewhere behind one `Keys` protocol** | chosen |

Named keys (`up`, `enter`, `esc`, `tab`, …) and printable characters come from one `read(timeout)`. The timeout is what lets a prompt animate between keys. A `Scripted` source with the same `read` drives the tests, so every frame and every transition is checked without a terminal, and a `None` entry in the script is a quiet tick.

### 3. Prompts in the Pace Line's idiom

| Option | Outcome |
|---|---|
| A boxed menu with brackets and asterisks | the common form; rejected as such |
| A spinner beside the question | says nothing about the choice |
| **Options on rails: the chosen one lit night-to-ice with the lantern at its tip, the rest dim track** | chosen |

The chooser is the Pace Line's vocabulary applied to a choice: the same gradient, the same lantern and glint, the same signature header, and the same collapse to a ledger line (`✓ Claude Code`) when answered, so the terminal history reads as one display. The path field carries a rail under the text whose colour is the verdict of a live scan (mint, lantern, alarm) and a caret in the lantern's colour; the scan says what the directory is before the person commits to it. Both prompts hide the cursor, draw through the same region as a journey, and restore the terminal on the way out, including on ctrl-c.

### 4. What enrolling a project means

| Host | What `pacer init --<host>` does | Measured |
|---|---|---|
| Claude Code | install from the source if missing; `claude plugin install pacer@mivim --scope project` in the project | writes only `enabledPlugins` into `.claude/settings.json`; the entry is listed with `projectPath`, matched case-sensitively |
| Codex | install from the source if missing; report the hooks switch | plugins have one scope; `codex features list` names `hooks` |

A project that already has `.pacer/` keeps its registers (`registers · already governed, registers kept`) and is enrolled anyway, so `init` is the one command for "make this project run under PACER in this agent" whether or not the registers exist.

### 5. Doctor: rows with verdicts, repairs it owns, commands for the rest

| Option | Outcome |
|---|---|
| A single pass/fail with a log | hides what is wrong |
| Repair everything automatically | a probe can take minutes; a hooks trust review is interactive; a format migration is a decision |
| **Every check as a row; `--fix` applies the repairs the doctor owns; every other row names its command** | chosen |

Three groups: the machine, the hosts, the project. Owned repairs: a host whose copy differs from the source, stale cache copies, the `pacer` command, an interrupted write. Named commands: `pacer update` for a newer release, `pacer probe <ID>` for stale evidence, `codex features enable hooks` for a disabled switch, `pacer init <path> --claude` for a project not enabled at project scope, `pacer migrate` for an older format. After `--fix` the vitals are read again, so the second panel is the proof.

### 6. The hook path pays nothing for the human layer

Importing the host module costs about 45 ms, and the CLI parser runs on every hook call. The `--claude` and `--codex` flags are therefore built from `AGENTS` in `pacer.identity`, a two-entry mapping, and the host, prompt and doctor modules are imported only inside the commands that use them.

## What this changes for an agent

Nothing. `pacer init` without flags off a terminal prints the same JSON; `pacer update` in a script takes every host; `pacer doctor` is one more command whose exit code says whether the installation is sound. The MCP tools are unchanged.
