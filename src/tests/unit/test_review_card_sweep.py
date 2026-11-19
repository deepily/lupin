"""
The review-card sweep: contested principles to one capped card, sent without waiting.

Real SQL on in-memory SQLite, a recording dispatcher double, and a fixed clock for the cap.
All rows are synthetic. Ids carry a letter other than "e", because SQLite reads an all-digit id back as a number.
"""

import asyncio
import json
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cosa.agents.principle_learner import review_card_sweep as sweep
from cosa.agents.principle_learner import review_cards as rc
from cosa.agents.principle_learner.extractor_job import PrincipleExtractorJob
from cosa.rest.job_state import JobState
from cosa.rest.postgres_models import Notification, PredictionLog, PreferenceEvidence, PreferencePrinciple

OWNER   = uuid.UUID( "00000000-0000-4000-8000-0000000000aa" )
T0      = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
NOW     = T0 + timedelta( hours=2 )
VERSION = "ext"


@compiles( JSONB, "sqlite" )
def _jsonb_as_json( element, compiler, **kw ):
    """Render JSONB as JSON on SQLite."""
    return "JSON"


@compiles( Vector, "sqlite" )
def _vector_as_text( element, compiler, **kw ):
    """Render a pgvector column as text on SQLite."""
    return "TEXT"


@pytest.fixture( autouse=True )
def _clean_sends():
    """Forget this process's sent cards before and after each test."""
    sweep.forget_sends()
    yield
    sweep.forget_sends()


@pytest.fixture
def db():
    """Yield a session over empty in-memory copies of the tables the sweep reads."""
    engine = create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    for model in ( Notification, PredictionLog, PreferencePrinciple, PreferenceEvidence ): model.__table__.create( engine )
    with Session( engine ) as session:
        yield session
    engine.dispose()


class Dispatcher:
    """A dispatcher double: records each call, and can hold the call open until released."""

    def __init__( self, hold=False, raises=None ):
        self.calls   = []
        self.release = threading.Event()
        self.hold    = hold
        self.raises  = raises
        self.entered = threading.Event()

    async def present_choices( self, questions, **kwargs ):
        self.calls.append( { "questions": questions, **kwargs } )
        self.entered.set()
        if self.hold: await asyncio.to_thread( self.release.wait, 5 )
        if self.raises is not None: raise self.raises
        return { "answers": {} }


def _ask( db, answer, minutes ):
    """Insert a yes/no ask with its stored answer, and return its id."""
    row = dict( id=uuid.uuid4(), sender_id="claude.code@lupin.deepily.ai#ab12cd34", recipient_id=OWNER, message="Approve?", title="T", type="task",
                priority="low", created_at=T0 + timedelta( minutes=minutes ), response_requested=True, response_type="yes_no",
                responded_at=T0 + timedelta( minutes=minutes + 1 ), response_value={ "value": answer, "source": "ui" } )
    db.add( Notification( **row ) )
    db.commit()
    return row[ "id" ]


def _contested( db, number, version=VERSION ):
    """Insert a principle with a supporting yes and a contradicting no; return its row."""
    principle = PreferencePrinciple( id=uuid.UUID( f"00000000-0000-4000-8000-0000000c{number:04d}" ), owner_id=str( OWNER ), kind="decision", dimension="ask.x",
                                     statement=f"Statement {number}.", scope="global", embedding=None, encoder_version="enc", extractor_version=version )
    db.add( principle )
    db.commit()
    for relation, answer, minutes in ( ( "supports", "yes", 1 ), ( "contradicts", "no", 5 ) ):
        nid = _ask( db, answer, minutes + number * 10 )
        db.add( PreferenceEvidence( id=uuid.uuid4(), principle_id=principle.id, notification_id=nid, field_key="answer", relation=relation, condition=None,
                                    answered_at=T0 + timedelta( minutes=minutes + 1 ), extracted_at=T0 + timedelta( minutes=minutes + 2 ),
                                    extractor_version=version, source="extractor" ) )
    db.commit()
    return principle


def _run( coroutine ):
    """Run one coroutine to the end."""
    return asyncio.run( coroutine )


def _sweep( db, dispatcher, now=NOW, cap=3 ):
    """Run one sweep over the session with the test settings."""
    return _run( sweep.sweep_review_cards( db, OWNER, now, cap, dispatcher, VERSION, 3600 ) )


def _join( dispatcher_used ):
    """Wait for every detached send thread to finish."""
    for thread in list( threading.enumerate() ):
        if thread.daemon and thread is not threading.current_thread() and thread.name.startswith( "Thread" ): thread.join( 2 )


# ---- the contested list ------------------------------------------------------------------------

def test_a_contested_principle_becomes_an_item_with_both_answers_and_a_plain_one_does_not( db ):
    """Only the contested principle is listed, with both of its answers."""
    contested = _contested( db, 1 )
    plain     = PreferencePrinciple( id=uuid.UUID( "00000000-0000-4000-8000-0000000c9999" ), owner_id=str( OWNER ), kind="decision", dimension="ask.y",
                                     statement="Plain.", scope="global", embedding=None, encoder_version="enc", extractor_version=VERSION )
    db.add( plain )
    db.add( PreferenceEvidence( id=uuid.uuid4(), principle_id=plain.id, notification_id=_ask( db, "yes", 300 ), field_key="answer", relation="supports",
                                condition=None, answered_at=T0, extracted_at=T0 + timedelta( minutes=1 ), extractor_version=VERSION, source="extractor" ) )
    db.commit()
    items = sweep.contested_items( db, OWNER, NOW, VERSION )
    assert [ i[ "principle_id" ] for i in items ] == [ str( contested.id ) ]
    assert items[ 0 ][ "statement" ] == "Statement 1."
    assert json.loads( items[ 0 ][ "answer_a" ] ) == { "qualifier": None, "stance": "yes" } and json.loads( items[ 0 ][ "answer_b" ] ) == { "qualifier": None, "stance": "no" }


def test_a_missing_ask_reads_as_a_placeholder_and_a_long_answer_is_cut( db ):
    """The answer line never raises and never runs past its limit."""
    assert sweep._answer_text( None ) == "(the answer could not be found)"
    row = Notification( id=uuid.uuid4(), sender_id="s", recipient_id=OWNER, message="m", type="task", priority="low", created_at=T0, response_requested=True,
                        response_type="open_ended", responded_at=T0, response_value={ "value": "x" * 500, "source": "ui" } )
    assert len( sweep._answer_text( row ) ) == sweep.ANSWER_CHARS


def test_a_principle_on_a_recent_unanswered_card_is_left_out_until_the_card_ages_out_of_the_window( db ):
    """The same principle is not sent twice while its card is open, and may be after a day."""
    principle = _contested( db, 1 )
    questions, extras = rc.build_card( [ { "principle_id": str( principle.id ), "statement": "s", "answer_a": "a", "answer_b": "b" } ] )
    db.add( Notification( id=uuid.uuid4(), sender_id="s", recipient_id=OWNER, message="m", type="task", priority="low", created_at=NOW - timedelta( hours=1 ),
                          response_requested=True, response_type="multiple_choice", response_options={ "questions": questions, **extras } ) )
    answered = Notification( id=uuid.uuid4(), sender_id="s", recipient_id=OWNER, message="m", type="task", priority="low", created_at=NOW - timedelta( hours=2 ),
                             response_requested=True, response_type="multiple_choice", responded_at=NOW - timedelta( hours=1, minutes=59 ),
                             response_options={ "questions": questions, **extras } )
    db.add( answered )
    db.add( Notification( id=uuid.uuid4(), sender_id="s", recipient_id=OWNER, message="m", type="task", priority="low", created_at=NOW - timedelta( hours=3 ),
                          response_requested=True, response_type="yes_no", response_options=None ) )
    db.commit()
    assert sweep.contested_items( db, OWNER, NOW, VERSION ) == []
    assert sweep.contested_items( db, OWNER, NOW + timedelta( hours=22 ), VERSION ) == []
    assert len( sweep.contested_items( db, OWNER, NOW + timedelta( hours=25 ), VERSION ) ) == 1


# ---- sending without waiting -------------------------------------------------------------------

def test_the_card_is_sent_on_its_own_thread_and_the_sweep_returns_before_the_answer( db ):
    """The sweep returns while the dispatcher holds its call; the call has the marker and wait."""
    _contested( db, 1 )
    dispatcher = Dispatcher( hold=True )
    report     = _sweep( db, dispatcher )
    assert dispatcher.entered.wait( 2 ) and report == { "contested": 1, "sent": True, "deferred": 0, "sent_in_window": 0 }
    call = dispatcher.calls[ 0 ]
    assert call[ "timeout" ] == 3600 and call[ "response_options_extra" ][ "review_card" ] is True
    dispatcher.release.set()
    _join( dispatcher )


def test_a_failing_send_thread_is_swallowed_and_reported_in_the_log( db, capsys ):
    """A card that ends with no answer prints one line and raises nothing."""
    _contested( db, 1 )
    dispatcher = Dispatcher( raises=RuntimeError( "no answer" ) )
    assert _sweep( db, dispatcher )[ "sent" ] is True
    assert dispatcher.entered.wait( 2 )
    _join( dispatcher )
    assert "card ended without an answer: RuntimeError: no answer" in capsys.readouterr().out


def test_no_contested_principle_sends_nothing( db ):
    """An empty list calls no dispatcher."""
    dispatcher = Dispatcher()
    assert _sweep( db, dispatcher ) == { "contested": 0, "sent": False, "deferred": 0, "sent_in_window": 0 }
    assert dispatcher.calls == []


# ---- the cap counts at send, with a fixed clock ------------------------------------------------

def test_a_card_counts_against_the_cap_when_it_is_sent_even_if_it_is_never_stored_or_answered( db ):
    """Sixteen contested principles, nothing stored: three cards go, a day later one more."""
    for number in range( 1, 17 ): _contested( db, number )
    dispatcher = Dispatcher()
    reports    = [ _sweep( db, dispatcher, now=NOW + timedelta( seconds=n ) ) for n in range( 4 ) ]
    _join( dispatcher )
    assert [ r[ "sent" ] for r in reports ] == [ True, True, True, False ]
    assert [ len( c[ "questions" ] ) for c in dispatcher.calls ] == [ 5, 5, 5 ]
    assert reports[ 3 ] == { "contested": 1, "sent": False, "deferred": 1, "sent_in_window": 3 }
    sent_ids = [ pid for c in dispatcher.calls for pid in c[ "response_options_extra" ][ "principle_ids" ].values() ]
    assert len( sent_ids ) == len( set( sent_ids ) ) == 15, "no principle went on two cards"
    after = _sweep( db, dispatcher, now=NOW + timedelta( hours=24, seconds=1 ) )
    assert after[ "sent" ] is True and after[ "sent_in_window" ] == 1


def test_a_stored_card_and_the_in_process_record_of_it_count_once( db ):
    """A stored card within a minute of a recorded send is the same card."""
    _contested( db, 1 )
    sweep._remember_send( OWNER, NOW, [ "x" ] )
    questions, extras = rc.build_card( [ { "principle_id": "00000000-0000-4000-8000-00000000f00d", "statement": "s", "answer_a": "a", "answer_b": "b" } ] )
    db.add( Notification( id=uuid.uuid4(), sender_id="s", recipient_id=OWNER, message="m", type="task", priority="low", created_at=NOW + timedelta( seconds=20 ),
                          response_requested=True, response_type="multiple_choice", responded_at=NOW + timedelta( seconds=30 ),
                          response_options={ "questions": questions, **extras } ) )
    db.commit()
    assert len( sweep._sent_times( db, OWNER, NOW + timedelta( minutes=5 ) ) ) == 1
    assert len( sweep._sent_times( db, OWNER, NOW + timedelta( minutes=5 ) + timedelta( hours=0 ) ) ) == 1
    sweep._remember_send( OWNER, NOW + timedelta( minutes=3 ), [ "y" ] )
    assert len( sweep._sent_times( db, OWNER, NOW + timedelta( minutes=5 ) ) ) == 2


def test_forgetting_sends_clears_the_process_record_and_old_sends_age_out( db ):
    """Old sends age out of the window, and forget_sends empties the record."""
    sweep._remember_send( OWNER, NOW, [ "a" ] )
    sweep._remember_send( OWNER, NOW + timedelta( hours=25 ), [ "b" ] )
    assert sweep._sent_principles( OWNER, NOW + timedelta( hours=25 ) ) == { "b" }
    sweep.forget_sends()
    assert sweep._sent_principles( OWNER, NOW + timedelta( hours=25 ) ) == set()


# ---- the job -----------------------------------------------------------------------------------

def _ini_version():
    """The extractor version the real INI file names, as the job computes it."""
    from cosa.agents.principle_learner.extractor_job import MODEL_KEY
    from cosa.config.configuration_manager import ConfigurationManager
    return sweep.extractor_version_of( ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get_required( MODEL_KEY ) )


def _job( db, dispatcher, cap=3, clock=lambda: NOW ):
    """Build the sweep job over the test doubles."""
    from contextlib import contextmanager

    @contextmanager
    def factory():
        yield db
        db.commit()
    return sweep.ReviewCardSweepJob( str( OWNER ), "owner@example.com", dispatcher=dispatcher, session_factory=factory, clock=clock, cap=cap )


def test_the_job_runs_one_sweep_and_returns_its_report_as_json_through_do_all( db ):
    """do_all sweeps once and completes, with the INI model and wait read for real."""
    _contested( db, 1, version=_ini_version() )
    job = _job( db, Dispatcher() )
    report = json.loads( job.do_all() )
    assert report[ "sent" ] is True and report[ "contested" ] == 1 and job.state == JobState.COMPLETED
    assert job.last_question_asked == f"[Review card sweep] {OWNER}" and job.id_hash.startswith( "pr" )


def test_the_job_reads_the_cap_from_the_ini_file_when_none_is_given( db ):
    """With no cap passed, the shipped cap of 3 applies."""
    for number in range( 1, 17 ): _contested( db, number, version=_ini_version() )
    job = _job( db, Dispatcher(), cap=None )
    assert job.cap is None
    reports = [ json.loads( asyncio.run( job._execute() ) ) for _ in range( 4 ) ]
    assert [ r[ "sent" ] for r in reports ] == [ True, True, True, False ]


def test_the_job_builds_a_dispatcher_for_the_owner_and_the_helper_builds_the_job_for_the_extractor_owner( db ):
    """The default dispatcher goes to the owner; the helper copies the extractor's owner."""
    job = sweep.ReviewCardSweepJob( str( OWNER ), "owner@example.com" )
    assert job._dispatcher().target_user == "owner@example.com"
    extractor = PrincipleExtractorJob( uuid.uuid4(), str( OWNER ), "owner@example.com" )
    follow    = sweep.sweep_job_after( extractor )
    assert isinstance( follow, sweep.ReviewCardSweepJob ) and follow.user_id == str( OWNER ) and follow.user_email == "owner@example.com"


def test_the_extractor_module_stays_silent_and_never_imports_the_sweep():
    """The extractor job's source names neither the sweep nor a card."""
    import cosa.agents.principle_learner.extractor_job as extractor_module
    source = open( extractor_module.__file__ ).read()
    assert "review_card_sweep" not in source and "send_review_card" not in source


def test_the_shipped_wait_is_at_least_as_long_as_the_cap_window():
    """A card stays open at least as long as the cap window lasts."""
    from cosa.config.configuration_manager import ConfigurationManager
    wait = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get_required( sweep.WAIT_KEY, return_type="int" )
    assert wait == 86400 and wait >= rc.WINDOW.total_seconds()


def test_an_answered_card_does_not_hold_its_principle_back_if_the_principle_is_still_contested( db ):
    """Only an unanswered card blocks; a card answered with no option leaves the principle free."""
    principle = _contested( db, 1 )
    questions, extras = rc.build_card( [ { "principle_id": str( principle.id ), "statement": "s", "answer_a": "a", "answer_b": "b" } ] )
    db.add( Notification( id=uuid.uuid4(), sender_id="s", recipient_id=OWNER, message="m", type="task", priority="low", created_at=NOW - timedelta( hours=2 ),
                          response_requested=True, response_type="multiple_choice", responded_at=NOW - timedelta( hours=1 ),
                          response_value={ "value": json.dumps( { "answers": { "P1": "free text" } } ), "source": "ui" },
                          response_options={ "questions": questions, **extras } ) )
    db.commit()
    assert [ i[ "principle_id" ] for i in sweep.contested_items( db, OWNER, NOW, VERSION ) ] == [ str( principle.id ) ]
