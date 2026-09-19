# Guardrail Doctrine — Authority, Not Ceremony

PACER v2 asks one question before stopping development:

> **Does the next action require authority the agent does not already have?**

If no, continue.

## Agent-resolved by default

These do not justify user interruption at prototype/integration maturity:

- ordinary unit/integration test failure;
- a straightforward implementation choice inside established architecture;
- a researchable API/tool question;
- documentation/lint/formatting repair;
- tuning/greybox values that can be measured or iterated;
- a local refactor needed by the active phase;
- visual polish consistent with an existing design system;
- sub-agent findings;
- absence of user playtesting for a small implementation;
- a check that can be run by the agent itself.

The correct response is **research / build / test / repair / continue**.

## User authority required

Stop only when one of these actually applies:

1. an irreversible external action needs the user's authority;
2. a required account, secret, credential, payment, or access grant is missing;
3. protected/released content would be destructively changed beyond existing authority;
4. two or more mutually exclusive product directions have major downstream cost and the project/user has not already chosen;
5. the user explicitly reserved the decision;
6. a higher-priority safety/legal/system constraint requires it.

## Maturity escalation

| Maturity | Default | Gate posture |
|---|---|---|
| sketch | continue | almost entirely agent-owned |
| prototype | continue | internal checks; no ceremonial review |
| playable | continue | user feedback useful at coherent states, not required per pace |
| integrated | continue with evidence | compatibility/migration checks grow |
| release | guarded | release, migration, distribution gates can block |
| protected | strict | finished/canonical/protected content gets explicit authority boundaries |

## Approval latch

A user approval or explicit skip becomes a **state latch**.

Do not ask again merely because a new pace started or context was reloaded. Reopen the decision only if:

- the approved subject materially changed;
- a governing assumption became false;
- new evidence makes the previous approval inapplicable;
- the user explicitly reopens it.

A latch is not weakened by an agent starting a fresh session.
