"""
The principles forecast, over in-memory SQLite and a stand-in for the baseline job.

The baseline job does not exist yet, so a small recording class stands in for it.
It holds the contract the module documents.
Everything else is real: episode_view, principle retrieval and status, and the sibling table.
The cosine operator of pgvector does not exist on SQLite, so dot_topk is replaced by a stand-in.
The stand-in applies the real filter and ranks by cosine in Python.

Each test names what it would catch:
  - the call running while switched off, or before the baseline exists  -> test_not_run_*
  - a prompt that differs from the baseline's by more than the block    -> test_the_call_*
  - a forecast built from principles that came after the ask            -> test_principles_after_the_ask_*
  - a failed or unreadable call that stores nothing or two rows         -> test_a_failed_*, test_an_unreadable_*
  - the cap queueing, leaking a place, or hiding in not_ready           -> test_the_cap_*, test_the_summary_*
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import cosa.agents.prediction_engine.episode_view as ev
import cosa.agents.prediction_engine.principle_retrieval as pr
import cosa.agents.prediction_engine.principles_forecast as pf
from cosa.research.preference_replay import scratch_db  # noqa: F401  registers the one shared SQLite hooks for JSONB and Vector
from cosa.rest.db.repositories.arm_forecast_repository import CAPPED_ARM_REASON
from cosa.rest.postgres_models import Notification, PredictionArmForecast, PredictionLog, PreferenceEvidence, PreferencePrinciple

T0       = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
RECIPIENT = uuid.UUID( "00000000-0000-4000-8000-0000000000aa" )
SENDER   = "claude.code@lupin.deepily.ai#ab12cd34"
ENCODER  = "model-x:statement-rationale-v1"
EXTRACT  = "sonnet|v1"


def vec( x, y ):
    """A 768-wide vector with two non-zero entries."""
    return [ float( x ), float( y ) ] + [ 0.0 ] * 766


@pytest.fixture
def factory( monkeypatch ):
    """
    Give a session factory over empty copies of the tables the call reads or writes.

    The engine is disposed afterwards.
    """
    engine = create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    for model in ( Notification, PredictionLog, PredictionArmForecast, PreferencePrinciple, PreferenceEvidence ): model.__table__.create( engine )
    monkeypatch.setattr( ev, "pool_limit", lambda: 50 )
    def stand_in( session, model, vector_column, query_embedding, limit, exclude_filter=None, threshold_pct=None, clamp=False, metric="dot" ):
        rows  = session.query( model ).filter( exclude_filter ).all()
        q     = np.array( query_embedding )
        pairs = [ ( float( np.dot( q, r.embedding ) / ( np.linalg.norm( q ) * np.linalg.norm( r.embedding ) ) ) * 100.0, r ) for r in rows ]
        return sorted( pairs, key=lambda pair: -pair[ 0 ] )[ :limit ]
    monkeypatch.setattr( pr, "dot_topk", stand_in )
    yield lambda: Session( engine )
    engine.dispose()


def ask( factory, minutes=0, **extra ):
    """Insert one ask to the test recipient and return its id as text."""
    row = dict( id=uuid.uuid4(), sender_id=SENDER, recipient_id=RECIPIENT, title="Which plan?", message="pick one", abstract="the plan", type="task",
                priority="medium", created_at=T0 + timedelta( minutes=minutes ), response_requested=True, response_type="yes_no" )
    row.update( extra )
    with factory() as db:
        db.add( Notification( **row ) )
        db.commit()
    return str( row[ "id" ] )


def principle( factory, statement="link what you ask me to approve", embedding=None, extracted=-60 ):
    """Insert one principle of the test recipient with one supporting row, and return its id."""
    pid = uuid.uuid4()
    with factory() as db:
        db.add( PreferencePrinciple( id=pid, owner_id=str( RECIPIENT ), kind="decision", dimension="d", statement=statement, scope="global",
                                     embedding=embedding or vec( 1, 1 ), encoder_version=ENCODER, extractor_version=EXTRACT ) )
        db.add( PreferenceEvidence( id=uuid.uuid4(), principle_id=pid, notification_id=uuid.uuid4(), field_key="f", relation="supports", condition=None,
                                    answered_at=T0 + timedelta( minutes=extracted ), extracted_at=T0 + timedelta( minutes=extracted ),
                                    extractor_version=EXTRACT, source="extractor" ) )
        db.commit()
    return pid


class Failed( Exception ):
    """A failed model call, as the baseline's contract declares it."""


class Baseline:
    """A recording stand-in for the baseline job, holding the contract the module documents."""
    model             = "haiku-x"
    timeout_seconds   = 30
    errors            = ( Failed, )
    predictor_version = "c0-v1"

    def __init__( self, reply="yes", fail=None, bad_reply=False ):
        self.reply, self.fail, self.bad_reply, self.calls = reply, fail, bad_reply, []

    def build_prompts( self, episode ):
        """The baseline's own prompts: they depend on the card."""
        return "SYSTEM", f"USER prompt for {episode[ 'title' ]}"

    async def complete( self, model, system, user, timeout_seconds=None ):
        """Record the call and answer, or fail."""
        self.calls.append( { "model": model, "system": system, "user": user, "timeout": timeout_seconds } )
        if self.fail: raise self.fail
        return self.reply

    def parse( self, text, episode ):
        """Read the reply as a stance, or refuse."""
        if self.bad_reply: raise ValueError( "not a stance" )
        return { "stance": text }


class Embedder:
    """Return one fixed query vector for every card."""
    def encode( self, text ): return vec( 1, 0 )


def run( factory, nid, c0, gate=None, enabled=True, now=None ):
    """Run the principles forecast for one card."""
    gate = gate or pf.CapGate( 2 )
    clock = ( lambda: now ) if now else None
    return asyncio.run( pf.run_b1( factory, nid, c0, Embedder(), ENCODER, EXTRACT, gate, enabled=enabled, clock=clock ) )


def rows( factory ):
    """All sibling rows."""
    with factory() as db: return db.query( PredictionArmForecast ).all()


def test_not_run_while_the_switch_is_off_reads_calls_and_writes_nothing( factory ):
    """With the switch off no row is written and the baseline is never touched."""
    nid = ask( factory )
    class Untouchable:
        def __getattr__( self, name ): raise AssertionError( f"the baseline was touched: {name}" )
    assert run( factory, nid, Untouchable(), enabled=False ) == { "status": "not_run", "reason": "switch off" }
    assert rows( factory ) == []


def test_not_run_before_the_baseline_exists_reads_blocked( factory ):
    """
    With the switch on and no baseline job, the answer is the blocked reason.

    Nothing is written.
    """
    assert run( factory, ask( factory ), None ) == { "status": "not_run", "reason": "blocked by phase 6" }
    assert rows( factory ) == []


def test_the_call_is_the_baselines_prompt_plus_the_block_and_nothing_else( factory ):
    """
    The call keeps the baseline's model, timeout and system prompt.

    The user prompt is the baseline's, then the heading and the block.
    """
    nid, pid = ask( factory ), principle( factory )
    c0       = Baseline()
    result   = run( factory, nid, c0, now=T0 + timedelta( minutes=1 ) )
    call     = c0.calls[ 0 ]
    assert result == { "status": "ran", "reason": None } and len( c0.calls ) == 1
    assert ( call[ "model" ], call[ "system" ], call[ "timeout" ] ) == ( "haiku-x", "SYSTEM", 30 )
    head, _, tail = call[ "user" ].partition( f"\n\n{pf.BLOCK_HEADING}\n" )
    assert head == "USER prompt for Which plan?" and "link what you ask me to approve" in tail and str( pid ) in tail


def test_the_row_carries_the_arm_the_version_the_cutoff_the_principles_and_the_ready_time( factory ):
    """
    One row: not displayed, the baseline's version plus the suffix, cutoff at the ask.

    It holds the principle ids and is ready at the clock.
    """
    nid, pid = ask( factory ), principle( factory )
    run( factory, nid, Baseline( reply="no" ), now=T0 + timedelta( minutes=1 ) )
    row = rows( factory )[ 0 ]
    assert ( row.arm, row.displayed, row.predictor_version, row.forecast, row.abstention_reason ) == ( "B1", False, "c0-v1+principles", { "stance": "no" }, None )
    assert row.evidence_ids == [ str( pid ) ] and str( row.notification_id ) == nid
    assert pf.aware_moment( row.input_cutoff ) == T0 and pf.aware_moment( row.forecast_ready_at ) == T0 + timedelta( minutes=1 )


def test_the_call_without_principles_equals_the_baselines_prompt( factory ):
    """
    With no principle the user prompt is the baseline's own.

    So the call differs from the baseline only by the block.
    """
    nid, c0 = ask( factory ), Baseline()
    run( factory, nid, c0 )
    assert c0.calls[ 0 ][ "user" ] == "USER prompt for Which plan?" and rows( factory )[ 0 ].evidence_ids == []


def test_principles_after_the_ask_are_not_in_the_block( factory ):
    """A principle whose only evidence was extracted after the ask is invisible to that ask."""
    nid = ask( factory )
    principle( factory, statement="a future rule", extracted=5 )
    c0 = Baseline()
    run( factory, nid, c0 )
    assert "a future rule" not in c0.calls[ 0 ][ "user" ] and rows( factory )[ 0 ].evidence_ids == []


def test_a_second_run_for_the_same_card_makes_no_call_and_writes_no_row( factory ):
    """A card with a principles row is left alone, at no cost."""
    nid, c0 = ask( factory ), Baseline()
    run( factory, nid, c0 )
    assert run( factory, nid, c0 ) == { "status": "not_run", "reason": "already stored" }
    assert len( c0.calls ) == 1 and len( rows( factory ) ) == 1


def test_a_failed_call_stores_one_row_with_the_reason_and_no_forecast( factory ):
    """
    A raised call error is recorded by class name.

    The row has no forecast and no ready time, and the cap place is returned.
    """
    nid, gate = ask( factory ), pf.CapGate( 1 )
    assert run( factory, nid, Baseline( fail=Failed( "boom" ) ), gate=gate ) == { "status": "failed", "reason": "model_error: Failed" }
    row = rows( factory )[ 0 ]
    assert ( row.forecast, row.forecast_ready_at, row.abstention_reason ) == ( None, None, "model_error: Failed" ) and gate.inflight == 0


def test_an_unreadable_reply_stores_one_row_with_its_reason( factory ):
    """A reply the baseline cannot parse is stored as unreadable_forecast with no forecast."""
    nid = ask( factory )
    assert run( factory, nid, Baseline( bad_reply=True ) ) == { "status": "failed", "reason": "unreadable_forecast" }
    assert rows( factory )[ 0 ].abstention_reason == "unreadable_forecast" and len( rows( factory ) ) == 1


def test_the_cap_turns_a_card_away_at_once_without_a_call_and_names_the_reason( factory ):
    """
    With the one place taken, a card gets a capacity row and no model call.

    The held place is not touched.
    """
    nid, gate, c0 = ask( factory ), pf.CapGate( 1 ), Baseline()
    assert gate.try_enter() is True
    assert run( factory, nid, c0, gate=gate ) == { "status": "capacity", "reason": CAPPED_ARM_REASON }
    row = rows( factory )[ 0 ]
    assert c0.calls == [] and ( row.forecast, row.abstention_reason, row.predictor_version ) == ( None, CAPPED_ARM_REASON, "c0-v1+principles" ) and gate.inflight == 1


def test_the_cap_for_a_missing_card_fails_loudly( factory ):
    """
    A card that does not exist cannot get a capacity row.

    The lookup error is raised, not swallowed.
    """
    gate = pf.CapGate( 1 )
    gate.try_enter()
    with pytest.raises( LookupError, match="does not exist" ): run( factory, str( uuid.uuid4() ), Baseline(), gate=gate )


def test_the_gate_validates_its_limit_counts_and_never_queues():
    """A gate refuses past its limit at once, frees a place on leave, and refuses a bad limit."""
    for bad in ( 0, -1, 1.5, "2" ):
        with pytest.raises( ValueError, match="positive int" ): pf.CapGate( bad )
    gate = pf.CapGate( 2 )
    assert [ gate.try_enter(), gate.try_enter(), gate.try_enter() ] == [ True, True, False ] and gate.inflight == 2
    gate.leave()
    assert gate.try_enter() is True and gate.inflight == 2


def test_with_principles_returns_the_prompts_unchanged_for_an_empty_block():
    """
    An empty block leaves both prompts as given.

    A block adds a blank line, the heading and the text to the user prompt only.
    """
    assert pf.with_principles( "S", "U", { "text": "" } ) == ( "S", "U" )
    assert pf.with_principles( "S", "U", { "text": "<b>" } ) == ( "S", f"U\n\n{pf.BLOCK_HEADING}\n<b>" )


def test_card_text_joins_the_title_the_abstract_and_the_field_prompts_and_skips_empties():
    """Empty parts are skipped, and each field's prompt is a line."""
    episode = { "title": "T", "abstract": None, "fields": [ { "prompt": "P1" }, { "prompt": "" }, { "prompt": "P2" } ] }
    assert pf.card_text( episode ) == "T\nP1\nP2"


class Stub:
    """A configuration manager stand-in."""
    def __init__( self, value=None, error=None ): self.value, self.error = value, error
    def get( self, key, default=None, return_type=None ):
        if self.error: raise self.error
        return self.value
    def get_required( self, key, return_type=None ): return self.value


def test_the_switch_reads_the_ini_and_an_unreadable_setting_reads_as_off( monkeypatch ):
    """True only when the key is true; a failing manager reads as off and does not raise."""
    monkeypatch.setattr( pf, "ConfigurationManager", lambda env_var_name=None: Stub( True ) )
    assert pf.principles_forecast_enabled() is True
    monkeypatch.setattr( pf, "ConfigurationManager", lambda env_var_name=None: Stub( False ) )
    assert pf.principles_forecast_enabled() is False
    monkeypatch.setattr( pf, "ConfigurationManager", lambda env_var_name=None: Stub( error=RuntimeError( "no ini" ) ) )
    assert pf.principles_forecast_enabled() is False


def test_run_b1_reads_the_switch_when_not_told( monkeypatch, factory ):
    """With no override the INI switch decides: off means not_run."""
    monkeypatch.setattr( pf, "ConfigurationManager", lambda env_var_name=None: Stub( False ) )
    result = asyncio.run( pf.run_b1( factory, ask( factory ), Baseline(), Embedder(), ENCODER, EXTRACT, pf.CapGate( 1 ) ) )
    assert result == { "status": "not_run", "reason": "switch off" }


def test_the_cap_is_read_from_the_ini_and_a_non_positive_cap_is_refused( monkeypatch ):
    """A positive cap is returned; zero is refused so a bad setting never means unbounded."""
    monkeypatch.setattr( pf, "ConfigurationManager", lambda env_var_name=None: Stub( 3 ) )
    assert pf.concurrency_cap() == 3
    monkeypatch.setattr( pf, "ConfigurationManager", lambda env_var_name=None: Stub( 0 ) )
    with pytest.raises( ValueError, match="positive integer" ): pf.concurrency_cap()


def test_the_writer_stores_one_row_per_card_even_when_called_twice( factory ):
    """
    Two writes for one card leave one row.

    This is the case of two runs racing past the check. The second write reports not written.
    """
    nid = ask( factory )
    first  = pf._write_row( factory, nid, T0, None, None, "v", [], "capacity" )
    second = pf._write_row( factory, nid, T0, None, None, "v", [], "capacity" )
    assert ( first, second, len( rows( factory ) ) ) == ( True, False, 1 )


def test_a_failure_gathering_inputs_stores_one_input_error_row_and_returns_failed( factory ):
    """
    An embedder that raises leaves one row with the reason, the cutoff and no forecast.

    The model is never called and the cap place is returned.
    """
    class Broken:
        def encode( self, text ): raise RuntimeError( "embedder down" )
    nid, gate, c0 = ask( factory ), pf.CapGate( 1 ), Baseline()
    result = asyncio.run( pf.run_b1( factory, nid, c0, Broken(), ENCODER, EXTRACT, gate, enabled=True ) )
    row    = rows( factory )[ 0 ]
    assert result == { "status": "failed", "reason": "input_error: RuntimeError", "stored": True } and c0.calls == [] and gate.inflight == 0
    assert ( row.forecast, row.forecast_ready_at, row.abstention_reason, row.evidence_ids, row.predictor_version ) == ( None, None, "input_error: RuntimeError", [], "c0-v1+principles" )
    assert pf.aware_moment( row.input_cutoff ) == T0 and len( rows( factory ) ) == 1


def test_a_missing_card_still_raises_because_it_has_no_cutoff_to_store( factory ):
    """A card that does not exist raises LookupError, writes no row and returns the cap place."""
    gate = pf.CapGate( 1 )
    with pytest.raises( LookupError, match="does not exist" ): run( factory, str( uuid.uuid4() ), Baseline(), gate=gate )
    assert rows( factory ) == [] and gate.inflight == 0


CONTRACT_NAMES = { "model", "timeout_seconds", "errors", "build_prompts", "complete", "parse", "predictor_version" }


def test_the_baseline_stand_in_meets_the_contract():
    """The recording stand-in passes the check, so the other tests start from a good baseline."""
    assert pf.check_baseline( Baseline() ) is None


def test_the_checked_names_are_exactly_the_documented_contract_and_the_ones_run_b1_uses( factory ):
    """
    The module docstring, the check and the run use one list of seven names.

    A name added on either side without the other reddens this test.
    """
    import re
    documented = set( re.findall( r"^- ``(\w+)", pf.__doc__.split( "contract, an object with:" )[ 1 ], flags=re.MULTILINE ) )
    checked    = set( pf.CONTRACT_VALUES ) | { pf.CONTRACT_ERRORS, pf.CONTRACT_ASYNC } | set( pf.CONTRACT_SYNC )
    touched    = set()
    class Watched( Baseline ):
        def __getattribute__( self, name ):
            if not name.startswith( "_" ) and name not in ( "reply", "fail", "bad_reply", "calls" ): touched.add( name )
            return super().__getattribute__( name )
    nid = ask( factory )
    run( factory, nid, Watched() )
    assert documented == checked == CONTRACT_NAMES and touched == CONTRACT_NAMES


@pytest.mark.parametrize( "name", sorted( CONTRACT_NAMES ) )
def test_a_baseline_missing_any_contract_member_is_refused_by_name( name ):
    """Removing any one member makes the check raise, naming that member."""
    class Missing( Baseline ): pass
    c0 = Missing()
    setattr( Missing, name, property( lambda self: ( _ for _ in () ).throw( AttributeError( name ) ) ) )
    with pytest.raises( TypeError, match=f"{name} is missing" ): pf.check_baseline( c0 )


@pytest.mark.parametrize( "change, expected", [
    ( { "model": "" },                                  "model must be a non-empty string" ),
    ( { "timeout_seconds": 0 },                         "timeout_seconds must be a positive number" ),
    ( { "timeout_seconds": True },                      "timeout_seconds must be a positive number" ),
    ( { "predictor_version": None },                    "predictor_version must be a non-empty string" ),
    ( { "errors": () },                                 "errors must be a non-empty tuple of exception classes" ),
    ( { "errors": [ Failed ] },                         "errors must be a non-empty tuple of exception classes" ),
    ( { "errors": ( "Failed", ) },                      "errors must be a non-empty tuple of exception classes" ),
    ( { "build_prompts": lambda a, b: None },           "build_prompts must take 1 argument(s)" ),
    ( { "build_prompts": None },                        "build_prompts must be a plain function" ),
    ( { "parse": lambda text: None },                   "parse must take 2 argument(s)" ),
    ( { "parse": None },                                "parse must be a plain function" ),
    ( { "complete": lambda *a, **k: None },             "complete must be an async function" ),
] )
def test_a_baseline_with_a_wrongly_shaped_member_is_refused_with_the_reason( change, expected ):
    """Each wrong shape is named: a bad value, a wrong argument count, a non-async complete."""
    c0 = Baseline()
    for key, value in change.items(): setattr( c0, key, value )
    with pytest.raises( TypeError, match=expected.replace( "(", r"\(" ).replace( ")", r"\)" ) ): pf.check_baseline( c0 )


def test_a_complete_that_cannot_take_a_timeout_and_an_async_parse_are_refused():
    """
    The call passes timeout_seconds, so complete must accept it.

    A coroutine parse would return an unawaited coroutine.
    """
    c0 = Baseline()
    async def no_timeout( model, system, user ): return "x"
    async def parse_async( text, episode ): return {}
    c0.complete = no_timeout
    with pytest.raises( TypeError, match="complete must accept timeout_seconds" ): pf.check_baseline( c0 )
    c0 = Baseline()
    c0.parse = parse_async
    with pytest.raises( TypeError, match="parse must be a plain function" ): pf.check_baseline( c0 )


def test_every_problem_is_reported_at_once():
    """A baseline wrong in two ways gets both reasons in one error."""
    c0 = Baseline()
    c0.model, c0.errors = "", ()
    with pytest.raises( TypeError ) as caught: pf.check_baseline( c0 )
    assert "model must be a non-empty string" in str( caught.value ) and "errors must be a non-empty tuple" in str( caught.value )


def test_run_b1_refuses_a_nonconforming_baseline_before_reading_or_writing_anything( factory ):
    """
    A baseline that fails the check raises TypeError at the first run.

    No row is written and no call is made.
    """
    nid, c0 = ask( factory ), Baseline()
    c0.errors = ()
    with pytest.raises( TypeError, match="does not meet the contract" ): run( factory, nid, c0 )
    assert rows( factory ) == [] and c0.calls == []


def test_a_row_that_arrives_between_the_check_and_the_insert_reads_as_already_stored( factory, monkeypatch ):
    """
    The check says no row, but another run's row exists, so the unique key refuses the insert.

    The write returns False, raises nothing, leaves one row, and the next write on a fresh session works.
    """
    nid, other = ask( factory ), ask( factory )
    assert pf._write_row( factory, nid, T0, None, None, "first", [], "capacity" ) is True
    monkeypatch.setattr( pf, "_row_present", lambda session, key, arm=None: False )
    assert pf._write_row( factory, nid, T0, None, None, "loser", [], "capacity" ) is False
    assert [ r.predictor_version for r in rows( factory ) ] == [ "first" ]
    assert pf._write_row( factory, other, T0, None, None, "next", [], "capacity" ) is True and len( rows( factory ) ) == 2


def test_with_the_database_down_the_input_failure_still_returns_failed_and_says_the_row_was_not_stored( factory ):
    """
    The first read works, then every session fails as a downed database would.

    The result is failed with stored False, nothing raises, no model is called and the cap place is returned.
    """
    from sqlalchemy.exc import OperationalError
    uses = []
    def going_down():
        uses.append( 1 )
        if len( uses ) > 1: raise OperationalError( "select", {}, Exception( "connection refused" ) )
        return factory()
    nid, gate, c0 = ask( factory ), pf.CapGate( 1 ), Baseline()
    result = asyncio.run( pf.run_b1( going_down, nid, c0, Embedder(), ENCODER, EXTRACT, gate, enabled=True ) )
    assert result == { "status": "failed", "reason": "input_error: OperationalError", "stored": False }
    assert c0.calls == [] and gate.inflight == 0 and rows( factory ) == [] and len( uses ) == 3


def test_the_capped_reason_is_the_one_word_the_repository_defines_and_the_summary_counts():
    """
    The capped reason is the repository's word, and the summary counts that word.

    This module imports it, so it has no copy of its own.
    """
    from cosa.research.preference_replay import arm_summary
    assert CAPPED_ARM_REASON == "capacity" and pf.CAPPED_ARM_REASON == CAPPED_ARM_REASON == arm_summary.CAPPED_ARM_REASON


def test_the_summary_reads_the_rows_this_module_writes_and_names_the_cap_and_the_missing_row( factory ):
    """
    The per-arm summary counts a ready row as timely and a capped row as capped.

    An answered card without a row is counted as no_row.

    This is the check that the rows written here are the rows the summary reads.
    """
    from cosa.research.preference_replay import arm_summary
    def logged( minutes ):
        nid = ask( factory, minutes )
        with factory() as db:
            db.add( PredictionLog( notification_id=uuid.UUID( nid ), response_type="yes_no", category="c", prediction_confidence=0.5, prediction_strategy="cbr",
                                   similar_case_count=0, predicted_at=T0, responded_at=T0 + timedelta( minutes=10 ), actual_value={ "value": "yes" } ) )
            db.commit()
        return nid
    ready, capped, missing = logged( 0 ), logged( 1 ), logged( 2 )
    gate = pf.CapGate( 1 )
    run( factory, ready, Baseline(), now=T0 + timedelta( minutes=5 ) )
    gate.try_enter()
    run( factory, capped, Baseline(), gate=gate )
    with factory() as db: summary = { row[ "arm" ]: row for row in arm_summary.per_arm_summary( db ) }[ "B1" ]
    assert ( summary[ "forecasts" ], summary[ "answered" ], summary[ "timely" ], summary[ "capped" ], summary[ "no_row" ] ) == ( 2, 2, 1, 1, 1 )
    assert missing not in [ str( r.notification_id ) for r in rows( factory ) ]


def test_no_forecast_prompt_renders_the_owners_draft_even_when_the_episode_is_read_after_the_reveal( factory, monkeypatch ):
    draft_marker = "UNAIDED-DRAFT-TEXT-0451"
    nid    = ask( factory, response_type="open_ended" )
    with factory() as db:
        db.add( PredictionLog( id=uuid.uuid4(), notification_id=uuid.UUID( nid ), response_type="open_ended", category="c", prediction_strategy="s", predicted_at=T0,
                               prediction_confidence=0.5, similar_case_count=0, fold_opened_at=T0 + timedelta( minutes=1 ), draft_at_reveal={ "value": draft_marker } ) )
        db.commit()
    late = T0 + timedelta( minutes=5 )
    with factory() as db: assert ev.episode_view( db, nid, as_of=late )[ "exposure" ][ "draft_at_reveal" ] == { "value": draft_marker }
    monkeypatch.setattr( pf, "episode_view", lambda session, notification_id: ev.episode_view( session, notification_id, as_of=late ) )
    principle( factory )
    for use_principles in ( False, True ):
        episode, _, block, system, user = pf._prepare( factory, nid, Baseline(), Embedder(), ENCODER, EXTRACT, 5, use_principles=use_principles )
        assert episode[ "exposure" ][ "draft_at_reveal" ] == { "value": draft_marker }
        assert draft_marker not in pf.card_text( episode ) and draft_marker not in block[ "text" ] and draft_marker not in system and draft_marker not in user
