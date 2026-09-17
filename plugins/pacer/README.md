# PACER for Codex and Claude Code

The PACER plugin gives Codex and Claude Code a local MCP server and three workflow skills:
onboard, develop and audit. It operates the project's four canonical CSV
registers through the same guarded engine used by the CLI.

The package uses OpenAI's portable Agent Plugins manifest and includes a Codex
compatibility manifest, plus Claude Code's native plugin manifest. Its runtime uses the official MCP Python SDK 1.x,
locked by uv. Python 3.11+ and uv must already be installed. It needs no OpenAI
API key and makes no model calls. Register data stays in the selected project.

First run `./install.ps1` from the PACER repository root. This checkout requires
existing Python 3.14 (selected by `.python-version`), uv and the selected agent
CLIs. The installer prepares the shared workspace before installing the plugins.
Then use these development commands:

```powershell
uv run --locked pacer --root . onboard
uv run --locked pacer --root . query todo --ready
uv run --locked pacer --root . query overlord --where Path=README.md
uv run --locked pacer --root . validate
uv build --package pacer-mcp
```

Repository development uses Python 3.14 and one root `.venv` and `uv.lock`.
The root and member declare matching default development groups, so syncing either
retains the same tools. This member owns the runtime dependencies.
Running uv from this member directory also uses that root environment. Installed
plugin copies remain standalone Python 3.11+ packages and use their bundled
lock with `--no-dev` and a host-specific environment.

For another project, first read its README.md and AGENTS.md, then initialize
absent registers with `pacer --root <project> initialize`. Initialization never
copies example rows or overwrites existing registers. Consult
[the executable format](references/FORMAT.md) for migration and exact commands.

Run `./install.ps1` from the repository root after changing PACER. The same command
installs a missing plugin or refreshes an existing one in **both** Codex and Claude
Code. Both CLIs, uv and this checkout's Python 3.14 must already be installed. To update just one
host, use `-Agent Codex` or `-Agent Claude`. The old `./scripts/install.ps1` entry
forwards to the same installer. No repository test suite or model calls run during
installation.

Setup runs in this order:

1. Check the existing uv and selected agent CLIs; find the existing Python version
   from `.python-version`, with Python downloads disabled.
2. Run `uv sync --locked` against the repository root and its `.venv`. This installs
   the pinned package and development dependencies; it does not rewrite either lock.
3. Verify root and member imports use that environment and this checkout's PACER
   source. Preserve an obsolete `plugins/pacer/.venv` under `.cache/retired-environments/`.
   If a running process prevents the move, leave it intact, report the issue and
   continue with the verified root environment; close that process and rerun later.
4. Prepare the current plugin snapshot, then install or refresh each selected host.

All paths are anchored to the script location, so invocation from another working
directory is supported. Workspace commands override inherited project/environment
routing only in child processes. They leave your shell and unrelated environments
unchanged. Deactivate an old environment and reopen your terminal before further
development commands. A missing prerequisite, incompatible environment or stale
lock stops setup with the full diagnostic before any host installation changes.
Correct the reported cause and rerun the same command; no separate setup command
is required. Dependencies may need network access on first use.

The installer copies current files into `.cache/install/builds/`, gives changed
contents a distinct version, and registers that local marketplace through each
host's official CLI. It preserves tracked release manifests. Keep `.cache/install`
in place while the plugin is installed; run the installer again if you move this
checkout. Old snapshots remain available to running sessions. The progress bar
tracks actual files, with the current path below it in gray. During uv setup the
activity bar shows the latest uv output; host operations show their command and elapsed time. Redirected
output (or `-NoAnimation`) prints milestones without cursor animation. Every run
retains `install.log`, full command stdout/stderr and a `result.json` under
`.cache/install/logs/`. The result includes workspace verification and completed
host installations; failures include their diagnostic and exit nonzero.

Start a **new agent session after installation**, then invoke `$pacer:pacer-onboard`,
`$pacer:pacer-develop` or `$pacer:pacer-audit` in Codex, or `/pacer:pacer-onboard`,
`/pacer:pacer-develop` or `/pacer:pacer-audit` in Claude Code.
Use `/mcp` to inspect the running server. Each MCP
call takes an explicit absolute project root. A manually configured server can
be restricted to a single project by launching `pacer serve --root <project>`.

The portable plugin starts uv using its installed package root and keeps the
environment/cache in Codex's writable plugin data directory. No package path is
hardcoded. Codex's compatibility configuration uses plugin-relative cwd. Claude's
native `.mcp.json` uses `${CLAUDE_PLUGIN_ROOT}` in uv's `--project` argument and
`${CLAUDE_PLUGIN_DATA}` for writable dependencies/cache, so the server starts from
any project's working directory. These integrations follow the official
[Codex plugin format](https://developers.openai.com/plugins/build/plugins) and
[Claude plugin reference](https://code.claude.com/docs/en/plugins-reference).

The server exposes onboarding, query, graph, schema, validate, initialize,
context, context-page, evaluate, preview, apply, migrate and recover tools (13 total), schema resources and an onboarding
prompt. The first 512 characters of its initialization instructions describe the
essential workflow. CLI failures use nonzero exits; MCP failures use tool errors.

PACER checks structure, workflow, explicit rules and source-bound acceptance.
`pacer context <PAC-ID>` returns columnar state, typed relations, applicable rules,
source deltas and a receipt. New operational scope requires that receipt for
writes. `checkpoint`, `verify` and `refresh` use the shared mutation lexicon.
`pacer evaluate <OGM-ID>` observes a rule without changing its accepted status.
It does not mechanically prove that a manual report is honest or that every changed source file was indexed.
The audit skill and repository verification command handle those boundaries.
Source-defined organism statuses remain unchanged.

Profile 0.5 gates pending proposals with explicit approval provenance and admits
their existing IDs into a nodule. Default compact context shares relation IDs;
request `--encoding expanded` (MCP `encoding="expanded"`) for the earlier view.
Both formats preserve required facts, freshness and receipts. See FORMAT.md for
the migration and decoding contracts.

Use `pacer context-page <PAC-ID> --max-bytes 8000` or `pacer_context_page` for
bounded delivery. Pass the returned cursor to `--cursor` (MCP `cursor`) with the
same byte limit until complete. Read all pages before using the final receipt.
The JSON byte bound excludes MCP framing and Codex token truncation; see FORMAT.md.
`scripts/prove_context_delivery.py --plugin <installed-plugin> --model <model>
--effort <effort>` runs two authenticated Codex turns in disposable fixtures and
retains their tool calls, checkpoint persistence and fresh-thread regression result.

`python scripts/prove_codex.py` installs into a disposable Codex home and proves
native skill discovery plus real MCP onboarding, context and evaluation calls without a model turn.
`python scripts/prove_codex.py --installed` checks your current installation.
Run these from the repository root using its uv environment. First startup may
download the dependencies already pinned in uv.lock. Python downloads are disabled.

Portable MCP environments use a directory derived from the full manifest version.
This lets a new plugin start while an older Windows process still holds its
environment's executable open. For a published release, synchronize
both manifest versions and set `mcp.json`'s `UV_PROJECT_ENVIRONMENT` to
`${PLUGIN_DATA}/venv-<first 16 hex characters of SHA256(version)>`. Packaging checks
enforce this relationship. Existing environments remain intact for their running
threads; cleanup happens only after those threads have stopped.
