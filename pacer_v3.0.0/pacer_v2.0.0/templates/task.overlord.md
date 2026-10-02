# types:FormalName::task — PACER continuity task

- parent: `OVERLORD`
- plan: `todo.PACER`
- rules: `rules.overlord.rs`
- map: `map.overlord.toml`

## State

`active('development','continuous')[01]:TODO[ ]`

## Contract

The task remains active across related paces. Internal tests, research, documentation, and repair do not automatically transition the task into user review. User intervention is requested only for a true authority blocker defined by `.MIVIM.spec` and `docs/GUARDRAIL_DOCTRINE.md`.

## Loop

`==> :loop⠁:`

Approval/absorption remains outside the internal pace loop. Once approved or explicitly skipped, the corresponding latch persists until its governed subject materially changes.
