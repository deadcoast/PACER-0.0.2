---
name: pacer-onboard
description: Start or resume work in a PACER-governed repository by reading its authority and querying ready tasks, design health, active growth and source references. Use when onboarding to PACER or recovering project context.
---

PACER is Project Actions, Constraints & Evidence Register. It is the project's
connected working memory: todo records work, overlord maps source assets,
organism records design truth and its history, and nodules admit scoped growth.
The human develops the project; this skill guides the assisting agent.

Read the project's README.md, then its applicable AGENTS.md. Pass the user's
absolute project directory to `pacer_onboard`. The installed plugin directory
is not the project. Inspect ready tasks, organism status counts, active nodules,
validation results and the returned revision/onboarding digest.

If live registers are absent and the user has requested PACER setup, use
`pacer_initialize` after the project authority files exist. It never imports
worked examples. If legacy columns are missing, inspect `pacer_schema` and the
[format reference](../../references/FORMAT.md), then preview migration. Preserve
existing work and resolve invalid data before publishing a migration.

Before source edits, query overlord with `where={"Path":"repo/relative/path"}`.
An absent row requires registration alongside the source change. Follow specific
IDs with `pacer_graph`; use explicit column projections and pagination when
more detail is necessary. Do not dump all registers to rediscover the project.

The onboarding digest identifies current authority bytes; it does not prove
that the instructions were understood. Explain the relevant purpose, scope and
invariants before developing. Report actual incomplete states without calling
scaffolding complete. A pending recovery journal needs `pacer_recover`; if
recovery reports conflicting edits, retain the journal and reconcile the files.
