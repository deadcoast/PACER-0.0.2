# Modulation

A modulation is a way to compress a large development map without deleting task detail.

## Principles

- Global tasks remain globally visible.
- Related tasks are grouped into development phases.
- Paces are consumed inside the phase, not treated as independent project identities.
- Phase exit means “coherent operational state,” not “all possible polishing complete.”
- The next phase may refine the previous one without invalidating it.

## Example

```text
GLOBAL G020 "Directory tagging product"
  PHASE P01 "Terminal rebase"
    PACE ...
  PHASE P02 "Core tree language"
    PACE ...
  PHASE P03 "Motion + topology"
    PACE ...
  PHASE P04 "Reliability + scale"
    PACE ...
```

A large number of paces is acceptable. What PACER avoids is treating every pace as a fresh project with independent context and a mandatory human gate.
