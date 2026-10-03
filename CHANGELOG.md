# Changelog

## 3.1.0 — 2026-10-03
Updates and releases become one command each, with a display worth watching.

### Update

- `pacer update` advances the source (a fast-forward of a checkout, a tag for a managed clone, a clone for an unpacked kit), syncs each host whose installed copy differs from the source byte for byte, keeps the `pacer` command editable, and records how long each stage took so the next run is paced to it.
- A newer version is announced once, in whichever comes first: a terminal after a `pacer` command, or the start of an agent session, where the host shows it to the person and keeps it out of the model's context. The notice carries the update command and the silence command (`pacer update --notify off`). The check behind it runs detached, at most once a day, through git and the credentials git already has.
- `pacer update --check` reports the installed version, the latest on the origin, and each host's sync state without changing anything.
- Installed copies in use are handled: PACER's own servers running from a copy that is being replaced are stopped by path and the removal is tried again.
- The `pacer` command is an editable uv tool, so updating the source updates the command; the launcher, which Windows will not let a running `pacer update` replace, never needs replacing.

### Display

- The Pace Line: one line cut into segments, one per stage, sized by how long each stage takes; drawn from night to ice with a lantern at the leading edge and a glint that travels the drawn line while work is in progress. Thirty frames a second in a terminal; one line per finished stage anywhere else; JSON events between processes, so an update draws one display across the old code and the new.
- `install.py`, `pacer update`, `scripts/check.py` and `scripts/release.py` are all journeys on it.

### Release

- `scripts/release.py <version>` writes the version everywhere it lives, runs the checks, builds the kit, syncs the hosts, proves this repository's requirements again, commits, tags `v<version>` and pushes. The tag is what `pacer update` looks for.

### Lineage

- `MIVIM.pipeline` at the repository root declares the hierarchy PACER belongs to: MIVIM, spec, vigiles. The runtime carries it in `pacer.identity`, shows it in every display, keeps the user-level home under `mivim/pacer`, and a test holds the two to each other.

## 3.0.0 — 2026-10-02

The baseline release of PACER 3. Earlier lineages (the agent pack, profile 0.5, v2.0.0) and the pre-baseline 3.0 builds are frozen under `archive/`.

### Format

- All state for a project lives in one tracked directory, `.pacer/`: `project.pacer.toml`, five registers, `ledger.pacer.jsonl`, `archive/`, and an untracked `run/`. Nothing is written to the project root.
- File names are lowercase `<name>.pacer.<ext>`. The project frame is `project.pacer.toml`; the name `.MIVIM.spec` belongs to v2.0.0 and is no longer used.
- Each relation is stored once. `overlord.Binds`, `overlord.Latch` and `todo.Latch` are gone; cards show the reverse view as derived fields `bound-by` and `latch`.
- Every register has an archive. `archive` retires finished rows, `absorb` retires a nodule, and live rows never reference archived ones.
- A missing asset file is a warning and a `missing` flag on its card, not a validation error. `pacer sync` retires such rows.
- `.pacer/.gitattributes` turns off end-of-line conversion so state is byte-identical in every clone.

### Runtime

- The Python package is `pacer` (was `pacer_mcp`). Everything except the MCP server uses the standard library only.
- Hooks start by file path on a bare interpreter, about 0.2 s per call, with nothing to install first.
- New operations: `archive`, `repath`. New commands: `pacer sync`, `pacer migrate` with source detection, `install.py --status`.
- Hooks follow renames: staged ones from git, unstaged ones by matching content. A shell command no longer registers files; only a deliberate edit does.
- A probe runs with the project lock released, so it may use PACER itself and may run longer than a hook waits. Its timeout is set in the project frame.
- The session frame treats every pace that is not DONE as open work and leaves finished paces out.
- One tier rule is shared by validation and the gates; the project tier counts in both.
- A project still on an older layout is named in one line at session start instead of being silently ignored.

### Distribution

- One marketplace, `mivim`, at the repository root. One installer, `install.py`, for both hosts and every platform. One kit, built by `scripts/build_kit.py` in the same layout as the repository.
- One manifest and one MCP file per host. The portable root `plugin.json` is not shipped: Codex 0.160 does not load a plugin's hooks when it is present.
- `pacer migrate` upgrades profile 0.5, v2.0.0 and pre-baseline 3.0 projects, previewing first and keeping imported originals under `.pacer/archive/import-<source>/`.

### Verified

Recorded in `docs/trials/baseline-3.0.0.md`: the test suite on Python 3.11 to 3.14, live sessions in Claude Code and Codex with every hook event, and migrations of two real projects from 0.5 and 2.0.
