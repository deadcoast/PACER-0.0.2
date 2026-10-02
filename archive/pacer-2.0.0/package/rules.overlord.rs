// OVERLORD pseudo-Rust. Intentionally non-compiling.
// PACER v2 parent workflow semantics.

types:FormalName::task PACER_CONTINUITY {
    authority: project_sources > user_direction > pacer_state > local_inference,
    default_transition: continue,
    lifecycle: [todo, active, integrated, done],
    review: evidence_not_state,
}

ALIGNMENT {
    preserve_global_plan: true,
    active_phase_is_context_frame: true,
    independent_task_fragmentation: reject_as_default,
}

STATE {
    WELL: global_project_knowledge,
    THEATRE: current_actionable_context,
    approval_latch: persistent_until_subject_changes,
    pace_end: integrate_then_loop,
}

BOUNDARY {
    user_gate only_if {
        irreversible_external_action
        || missing_authority
        || protected_content_destructive_change
        || unresolved_high_cost_mutually_exclusive_direction
        || explicitly_reserved_user_decision
    }

    agent_resolves {
        tests;
        research;
        local_design;
        prototype_tuning;
        routine_refactor;
        documentation;
        subagent_work;
    }
}

OUTPUT {
    coherent_operational_state > ceremonial_signoff,
    source_integration > detached_validation_artifacts,
    development_progress > review_parking,
}

LOOP {
    sequence: orient -> build -> integrate -> self_check -> absorb -> :loop⠁: -> overlord_update -> continue,
    stop: true_authority_blocker || requested_checkpoint || global_scope_complete,
}
