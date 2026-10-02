# Archive

Earlier lineages of PACER, kept as they were. Nothing here is installed, built, tested or read by the current product. File names keep their original spelling.

The current version is in `plugins/pacer/`; its history from 3.0.0 on is in `CHANGELOG.md`.

| Directory | What it is | Period |
|---|---|---|
| `pacer-agent-pack/` | The original prompt-only pack: one `AGENTS.md` and four register templates. No runtime. | predates the runtime |
| `pacer-0.5/` | Profile 0.5: the first runtime (`pacer_mcp`), an MCP server over four wide registers with context packets, receipts and approval columns. | 2026-09-14 to 2026-09-28 |
| `pacer-2.0.0/` | v2.0.0: the doctrine package. An indented `todo.PACER` plan, `.MIVIM.spec`, maturity tiers and continue-by-default, with a small parser and no registers. | added 2026-09-18 |
| `pacer-3.0-pre-baseline/` | PACER 3 as first built: cards and hooks over registers kept in the project root. Superseded by the 3.0.0 baseline, which moved state into `.pacer/` and rebuilt the runtime. | 2026-09-29 to 2026-10-01 |

## pacer-agent-pack

`AGENTS.pacer.zip`: `PACER/AGENTS.md`, `PACER/README.md`, and `PACER/TEMPLATES/` with `todo`, `overlord`, `organism` and `nodule` templates.

## pacer-0.5

| Path | Contents |
|---|---|
| `registers/` | this repository's own 0.5 registers at the moment of migration, and `nodules/` with the absorbed nodule files |
| `evidence/` | approval reports, context-delivery measurements, per-pace evidence (`pac-024` to `pac-036`), source inventories |
| `installers/` | `install.ps1` (the 0.5 installer), `scripts-install.ps1` (the forwarder that sat in `scripts/`), `test_install.ps1` |
| `logs/` | `00_master_error_log.txt`, `active_errors.txt`, `mypy_errors.txt` |
| `dist/` | the last 0.5 build: `pacer_mcp-0.5.0` wheel and source distribution |

The 0.5 source tree was rewritten in place rather than copied. Commit `9e642b0` is the last one holding it complete (`plugins/pacer/src/pacer_mcp/`, `scripts/`, the tests).

## pacer-2.0.0

| Path | Contents |
|---|---|
| `package/` | the v2.0.0 package: grammar, parser, contract, machine files, templates, tests, `todo.pacer` |
| `pacer_v2.0.0.zip` | the same package as distributed |
| `MIVIM.spec`, `pacer_manifest.txt` | the v2 doctrine files |
| `client-update-core.pacer.zip` | those two files as distributed |
| `organic-original-pacer_v2.0.0.md` | the original design description |

## pacer-3.0-pre-baseline

| Path | Contents |
|---|---|
| `FORMAT.md` | the format document derived from the first design |
| `implementation-plan.md` | the task-by-task plan the first build followed |
| `kit/` | sources of the first kit: `INSTALL.ps1`, `install.sh`, project templates |
| `pacer-3-KIT-3.0.0.zip` | the first kit as built |

The design that both the pre-baseline build and the baseline follow is current and lives in `docs/design/pacer-3-design.md`.

## Reading old projects

A project still in one of these formats is upgraded by the current runtime: `pacer migrate` recognises profile 0.5, v2.0.0 and pre-baseline 3.0 layouts.
