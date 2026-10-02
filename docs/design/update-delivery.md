# Update delivery: decisions

2026-10-02. How PACER announces, performs and ships an update, what else was considered, and why.

## What was asked

Updating had been a struggle: reinstall into each host, chase a locked copy, rebuild the kit, re-prove, then merge, push and tag by hand. The request was one command for all of it, a display worth watching while it runs, a notice that a new version exists, said once, with the update command and a way to silence it, and the MIVIM hierarchy built in for what comes after PACER.

## Decisions

### 1. Versions are tags, read with git

| Option | Outcome |
|---|---|
| GitHub releases API | needs a token for a private repository; one host's API |
| A version file fetched over HTTPS | needs hosting; another credential |
| **`git ls-remote --tags` on the origin** | chosen |

Git already has the credentials that cloned the repository, and the same call works on any git host. The background check runs it with `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never` and a no-op `GIT_ASKPASS`, so it can only fail quietly, never pop a prompt out of a hook. A release is therefore exactly a tag, and `scripts/release.py` is the only thing that makes one.

### 2. The notice is said once, and never to the model

| Option | Outcome |
|---|---|
| Every run, like pip | rejected by the request |
| Once per channel | a person in two hosts would see it twice |
| **Once per version, whichever channel comes first** | chosen |

Channels: a terminal, after any `pacer` command, to stderr and only when stderr is a terminal; and the start of an agent session, through the host's `systemMessage`, which Claude Code shows to the person and keeps out of the model's context. The frame the model receives is unchanged. The state that makes it once lives in the user-level home, shared by every project.

Silencing (`pacer update --notify off`) stops the background check as well as the notice: a silenced PACER makes no network calls on its own.

### 3. The check never runs inside a hook

A hook runs on every edit. The check is spawned detached (`DETACHED_PROCESS` and `CREATE_NO_WINDOW` on Windows, a new session elsewhere) with every standard handle on the null device, so the hook's own output pipe is not inherited and the host never waits on it. The slot is claimed before spawning, so a burst of hooks starts one check, and at most one a day.

### 4. The source advances by its kind

| Source | What `pacer update` does |
|---|---|
| a checkout on a branch | `git fetch`, then `git merge --ff-only` when clean and behind; local commits or edits are never overwritten, the stage says so and the rest proceeds from the local source |
| PACER's own clone under the user home (`managed`) | fetch tags, check out the latest `v*` tag |
| an unpacked kit | clone the latest tag into the managed location and continue from there |

A developer's checkout is the common case on this machine: `pacer update` there is "sync every host from the tree", and a pull happens only when it is safe.

### 5. The host is synced when its copy differs, not when the version does

Hosts refresh nothing on their own, and version strings do not change between edits. Each host's installed copy is compared with the source file by file (caches and environments left out); only a differing, missing or duplicated copy is reinstalled, and the text says how many files changed. The same comparison makes `--status` and `--check` exact.

A project-scope enablement in Claude Code is the same installed copy enabled in one project; refreshing the copy is enough, and the project's setting is left alone.

### 6. A copy in use is unlocked, not reported

On Windows the MCP servers running from an installed copy lock it. They are PACER's own processes, found by path under the host's plugin cache, stopped, and the removal is retried. Nothing else on the machine is touched.

### 7. The `pacer` command is an editable tool

Measured: uv cannot replace `pacer.exe` while a `pacer` process runs, which is exactly `pacer update`'s situation. With `uv tool install --editable`, the launcher never changes between versions and the command runs the source directly, so advancing the source advances the command. The environment is rebuilt only when the project's version, interpreter or dependencies change, and if that happens while the launcher is running the environment still updates and the launcher is kept.

### 8. One display for update, install, check and release

| Option | Outcome |
|---|---|
| a progress library | a dependency on the hook path, and someone else's look |
| a spinner | shows nothing about how far along the work is |
| **the Pace Line** | chosen |

One line, segmented per stage, each segment as long as the stage is expected to take, so the line moves at an even pace. The expectation comes from the last run on this machine. Within a stage the line approaches the segment's end without reaching it, so it never stalls and never lies. The leading edge carries a lantern that breathes and a glint runs the drawn line while work is in progress; when the last stage ends, the line completes and the light is gone. A journey has three renderings: live (a terminal), plain (a log), events (JSON lines between processes).

The events form is what lets an update draw one continuous display across two processes: the old `pacer update` renders, the new `install.py` reports, so the installer that runs is always the version being installed.

Colour: night indigo to ice for the line, a gold lantern, a mint check and a red cross. Chosen to read on dark and light backgrounds alike, which was checked by rendering captured frames on both.

### 9. The lineage is data

`MIVIM.pipeline` declares the hierarchy; `pacer.identity` repeats it as constants; a test holds the two together. The runtime shows it in the display signature, keeps the user-level home under `mivim/pacer` so a later MIVIM tool has a place beside it, and ships the file in the kit.

## Not done

| Item | Reason |
|---|---|
| Automatic updates | an update restarts the host's servers; that is the person's moment to choose |
| A notice inside the model's context | the model cannot act on it and it would cost every session |
| Pre-release channels | one line of versions is enough until there is a reason for two |
