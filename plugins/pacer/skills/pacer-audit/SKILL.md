---
name: pacer-audit
description: Audit PACER register integrity and compare design claims with changed source, tests and evidence. Use for PACER health checks, pre-commit review, stale work, reference drift or completion verification.
---

Read project authority and run `pacer_onboard`, then `pacer_validate`. Inspect
only rows implicated by failures, current changes or the user's audit scope.
Use `pacer_query` projections and bounded `pacer_graph` neighborhoods.
For an active PAC, retrieve `pacer_context` and inspect typed rules, dependencies,
source hashes, diagnostics and checkpoint deltas. Compare `pacer_evaluate` outcomes
with stored freshness; structurally valid data may still have stale acceptance.
Use a separate `refresh` batch with the current task receipt to record regressions
across the packet's affected requirements. Unrelated lanes remain untouched.

Separate three checks:

- Mechanical integrity: schema, IDs, dependencies, evidence presence, paths,
  reciprocal links, lane ownership, timestamps and archived reference resolution.
- Source correspondence: every changed file has a FILE OVR row; public and
  cross-file symbols have their own rows; literal imports/exports and dependency
  edges agree with source. A structurally valid register can still be stale.
- Acceptance truth: actual test or audit evidence supports each completion
  claim against current source and live requirements. A nonempty evidence cell
  alone does not prove behavior.
  In operational scope, verify requires a current deterministic rule or a registered
  source-bound manual report. Verify the command's real execution and preserve
  its output. Check final source identity after the last edit, then complete work.

Compare changed paths with overlord and inspect the relevant source/tests.
Use the repository's declared validation commands; preserve failed evidence and
repair the root cause. Record significant findings as Notes, failed approaches
as PreviousAttempts and durable lessons as LearningNotes. Demote regressed
requirements with the offending PAC/commit rather than retaining false completion.
The organism is the design history; do not add a separate changelog.

For format or archive questions, query the schema and read the relevant section
of [FORMAT.md](../../references/FORMAT.md). Recovery never discards conflicting
edits. Audit findings should identify the exact row, source path, evidence and
remaining work. Only absorb a nodule whose original criteria have been met.
