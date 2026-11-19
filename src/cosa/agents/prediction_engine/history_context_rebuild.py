"""
Rebuild the context of an old ask, strongest link first, from raw notification rows.

An ask is joined to the earlier notifications that framed it, in descending order
of certainty. The order is the notification it answers, its thread, its job, its
full sender, and last a time-bounded match on the sender's session.
A join that cannot be told from a coincidence stays missing, with its reason.
Nothing later than the ask is read. An earlier question carries its answer only
if the answer existed when the ask was made.
"""

from datetime import timedelta

from cosa.utils.iso_timestamp import aware_moment
from cosa.utils.notification_utils import sender_session_suffix

REBUILD_VERSION = "history-context-v1"

TIERS = ( "parent", "thread", "job", "sender", "session" )

CONFIDENCE = { "parent": "certain", "thread": "certain", "job": "certain", "sender": "high", "session": "inferred" }

# An assumption, not a measurement: the spec says "time-bounded session matches" and gives no figure.
# Two hours is a guess. The gap distribution between asks on the real export is recorded beside it.
SESSION_WINDOW = timedelta( hours=2 )


def _answer_as_of( candidate, asked_at ):
    """
    Say what the target's author could know of a candidate's answer at the ask.

    Requires:
        - candidate is a notification dict with response_requested, responded_at and response_value
        - asked_at is an aware datetime

    Ensures:
        - returns { status, value, answer_known_at }
        - status is "not_a_question", "answered" (answered at or before the ask) or "pending"
        - value and answer_known_at are None unless the status is "answered"
    """
    if not candidate.get( "response_requested", False ): return { "status": "not_a_question", "value": None, "answer_known_at": None }
    responded = aware_moment( candidate.get( "responded_at" ) )
    if responded is not None and responded <= asked_at:
        return { "status": "answered", "value": candidate.get( "response_value" ), "answer_known_at": responded.isoformat() }
    return { "status": "pending", "value": None, "answer_known_at": None }


def _link_for( target, candidate, asked_at, session_window ):
    """
    Find the strongest link between a target and one earlier candidate.

    Requires:
        - candidate was created before the ask

    Ensures:
        - returns ( tier, evidence, None ) for the strongest link that holds; a full sender is one with a session part
        - returns ( None, None, reason ) when only a weaker or conflicting signal exists
        - returns ( None, None, None ) when the candidate has nothing to do with the target
        - a candidate whose explicit thread or job differs from the target's own is never joined
          through the sender or the session: its reason is conflicting_explicit_link
    """
    if target.get( "reply_to" ) and target[ "reply_to" ] == candidate[ "id" ]:
        return "parent", [ "target.reply_to equals candidate.id" ], None
    if target.get( "thread_id" ) and candidate.get( "thread_id" ) == target[ "thread_id" ]:
        return "thread", [ "same thread_id" ], None
    if target.get( "job_id" ) and candidate.get( "job_id" ) == target[ "job_id" ]:
        return "job", [ "same job_id" ], None
    conflicts = [ name for name in ( "thread_id", "job_id" )
                  if target.get( name ) and candidate.get( name ) and candidate[ name ] != target[ name ] ]
    sender    = target.get( "sender_id" )
    session   = sender_session_suffix( sender )
    same_full = session is not None and candidate.get( "sender_id" ) == sender
    same_sess = session is not None and sender_session_suffix( candidate.get( "sender_id" ) ) == session
    human_msg = ( session is not None and candidate.get( "direction" ) == "human_to_ai" and candidate.get( "job_id" ) == session )
    if not ( same_full or same_sess or human_msg ):
        if sender and "#" not in sender and candidate.get( "sender_id" ) == sender: return None, None, "bare_sender_only"
        return None, None, None
    if conflicts: return None, None, "conflicting_explicit_link"
    if same_full: return "sender", [ "same full sender_id" ], None
    if asked_at - aware_moment( candidate[ "created_at" ] ) > session_window: return None, None, "session_match_outside_window"
    if human_msg: return "session", [ "human message addressed to the session", f"within {session_window}" ], None
    return "session", [ "same sender session", f"within {session_window}" ], None


def rebuild_context( target, notifications, session_window=SESSION_WINDOW ):
    """
    Rebuild the context of one ask from the notifications that existed before it.

    Requires:
        - target is a notification dict with id and created_at, and optionally reply_to, thread_id,
          job_id and sender_id
        - notifications is a list of notification dicts with id, created_at and optionally the same link
          fields, direction, response_requested, responded_at and response_value
        - session_window is a timedelta, the longest gap a session-only match may span

    Ensures:
        - returns { rebuild_version, target_id, context_state, attachments, missing, unrelated, not_earlier }
        - the target and every notification not created strictly before it are left out and counted in not_earlier
        - attachments are ordered by tier (parent, thread, job, sender, session), then newest first, then id
        - each attachment has id, tier, confidence, evidence, first_known_at and the answer as of the ask;
          a later answer is withheld and reads pending
        - missing lists each candidate with a partial or conflicting signal, with its reason, and never attaches it
        - context_state is reconstructed, ambiguous_only or no_context
        - the result does not depend on the order of notifications, and nothing is changed in the inputs
    """
    asked_at     = aware_moment( target[ "created_at" ] )
    attachments  = []
    missing      = []
    unrelated    = 0
    not_earlier  = 0
    for candidate in notifications:
        if aware_moment( candidate[ "created_at" ] ) >= asked_at:
            not_earlier += 1
            continue
        tier, evidence, reason = _link_for( target, candidate, asked_at, session_window )
        if tier is not None:
            attachments.append( { "id": candidate[ "id" ], "tier": tier, "confidence": CONFIDENCE[ tier ], "evidence": evidence,
                                  "first_known_at": aware_moment( candidate[ "created_at" ] ).isoformat(),
                                  "answer": _answer_as_of( candidate, asked_at ) } )
        elif reason is not None:
            missing.append( { "id": candidate[ "id" ], "reason": reason } )
        else:
            unrelated += 1
    attachments.sort( key=lambda a: ( TIERS.index( a[ "tier" ] ), -aware_moment( a[ "first_known_at" ] ).timestamp(), a[ "id" ] ) )
    missing.sort( key=lambda m: ( m[ "reason" ], m[ "id" ] ) )
    state = "reconstructed" if attachments else ( "ambiguous_only" if missing else "no_context" )
    return { "rebuild_version": REBUILD_VERSION, "target_id": target[ "id" ], "context_state": state,
             "attachments": attachments, "missing": missing, "unrelated": unrelated, "not_earlier": not_earlier }


def reconstructable_stage( results ):
    """
    Count the asks whose context could be rebuilt, as one stage of the yield funnel.

    Requires:
        - results is a list of dicts returned by rebuild_context

    Ensures:
        - returns { stage, count, reason, dropped }
        - count is the number of results with context_state reconstructed
        - dropped maps each other context_state to its count, so every dropped ask has a named reason
        - count plus the dropped counts equals len( results )
    """
    dropped = {}
    for result in results:
        if result[ "context_state" ] != "reconstructed":
            dropped[ result[ "context_state" ] ] = dropped.get( result[ "context_state" ], 0 ) + 1
    return { "stage": "reconstructable_context", "count": len( results ) - sum( dropped.values() ),
             "reason": "no earlier notification could be joined to the ask with a stated link", "dropped": dropped }
