#!/usr/bin/env python3
"""
Rebuilding the context of an old ask, strongest link first.

Every test builds small synthetic notification rows around one target ask.
The rules under test are the order of the links and the strict cut-off at the ask.
Also tested: answers withheld when they came later, and ambiguous joins left missing.
"""

import copy
import random
from datetime import datetime, timedelta, timezone

import pytest

from cosa.agents.prediction_engine.history_context_rebuild import (
    CONFIDENCE, SESSION_WINDOW, TIERS, rebuild_context, reconstructable_stage,
)

T0      = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
SESSION = "ab12cd34"
SENDER  = f"claude.code@lupin.deepily.ai#{SESSION}"


def _note( note_id, minutes, **extra ):
    """
    Build one notification dict `minutes` after the target ask.

    Requires:
        - note_id is a string and minutes is a number, negative for earlier

    Ensures:
        - returns a dict with id, created_at and the fields given in extra
    """
    note = { "id": note_id, "created_at": ( T0 + timedelta( minutes=minutes ) ).isoformat() }
    note.update( extra )
    return note


def _target( **extra ):
    """
    Build the target ask.

    Requires:
        - extra holds link fields to set on the target

    Ensures:
        - returns a notification dict with id "target"
    """
    return _note( "target", 0, **extra )


def _ids( result ):
    """
    List the attached ids in order.

    Requires:
        - result comes from rebuild_context

    Ensures:
        - returns the attachment ids in the result's order
    """
    return [ a[ "id" ] for a in result[ "attachments" ] ]


def _each_tier_once():
    """
    Build a target and one earlier candidate for every tier.

    Ensures:
        - returns ( target, candidates ) where each candidate can only join through its own tier
    """
    target = _target( reply_to="parent-note", thread_id="thread-1", job_id="job-1", sender_id=SENDER )
    notes  = [ _note( "parent-note", -50 ),
               _note( "thread-note", -40, thread_id="thread-1" ),
               _note( "job-note", -30, job_id="job-1" ),
               _note( "sender-note", -20, sender_id=SENDER ),
               _note( "session-note", -10, sender_id=f"other.persona@lupin.deepily.ai#{SESSION}" ) ]
    return target, notes


def test_the_tiers_come_in_descending_order_of_certainty():
    target, notes = _each_tier_once()
    result        = rebuild_context( target, notes )
    assert [ a[ "tier" ] for a in result[ "attachments" ] ] == [ "parent", "thread", "job", "sender", "session" ]
    assert _ids( result ) == [ "parent-note", "thread-note", "job-note", "sender-note", "session-note" ]
    assert tuple( a[ "tier" ] for a in result[ "attachments" ] ) == TIERS


def test_each_attachment_states_its_evidence_and_the_confidence_of_its_tier():
    target, notes = _each_tier_once()
    for attachment in rebuild_context( target, notes )[ "attachments" ]:
        assert attachment[ "evidence" ], attachment[ "id" ]
        assert attachment[ "confidence" ] == CONFIDENCE[ attachment[ "tier" ] ]
    assert [ CONFIDENCE[ t ] for t in TIERS ] == [ "certain", "certain", "certain", "high", "inferred" ]


def test_a_notification_that_fits_two_tiers_is_attached_once_at_the_stronger_one():
    target = _target( thread_id="thread-1", sender_id=SENDER )
    both   = _note( "both", -5, thread_id="thread-1", sender_id=SENDER )
    result = rebuild_context( target, [ both ] )
    assert [ ( a[ "id" ], a[ "tier" ] ) for a in result[ "attachments" ] ] == [ ( "both", "thread" ) ]


def test_only_notifications_strictly_before_the_ask_are_read():
    target = _target( sender_id=SENDER )
    notes  = [ _note( "before", -1, sender_id=SENDER ), _note( "same-instant", 0, sender_id=SENDER ),
               _note( "after", 1, sender_id=SENDER ), target ]
    result = rebuild_context( target, notes )
    assert _ids( result ) == [ "before" ]
    assert result[ "not_earlier" ] == 3, "the same-instant and later notes and the target itself are counted out"


def test_an_answer_that_came_after_the_ask_is_withheld_and_reads_pending():
    target = _target( sender_id=SENDER )
    notes  = [ _note( "early-answer", -30, sender_id=SENDER, response_requested=True, responded_at=( T0 - timedelta( minutes=20 ) ).isoformat(), response_value="yes" ),
               _note( "late-answer", -20, sender_id=SENDER, response_requested=True, responded_at=( T0 + timedelta( minutes=5 ) ).isoformat(), response_value="no" ),
               _note( "at-the-ask", -10, sender_id=SENDER, response_requested=True, responded_at=T0.isoformat(), response_value="yes" ),
               _note( "no-question", -5, sender_id=SENDER ) ]
    by_id  = { a[ "id" ]: a[ "answer" ] for a in rebuild_context( target, notes )[ "attachments" ] }
    assert by_id[ "early-answer" ][ "status" ] == "answered" and by_id[ "early-answer" ][ "value" ] == "yes"
    assert by_id[ "late-answer" ] == { "status": "pending", "value": None, "answer_known_at": None }
    assert by_id[ "at-the-ask" ][ "status" ] == "answered", "an answer at the ask instant was known"
    assert by_id[ "no-question" ][ "status" ] == "not_a_question"


def test_a_candidate_whose_explicit_thread_differs_is_left_missing_not_attached():
    target = _target( thread_id="thread-1", sender_id=SENDER )
    other  = _note( "other-thread", -5, thread_id="thread-2", sender_id=SENDER )
    result = rebuild_context( target, [ other ] )
    assert result[ "attachments" ] == []
    assert result[ "missing" ] == [ { "id": "other-thread", "reason": "conflicting_explicit_link" } ]
    assert result[ "context_state" ] == "ambiguous_only"


def test_a_candidate_whose_explicit_job_differs_is_left_missing():
    target = _target( job_id="job-1", sender_id=SENDER )
    other  = _note( "other-job", -5, job_id="job-2", sender_id=SENDER )
    assert rebuild_context( target, [ other ] )[ "missing" ] == [ { "id": "other-job", "reason": "conflicting_explicit_link" } ]


def test_a_session_match_is_kept_inside_the_window_and_missing_outside_it():
    target  = _target( sender_id=SENDER )
    other   = f"other.persona@lupin.deepily.ai#{SESSION}"
    inside  = _note( "inside", -( SESSION_WINDOW.total_seconds() / 60 ) + 1, sender_id=other )
    outside = _note( "outside", -( SESSION_WINDOW.total_seconds() / 60 ) - 1, sender_id=other )
    result  = rebuild_context( target, [ inside, outside ] )
    assert [ ( a[ "id" ], a[ "tier" ], a[ "confidence" ] ) for a in result[ "attachments" ] ] == [ ( "inside", "session", "inferred" ) ]
    assert result[ "missing" ] == [ { "id": "outside", "reason": "session_match_outside_window" } ]


def test_the_window_is_a_parameter():
    target = _target( sender_id=SENDER )
    note   = _note( "n", -30, sender_id=f"other.persona@lupin.deepily.ai#{SESSION}" )
    assert _ids( rebuild_context( target, [ note ], session_window=timedelta( minutes=60 ) ) ) == [ "n" ]
    assert rebuild_context( target, [ note ], session_window=timedelta( minutes=10 ) )[ "missing" ][ 0 ][ "reason" ] == "session_match_outside_window"


def test_a_bare_sender_with_no_session_is_not_a_link():
    bare   = "claude.code@lupin.deepily.ai"
    target = _target( sender_id=bare )
    result = rebuild_context( target, [ _note( "same-bare", -5, sender_id=bare ) ] )
    assert result[ "attachments" ] == []
    assert result[ "missing" ] == [ { "id": "same-bare", "reason": "bare_sender_only" } ]


def test_a_human_message_to_the_session_joins_at_the_session_tier():
    target = _target( sender_id=SENDER )
    human  = _note( "human", -5, direction="human_to_ai", job_id=SESSION, sender_id="rick@human" )
    result = rebuild_context( target, [ human ] )
    assert [ ( a[ "id" ], a[ "tier" ] ) for a in result[ "attachments" ] ] == [ ( "human", "session" ) ]
    assert "human message addressed to the session" in result[ "attachments" ][ 0 ][ "evidence" ]


def test_a_notification_with_no_signal_is_unrelated_and_is_not_missing():
    target = _target( sender_id=SENDER )
    result = rebuild_context( target, [ _note( "stranger", -5, sender_id="x@y#zzzz9999" ) ] )
    assert ( result[ "unrelated" ], result[ "missing" ], result[ "context_state" ] ) == ( 1, [], "no_context" )


def test_within_a_tier_the_newest_comes_first_and_ties_break_on_id():
    target = _target( sender_id=SENDER )
    notes  = [ _note( "old", -30, sender_id=SENDER ), _note( "new", -5, sender_id=SENDER ),
               _note( "tie-b", -15, sender_id=SENDER ), _note( "tie-a", -15, sender_id=SENDER ) ]
    assert _ids( rebuild_context( target, notes ) ) == [ "new", "tie-a", "tie-b", "old" ]


def test_the_result_does_not_depend_on_input_order_and_leaves_the_inputs_alone():
    target, notes = _each_tier_once()
    notes        += [ _note( "late", -1, sender_id=SENDER, response_requested=True, responded_at=( T0 + timedelta( minutes=9 ) ).isoformat() ),
                      _note( "conflict", -2, thread_id="thread-9", sender_id=SENDER ) ]
    frozen        = copy.deepcopy( ( target, notes ) )
    first         = rebuild_context( target, notes )
    for seed in range( 5 ):
        shuffled = list( notes )
        random.Random( seed ).shuffle( shuffled )
        assert rebuild_context( target, shuffled ) == first
    assert ( target, notes ) == frozen
    assert rebuild_context( target, notes ) == first, "run twice, same result"


def test_the_context_state_names_what_was_found():
    target = _target( sender_id=SENDER )
    assert rebuild_context( target, [ _note( "a", -1, sender_id=SENDER ) ] )[ "context_state" ] == "reconstructed"
    assert rebuild_context( target, [ _note( "b", -1, sender_id="claude.code@lupin.deepily.ai" ) ] )[ "context_state" ] == "no_context"
    bare_target = _target( sender_id="claude.code@lupin.deepily.ai" )
    assert rebuild_context( bare_target, [ _note( "c", -1, sender_id="claude.code@lupin.deepily.ai" ) ] )[ "context_state" ] == "ambiguous_only"
    assert rebuild_context( target, [] )[ "context_state" ] == "no_context"


def test_the_funnel_stage_counts_reconstructed_asks_and_names_every_drop():
    good       = rebuild_context( _target( sender_id=SENDER ), [ _note( "a", -1, sender_id=SENDER ) ] )
    none       = rebuild_context( _target( sender_id=SENDER ), [] )
    ambiguous  = rebuild_context( _target( sender_id="x@y" ), [ _note( "b", -1, sender_id="x@y" ) ] )
    stage      = reconstructable_stage( [ good, none, none, ambiguous ] )
    assert ( stage[ "stage" ], stage[ "count" ] ) == ( "reconstructable_context", 1 )
    assert stage[ "dropped" ] == { "no_context": 2, "ambiguous_only": 1 }
    assert stage[ "count" ] + sum( stage[ "dropped" ].values() ) == 4
    assert stage[ "count" ] <= 4


def test_the_result_carries_its_version():
    result = rebuild_context( _target(), [] )
    assert result[ "rebuild_version" ] == "history-context-v1" and result[ "target_id" ] == "target"


def test_a_question_that_was_never_answered_reads_pending():
    target = _target( sender_id=SENDER )
    never  = _note( "never", -5, sender_id=SENDER, response_requested=True, responded_at=None )
    assert rebuild_context( target, [ never ] )[ "attachments" ][ 0 ][ "answer" ] == { "status": "pending", "value": None, "answer_known_at": None }


def test_a_time_with_no_offset_is_read_as_utc():
    naive  = ( T0 - timedelta( minutes=3 ) ).replace( tzinfo=None )
    target = _target( sender_id=SENDER )
    note   = { "id": "naive", "created_at": naive, "sender_id": SENDER }
    assert _ids( rebuild_context( target, [ note ] ) ) == [ "naive" ]
