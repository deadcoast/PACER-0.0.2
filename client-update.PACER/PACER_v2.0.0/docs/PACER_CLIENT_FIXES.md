# PACER Client Fixes — Normative Interpretation

This document captures the operational correction requested for PACER v2.

## Problem

PACER had begun applying shipping-team process at proof-of-concept maturity. Agents then conflated internal validation with external authority and repeatedly stopped after tiny paces, dropping the global plan while waiting for user intervention.

The result was:

- excessive context reload;
- document drift and validation bloat;
- one-small-step/one-guardrail death loops;
- user testing of trivial functions the agent could validate itself;
- fragmented implementation resembling many independent developers;
- global project knowledge sitting unused while local work stalled.

## Fix

PACER is an **agent development aid**. It must:

- route global knowledge into local action;
- preserve future-plan context;
- group work into integrated phases;
- use internal research/tests/sub-agents to resolve ordinary uncertainty;
- continue until a coherent operational state;
- treat user playtesting as high-value feedback, not mandatory fuel for every pace;
- demote strict guardrails toward release/protected content;
- remember approvals/skips;
- keep the loop alive.
