# PACER v2 Operating Guide

## 1. Plan globally; work locally

PACER should know the whole route without forcing the agent to carry every source token into every step.

The agent maintains:

- **WELL** — global project map, prior decisions, source anchors, future dependencies.
- **THEATRE** — active phase, relevant sources, nearby dependencies, exit condition, next known phase.

A pace consumes THEATRE. The agent queries the WELL only when the work crosses an unrepresented boundary.

## 2. Modulate work into coherent phases

A good PACER plan groups work by a development area that can be integrated and reasoned about as one system.

Bad:

```text
TASK 1 -> user review
TASK 2 -> user review
TASK 3 -> user review
...
```

Good:

```text
GLOBAL: Terminal visual language
  PHASE: hierarchy + topology
    PACE: rail grammar
    PACE: focus route
    PACE: whitespace allocation
    PACE: transaction choreography
  EXIT: coherent terminal visual system
  :loop⠁:
```

The paces can still be individually tracked. Their existence does not imply separate developers, separate context, or separate user ceremonies.

## 3. Build through the phase

For each active phase:

1. **ORIENT** — compile THEATRE from global plan + source anchors.
2. **BUILD** — implement the next cohesive pace or small group of paces.
3. **INTEGRATE** — write the change into the actual project system; avoid detached islands.
4. **SELF-CHECK** — run tests, inspections, research, simulation, sub-agent review, or local experiments needed to continue confidently.
5. **REPAIR** — if self-check exposes an ordinary defect, fix it. Do not convert it into a user gate.
6. **ABSORB** — consolidate approved nodules/state where applicable.
7. **LOOP** — run `:loop⠁:` and advance to the next eligible pace.
8. **CHECKPOINT** — only at a coherent operational state, explicit user request, or true authority blocker.

## 4. User feedback is steering, not process fuel

The user may test/play/use the current coherent state and report what feels wrong. PACER must accept that feedback and route it into the next phase/pace without requiring the user to sign every preceding micro-decision.

If the user does not test a trivial implementation, development does not freeze. The agent may proceed using project sources, research, documentation, sub-agents, or bounded assumptions.

## 5. Tests are subordinate evidence

Testing answers questions such as:

- did the implementation behave as intended?
- did a previous invariant regress?
- is the current phase coherent enough to continue?

Testing is not itself the project roadmap. A passing test does not mean “development complete”; a failing ordinary test means “repair and continue.”

## 6. Guardrails follow maturity

Prototype-stage PACER should maximize learning and integrated progress. Release-stage PACER should maximize preservation, migration safety, reproducibility, and protected-content integrity.

Do not import shipping-team sign-off structure into the first proof of concept.
