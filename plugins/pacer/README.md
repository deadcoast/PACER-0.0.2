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
preview, apply, migrate and recover tools, schema resources and an onboarding
prompt. The first 512 characters of its initialization instructions describe the
essential workflow. CLI failures use nonzero exits; MCP failures use tool errors.

PACER checks structure and workflow transitions. It does not mechanically prove
that arbitrary evidence is honest or that every changed source file was indexed.
The audit skill and repository verification command handle those boundaries.
Source-defined organism statuses remain unchanged.

`python scripts/prove_codex.py` installs into a disposable Codex home and proves
native skill discovery plus a real MCP onboarding call without a model turn.
`python scripts/prove_codex.py --installed` checks your current installation.
Run these from the repository root using its uv environment. First startup may
download the dependencies already pinned in uv.lock. Python downloads are disabled.
