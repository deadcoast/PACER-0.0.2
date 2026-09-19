.MIVIM.spec::PACER
version = "2.0.0"
role = "agent-development-continuity"

[authority]
project_truth = "project sources + explicit user direction"
workflow_state = "overlord"
development_plan = "todo.PACER"
active_context = "THEATRE"
deep_context = "WELL"

[doctrine]
default = "continue"
pace_is_gate = false
review_is_lifecycle_state = false
test_is_user_gate = false
approval_latches = true
protect_by_maturity = true

[maturity]
sketch = "agent-autonomous"
prototype = "agent-autonomous"
playable = "continuous-with-coherent-checkpoints"
integrated = "continuous-with-evidence"
release = "strict-release-gates"
protected = "strict-content-authority"

[guardrail.user_required]
classes = [
  "irreversible_external_action",
  "missing_secret_or_account_authority",
  "destructive_change_to_protected_or_released_content",
  "mutually_exclusive_high_cost_product_direction_without_project_answer",
  "explicit_user_reserved_decision"
]

[guardrail.agent_resolves]
classes = [
  "ordinary_test_failure",
  "local_implementation_choice",
  "researchable_unknown",
  "greybox_value",
  "style_choice_within_existing_system",
  "routine_refactor",
  "routine_validation",
  "documentation_update",
  "subagent_delegation",
  "prototype_playtest_absence"
]

[loop]
syntax = ":loop⠁:"
position = "after integrate/self-check/absorb; before overlord update"
auto_continue = true
stop_on = "true_authority_blocker | coherent_user_requested_checkpoint | completed_global_scope"
