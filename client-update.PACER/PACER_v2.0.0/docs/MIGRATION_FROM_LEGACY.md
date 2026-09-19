# Migration from Legacy PACER Behavior

## Old pattern

`TODO → DOING → REVIEW → DONE` was often interpreted as mandatory user-facing lifecycle. In practice this caused micro-review parking and context resets.

## v2 interpretation

Canonical lifecycle:

```text
TODO → ACTIVE → INTEGRATED → DONE
```

`REVIEW` is evidence metadata, not a required state. A legacy task found in REVIEW should be normalized according to reality:

- implementation still changing → `ACTIVE`;
- implementation coherent and checks complete → `INTEGRATED`;
- project scope actually complete → `DONE`.

Do not ask the user to re-review merely because the legacy file says REVIEW.

## Legacy one-task files

Do not delete useful detail. Absorb related tasks into a modulated phase and preserve their identifiers as pace IDs/source references.

## Guardrails

Convert generic validation/user-test gates into one of:

- internal self-check;
- phase exit evidence;
- true user-authority gate.

Only the third blocks progression.
