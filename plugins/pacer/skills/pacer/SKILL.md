---
name: pacer
description: PACER 3 card grammar and write lexicon. Use when reading a PACER frame, querying an ID, path or #tag, recording work, decisions or evidence, or pacing new scope into a PACER-governed project.
---

Frames arrive by hook; you do not onboard. Every line is a card:

    PAC PAC-041 A2.P3.05 ACTIVE prototype | Produce: … | In: OVR-012 | Out: src/x.py:Foo | Binds: OGM-004 | Probe: … | Next: implement
    OVR OVR-012 src/a.py:S integrated | Purpose: … | Binds: OGM-004 | Latch: DEC-003 | used-by: src/main.py (+3)
    OGM OGM-004 PACED_REQUIREMENT USER release | Requirement: … | Probe: pytest -q | Evidence: rev:a1b2c3d exit:0 at:2026-09-20 STALE(src/a.py)
    DEC DEC-003 LATCH USER latched | Subject: OVR-012 | Chosen: … | Why: …
    NDL NDL-019 ACTIVE lane=auth | Intent: … | Targets: OGM-004 | Spawned: PAC-040;PAC-041 | Exit: …

Head tokens are positional: PAC `Pos Status Tier`; OVR `path[:symbol] Tier`; OGM `Status Authority Tier`; DEC `Kind Authority latched|open`; NDL `Status lane=`.

Read: `pacer_q(root, "<ID|path|#tag|register|register:STATUS>")` returns cards; an ID also returns its neighbours within distance 2.

Write: `pacer_write(root, [ops], actor)` with `add{register,row}`, `set{id,fields}`, `link{id,field,target[,remove]}`, `move{id,pos}`, `status{id,status}`, `latch{id,latched,evidence}`, `pace{nodule,tasks,requirements,decisions}`, `absorb{id}`. Batches are atomic; every change lands in `ledger.PACER.jsonl`.

Prove: `pacer_probe(root, "OGM-004", actor)` runs the Probe command and writes the Evidence cell. VALIDATED_COMPLETE requires `exit:0` and CURRENT; editing a bound file makes evidence STALE automatically.

Runtime-enforced: cells within limits and free of `|`; IDs immutable; `Needs` gates DONE; LATCH latched needs Authority USER; one ACTIVE nodule per lane; PACE at tier ≥ integrated needs a Probe.

Behaviour: continue through paces. A `DEC … LATCH … open` card is the only reason to ask the user, and you ask once; record the answer with `latch`. `OFF-PACE` on an edit card means the path is outside the active pace's In/Out: pace it or move on. `#unpurposed` OVR rows need a Purpose before phase exit. New scope enters through `pace`; positions `A<area>.P<phase>.<pace>` inherit context; PHASE rows carry Exit and Tier.

Tiers: sketch, prototype and playable never block; integrated blocks stop on a FAILED probe; release blocks on FAILED or STALE; protected denies edits without a USER latch.
