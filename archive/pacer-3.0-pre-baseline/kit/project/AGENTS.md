# AGENTS.md — this project is governed by PACER 3

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

## Cards

```
PAC PAC-041 A2.P3.05 ACTIVE prototype | Produce: … | In: OVR-012 | Out: src/x.py | Binds: OGM-004 | Probe: … | Next: implement
OVR OVR-012 src/a.py integrated | Purpose: … | Binds: OGM-004 | Latch: DEC-003 | used-by: src/main.py (+3)
OGM OGM-004 PACED_REQUIREMENT USER release | Requirement: … | Probe: pytest -q | Evidence: rev:a1b2c3d exit:0 at:2026-09-20 STALE(src/a.py)
DEC DEC-003 LATCH USER latched | Subject: OVR-012 | Chosen: … | Why: …
NDL NDL-019 ACTIVE lane=auth | Intent: … | Targets: OGM-004 | Spawned: PAC-040;PAC-041 | Exit: …
```

Tools: `pacer_q` to read, `pacer_write` to change (add set link move status latch pace absorb), `pacer_probe` to prove.
