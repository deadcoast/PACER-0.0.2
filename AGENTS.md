# AGENTS.md — operating in a PACER 3 repository

The runtime enforces structure. These are the rules it cannot enforce.

1. **Frames are your context.** The session frame names the active pace, its phase, the requirements bound to it and the latches in force. Work from it. Do not rebuild project context as a Markdown design document.
2. **Continue.** A pace is not a user gate. Tests, research, tuning, refactors and sub-agent findings are yours to resolve. Stop only when the stop frame blocks or an `open` LATCH card appears, and ask that question once.
3. **New scope enters through `pace`.** A nodule carries the user's literal `Request`; its PACE rows carry an imperative `Produce`. Positions `A<area>.P<phase>.<pace>` are inherited context; never grow an active pace's Intent silently.
4. **Fill `Purpose`.** Edits register unknown files as `#unpurposed` OVR rows. Give each a one-line Purpose before the phase exits.
5. **Probes are proof.** A requirement advances to VALIDATED_COMPLETE only through `probe` with `exit:0` and CURRENT evidence. Prose in a cell proves nothing.
6. **Decisions are rows.** Record a choice, a failed approach or a lesson as a DEC bound to its subject; the compiler re-delivers it whenever that subject is in frame.
7. **`OFF-PACE` means decide.** Either pace the path into the active work or leave it alone.

## Gate matrix

| Tier | Stop blocks when | Edit denied when |
|---|---|---|
| sketch, prototype, playable | never | never |
| integrated | a phase-bound OGM probe FAILED | never |
| release | FAILED or STALE on a phase-bound OGM | never |
| protected | as release | no USER latch covers the path |

## Repository commands

```powershell
uv run --locked python scripts/check.py      # ruff, pytest, register validation; run before commits
uv run --locked pacer --root . validate
./install.ps1                                 # refresh the installed plugin after source changes
```

The root uv workspace owns `.venv` and `uv.lock`; the plugin's own `uv.lock` serves standalone installs and is regenerated from a copy outside the workspace after dependency or version changes.
