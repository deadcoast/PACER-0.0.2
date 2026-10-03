# Trial: the human CLI layer, 3.2.0

2026-10-03, Windows 11, Claude Code 2.1.287, Codex 0.160.0, uv 0.9.5. What was measured in the hosts before the commands were written, and what the commands did when run for real on this machine.

## Measured before writing

**Claude Code, project scope.** In an empty git repository: `claude plugin install pacer@mivim --scope project` wrote `.claude/settings.json` containing only `{"enabledPlugins": {"pacer@mivim": true}}` and nothing else (no `extraKnownMarketplaces`). `claude plugin list --json` then listed a third `pacer@mivim` entry with `scope: project` and the `projectPath`. `claude plugin uninstall pacer@mivim --scope project --keep-data` removed the entry and left the file as `{"enabledPlugins": {}}`.

**Claude Code matches the project path as a string.** The same uninstall run from the same directory spelled with a different letter case (`C--Users…` against the recorded `c--Users…`) failed with "installed in user scope, not project". `Claude.enroll` therefore passes the resolved path as the working directory, and `Claude.enrolled` resolves both sides before comparing.

**Codex.** `codex features list` reports `hooks … true` as the unified switch; `plugin_hooks` is listed as removed. Plugins have one scope.

**uv.** `uv python find --no-project ">=3.11"` honours `VIRTUAL_ENV` from the caller's shell, so the doctor runs it without that variable and from the user-level home, to answer the question the hooks ask: can uv start an interpreter anywhere.

## `pacer doctor`, run from the working tree with uncommitted edits

```
PACER doctor 3.1.0
machine
  ok  uv             uv 0.9.5 (d5f39331a 2025-10-21)  C:\Users\…\uv.EXE
  ok  python         3.13.9  C:\Users\…\uv\python\cpython-3.13.9-windows-x86_64-none\python.exe
  ok  git            git version 2.53.0.windows.1
  ok  source         3.1.0 (checkout)  C:\Users\ryanf\github\ASSETS\PACER
  ok  origin         v3.1.0, current
  ok  home           C:\Users\ryanf\AppData\Local\mivim\pacer

hosts
  !!  Claude Code    15 file(s) differ from the source; pacer@mivim  3.1.0  (user, project scope)
   !  Claude Code cache stale copy: 3.0.0
  ok  Claude Code project enabled for PACER
  !!  Codex          15 file(s) differ from the source; pacer@mivim  3.1.0  (user scope)
  ok  Codex cache    one copy per installed version
  ok  Codex hooks    enabled
  ok  command        pacer v3.1.0
  ok  command path   C:\Users\…\pacer.EXE

project
  ok  registers      valid, 7 warning(s)
  ok  format         format 3.0
  ok  tracking       registers are tracked
   !  evidence       5 of 5 proven not current: OGM-034, OGM-035, OGM-036, OGM-037…
pacer doctor --fix repairs 3 of these
pacer probe OGM-034
```

Every row was true: the source had been edited since the hosts were synced, a `3.0.0` directory from the previous release was still in Claude Code's cache, and the edits had made the proven requirements stale. Exit 1.

## `pacer init <scratch> --claude`

```
PACER init proj2
  ok  registers      5 registers, tier prototype
  ok  Claude Code    pacer@mivim 3.1.0, 15 file(s) refreshed; enabled at project scope in .claude/settings.json
proj2 governed in 10.1s
Open a session in C:\…\scratchpad\proj2: the frame arrives at session start.
```

Afterwards the project held `.pacer/` (five registers, the ledger, the git settings files) and `.claude/settings.json` with the one enablement; `claude plugin list --json` showed the user entry, this repository's project entry and the new one, all at 3.1.0. Running the host sync first meant the user-scope copy was refreshed from the edited source in the same stage. The scratch entry was removed afterwards with the host's own uninstall.

## The prompts

Frames of the chooser and the field were captured with a scripted key source, converted with their 24-bit colours to HTML and viewed in Chrome on dark and light backgrounds: the lit rail reads as the Pace Line, the dim track rails recede, the lantern arrow marks the row, and the field's rail changes colour with the scan (mint, lantern, alarm). Interactive key reading was not exercised from this session, which has no console; the Windows path uses `msvcrt.getwch` with the documented `\x00`/`\xe0` prefixes for the arrow and edit keys, and the POSIX path reads escape sequences with a 30 ms window.

## After the release

To be appended once `scripts/release.py 3.2.0` has synced both hosts: `pacer doctor` with every host row `ok`.
