# Continuity Model

PACER v2 is designed to avoid the “50 different developers” effect.

## Fragmented model

Fifty isolated tasks each arrive with local context, local validation, local review, and a fresh mental reset. The agent repeatedly optimizes the current item without carrying the design pressure of adjacent work. The repository accumulates detached documents, duplicate checks, incompatible local abstractions, and process artifacts.

## Modulated model

The same work is represented inside a global development area and a finite number of integrated phases. Paces stay individually addressable, but they inherit:

- the global project objective;
- the active phase objective;
- decisions already made in the phase;
- shared source anchors;
- upcoming dependencies;
- the phase exit condition;
- the default continuation loop.

This makes the agent behave like one developer/team carrying a system forward rather than fifty unrelated contractors.

## The descriptor

The user-provided form:

```text
50[10]X[5]:(1:1:1:1:1:1:1:1:1:1)
```

is retained as a compact modulation descriptor. PACER does not make its arithmetic the authority over the task map. The descriptor communicates **grouping density and intended development rhythm**; `todo.PACER` remains canonical for the actual phase/pace content.
