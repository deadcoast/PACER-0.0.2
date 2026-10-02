# Changelog

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
