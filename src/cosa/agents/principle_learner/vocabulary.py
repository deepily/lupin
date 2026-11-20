"""
The 14 dimension headings Rick approved, and where the 60 old dimension names go.

Rick approved the headings on the evening of 19 November 2026. The source is
io/tmp/principle-learner-briefs/2026.11.19-ph1-dimension-vocabulary-draft.md, which also explains each placement.
The extractor prompt reads the headings from here, so this module is the one place the vocabulary lives.
A new vocabulary gets a new VOCABULARY_VERSION date; it never edits the headings of an old one in place.
"""

VOCABULARY_VERSION = "2026.11.19"

HEADINGS = (
    "Keep changes small and in scope",
    "Fix the real cause",
    "Tests must earn their keep",
    "Evidence before decisions",
    "Review and release gates",
    "Spend, limits and fleet capacity",
    "Settings live in one place",
    "Scripted, repeatable operations",
    "Tidy documents and old work",
    "How to ask me",
    "Save my attention",
    "Interface, alerts and interruptions",
    "Security and exposure",
    "Timing and deferral",
)

# The 60 old names, listed under the heading each one moves to.
LEGACY_BY_HEADING = {
    "Keep changes small and in scope"     : (
        "abstraction_timing",
        "debt_tracking_granularity",
        "pr_scope",
        "release_risk_management",
        "ui_scope",
    ),
    "Fix the real cause"                  : (
        "bug_verification",
        "dead_code_handling",
        "fix_depth",
        "scope_completeness_expectation",
    ),
    "Tests must earn their keep"          : (
        "test_coverage_maintenance",
        "test_design",
        "test_isolation",
        "test_validity_of_runtime_config",
    ),
    "Evidence before decisions"           : (
        "evidence_before_tuning",
        "quality_measurement_approach",
        "research_scope",
        "review_evidence_basis",
        "validation_target_choice",
    ),
    "Review and release gates"            : (
        "ci_investment",
        "pr_check_strictness",
        "pr_review_before_publish",
        "review_independence",
    ),
    "Spend, limits and fleet capacity"    : (
        "agent_fleet_capacity",
        "budget_limit",
        "cross_project_agent_spawning",
        "spend_limit_safeguards",
        "throughput_vs_cost_guard",
        "timeout",
    ),
    "Settings live in one place"          : (
        "configuration_centralization",
        "configuration_location",
        "runtime_configurability",
    ),
    "Scripted, repeatable operations"     : (
        "delegated_command_execution",
        "infrastructure_reproducibility",
        "live_verification_scope",
        "manual_step_batching",
        "ops_change_execution",
    ),
    "Tidy documents and old work"         : (
        "doc_placement",
        "documentation_organization",
        "stale_work_cleanup",
    ),
    "How to ask me"                       : (
        "approval_gating",
        "approval_presentation",
        "approval_workflow",
        "priority_escalation",
        "question_context_framing",
        "question_deduplication",
    ),
    "Save my attention"                   : (
        "delegated_followup_work",
        "destructive_action_confirmation",
        "maintenance_batching",
        "manual_toil_avoidance",
    ),
    "Interface, alerts and interruptions" : (
        "alert_configurability",
        "alert_sensitivity",
        "list_sort_order",
        "playback_interruption",
    ),
    "Security and exposure"               : (
        "credential_exposure_remediation",
        "data_privacy_storage",
        "permission_scope_control",
        "safety_block_resolution",
    ),
    "Timing and deferral"                 : (
        "decision_timing",
        "deferral_condition_handling",
        "security_task_timing",
    ),
}

LEGACY_HEADINGS = { old: heading for heading, olds in LEGACY_BY_HEADING.items() for old in olds }


def is_heading( dimension ):
    """
    Say whether a dimension is one of the approved headings, written exactly.

    Requires:
        - dimension is a string or None

    Ensures:
        - returns True only when dimension equals one approved heading, character for character
    """
    return dimension in HEADINGS


def heading_for( dimension ):
    """
    Give the approved heading a stored dimension belongs under.

    Requires:
        - dimension is a string or None

    Ensures:
        - returns dimension itself when it is a heading
        - returns the mapped heading when dimension is one of the 60 old names
        - returns None for anything else, so an unknown name is never filed under a guessed heading
    """
    if is_heading( dimension ): return dimension
    return LEGACY_HEADINGS.get( dimension )


def shown_dimension( dimension ):
    """
    Give the name a stored dimension is shown and compared under.

    Requires:
        - dimension is a string or None

    Ensures:
        - returns heading_for( dimension ) when it has one, so an old name reads as its heading
        - returns dimension unchanged otherwise, so an unknown name is shown as stored and never guessed
    """
    return heading_for( dimension ) or dimension


def same_heading( first, second ):
    """
    Say whether two dimensions file under the same heading.

    Requires:
        - first and second are strings or None

    Ensures:
        - returns True when shown_dimension gives both the same name, so an old name and its heading agree
        - two unknown names agree only when they are equal
    """
    return shown_dimension( first ) == shown_dimension( second )


def headings_block():
    """
    Write the headings as the numbered list the extractor prompt carries.

    Ensures:
        - returns one line per heading, in the approved order, each "<n>. <heading>"
    """
    return "\n".join( f"{number}. {heading}" for number, heading in enumerate( HEADINGS, start=1 ) )
