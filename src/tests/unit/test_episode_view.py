"""
The ask-time record, checked over real SQL on an in-memory SQLite copy.

SQLite stands in for Postgres only for the two tables read here; the JSONB columns are rendered as JSON.
Rows are synthetic. The fixture `fixtures/episode_view/synthetic-context-50.json` has the shape of the
50-target context export (targets and records) with invented content; no real row is committed.
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import cosa.agents.prediction_engine.episode_view as ev
from cosa.agents.prediction_engine.history_context_rebuild import SESSION_WINDOW, rebuild_context
from cosa.research.preference_replay.scratch_db import scratch_session
from cosa.rest.postgres_models import Notification, PredictionLog
from cosa.utils.iso_timestamp import aware_moment
import cosa.agents.prediction_engine.full_answer as fa


@pytest.fixture( autouse=True )
def full_answer_off( monkeypatch ):
    """
    Turn the full-answer reply off for every test in this file.

    These tests pin the episode without stable option ids. The INI ships the switch on since 24 Nov 2026.
    The on path is tested in test_full_answer.py.
    """
    monkeypatch.setattr( fa, "full_answer_enabled", lambda: False )


FIXTURE   = os.path.join( os.path.dirname( __file__ ), "fixtures", "episode_view", "synthetic-context-50.json" )
RECIPIENT = uuid.UUID( "00000000-0000-4000-8000-0000000000aa" )
STRANGER  = uuid.UUID( "00000000-0000-4000-8000-0000000000bb" )
T0        = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
SENDER    = "claude.code@lupin.deepily.ai#ab12cd34"


@pytest.fixture
def db():
    """
    Give a session over empty in-memory copies of the replay's tables.

    Ensures:
        - yields an active session from scratch_session; the SQLite caveats on ids are in that module
    """
    with scratch_session() as session:
        yield session


def _add( db, minutes=-60, nid=None, **extra ):
    """
    Insert one notification a number of minutes after the base time and return its id as text.

    Requires:
        - db is an open session and extra holds Notification columns

    Ensures:
        - the row goes to the test recipient from the test sender unless extra says otherwise
    """
    row = dict( id=uuid.UUID( nid ) if nid else uuid.uuid4(), sender_id=SENDER, recipient_id=RECIPIENT, message=f"message {minutes}", type="task",
                priority="medium", created_at=T0 + timedelta( minutes=minutes ), response_requested=False )
    row.update( extra )
    db.add( Notification( **row ) )
    db.commit()
    return str( row[ "id" ] )


def _question( db, minutes, answer_minutes=None, **extra ):
    """
    Insert a question, answered answer_minutes after the base time when given.

    Ensures:
        - returns the id as text
    """
    if answer_minutes is not None:
        extra.update( responded_at=T0 + timedelta( minutes=answer_minutes ), response_value={ "value": "yes", "source": "ui" } )
    return _add( db, minutes, response_requested=True, response_type="yes_no", **extra )


def _ids( episode ):
    """
    List the notification ids of an episode's history, in order.

    Ensures:
        - returns a list of strings
    """
    return [ h[ "notification_id" ] for h in episode[ "history" ] ]


def test_as_of_withholding_shows_an_answer_given_before_the_ask_and_reads_pending_after_it( db ):
    early  = _question( db, -50, answer_minutes=-10, thread_id="t1" )
    late   = _question( db, -40, answer_minutes=5, thread_id="t1" )
    ask    = _add( db, 0, thread_id="t1", response_requested=True, response_type="yes_no" )
    by_id  = { h[ "notification_id" ]: h for h in ev.episode_view( db, ask, limit=50 )[ "history" ] }
    assert by_id[ early ][ "status" ] == "answered" and by_id[ early ][ "answer" ] == { "value": "yes", "source": "ui" }
    assert by_id[ late ][ "status" ] == "pending" and "answer" not in by_id[ late ] and "answer_known_at" not in by_id[ late ]


def test_a_later_as_of_lets_the_later_answer_in_and_a_rows_after_the_ask_join_the_pool( db ):
    late   = _question( db, -40, answer_minutes=5, thread_id="t1" )
    after  = _question( db, 3, answer_minutes=4, thread_id="t1" )
    ask    = _add( db, 0, thread_id="t1", response_requested=True, response_type="yes_no" )
    narrow = { h[ "notification_id" ]: h[ "status" ] for h in ev.episode_view( db, ask, limit=50 )[ "history" ] }
    wide   = { h[ "notification_id" ]: h[ "status" ] for h in ev.episode_view( db, ask, as_of=T0 + timedelta( minutes=10 ), limit=50 )[ "history" ] }
    assert narrow == { late: "pending" }
    assert wide == { late: "answered", after: "answered" }


def test_the_ask_itself_is_never_in_its_own_history_even_when_as_of_is_later( db ):
    ask = _add( db, 0, thread_id="t1", response_requested=True, response_type="yes_no" )
    assert ev.episode_view( db, ask, as_of=T0 + timedelta( minutes=5 ), limit=50 )[ "history" ] == []


def test_as_of_before_the_ask_is_refused_and_a_missing_notification_is_named( db ):
    ask = _add( db, 0 )
    with pytest.raises( ValueError, match="before the ask" ):
        ev.episode_view( db, ask, as_of=T0 - timedelta( minutes=1 ), limit=50 )
    with pytest.raises( LookupError, match="does not exist" ):
        ev.episode_view( db, str( uuid.uuid4() ), limit=50 )
    with pytest.raises( ValueError, match="limit must be positive" ):
        ev.episode_view( db, ask, limit=0 )


def test_three_question_cut_takes_the_first_three_counts_pending_drops_missing_and_keeps_info_outside( db ):
    thread = [ _question( db, -60 + step, answer_minutes=-5, thread_id="t1" ) for step in range( 3 ) ]       # three answered thread questions
    job    = _question( db, -30, thread_id=None, job_id="j1" )                                              # pending, job tier, 4th in order
    info   = _add( db, -20, thread_id="t1", direction="human_to_ai" )                                         # informational, thread tier
    gap    = _question( db, -70, answer_minutes=-5, thread_id="other", job_id="j1" )                          # conflicting thread, so missing
    ask    = _add( db, 0, thread_id="t1", job_id="j1", response_requested=True, response_type="yes_no" )
    history = ev.episode_view( db, ask, limit=50 )[ "history" ]
    thread_newest_first = list( reversed( thread ) )
    assert [ h[ "notification_id" ] for h in history ] == thread_newest_first[ :0 ] + [ info ] + thread_newest_first
    questions = [ h for h in history if h[ "status" ] != "not_a_question" ]
    assert [ q[ "notification_id" ] for q in questions ] == thread_newest_first
    assert job not in _ids( { "history": history } ) and gap not in _ids( { "history": history } )
    assert [ h[ "status" ] for h in history if h[ "notification_id" ] == info ] == [ "not_a_question" ]


def test_a_pending_question_counts_toward_the_three( db ):
    pending  = _question( db, -10, thread_id="t1" )
    answered = [ _question( db, -30 + step, answer_minutes=-5, thread_id="t1" ) for step in range( 3 ) ]
    ask      = _add( db, 0, thread_id="t1", response_requested=True, response_type="yes_no" )
    ids      = _ids( ev.episode_view( db, ask, limit=50 ) )
    assert ids == [ pending, answered[ 2 ], answered[ 1 ] ]


def test_five_earlier_questions_keep_the_first_three_in_tier_then_newest_first_order( db ):
    ids = [ _question( db, -50 + step, answer_minutes=-5, thread_id="t1" ) for step in range( 5 ) ]
    ask = _add( db, 0, thread_id="t1", response_requested=True, response_type="yes_no" )
    assert _ids( ev.episode_view( db, ask, limit=50 ) ) == [ ids[ 4 ], ids[ 3 ], ids[ 2 ] ]


def test_a_stronger_tier_comes_before_a_newer_row_of_a_weaker_tier( db ):
    sender = _question( db, -5, answer_minutes=-1 )
    thread = _question( db, -40, answer_minutes=-1, thread_id="t1" )
    ask    = _add( db, 0, thread_id="t1", response_requested=True, response_type="yes_no" )
    assert _ids( ev.episode_view( db, ask, limit=50 ) ) == [ thread, sender ]


def test_session_tier_evidence_is_marked_inferred_and_thread_evidence_is_not( db ):
    thread  = _question( db, -30, answer_minutes=-5, thread_id="t1" )
    session = _question( db, -20, answer_minutes=-5, sender_id="other.agent@lupin.deepily.ai#ab12cd34" )
    ask     = _add( db, 0, thread_id="t1", response_requested=True, response_type="yes_no" )
    by_id   = { h[ "notification_id" ]: h for h in ev.episode_view( db, ask, limit=50 )[ "history" ] }
    assert ( by_id[ thread ][ "tier" ], by_id[ thread ][ "inferred" ], by_id[ thread ][ "confidence" ] ) == ( "thread", False, "certain" )
    assert ( by_id[ session ][ "tier" ], by_id[ session ][ "inferred" ], by_id[ session ][ "confidence" ] ) == ( "session", True, "inferred" )


def test_a_human_message_addressed_to_the_session_is_kept_beside_the_questions( db ):
    human = _add( db, -10, direction="human_to_ai", sender_id="rick@lupin.deepily.ai", job_id="ab12cd34" )
    ask   = _add( db, 0, response_requested=True, response_type="yes_no" )
    entry = ev.episode_view( db, ask, limit=50 )[ "history" ]
    assert [ ( e[ "notification_id" ], e[ "tier" ], e[ "status" ], e[ "inferred" ] ) for e in entry ] == [ ( human, "session", "not_a_question", True ) ]


def test_pool_filters_other_recipients_later_rows_and_rows_outside_the_session_window( db ):
    mine     = _question( db, -30, answer_minutes=-5, thread_id="t1" )
    _question( db, -30, answer_minutes=-5, thread_id="t1", recipient_id=STRANGER )                           # someone else's
    _question( db, 0, answer_minutes=1, thread_id="t1" )                                                       # created at the ask, not strictly before
    old      = _question( db, -( SESSION_WINDOW.total_seconds() / 60 ) - 1, answer_minutes=-5, sender_id="o.a@lupin.deepily.ai#ab12cd34" )
    ask      = _add( db, 0, thread_id="t1", response_requested=True, response_type="yes_no" )
    assert _ids( ev.episode_view( db, ask, limit=50 ) ) == [ mine ] and old not in _ids( ev.episode_view( db, ask, limit=50 ) )


def test_a_same_full_sender_joins_at_any_age_and_a_bare_sender_never_attaches( db ):
    ancient = _question( db, -60 * 24 * 30, answer_minutes=-60 * 24 * 29 )
    _question( db, -20, answer_minutes=-5, sender_id="bare.agent@lupin.deepily.ai" )
    ask     = _add( db, 0, sender_id="bare.agent@lupin.deepily.ai", response_requested=True, response_type="yes_no" )
    full    = _add( db, 0, response_requested=True, response_type="yes_no" )
    assert ev.episode_view( db, ask, limit=50 )[ "history" ] == []
    assert _ids( ev.episode_view( db, full, limit=50 ) ) == [ ancient ]


def test_parent_is_read_by_reply_to_and_a_reply_to_that_is_not_a_uuid_is_ignored( db ):
    parent = _question( db, -30, answer_minutes=-5 )
    ask    = _add( db, 0, reply_to=parent, sender_id="solo.agent@lupin.deepily.ai", response_requested=True, response_type="yes_no" )
    junk   = _add( db, 1, reply_to="not-a-uuid", sender_id="solo.agent@lupin.deepily.ai", response_requested=True, response_type="yes_no" )
    entry  = ev.episode_view( db, ask, limit=50 )[ "history" ]
    assert [ ( e[ "notification_id" ], e[ "tier" ] ) for e in entry ] == [ ( parent, "parent" ) ]
    assert ev.episode_view( db, junk, limit=50 )[ "history" ] == []


def test_a_row_found_by_two_tiers_enters_the_pool_once( db ):
    both = _question( db, -30, answer_minutes=-5, thread_id="t1", job_id="j1" )
    ask  = _add( db, 0, thread_id="t1", job_id="j1", response_requested=True, response_type="yes_no" )
    assert _ids( ev.episode_view( db, ask, limit=50 ) ) == [ both ]


def test_session_suffix_wildcards_do_not_widen_the_session_query( db ):
    _question( db, -10, answer_minutes=-5, sender_id="o.a@lupin.deepily.ai#abXXcd34" )
    ask = _add( db, 0, sender_id="claude.code@lupin.deepily.ai#ab%cd34", response_requested=True, response_type="yes_no" )
    assert ev.episode_view( db, ask, limit=50 )[ "history" ] == []


@pytest.mark.parametrize( "limit", [ 50, 500 ] )
def test_bounded_pool_equals_a_full_pool_rebuild_when_every_tier_is_under_the_limit( db, limit ):
    _fill_from_fixture( db )
    checked = 0
    statuses = {}
    for target_id, target in _fixture_targets().items():
        rows = [ r for r in _fixture_records().values() if r[ "id" ] != target_id ]
        full = ev.history_of( rebuild_context( target, rows ) )
        got  = ev.episode_view( db, target_id, limit=limit )
        assert got[ "pool" ][ "truncated" ] == []
        assert got[ "history" ] == full, target_id
        for entry in got[ "history" ]: statuses[ entry[ "status" ] ] = statuses.get( entry[ "status" ], 0 ) + 1
        checked += 1
    assert checked == 50
    assert statuses == { "not_a_question": 10, "pending": 10, "answered": 92 }, "literal counts of the fixture, not derived from the code under test"


def test_the_fixture_has_fifty_targets_and_each_tier_is_exercised():
    assert len( _fixture_targets() ) == 50 and len( _fixture_records() ) == 160
    tiers = set()
    states = set()
    for target in _fixture_targets().values():
        context = rebuild_context( target, list( _fixture_records().values() ) )
        states.add( context[ "context_state" ] )
        tiers |= { a[ "tier" ] for a in context[ "attachments" ] }
    assert tiers == { "thread", "job", "sender", "session" } and states == { "reconstructed", "no_context", "ambiguous_only" }


def test_a_tier_over_the_limit_is_named_and_the_rows_that_drop_are_its_oldest( db ):
    thread = [ _question( db, -100 + step, answer_minutes=-5, thread_id="t1" ) for step in range( 6 ) ]   # oldest first
    ask    = _add( db, 0, thread_id="t1", response_requested=True, response_type="yes_no" )
    small  = ev.episode_view( db, ask, limit=4 )
    full   = ev.episode_view( db, ask, limit=50 )
    assert small[ "pool" ] == { "limit": 4, "truncated": [ "thread", "sender", "session" ] }
    assert _ids( full ) == [ thread[ 5 ], thread[ 4 ], thread[ 3 ] ]
    assert _ids( small ) == _ids( full )                                                                      # the cut keeps the same three
    dropped = set( thread ) - set( _pool_ids( db, ask, 4 ) )
    assert dropped == { thread[ 0 ], thread[ 1 ] }


def test_over_the_limit_with_mostly_informational_rows_the_cut_loses_a_question_and_the_tier_says_so( db ):
    first  = _question( db, -100, answer_minutes=-5, thread_id="t1" )
    for step in range( 5 ): _add( db, -90 + step, thread_id="t1", direction="human_to_ai" )
    ask    = _add( db, 0, thread_id="t1", response_requested=True, response_type="yes_no" )
    got    = ev.episode_view( db, ask, limit=3 )
    assert first not in _ids( got ) and "thread" in got[ "pool" ][ "truncated" ]
    assert first in _ids( ev.episode_view( db, ask, limit=50 ) )


def _pool_ids( db, ask_id, limit ):
    """
    List the ids the loader keeps for one ask at one limit.

    Ensures:
        - returns the pool's notification ids as a list of strings
    """
    row = db.get( Notification, uuid.UUID( ask_id ) )
    return [ n[ "id" ] for n in ev.load_pool( db, row, aware_moment( row.created_at ), limit )[ 0 ] ]


def test_pool_loader_reports_each_truncated_tier_once_in_tier_order( db ):
    for step in range( 3 ):
        _question( db, -60 + step, thread_id="t1", job_id="j1", answer_minutes=-5 )
    ask = _add( db, 0, thread_id="t1", job_id="j1", response_requested=True, response_type="yes_no" )
    row = db.get( Notification, uuid.UUID( ask ) )
    pool, truncated = ev.load_pool( db, row, aware_moment( row.created_at ), 2 )
    assert truncated == [ "thread", "job", "sender", "session" ] and len( pool ) == 2


def test_card_fields_carry_prompt_mode_option_descriptions_recommended_flags_and_default( db ):
    options = { "questions": [
        { "header": "held_bugs", "question": "Approve the held bugs?", "multi_select": False,
          "options": [ { "label": "Approve", "description": "Merge now", "recommended": True }, { "label": "Hold (Recommended)" }, { "label": "Reject", "description": "Drop it" } ] },
        { "header": "themes", "question": "Which themes?", "multi_select": True, "options": [ { "label": "A" }, { "label": "B" } ] },
        { "header": "budget", "question": "Budget?", "input_type": "text", "default_value": "no limit" } ] }
    ask    = _add( db, 0, response_requested=True, response_type="multiple_choice", response_options=options, response_default="Reject" )
    fields = ev.episode_view( db, ask, limit=50 )[ "fields" ]
    assert fields[ 0 ] == { "key": "held_bugs", "prompt": "Approve the held bugs?", "mode": "single", "default": "o3", "options": [
        { "id": "o1", "label": "Approve", "description": "Merge now", "recommended": True },
        { "id": "o2", "label": "Hold (Recommended)", "description": None, "recommended": True },
        { "id": "o3", "label": "Reject", "description": "Drop it", "recommended": False } ] }
    assert ( fields[ 1 ][ "mode" ], fields[ 1 ][ "default" ] ) == ( "multi", None )
    assert fields[ 2 ] == { "key": "budget", "prompt": "Budget?", "mode": "text", "options": [], "default": "no limit" }


def test_a_card_with_no_questions_has_no_fields_and_no_default_text( db ):
    plain = _add( db, 0, response_requested=True, response_type="yes_no" )
    assert ev.episode_view( db, plain, limit=50 )[ "fields" ] == []
    assert ev.fields_of( { "questions": [ { "header": "h", "question": "q", "options": [ { "label": "x" } ] } ] }, None )[ 0 ][ "default" ] is None
    assert ev.fields_of( { "questions": [ { "header": "h", "question": "q" } ] }, None )[ 0 ] == { "key": "h", "prompt": "q", "mode": "single", "options": [], "default": None }


def test_links_are_typed_by_what_they_point_to():
    abstract = ( "See [spec](/app/docs?path=lupin/a.md), [approve](/app/tasks/approve?row=abc), [view](/app/tasks/view?row=abc), "
                 "[site](https://example.org/x) and [odd](/somewhere)." )
    assert [ l[ "kind" ] for l in ev.links_of( abstract ) ] == [ "supporting_doc", "approval", "task_view", "external", "other" ]
    assert ev.links_of( abstract )[ 1 ] == { "kind": "approval", "target": "/app/tasks/approve?row=abc" }
    assert ev.links_of( None ) == [] and ev.links_of( "no links here" ) == []


def test_header_fields_project_asker_title_and_asked_at_are_the_asks_own( db ):
    ask = _add( db, 0, title="A title", abstract="abs [d](/app/docs?path=lupin/x.md)", message="Q?" )
    ep  = ev.episode_view( db, ask, as_of=T0 + timedelta( minutes=9 ), limit=50 )
    assert ( ep[ "owner_id" ], ep[ "project" ], ep[ "asker" ], ep[ "title" ] ) == ( str( RECIPIENT ), "lupin", SENDER, "A title" )
    assert ep[ "asked_at" ] == T0.isoformat() and ep[ "links" ] == [ { "kind": "supporting_doc", "target": "/app/docs?path=lupin/x.md" } ]
    odd = _add( db, 1, sender_id="nobody" )
    assert ev.episode_view( db, odd, limit=50 )[ "project" ] is None


def _log( db, notification_id, **extra ):
    """
    Insert a prediction_log row for a notification.

    Ensures:
        - the row carries only the required columns plus extra
    """
    db.add( PredictionLog( id=uuid.uuid4(), notification_id=uuid.UUID( notification_id ), response_type="yes_no", category="c", prediction_strategy="s",
                           predicted_at=T0, prediction_confidence=0.5, similar_case_count=0, **extra ) )
    db.commit()


def test_exposure_reads_fold_opened_at_once_it_is_known_and_leaves_a_missing_draft_unknown( db ):
    seen   = _add( db, 0, response_requested=True, response_type="yes_no" )
    unseen = _add( db, 1, response_requested=True, response_type="yes_no" )
    opened = T0 + timedelta( minutes=7 )
    _log( db, seen, fold_opened_at=opened )
    _log( db, unseen )
    later  = ev.episode_view( db, seen, as_of=opened + timedelta( minutes=1 ), limit=50 )
    assert later[ "exposure" ] == { "revealed_at": opened.isoformat(), "draft_at_reveal": None }
    assert ev.episode_view( db, unseen, limit=50 )[ "exposure" ] == { "revealed_at": None, "draft_at_reveal": None }
    nolog = _add( db, 2 )
    assert ev.episode_view( db, nolog, limit=50 )[ "exposure" ] == { "revealed_at": None, "draft_at_reveal": None }


def test_a_reveal_after_as_of_reads_none_and_the_raw_value_stays_readable_for_the_ledger( db ):
    seen   = _add( db, 0, response_requested=True, response_type="yes_no" )
    opened = T0 + timedelta( minutes=7 )
    _log( db, seen, fold_opened_at=opened )
    assert ev.episode_view( db, seen, limit=50 )[ "exposure" ][ "revealed_at" ] is None
    assert ev.episode_view( db, seen, as_of=opened - timedelta( seconds=1 ), limit=50 )[ "exposure" ][ "revealed_at" ] is None
    assert ev.revealed_at( db, uuid.UUID( seen ) ) == opened.isoformat()


def test_a_reveal_exactly_at_as_of_is_known( db ):
    seen   = _add( db, 0, response_requested=True, response_type="yes_no" )
    opened = T0 + timedelta( minutes=7 )
    _log( db, seen, fold_opened_at=opened )
    assert ev.episode_view( db, seen, as_of=opened, limit=50 )[ "exposure" ][ "revealed_at" ] == opened.isoformat()


def test_an_answer_given_exactly_at_the_ask_reads_answered( db ):
    exact = _question( db, -30, answer_minutes=0, thread_id="t1" )
    ask   = _add( db, 0, thread_id="t1", response_requested=True, response_type="yes_no" )
    entry = ev.episode_view( db, ask, limit=50 )[ "history" ][ 0 ]
    assert ( entry[ "notification_id" ], entry[ "status" ], entry[ "answer_known_at" ] ) == ( exact, "answered", T0.isoformat() )


def test_sixty_newer_same_sender_rows_on_another_thread_do_not_push_out_an_older_question( db ):
    old = _question( db, -200, answer_minutes=-150 )
    for step in range( 60 ): _question( db, -100 + step, answer_minutes=-5, thread_id="tX" )
    ask = _add( db, 0, thread_id="t1", response_requested=True, response_type="yes_no" )
    got = ev.episode_view( db, ask, limit=50 )
    assert _ids( got ) == [ old ] and got[ "pool" ][ "truncated" ] == []


def test_sixty_newer_rows_on_another_job_do_not_push_out_an_older_question_in_the_sender_or_session_tier( db ):
    old     = _question( db, -200, answer_minutes=-150 )
    old_ses = _question( db, -110, answer_minutes=-105, sender_id="o.a@lupin.deepily.ai#ab12cd34" )
    for step in range( 60 ):
        _question( db, -100 + step, answer_minutes=-5, job_id="jX" )
        _question( db, -100 + step, answer_minutes=-5, job_id="jX", sender_id="o.a@lupin.deepily.ai#ab12cd34" )
    ask = _add( db, 0, job_id="j1", response_requested=True, response_type="yes_no" )
    got = ev.episode_view( db, ask, limit=50 )
    assert _ids( got ) == [ old, old_ses ] and got[ "pool" ][ "truncated" ] == []


def test_sixty_newer_human_messages_on_another_job_do_not_push_out_an_older_one_in_the_session_tier( db ):
    old = _add( db, -100, direction="human_to_ai", sender_id="rick@lupin.deepily.ai", job_id="ab12cd34" )
    for step in range( 60 ): _add( db, -90 + step, direction="human_to_ai", sender_id="rick@lupin.deepily.ai", job_id="ab12cd34", thread_id="tX" )
    ask = _add( db, 0, thread_id="t1", response_requested=True, response_type="yes_no" )
    got = ev.episode_view( db, ask, limit=50 )
    assert _ids( got ) == [ old ] and got[ "pool" ][ "truncated" ] == []


def test_rows_with_no_thread_or_a_blank_one_still_join_through_the_sender_when_the_ask_has_a_thread( db ):
    none  = _question( db, -30, answer_minutes=-5 )
    blank = _question( db, -20, answer_minutes=-5, thread_id="" )
    same  = _question( db, -10, answer_minutes=-5, thread_id="t1" )
    ask   = _add( db, 0, thread_id="t1", response_requested=True, response_type="yes_no" )
    assert _ids( ev.episode_view( db, ask, limit=50 ) ) == [ same, blank, none ]


def test_the_limit_comes_from_the_ini_key_when_not_passed( db, monkeypatch ):
    thread = [ _question( db, -100 + step, answer_minutes=-5, thread_id="t1" ) for step in range( 3 ) ]
    ask    = _add( db, 0, thread_id="t1", response_requested=True, response_type="yes_no" )
    monkeypatch.setattr( ev, "pool_limit", lambda: 2 )
    ep = ev.episode_view( db, ask )
    assert ep[ "pool" ] == { "limit": 2, "truncated": [ "thread", "sender", "session" ] }


def test_pool_limit_reads_the_live_ini_key_as_fifty():
    assert ev.POOL_LIMIT_KEY == "prediction learner episode pool per tier limit" and ev.pool_limit() == 50


def test_pool_limit_refuses_a_non_positive_value( monkeypatch ):
    class _Manager:
        def __init__( self, env_var_name ): pass
        def get_required( self, key, return_type=None ): return 0
    monkeypatch.setattr( ev, "ConfigurationManager", _Manager )
    with pytest.raises( ValueError, match="positive integer" ):
        ev.pool_limit()


def _fixture():
    """
    Load the synthetic export.

    Ensures:
        - returns the parsed JSON dict with targets and records
    """
    with open( FIXTURE, encoding="utf-8" ) as handle: return json.load( handle )


def _fixture_records():
    """
    Give the fixture's notifications keyed by id.

    Ensures:
        - returns { id: notification dict } for all 160 rows, targets included
    """
    return { k: v[ "notification" ] for k, v in _fixture()[ "records" ].items() }


def _fixture_targets():
    """
    Give the fixture's fifty targets keyed by id.

    Ensures:
        - returns { id: notification dict }
    """
    return { t[ "target_notification_id" ]: t[ "target_notification" ] for t in _fixture()[ "targets" ] }


def _fill_from_fixture( db ):
    """
    Insert every fixture notification as a row.

    Requires:
        - db is an open session over empty tables

    Ensures:
        - one Notification row per fixture record, with times parsed and ids as UUIDs
    """
    for record in _fixture_records().values():
        row = dict( record )
        row[ "id" ]           = uuid.UUID( row[ "id" ] )
        row[ "recipient_id" ] = uuid.UUID( row[ "recipient_id" ] )
        for name in ( "created_at", "responded_at" ):
            row[ name ] = aware_moment( row[ name ] )
        row.pop( "answer_status_at_target", None )
        db.add( Notification( **row ) )
    db.commit()


def test_a_stored_draft_is_returned_with_its_reveal_and_a_draft_stored_after_as_of_is_not( db ):
    seen   = _add( db, 0, response_requested=True, response_type="yes_no" )
    opened = T0 + timedelta( minutes=7 )
    draft  = { "value": "half typed" }
    _log( db, seen, fold_opened_at=opened, draft_at_reveal=draft )
    known  = ev.episode_view( db, seen, as_of=opened, limit=50 )[ "exposure" ]
    assert known == { "revealed_at": opened.isoformat(), "draft_at_reveal": draft }
    early  = ev.episode_view( db, seen, as_of=opened - timedelta( seconds=1 ), limit=50 )[ "exposure" ]
    assert early == { "revealed_at": None, "draft_at_reveal": None }
    assert ev.revealed_draft( db, uuid.UUID( seen ) ) == draft


def test_revealed_draft_is_none_with_no_log_row_no_reveal_or_no_draft( db ):
    nolog = _add( db, 0 )
    plain = _add( db, 1 )
    nodr  = _add( db, 2 )
    _log( db, plain, draft_at_reveal={ "value": "x" } )
    _log( db, nodr, fold_opened_at=T0 + timedelta( minutes=1 ) )
    assert [ ev.revealed_draft( db, uuid.UUID( n ) ) for n in ( nolog, plain, nodr ) ] == [ None, None, None ]


_CARD = { "title": "T", "abstract": "", "fields": [ { "prompt": "P1", "options": [ { "label": "A" }, { "label": "" } ] }, { "prompt": "P2", "options": [ { "label": "B" } ] } ] }


def test_card_text_leaves_the_option_labels_out_unless_asked():
    assert ev.card_text( _CARD ) == "T\nP1\nP2"


def test_card_text_with_options_puts_each_field_s_labels_after_its_prompt_and_skips_blanks():
    assert ev.card_text( _CARD, include_options=True ) == "T\nP1\nA\nP2\nB"
