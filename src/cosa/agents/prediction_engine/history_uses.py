"""
The fourth history step: give each derived example the use its evidence supports.

A verified answer with a rebuilt question can train or test. A weaker answer can only support a
sensitivity check or a prompt-only baseline. An ask nobody answered supports vocabulary and nothing else.
No recovered example joins the frozen cohort; recovered asks are reported beside it.
"""

TRAIN_OR_TEST   = "train_or_test"
PROMPT_ONLY     = "prompt_only"
SENSITIVITY     = "sensitivity"
VOCABULARY_ONLY = "vocabulary_only"

USES = ( TRAIN_OR_TEST, PROMPT_ONLY, SENSITIVITY, VOCABULARY_ONLY )

WEAK_ACTOR_TIERS = ( "unknown_actor", "other_account" )


def assign_use( example, context_state ):
    """
    Assign one derived example its use, with the reason.

    Requires:
        - example is a derived example with attribution_tier and an answer carrying kind
        - context_state is "reconstructed", "ambiguous_only" or "no_context", as rebuild_context names it

    Ensures:
        - Returns { "use", "reason", "frozen_cohort" } and frozen_cohort is always False
        - An ask with no stored answer, or only a timeout default, is vocabulary_only: it carries no human label
        - An answer that could not be read is sensitivity: its mapping is ambiguous
        - An answer whose actor is unknown or another account is sensitivity: it is weakly attributable
        - A recipient answer with a reconstructed context is train_or_test, and with any other context state is prompt_only
        - The first rule that applies decides, in the order above
    """
    tier = example[ "attribution_tier" ]
    kind = example[ "answer" ][ "kind" ]
    if kind == "none":            return _use( VOCABULARY_ONLY, "unanswered" )
    if tier == "timeout_default": return _use( VOCABULARY_ONLY, "timeout default, no human label" )
    if kind == "unread":          return _use( SENSITIVITY, "answer could not be read" )
    if tier in WEAK_ACTOR_TIERS:  return _use( SENSITIVITY, f"actor not established: {tier}" )
    if context_state == "reconstructed": return _use( TRAIN_OR_TEST, "recipient answer, context reconstructed" )
    return _use( PROMPT_ONLY, f"recipient answer, context {context_state}" )


def _use( use, reason ):
    """
    Build one assignment.

    Requires:
        - use is one of the four use names above and reason is a non-empty string

    Ensures:
        - Returns the assignment dict, kept out of the frozen cohort
    """
    return { "use": use, "reason": reason, "frozen_cohort": False }


def assign_uses( examples, context_states ):
    """
    Assign every example its use and count them.

    Requires:
        - examples is a list of derived examples
        - context_states maps each example's notification_id to its context state

    Ensures:
        - Returns ( assignments, counts ), assignments in the order of examples and counts keyed by use then reason
        - Every one of the four use names is a key of counts, with an empty dict when none was assigned

    Raises:
        - KeyError naming the notification id when an example has no context state
    """
    assignments = [ assign_use( e, context_states[ e[ "notification_id" ] ] ) for e in examples ]
    counts      = { use: {} for use in USES }
    for a in assignments: counts[ a[ "use" ] ][ a[ "reason" ] ] = counts[ a[ "use" ] ].get( a[ "reason" ], 0 ) + 1
    return assignments, counts
