# Trials for update delivery (3.1.0)

2026-10-02. Windows 11, uv 0.9.5, git 2.53.0, Claude Code 2.1.287, Codex CLI 0.160.0 with hooks enabled and the plugin's hooks trusted. Everything below was run; what was not is listed at the end.

## 1. Why the `pacer` command is editable

Measured before the design was fixed. With a `pacer serve` running from the uv tool environment:

| Command | Result |
|---|---|
| `uv tool install --force plugins/pacer` | the package installs, then `Failed to install entrypoint … pacer.exe … being used by another process (os error 32)` |
| `uv tool install --force --editable plugins/pacer` | the same: environment updated, launcher copy refused |

`pacer update` itself runs from that launcher, so the launcher must never need replacing. An editable install makes the command run the source tree; the environment is rebuilt only when the project's version, interpreter or dependencies change, and a refused launcher copy in that case is reported as "launcher in use, kept", since the environment did update.

## 2. The notice reaches the person

Set up by writing `latest = 9.9.9` into the real state file, then restoring it.

| Where | What happened |
|---|---|
| hook, `session-start` | output became JSON: `hookSpecificOutput.additionalContext` holds the frame; `systemMessage` holds the three-line notice. The frame the model receives is unchanged |
| Claude Code, `claude -p … --output-format stream-json` | the `hook_response` event carries that JSON; the documentation defines `systemMessage` as "Warning message shown to the user" on every event except `Notification` and `StopFailure` |
| Codex, `codex exec` | the hook ran (SessionStart `Completed`, no `Failed`), the notice was consumed; `exec` printed nothing of it, and the rollout records only `hooks.additional_context` |
| a second session, either host | nothing: the notice is said once per version |
| `pacer frame session` with stderr piped | nothing: the terminal notice goes only to a terminal |

## 3. Live update on this machine

`pacer update` from the development checkout, plain mode (stdout piped), both hosts holding copies that differed from the source in 14 files:

```
PACER update 3.0.0
  ok  resolve        v3.0.0 on origin, current
  --  source         codex/operational-context current
  ok  Claude Code    pacer@mivim 3.0.0, 14 file(s) refreshed
  ok  Codex          pacer@mivim 3.0.0, 14 file(s) refreshed
  ok  command        pacer command installed
ready in 12.8s
Start a new session to load it.
```

The state file afterwards held the install record, the editable command's fingerprint, and the timings (Claude Code 3.9 s, Codex 5.8 s, command 0.5 s, resolve 1.2 s) that pace the next run.

A second run with nothing changed: every host stage `current`, headline `current`, no reinstall.

`pacer update --force --host codex` while four PACER server processes were running from the Codex copy (open Codex sessions): the copy was replaced in 4.3 s without the lock that defeated the earlier installer; Codex restarted its servers from the new copy (new process ids). The stop-by-path fallback was therefore not exercised live; it is covered by its unit test on the matching rule only.

A reinstall in Claude Code removed the project-scope enablement in `.claude/settings.json` on its first run. Fixed: a project-scope entry is the same installed copy enabled in one project and is now left alone; `claude plugin list --json` reports it with `projectPath`.

## 4. The source stage

Unit tests on a local bare origin tagged `v3.0.0` and `v3.1.0`: a checkout on a branch fast-forwards one commit; a checkout with a local commit is left alone and says `diverged … local work kept`; a kit becomes a managed clone at `v3.1.0` under the user home; a managed clone at the tag reports `current`. The real checkout here reported `codex/operational-context current, 1 local commit(s) ahead`.

## 5. The detached check

`spawn_refresh()` on Windows uses `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW` with every standard handle on the null device. A test spawns it for real against the local origin and waits for the state file to carry `latest = 3.1.0`; the hook that spawns it returns without waiting. The slot is claimed before the spawn, once a day.

## 6. The display

Captured with `PACER_DISPLAY=live` into a file: 70 frames for a 5-second journey, cursor hidden at the start and restored at the end, every frame inside synchronized-output markers, no visible line wider than the terminal. Frames rendered to HTML and viewed on dark and light backgrounds: the night-to-ice line, the gold lantern and the mint marks read on both.

## 7. The checks and the installer

`python scripts/check.py` runs as a journey; a failed stage's output is printed after the ledger. `uv run install.py --status` from the repository root works without a project file. The test suite: 121 tests.

## Not verified

| Item | Why |
|---|---|
| How Codex's interactive interface renders `systemMessage` from SessionStart | only `codex exec` was run, which prints nothing of it; Codex's documentation lists `systemMessage` among the fields SessionStart supports |
| `stop_servers` against a copy that is actually locked | Codex 0.160 replaced the copy without a lock this time; the earlier lock was observed with Codex's own servers from a different copy |
| The kit path on a machine without a checkout | tested against a local origin only |
| Either host on macOS or Linux | no such machine here |
