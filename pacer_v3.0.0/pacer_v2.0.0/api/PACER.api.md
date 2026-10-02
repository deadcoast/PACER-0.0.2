# PACER v2 API / Command Semantics

PACER is primarily a prompt/workflow language. The included Python utility exposes three non-destructive commands.

## `pacer audit <todo.PACER>`

Reports anti-patterns such as:
- one-pace phase fragmentation;
- mandatory REVIEW parking;
- excessive user-gate density;
- missing continuation loop;
- repeated approval latch requests.

Warnings are advisory. The auditor never changes project state.

## `pacer theatre <todo.PACER> [--phase ID]`

Compiles the smallest actionable context frame for the requested/active phase:
- global objective;
- phase objective and paces;
- inherited sources;
- phase-local sources;
- exit condition;
- continuation rule.

It deliberately does not dump the entire WELL.

## `pacer summary <todo.PACER>`

Prints counts and active state without interpreting it as a release gate.
