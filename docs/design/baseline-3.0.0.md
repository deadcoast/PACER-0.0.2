# The 3.0.0 baseline: decisions

2026-10-02. What changed between the first PACER 3 build and the baseline release, what else was considered, and why each choice was made. `pacer-3-design.md` explains PACER 3 itself; this document covers the revision.

## What was wrong

The first build delivered the design's behaviour and inherited its surroundings from the versions it replaced.

| Symptom | Cause |
|---|---|
| Six files and a 3.8 MB ledger in every governed project's root, and the runtime wrote into the project's own `archive/` | registers stayed where profile 0.5 had put them |
| The project frame was called `.MIVIM.spec` | v2.0.0's file name was reused for a different file |
| The package was `pacer_mcp` | profile 0.5's name was kept "so the installer keeps working" |
| Six manifest and MCP files in the plugin | each lineage's set was kept beside the next; none was checked against a running host |
| Three installers in two languages, a kit with a second marketplace identity | each delivery step added one |
| v3 design, plan and kit lived inside the v2 folder | new work was filed next to what it replaced |
| A moved file blocked every later write | a missing asset was a validation error |
| The repository's asset register described files deleted weeks earlier | nothing retired rows |

One defect was found only by measuring: with the manifests the first build shipped, **Codex never ran PACER's hooks**. A root `plugin.json` was present, and Codex 0.160 registers no plugin hooks when it is. The earlier trial notes say a live Codex session was not exercised.

## Decisions

### 1. State lives in `.pacer/`

| Option | Outcome |
|---|---|
| Registers in the project root (as built) | root clutter; the ledger pollutes every search; the runtime needs a second directory for archives |
| **One tracked directory, `.pacer/`** | chosen |
| State outside the repository | not shared with collaborators or other machines; loses the git history of decisions |

A dot-directory is where both hosts and most tools put their per-project files, and searches skip it by default. `run/` inside it is ignored by a `.gitignore` the directory carries itself, so a project needs no change to its own ignore file. A `.gitattributes` beside it turns off end-of-line conversion: with `core.autocrlf` on, a checkout rewrote every register and PACER then rewrote them back.

The marker for a governed project is `.pacer/project.pacer.toml`, found by walking up from the working directory, so hooks and the CLI work from any subdirectory.

### 2. Names

Lowercase `<name>.pacer.<ext>` everywhere on disk; `PACER` in capitals only as a name in prose. The frame is `project.pacer.toml`: it says what the file is and carries no other version's name. All names are defined in one module, `layout.py`.

### 3. Relations are stored once

`overlord.Binds`, `overlord.Latch` and `todo.Latch` mirrored `organism.Binds` and `decision.Subject`. Two stored directions can disagree, and validation existed mostly to detect that. The reverse view is now computed when a card is rendered and shown in lowercase (`bound-by`, `latch`) so a derived field cannot be mistaken for a writable one.

### 4. Every register has an archive

The first build archived only absorbed nodules, into the project's `archive/nodules/`, one file each. Finished paces, superseded decisions and rows for deleted files stayed live forever; this repository's asset register was 93% dead rows.

Now `archive` moves any finished row to `.pacer/archive/<register>.pacer.csv`. The live web is closed: retiring a row strips it from live references, and validation refuses a live reference to an archived row. An ID stays taken and stays queryable. Decisions whose every subject retires go with them; requirements and assets never cascade, because retiring those is a judgement.

### 5. A missing file is an observation

| Option | Outcome |
|---|---|
| Validation error (as built) | one `git mv` made every subsequent write fail, including the hook's own |
| A `#dead` tag the agent must add | bookkeeping the runtime can do itself |
| **Warning, a derived `missing` flag, and automatic rename following** | chosen |

Hooks read staged renames from git and pair an unstaged delete with a new file of the same name and identical content. `repath` does it by hand for a file or a directory. `sync` retires what is truly gone.

### 6. The runtime needs nothing installed

| Option | Hook cost | Outcome |
|---|---|---|
| `uv run --locked --project <plugin> pacer hook` (as built) | 0.2 to 0.3 s warm, 1.1 to 1.8 s first call, a virtual environment per plugin version | one third-party lock library forced an environment for a path that runs on every edit |
| A compiled launcher | fastest | a build per platform for a 0.2 s call |
| **Standard library only; start by file path** | 0.19 s, no first-call cost, no environment | chosen |

The file lock is one small module over `msvcrt` and `fcntl`. Only the MCP server keeps a dependency (`mcp`), in its own locked environment. A test parses every other module and fails on a third-party import; another runs a hook on an isolated base interpreter.

uv still picks the interpreter, because `python` on a user's PATH may be absent, a store stub, or too old. Measured: it uses a project's own `.venv` when that satisfies `>=3.11`, falls through to another interpreter when it does not, and never modifies it.

### 7. One manifest and one MCP file per host

Measured on Codex 0.160.0, each row a live session:

| Layout | Hooks registered | `${PLUGIN_ROOT}` resolved in MCP config |
|---|---|---|
| root `plugin.json` with `extensions.com.openai.hooks` | no | yes |
| root `plugin.json` plus `.codex-plugin/plugin.json` | no | yes |
| `.codex-plugin/plugin.json` only | **yes** | no |
| Claude files only | yes | no |

No layout gives both through placeholders. The shipped one is the third, with an MCP entry that needs none: `cwd: "."` resolves against the plugin root. Claude Code keeps its own pair. The portable root manifest is documented as Codex's primary format; it is left out until Codex loads hooks through it, because its presence disables them today.

Codex passes hooks to PowerShell on Windows and substitutes nothing into the command, so each hook carries a `commandWindows` reading `$env:PLUGIN_ROOT`. Claude Code ignores that key and substitutes `${CLAUDE_PLUGIN_ROOT}` itself.

### 8. One installer, one marketplace, one kit

| Option | Outcome |
|---|---|
| PowerShell and shell installers kept in step (as built) | the same logic twice; three copies existed |
| Documentation only: "run these host commands" | leaves duplicate copies on machines that had an earlier install |
| **`install.py`, standard library, run through uv** | chosen |

It removes every other installed copy of the plugin and any marketplace that existed only to serve one, reinstalls from this directory (hosts do not refresh a plugin whose version is unchanged), and reports the Codex hook setting. `--status` answers what each host runs.

The repository root is the marketplace, named `mivim`. The kit is the same layout minus tests, built from the files git knows, so there is no second identity and no staging directory. `check.py` compares the committed kit with a fresh build by content.

### 9. One Python project

A root workspace and a second lock file existed so the development environment would not sit inside the plugin directory, which hosts copy verbatim or run in place. The cost was two locks that could drift. Now the plugin is the only project, and `scripts/check.py` places the environment at the repository root and every cache under `.cache/` through environment variables. The product directory stays free of generated files under the documented commands.

### 10. Smaller corrections

- A probe runs with the project lock released. It held the lock for up to two minutes, stalling every hook, and deadlocked on any command that used PACER.
- The tier rule existed twice and disagreed: validation ignored the project tier. One function serves both.
- The session frame showed "no open work" for a project whose paces were all INTEGRATED. Open work is every pace that is not DONE; finished paces leave the frame.
- A superseded decision could still be delivered through the ranked fill.
- A shell command registered every file it created as an asset. Only a deliberate edit does now.
- A project on an older layout was silently ignored. Session start now names the upgrade.
- The tree view is indented ordinary cards. The first build printed a v2-style header above it.

## Not done, and why

| Item | Reason |
|---|---|
| Portable Agent Plugins manifest | disables hooks in the current Codex; see decision 7 |
| A `bin/` launcher for the `pacer` command inside the plugin | Claude Code only; the MCP tools serve both hosts and `uv tool install` serves people |
| An `AGENTS.md` block for governed projects | the rules that must always hold arrive in the MCP server's instructions and the frames; a copied block would go stale |
| Symbol-level asset rows registered automatically | the provider derives structure; hand-kept symbol rows were the stalest part of the old register |
| A licence file | not the developer's to choose |
