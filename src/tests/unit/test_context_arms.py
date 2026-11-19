#!/usr/bin/env python3
"""
The text behind each vector in the context comparison, arm by arm.

Contexts come from the real rebuild_context over small synthetic notifications, so the tests
exercise the as-of rule where it is enforced. The question is the base of every arm.
A missing context falls back to the question alone and is counted.
A previous answer appears only when it was given at or before the ask.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from cosa.agents.prediction_engine.history_context_rebuild import rebuild_context
from cosa.research.preference_replay.context_arms import (
    ARMS, arm_text, build_arm_texts, build_cohort_arms, notification_dict, question_text, read_arm_inputs )

T0     = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
SENDER = "claude.code@lupin.deepily.ai#ab12cd34"


def _note( note_id, minutes, **extra ):
    """
    Build one notification dict `minutes` after the target ask.

    Requires:
        - note_id is a string and minutes is a number

    Ensures:
        - returns a dict with id, created_at, a message and the fields in extra
    """
    note = { "id": note_id, "created_at": ( T0 + timedelta( minutes=minutes ) ).isoformat(), "message": f"  message of {note_id}  " }
    note.update( extra )
    return note


def _ctx( target, others ):
    """
    Rebuild the context of a target and index every note.

    Requires:
        - target and others are notification dicts

    Ensures:
        - returns ( context, notes_by_id )
    """
    return rebuild_context( target, others ), { n[ "id" ]: n for n in [ target ] + others }


def _prev( minutes=-30, answered_minutes=-20, **extra ):
    """
    Build an earlier question on thread t1, answered `answered_minutes` after the target.

    Requires:
        - minutes and answered_minutes are numbers

    Ensures:
        - returns a notification dict asking for a response, with its answer
    """
    return _note( extra.pop( "note_id", "prev" ), minutes, thread_id="t1", response_requested=True, response_value=extra.pop( "value", "yes" ),
                  responded_at=( T0 + timedelta( minutes=answered_minutes ) ).isoformat(), **extra )


def test_arms_are_the_five_named_arms():
    assert ARMS == ( "Q", "Q+A", "Q+O", "Q+P", "Q+H" )


def test_question_is_stripped_message():
    assert question_text( _note( "x", 0 ) ) == "message of x"


def test_arm_q_ignores_context_and_reports_no_reason():
    target       = _note( "target", 0 )
    context, ids = _ctx( target, [] )
    assert context[ "context_state" ] == "no_context"
    assert arm_text( "Q", target, context, ids ) == ( "message of target", None )


def test_unknown_arm_is_refused():
    target       = _note( "target", 0 )
    context, ids = _ctx( target, [] )
    with pytest.raises( ValueError, match="arm must be one of" ):
        arm_text( "Q+Z", target, context, ids )


def test_history_arm_with_no_context_falls_back_to_question():
    target       = _note( "target", 0, abstract="an abstract", sender_id=SENDER )
    context, ids = _ctx( target, [] )
    assert arm_text( "Q+H", target, context, ids ) == ( "message of target", "no_context" )


def test_ambiguous_only_context_counts_as_no_context_for_history():
    target       = _note( "target", 0, sender_id="claude.code@lupin.deepily.ai" )
    other        = _note( "bare", -5, sender_id="claude.code@lupin.deepily.ai" )
    context, ids = _ctx( target, [ other ] )
    assert context[ "context_state" ] == "ambiguous_only"
    assert arm_text( "Q+H", target, context, ids ) == ( "message of target", "no_context" )


def test_own_field_arms_work_without_any_rebuilt_context():
    options = { "questions": [ { "question": "Go?", "options": [ { "label": "Yes" } ] } ] }
    target  = _note( "target", 0, abstract="abs", response_options=options, sender_id=SENDER )
    context, ids = _ctx( target, [] )
    assert context[ "context_state" ] == "no_context"
    assert arm_text( "Q+A", target, context, ids ) == ( "message of target\n\nAbstract: abs", None )
    assert arm_text( "Q+O", target, context, ids )[ 1 ] is None
    assert arm_text( "Q+P", target, context, ids ) == ( "message of target\n\nProject: lupin\nSession: ab12cd34", None )


def _reconstructed( **target_extra ):
    """
    Build a target with one thread-linked earlier note, so its context is reconstructed.

    Requires:
        - target_extra holds fields to set on the target

    Ensures:
        - returns ( target, context, notes_by_id ) with context_state reconstructed
    """
    target       = _note( "target", 0, thread_id="t1", **target_extra )
    context, ids = _ctx( target, [ _note( "earlier", -10, thread_id="t1" ) ] )
    assert context[ "context_state" ] == "reconstructed"
    return target, context, ids


def test_abstract_arm_appends_stripped_abstract():
    target, context, ids = _reconstructed( abstract="  why this matters  " )
    assert arm_text( "Q+A", target, context, ids ) == ( "message of target\n\nAbstract: why this matters", None )


@pytest.mark.parametrize( "abstract", [ None, "", "   " ] )
def test_abstract_arm_without_abstract_is_counted_as_absent( abstract ):
    target, context, ids = _reconstructed( abstract=abstract )
    assert arm_text( "Q+A", target, context, ids ) == ( "message of target", "arm_input_absent" )


def test_options_arm_lists_labels_and_flags_recommended():
    options = { "questions": [ { "header": "Push", "question": "Push now?", "options": [
        { "label": "Yes (Recommended)" }, { "label": "No", "recommended": True }, { "label": "Later" }, { "label": "  " }, "junk" ] } ] }
    target, context, ids = _reconstructed( response_options=options )
    text, reason = arm_text( "Q+O", target, context, ids )
    assert reason is None
    assert text == ( "message of target\n\nOptions:\n- Push: Push now?\n  * Yes (Recommended)\n  * No (recommended)\n  * Later" )


def test_options_arm_does_not_flag_twice_a_label_that_already_says_recommended():
    options = { "questions": [ { "question": "Go?", "options": [ { "label": "Yes (Recommended)", "recommended": True } ] } ] }
    target, context, ids = _reconstructed( response_options=options )
    assert arm_text( "Q+O", target, context, ids )[ 0 ].endswith( "  * Yes (Recommended)" )


def test_history_arm_uses_an_answer_reached_through_the_parent_link():
    target       = _note( "target", 0, reply_to="prev" )
    parent       = _note( "prev", -30, response_requested=True, response_value="no", responded_at=( T0 + timedelta( minutes=-20 ) ).isoformat() )
    context, ids = _ctx( target, [ parent ] )
    assert context[ "attachments" ][ 0 ][ "tier" ] == "parent"
    assert arm_text( "Q+H", target, context, ids ) == ( "message of target\n\nPrevious answer on this thread: message of prev -> no", None )


def test_options_arm_handles_question_without_header_or_text():
    options = { "questions": [ { "question": "Only question", "options": [ { "label": "A" } ] }, { "options": [ { "label": "B" } ] }, "junk" ] }
    target, context, ids = _reconstructed( response_options=options )
    assert arm_text( "Q+O", target, context, ids )[ 0 ] == "message of target\n\nOptions:\n- Only question\n  * A\n  * B"


@pytest.mark.parametrize( "options", [ None, "text", { "questions": "x" }, { "questions": [] }, { "questions": [ { "question": "q" } ] },
                                       { "questions": [ { "options": [ { "nolabel": 1 } ] } ] }, { "questions": [ "junk" ] },
                                       { "questions": 5 }, { "questions": { "a": 1 } } ] )
def test_options_arm_without_labels_is_counted_as_absent( options ):
    target, context, ids = _reconstructed( response_options=options )
    assert arm_text( "Q+O", target, context, ids ) == ( "message of target", "arm_input_absent" )


def test_project_arm_names_project_and_session():
    target, context, ids = _reconstructed( sender_id=SENDER )
    assert arm_text( "Q+P", target, context, ids ) == ( "message of target\n\nProject: lupin\nSession: ab12cd34", None )


def test_project_arm_with_project_but_no_session():
    target, context, ids = _reconstructed( sender_id="claude.code@lupin.deepily.ai" )
    assert arm_text( "Q+P", target, context, ids )[ 0 ] == "message of target\n\nProject: lupin"


def test_project_arm_with_session_but_no_project():
    target, context, ids = _reconstructed( sender_id="someone#ab12cd34" )
    assert arm_text( "Q+P", target, context, ids )[ 0 ] == "message of target\n\nSession: ab12cd34"


@pytest.mark.parametrize( "sender", [ None, "", "plainsender" ] )
def test_project_arm_without_either_is_counted_as_absent( sender ):
    target, context, ids = _reconstructed( sender_id=sender )
    assert arm_text( "Q+P", target, context, ids ) == ( "message of target", "arm_input_absent" )


def test_history_arm_uses_answer_given_before_the_ask():
    target       = _note( "target", 0, thread_id="t1" )
    context, ids = _ctx( target, [ _prev() ] )
    assert arm_text( "Q+H", target, context, ids ) == ( "message of target\n\nPrevious answer on this thread: message of prev -> yes", None )


def test_history_arm_ignores_answer_given_after_the_ask():
    target       = _note( "target", 0, thread_id="t1" )
    context, ids = _ctx( target, [ _prev( answered_minutes=+5 ) ] )
    assert context[ "context_state" ] == "reconstructed"
    assert arm_text( "Q+H", target, context, ids ) == ( "message of target", "arm_input_absent" )


def test_history_arm_answer_exactly_at_the_ask_counts_as_known():
    target       = _note( "target", 0, thread_id="t1" )
    context, ids = _ctx( target, [ _prev( answered_minutes=0 ) ] )
    assert "-> yes" in arm_text( "Q+H", target, context, ids )[ 0 ]


def test_history_arm_ignores_unanswered_and_non_question_notes():
    target       = _note( "target", 0, thread_id="t1" )
    others       = [ _note( "plain", -20, thread_id="t1" ), _note( "open", -15, thread_id="t1", response_requested=True ) ]
    context, ids = _ctx( target, others )
    assert arm_text( "Q+H", target, context, ids ) == ( "message of target", "arm_input_absent" )


def _sender_note( minutes, **extra ):
    """
    Build an earlier question from the target's own sender, answered just before the ask.

    Requires:
        - minutes is a number, negative for earlier

    Ensures:
        - returns a notification dict with the same full sender id as the target
    """
    fields = { "sender_id": SENDER, "response_requested": True, "response_value": extra.pop( "value", "yes" ),
               "responded_at": ( T0 - timedelta( minutes=1 ) ).isoformat() }
    fields.update( extra )
    return _note( fields.pop( "note_id", "prev" ), minutes, **fields )


def test_history_arm_falls_back_to_an_answer_from_the_same_session_within_the_window():
    target       = _note( "target", 0, sender_id=SENDER )
    context, ids = _ctx( target, [ _sender_note( -90 ) ] )
    assert context[ "attachments" ][ 0 ][ "tier" ] == "sender"
    assert arm_text( "Q+H", target, context, ids ) == ( "message of target\n\nPrevious answer in this session: message of prev -> yes", None )


def test_history_arm_session_answer_outside_the_window_is_not_used():
    target       = _note( "target", 0, sender_id=SENDER )
    context, ids = _ctx( target, [ _sender_note( -121 ) ] )
    assert context[ "context_state" ] == "reconstructed"
    assert arm_text( "Q+H", target, context, ids ) == ( "message of target", "arm_input_absent" )


def test_history_arm_session_answer_exactly_at_the_window_edge_is_used():
    target       = _note( "target", 0, sender_id=SENDER )
    context, ids = _ctx( target, [ _sender_note( -120 ) ] )
    assert "in this session" in arm_text( "Q+H", target, context, ids )[ 0 ]


def test_history_arm_uses_a_session_tier_answer_from_another_sender_of_the_same_session():
    target       = _note( "target", 0, sender_id=SENDER )
    other        = _sender_note( -30, sender_id="other.agent@lupin.deepily.ai#ab12cd34" )
    context, ids = _ctx( target, [ other ] )
    assert context[ "attachments" ][ 0 ][ "tier" ] == "session"
    assert "in this session: message of prev -> yes" in arm_text( "Q+H", target, context, ids )[ 0 ]


def test_history_arm_thread_answer_wins_over_a_later_session_answer():
    target       = _note( "target", 0, thread_id="t1", sender_id=SENDER )
    thread_prev  = _prev( note_id="th", minutes=-100, answered_minutes=-90, value="thread-answer", sender_id="x@y#zzzz" )
    session_prev = _sender_note( -10, note_id="se", value="session-answer" )
    context, ids = _ctx( target, [ thread_prev, session_prev ] )
    text = arm_text( "Q+H", target, context, ids )[ 0 ]
    assert "on this thread" in text and text.endswith( "thread-answer" )


def test_history_arm_session_answer_wins_by_latest_answer_among_session_candidates():
    target       = _note( "target", 0, sender_id=SENDER )
    early        = _sender_note( -60, note_id="early", value="early-answer", responded_at=( T0 - timedelta( minutes=50 ) ).isoformat() )
    late         = _sender_note( -70, note_id="late", value="late-answer" )
    context, ids = _ctx( target, [ early, late ] )
    assert arm_text( "Q+H", target, context, ids )[ 0 ].endswith( "late-answer" )


def test_history_arm_takes_the_answer_given_last_and_breaks_ties_by_id():
    target       = _note( "target", 0, thread_id="t1" )
    others       = [ _prev( note_id="b", minutes=-40, answered_minutes=-10, value="b-answer" ),
                     _prev( note_id="a", minutes=-35, answered_minutes=-10, value="a-answer" ),
                     _prev( note_id="old", minutes=-50, answered_minutes=-30, value="old" ) ]
    context, ids = _ctx( target, others )
    assert arm_text( "Q+H", target, context, ids )[ 0 ].endswith( "message of a -> a-answer" )


def test_history_arm_renders_structured_answer_as_sorted_json():
    target       = _note( "target", 0, thread_id="t1" )
    context, ids = _ctx( target, [ _prev( value={ "b": 1, "a": [ "x" ] } ) ] )
    assert arm_text( "Q+H", target, context, ids )[ 0 ].endswith( '-> {"a": ["x"], "b": 1}' )


def test_history_arm_refuses_an_answer_that_postdates_the_ask():
    target  = _note( "target", 0, thread_id="t1" )
    context = { "context_state": "reconstructed", "attachments": [
        { "id": "prev", "tier": "thread", "answer": { "status": "answered", "value": "yes", "answer_known_at": ( T0 + timedelta( minutes=1 ) ).isoformat() } } ] }
    with pytest.raises( ValueError, match="after the ask" ):
        arm_text( "Q+H", target, context, { "prev": _prev() } )


def test_build_counts_each_fallback_reason_and_adds_up():
    with_prev = _note( "t", 0, thread_id="t1" )
    no_answer = _note( "b", 0, thread_id="t2" )
    lone_ask  = _note( "l", 0, thread_id="t3" )
    contexts  = { "t": rebuild_context( with_prev, [ _prev() ] ), "b": rebuild_context( no_answer, [ _note( "e", -5, thread_id="t2" ) ] ),
                  "l": rebuild_context( lone_ask, [] ) }
    result    = build_arm_texts( "Q+H", [ with_prev, no_answer, lone_ask ], contexts, { "prev": _prev() } )
    assert result[ "arm" ] == "Q+H"
    assert list( result[ "texts" ] ) == [ "t", "b", "l" ]
    assert result[ "texts" ][ "t" ].endswith( "-> yes" )
    assert result[ "texts" ][ "b" ] == "message of b" and result[ "texts" ][ "l" ] == "message of l"
    assert result[ "counts" ] == { "asks": 3, "with_section": 1, "no_context": 1, "arm_input_absent": 1 }


def test_build_for_arm_q_counts_every_ask_as_with_text_and_needs_no_notes():
    asks   = [ _note( "a", 0 ), _note( "b", 1 ) ]
    result = build_arm_texts( "Q", asks, { "a": rebuild_context( asks[ 0 ], [] ), "b": rebuild_context( asks[ 1 ], [] ) }, {} )
    assert result[ "texts" ] == { "a": "message of a", "b": "message of b" }
    assert result[ "counts" ] == { "asks": 2, "with_section": 2, "no_context": 0, "arm_input_absent": 0 }


def test_build_refuses_an_unknown_arm_and_a_missing_context():
    ask = _note( "a", 0 )
    with pytest.raises( ValueError ): build_arm_texts( "nope", [ ask ], { "a": rebuild_context( ask, [] ) }, {} )
    with pytest.raises( KeyError ): build_arm_texts( "Q", [ ask ], {}, {} )


def _row( note_id, minutes, **extra ):
    """
    Build a Notification-shaped row `minutes` after the fixed ask time.

    Requires:
        - note_id is a string and minutes is a number

    Ensures:
        - returns a namespace with every Notification column the arm builders read
    """
    row = dict( id=note_id, created_at=T0 + timedelta( minutes=minutes ), message=f" row {note_id} ", abstract=None, response_options=None,
                sender_id=SENDER, reply_to=None, thread_id=None, job_id=None, direction="ai_to_human", response_requested=False,
                responded_at=None, response_value=None )
    row.update( extra )
    return SimpleNamespace( **row )


class _Query:
    """Hands back its rows and keeps the filter it was given, so a test can read the SQL."""

    def __init__( self, rows, seen ):
        self.rows = rows
        self.seen = seen

    def filter( self, condition ):
        self.seen.append( str( condition ) )
        return self

    def all( self ):
        return self.rows


class _Session:
    """A session over a few rows: get by id, and a query that returns the question rows."""

    def __init__( self, rows ):
        self.rows = { r.id: r for r in rows }
        self.seen = []

    def get( self, model, key ):
        return self.rows.get( key )

    def query( self, model ):
        return _Query( [ r for r in self.rows.values() if r.response_requested ], self.seen )


def test_notification_dict_carries_the_columns_as_text_and_iso_times():
    row    = _row( "n1", 0, responded_at=T0 + timedelta( minutes=1 ), response_value="yes", abstract="abs" )
    result = notification_dict( row )
    assert result[ "created_at" ] == T0.isoformat() and result[ "responded_at" ] == ( T0 + timedelta( minutes=1 ) ).isoformat()
    assert result[ "response_value" ] == "yes" and result[ "abstract" ] == "abs" and result[ "id" ] == "n1"
    assert notification_dict( _row( "n2", 0 ) )[ "responded_at" ] is None


def _cohort():
    """
    Build a prior answered question and two asks on one thread.

    Ensures:
        - returns ( session, asks ) where the ask ids are "a1" and "a2"
    """
    prior = _row( "p", -30, thread_id="t1", response_requested=True, response_value="yes", responded_at=T0 - timedelta( minutes=20 ) )
    a1    = _row( "a1", 0, thread_id="t1", response_requested=True, abstract="why" )
    a2    = _row( "a2", 5, thread_id="t9", response_requested=True )
    return _Session( [ prior, a1, a2 ] ), [ { "id": "a1" }, { "id": "a2" } ]


def test_read_arm_inputs_returns_targets_in_order_and_a_question_pool():
    session, asks = _cohort()
    session.rows[ "plain" ] = _row( "plain", -40 )
    targets, notes = read_arm_inputs( session, asks )
    assert [ t[ "id" ] for t in targets ] == [ "a1", "a2" ]
    assert set( notes ) == { "p", "a1", "a2" }
    assert "response_requested IS true" in session.seen[ 0 ]


def test_read_arm_inputs_refuses_an_ask_with_no_notification():
    session, _ = _cohort()
    with pytest.raises( LookupError, match="no notification row" ):
        read_arm_inputs( session, [ { "id": "missing" } ] )


def test_build_cohort_arms_builds_every_arm_from_the_notification_not_the_case_row():
    session, asks = _cohort()
    result = build_cohort_arms( session, asks )
    assert list( result ) == list( ARMS )
    assert result[ "Q" ][ "texts" ][ "a1" ] == "row a1"
    assert result[ "Q+A" ][ "texts" ][ "a1" ] == "row a1\n\nAbstract: why"
    assert result[ "Q+H" ][ "texts" ][ "a1" ] == "row a1\n\nPrevious answer on this thread: row p -> yes"
    assert result[ "Q+H" ][ "texts" ][ "a2" ] == "row a2"
    assert result[ "Q+H" ][ "counts" ][ "with_section" ] == 1


def test_build_cohort_arms_can_build_a_chosen_subset_of_arms():
    session, asks = _cohort()
    assert list( build_cohort_arms( session, asks, ( "Q+P", ) ) ) == [ "Q+P" ]
