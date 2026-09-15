# PACER for Codex

The PACER plugin gives Codex a local MCP server and three workflow skills:
onboard, develop and audit. It operates the project's four canonical CSV
registers through the same guarded engine used by the CLI.

The package uses OpenAI's portable Agent Plugins manifest and includes a Codex
compatibility manifest. Its runtime uses the official MCP Python SDK 1.x,
locked by uv. Python 3.11+ and uv must already be installed. It needs no OpenAI
API key and makes no model calls. Register data stays in the selected project.

From the PACER repository root:

```powershell
uv sync --project plugins/pacer --locked
uv run --project plugins/pacer --locked pacer --root . onboard
uv run --project plugins/pacer --locked pacer --root . query todo --ready
uv run --project plugins/pacer --locked pacer --root . query overlord --where Path=README.md
uv run --project plugins/pacer --locked pacer --root . validate
```

For another project, first read its README.md and AGENTS.md, then initialize
absent registers with `pacer --root <project> initialize`. Initialization never
copies example rows or overwrites existing registers. Consult
[the executable format](references/FORMAT.md) for migration and exact commands.

Install this repository's plugin with `./scripts/install.ps1` from the repository
root. It uses the official Codex plugin CLI and the explicit repository marketplace.
Start a new Codex thread after installation. Invoke `$pacer:pacer-onboard`,
`$pacer:pacer-develop` or `$pacer:pacer-audit`; Codex namespaces installed skills.
Use `/mcp` to inspect the running server. Each MCP
call takes an explicit absolute project root. A manually configured server can
be restricted to a single project by launching `pacer serve --root <project>`.

The portable plugin starts uv using its installed package root and keeps the
environment/cache in Codex's writable plugin data directory. No package path is
hardcoded. The compatibility configuration uses plugin-relative cwd; it does
not assume hook environment substitutions work in MCP command arguments.

The server exposes onboarding, query, graph, schema, validate, initialize,
context, evaluate, preview, apply, migrate and recover tools (12 total), schema resources and an onboarding
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
environment's executable open. After the official cachebuster update, synchronize
both manifest versions and set `mcp.json`'s `UV_PROJECT_ENVIRONMENT` to
`${PLUGIN_DATA}/venv-<first 16 hex characters of SHA256(version)>`. Packaging checks
enforce this relationship. Existing environments remain intact for their running
threads; cleanup happens only after those threads have stopped.
