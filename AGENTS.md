# AGENTS.md — working in the PACER repository

This repository builds PACER and is governed by it. The plugin delivers frames from `.pacer/`; work from them.

## Operating rules

The runtime enforces structure. These are the rules it cannot enforce.

1. **Frames are your context.** The session frame names the active pace, its phase, the requirements bound to it and the latches in force. Do not rebuild project context as a design document.
2. **Continue.** A pace is not a user gate. Tests, research, tuning, refactors and sub-agent findings are yours to resolve. Stop only when the stop frame blocks or an `open` LATCH card appears, and ask that question once.
3. **New scope enters through `pace`.** A nodule carries the user's literal `Request`; its PACE rows carry an imperative `Produce`. Never grow an active pace silently.
4. **Fill `Purpose`.** A deliberate edit registers an unknown file as `#unpurposed`. Give it a one-line Purpose before the phase exits.
5. **Probes are proof.** A requirement reaches VALIDATED_COMPLETE only through `probe` with `exit:0` and CURRENT evidence.
6. **Decisions are rows.** Record a choice, a failed approach or a lesson as a DEC bound to its subject.
7. **`OFF-PACE` means decide.** Pace the path into the active work or leave it alone.
8. **Archive what is finished.** Live registers hold current work.

## Where things go

`docs/structure.md` is the map. The short form:

| Kind of thing | Place |
|---|---|
| anything a user installs or the runtime needs | `plugins/pacer/` |
| a check, a build step, a one-off development script | `scripts/` |
| a design decision, a measurement, a trial | `docs/design/`, `docs/trials/` |
| a built kit | `releases/` |
| anything superseded | `archive/<lineage>/`, with a line in `archive/README.md` |
| scratch, caches, environments | `.cache/`, `.venv/` (ignored) |

Three rules keep the product apart from the tooling that develops it:

- **Nothing generated goes in `plugins/pacer/`.** Hosts copy that directory verbatim or run it in place. `scripts/check.py` keeps the environment and every cache outside it.
- **The working tree is live.** With this checkout as the marketplace, Claude Code runs the plugin from `plugins/pacer/` directly, so a broken edit there breaks the frames of the session making it. Run `check.py` before leaving it broken.
- **No second copy of the product.** The sessions developing PACER use the installed plugin (`uv run install.py`) or `claude --plugin-dir plugins/pacer`. Do not add project-level skills, hooks or MCP entries under `.claude/` or `.codex/` that duplicate what the plugin ships.
- **A host-facing change is measured, not assumed.** Manifests, hook commands and MCP configuration change only with a live session in the affected host, recorded under `docs/trials/`.

## Commands

```
uv run --no-project --python ">=3.11" scripts/check.py              # lint, format, types, tests, manifests, registers, kit
uv run --no-project --python ">=3.11" scripts/check.py --fix        # apply lint fixes and formatting first
uv run --no-project --python ">=3.11" scripts/check.py --matrix     # tests on Python 3.11 to 3.14
uv run --no-project --python ">=3.11" scripts/build_kit.py          # rebuild releases/pacer-kit-<version>.zip
uv run --no-project --python ">=3.11" scripts/release.py X.Y.Z      # ship a release: version, checks, kit, sync, proof, commit, tag, push
pacer update --all                   # sync every host from the working tree (install.py does the same)
pacer update --check                 # what each host runs, and what the origin has
pacer doctor                         # the vitals of the machine, the hosts and this project; --fix repairs
pacer init <path> --claude           # govern another project and enrol it with a host
uv run --no-project --python ">=3.11" python -B plugins/pacer/src/pacer/__main__.py <command>   # the runtime from source
```

Every Python here starts through uv; nothing calls an interpreter from PATH. Run `check.py` before a commit. Rebuild the kit when anything under `plugins/pacer/`, the installer, the README or the changelog changes; `check.py` fails when the kit is stale. A release is `release.py` on a clean tree with a `## X.Y.Z` section in `CHANGELOG.md`; it is the only thing that tags, and the tag is what `pacer update` finds on other machines.

## Gate matrix

| Tier | Stop blocks when | Edit denied when |
|---|---|---|
| sketch, prototype, playable | never | never |
| integrated | a bound probe FAILED | never |
| release | FAILED or STALE on a bound requirement | never |
| protected | as release | no USER latch covers the path |

This repository runs at `integrated`.
