# Repository structure

What every entry is, who reads it, and where a new thing belongs. Four kinds of content live here and they do not mix: the product, the tooling that develops it, the record of how it was developed, and frozen earlier lineages.

```
README.md  CHANGELOG.md          what PACER is; what changed
AGENTS.md                        rules for agents working in this repository
install.py                       the installer (product; shipped in the kit)
ruff.toml                        lint settings for scripts/ and install.py, inherited from the product

.claude-plugin/marketplace.json  marketplace manifest, read by Claude Code
.agents/plugins/marketplace.json marketplace manifest, read by Codex

plugins/pacer/                   THE PRODUCT
  .claude-plugin/plugin.json       Claude Code manifest
  .mcp.json                        Claude Code MCP server
  .codex-plugin/plugin.json        Codex manifest
  .codex-plugin/mcp.json           Codex MCP server
  hooks/hooks.json                 hook wiring, both hosts
  skills/pacer/                    the skill; references/format.md is the format reference
  src/pacer/                       the runtime
  tests/                           its tests
  pyproject.toml  uv.lock          the one Python project and its lock

scripts/                         DEVELOPMENT TOOLING
  check.py                         every check, one command
  build_kit.py                     builds and verifies the kit

docs/                            DEVELOPMENT RECORD
  structure.md                     this file
  design/                          why PACER 3 is shaped as it is; decisions and options considered
  trials/                          measurements and live-session records

releases/                        built kits, one per version

.pacer/                          this repository's own PACER state
.claude/settings.json            enables the installed pacer@mivim plugin for sessions in this repository

archive/                         FROZEN LINEAGES; see archive/README.md
```

Ignored and local: `.venv/` (development environment), `.cache/` (tool caches and old scratch), `.codegraph/`, `dist/`.

## The product

`plugins/pacer/` is everything a user installs and the only place product code lives. Hosts copy the directory verbatim into their plugin cache, or run it where it sits: with this checkout registered as a local marketplace, Claude Code 2.1.287 starts the MCP server straight from `plugins/pacer/`. So two rules hold:

1. The repository's tooling generates nothing inside it. `scripts/check.py` points uv at `.venv/` in the repository root and sends bytecode, lint and type caches to `.cache/`. The one thing that does appear is `__pycache__/` written by a host running the plugin in place; git and the kit builder ignore it.
2. It stands alone. It carries its own `pyproject.toml` and `uv.lock`, and nothing in it refers to a path outside itself.

`install.py`, the two marketplace manifests, `README.md` and `CHANGELOG.md` are the rest of what ships. `scripts/build_kit.py` packs exactly these, minus `tests/`, into `releases/pacer-kit-<version>.zip` with the same relative layout, so the installer and manifests work unchanged from an unpacked kit. `check.py` fails when the committed kit does not match the sources.

Version numbers appear in `pyproject.toml`, `src/pacer/__init__.py` and both plugin manifests. A test holds them equal.

## Host-facing files

These locations are fixed by the hosts, not chosen here.

| File | Host | Why it is where it is |
|---|---|---|
| `.claude-plugin/marketplace.json` | Claude Code | a marketplace is a directory with this file; plugin sources are relative to it |
| `.agents/plugins/marketplace.json` | Codex | Codex's marketplace location for a repository |
| `plugins/pacer/.claude-plugin/plugin.json` | Claude Code | plugin manifest |
| `plugins/pacer/.mcp.json` | Claude Code | discovered by default at the plugin root |
| `plugins/pacer/.codex-plugin/plugin.json` | Codex | the manifest Codex 0.160 loads hooks from |
| `plugins/pacer/hooks/hooks.json` | both | default hook location in both hosts |
| `plugins/pacer/skills/` | both | default skill location in both hosts |

The Agent Plugins portable manifest (`plugin.json` and `mcp.json` at the plugin root) is deliberately absent. Codex 0.160 was measured with every combination: when a root `plugin.json` exists it resolves `${PLUGIN_ROOT}` in MCP configuration but never registers the plugin's hooks; without one it registers hooks but resolves no placeholders. Hooks are the product, so the Codex manifest stays and its MCP entry uses a plugin-relative `cwd`. The measurements are in `docs/trials/baseline-3.0.0.md`. Revisit when Codex loads hooks through the portable manifest.

## Development tooling

`scripts/` holds what develops the product and is never shipped. Both scripts use the standard library only and run with any Python 3.11 or newer.

The agent tooling used to develop PACER is the product itself, installed the normal way:

- `AGENTS.md` at the root carries the rules for this repository. Claude Code and Codex both read it.
- `.pacer/` is this repository's state, read by the installed plugin like any other project.
- `.claude/settings.json` holds one setting: it enables the installed plugin here. Neither `.claude/` nor `.codex/` carries project-level skills, hooks or MCP servers. Adding those would give a session two sources for the same skill and hooks: the installed plugin and the working tree. Develop against the working tree with `claude --plugin-dir plugins/pacer`, or reinstall with `uv run install.py`.

Neither host documents a layout for a repository whose product is itself agent tooling. Both document where a project's own agent configuration goes (`AGENTS.md`, `.claude/`, `.codex/`) and where a distributable plugin goes (a plugin directory under a marketplace). The separation above follows from that: the distributable lives in the plugin directory, and the project-configuration locations stay empty except for `AGENTS.md`.

## Development record

`docs/design/` explains decisions: what was chosen, what was rejected and why. `docs/trials/` records what was run and what it showed. A claim about host behaviour in the product, its README or this file should be traceable to a trial.

Decisions and lessons that govern ongoing work are also DEC rows in `.pacer/`, so they are delivered with the cards they concern.

## Archive

`archive/` is read-only history, one directory per lineage, indexed by `archive/README.md`. Nothing in the product, the scripts or the checks reads from it. Files there keep their original names, including the upper-case `PACER` of earlier versions.

## Where a new thing goes

| It is | It goes |
|---|---|
| code or data the runtime, a hook, the skill or a host needs | `plugins/pacer/` |
| a test of the product | `plugins/pacer/tests/` |
| a development check or build step | `scripts/`, called from `check.py` |
| a decision with its reasoning | `docs/design/`, and a DEC row |
| a measurement or a live-session record | `docs/trials/` |
| a release artifact | `releases/`, built by `scripts/build_kit.py` |
| something replaced by a newer version | `archive/<lineage>/`, with an entry in `archive/README.md` |
| temporary output | `.cache/` or the system temporary directory; never the repository root |
