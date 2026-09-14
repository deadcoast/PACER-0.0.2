---
name: pacer-develop
description: Pace and execute development requests in PACER repositories, keeping tasks, source assets, requirements, evidence and nodule absorption connected through the guarded command lexicon.
---

Use the project's README.md and AGENTS.md as authority. Complete PACER onboarding
with `pacer_onboard` and query the target OVR rows before touching source.
Use [FORMAT.md](../../references/FORMAT.md) and `pacer_schema` when constructing
commands or migrating older columns; the four CSV registers remain authoritative.

Translate the user's authorized request into one scoped `pace` command: nodule
Intent, Lane, TargetOVR, NewAssets, OGMTargets and AbsorptionCriteria; spawned
tasks with explicit DoDs and dependencies; and any new provisional requirements.
Suggested unused IDs come from onboarding. Check the current active lanes.
Different lanes require disjoint affected assets. Scope beyond the active Intent
enters another nodule after resolving overlap. Do not weaken or erase admitted
scope to obtain absorption.

Use `pacer_preview` for a reviewable candidate when useful, then `pacer_apply`
with the current revision, onboarding digest and actor. The same lexicon is
available through the bundled `pacer` CLI. A stale revision means requery and
reconcile, not blindly resubmit. A stale onboarding digest means reread authority.
Respect existing user authorization; PACER adds no permission for external actions.

Execute TODO -> DOING -> REVIEW -> DONE. Return DOING -> TODO when appropriate;
review failures return REVIEW -> DOING. At most three tasks may be DOING per
agent. Split tasks exceeding 48 hours into narrower children while preserving
the parent DoD. Complete hard dependencies before DONE; soft/optional refs do
not gate. Record failed approaches and useful learning in their dedicated fields.

For every changed source file, update its FILE row and the public or cross-file
symbols referenced by consumers or requirements. Record literal exports/imports
and OVR dependency edges. The applying writer maintains reciprocal typed refs.
Source edits and their register changes belong in the same commit. Validation
checks recorded paths; inspect the changed file list to catch missing OVR rows.

Advance organism states only on evidence: SCAFFOLD means initial scaffolding;
PACED_REQUIREMENT means incompleteness caused by named unbuilt references;
VALIDATED_COMPLETE means the live requirement is implemented and verified.
Demote a completed requirement before materially changing its meaning or basis;
name the regression's PAC/commit in evidence. Preserve previous acceptance history.

After satisfying every task DoD and the nodule's criteria, validate the full web,
record concrete test/audit evidence, and `absorb`. The command checks spawned
tasks, requirement targets and new asset registrations before moving the sole
nodule row to its resolvable archive. Arbitrary evidence text is not executable
proof; inspect the actual checks and report unverified boundaries plainly.
