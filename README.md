# PACER

PACER keeps a project's working knowledge in five small registers and delivers the relevant part of it to a coding agent at the moments it acts: session start, after compaction, before and after every edit, and when it stops. The agent does not onboard, fetch or operate a database. It receives cards.

```
PACER my-project tier=integrated pace=PAC-041
PAC PAC-040 A2.P3 ACTIVE integrated | Title: Session handling | Binds: OGM-004 | Exit: sessions survive restart
PAC PAC-041 A2.P3.05 ACTIVE | Produce: session manager with expiry | In: OVR-012 | Out: src/session.py | Probe: pytest tests/test_session.py -q
DEC DEC-003 LATCH USER latched | Subject: OVR-012 | Chosen: keep the sync API; no async rewrite
OGM OGM-004 PACED_REQUIREMENT USER | Requirement: a session expires after 30 idle minutes | Probe: pytest tests/test_session.py -q | Evidence: rev:a1b2c3d exit:0 at:2026-09-20 STALE(src/auth.py)
OVR OVR-012 src/auth.py | Purpose: login and token checks | bound-by: OGM-004 | latch: DEC-003 | used-by: src/main.py, src/api.py
```

| Card | Register | One row per |
|---|---|---|
| PAC | `todo.pacer.csv` | area, phase or pace of work, with its position `A2.P3.05` |
| OVR | `overlord.pacer.csv` | source asset and its one-line purpose |
| OGM | `organism.pacer.csv` | requirement, the command that proves it, and the evidence |
| DEC | `decision.pacer.csv` | choice, lesson, failed approach, or a latch only the user answers |
| NDL | `nodule.pacer.csv` | scoped intake of new work, carrying the user's literal request |

State lives in `.pacer/` inside the governed project and is committed with it. It works with Claude Code and Codex, makes no model calls and needs no API key.

## Install

Requires [uv](https://docs.astral.sh/uv/), Python 3.11 or newer, git, and Claude Code or Codex.

```
uv run install.py                  # every host found, plus the `pacer` command
uv run install.py --host claude    # one host
uv run install.py --status         # what is installed where
uv run install.py --uninstall
```

Run it from a checkout of this repository or from an unpacked `releases/pacer-kit-<version>.zip`; the layout is the same. A host never runs two copies: the installer replaces any earlier one.

Codex delivers frames only with hooks enabled (`codex features enable hooks`) and after the plugin's hooks are trusted once (`/hooks`).

## Update

```
pacer update                       # the latest version, in every host, in one go
pacer update --check               # what is installed, what is on the origin, nothing changed
pacer update --notify off          # stop announcing new versions
```

When a newer version exists you hear about it once: after a `pacer` command in a terminal, or at the start of an agent session, with the two commands above. The check runs in the background at most once a day, through git. `pacer update` advances the source, refreshes only the hosts whose copy differs, and shows its progress on the Pace Line.

```
  PACER  update · 3.0.0 ▸ 3.1.0                         MIVIM · spec · vigiles
  ━━━━ ━━━━━━ ━━━━━━━━━━━━━━━━━ ━━━━━━━━━━━━ ━━━  ready in 12.8s

  ✓ resolve      v3.1.0 on origin
  ✓ source       fast-forward c8e16ee..4f0a1d2, 9 commit(s)
  ✓ Claude Code  pacer@mivim 3.1.0, 14 file(s) refreshed
  ✓ Codex        pacer@mivim 3.1.0, 14 file(s) refreshed
  · command      pacer command current

  Start a new session to load it.
```

## Use

```
cd <project>
pacer init                         # creates .pacer/
```

Then work with the agent. Ask it to pace a request; frames arrive on their own.

| When | The agent receives |
|---|---|
| session start, resume, after compaction | the active area, phase and pace; their decisions; bound requirements with evidence state; what comes next |
| a prompt names an ID, a path or a `#tag` | those cards |
| before an edit | the file's card, the requirements that bind it, the decisions on it, who uses it, `OFF-PACE` when it is outside the active pace |
| after an edit | what was recorded: the touch, a new asset, a followed rename, evidence gone stale |
| at stop | nothing, unless a gate blocks |

The same operations are available to you:

```
pacer frame session                pacer q OGM-004            pacer tree
pacer write --file ops.json --actor me                        pacer probe OGM-004
pacer validate                     pacer log PAC-041          pacer sync --apply
```

A project on an older PACER layout is upgraded in place with `pacer migrate` (preview) and `pacer migrate --apply`.

## Gates

| Tier | A stop is blocked when | An edit is denied when |
|---|---|---|
| sketch, prototype, playable | never | never |
| integrated | a bound probe failed | never |
| release | a bound probe failed or its evidence is stale | never |
| protected | as release | no user latch covers the file |

An open latch on the active work is the one question put to the user, once.

## Where things are

| Path | What |
|---|---|
| `plugins/pacer/` | the product: runtime, hooks, skill, manifests for both hosts |
| `plugins/pacer/skills/pacer/references/format.md` | the format reference |
| `install.py` | the installer; `pacer update` runs it again from the latest version |
| `MIVIM.pipeline` | the hierarchy PACER belongs to: MIVIM, spec, vigiles |
| `releases/` | built kits |
| `docs/` | repository map, design record, trial records |
| `archive/` | earlier lineages, frozen |
| `scripts/` | development checks and the kit builder |

`docs/structure.md` explains every entry and where new things go.
