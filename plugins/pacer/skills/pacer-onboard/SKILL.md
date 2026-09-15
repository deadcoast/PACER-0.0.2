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
Ready queries exclude pending/withdrawn proposals. If no work is ready, query
`ApprovalState=PENDING` as needed and use a user's already supplied decision;
absence of ready work is not permission to invent approval. Compact context
edges index the packet's `required_ids` and `relations.kinds`; the schema explains
this wire encoding, and `encoding=expanded` supplies the compatible explicit view.

If live registers are absent and the user has requested PACER setup, use
`pacer_initialize` after the project authority files exist. It never imports
worked examples. If legacy columns are missing, inspect `pacer_schema` and the
[format reference](../../references/FORMAT.md), then preview migration. Preserve
existing work and resolve invalid data before publishing a migration.

Before source edits, query overlord with `where={"Path":"repo/relative/path"}`.
An absent row requires registration alongside the source change. Follow specific
IDs with `pacer_context(root, id=<PAC>)`. Treat its columnar tables, typed relations,
rule outcomes and source deltas as the working context. `complete=false` requires
resolving the diagnostic or increasing the explicit byte budget; it never grants
a write receipt. Use projected queries for investigation and `pacer_schema` for
the rule vocabulary. Do not rebuild project context as a Markdown design document.

For bounded responses use `pacer_context_page` from an empty cursor. Read all
entries and follow every `next_cursor` with the same byte limit until complete;
only the final page provides the receipt. Restart on drift. Consult FORMAT.md
for exact path/value and long-string append semantics and transport limits.

On resumption, inspect `next_action`, `delta`, `diagnostics` and the task's retained
failed approaches. A checkpoint lives in the task register and works in a fresh
process. Read source files implicated by the packet; source hashes are identities,
not source content. Check `stale_evidence` even when structural validation passes.

The onboarding digest identifies current authority bytes; it does not prove
that the instructions were understood. Explain the relevant purpose, scope and
invariants before developing. Report actual incomplete states without calling
scaffolding complete. A pending recovery journal needs `pacer_recover`; if
recovery reports conflicting edits, retain the journal and reconcile the files.
