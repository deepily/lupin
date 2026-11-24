"""
The answer history arm, over in-memory SQLite and the real time-sliced store.

The baseline's model call is a stand-in.

The baseline stand-in reads its replies with the real full-answer parser, so what the arm can emit is what that parser can store.
No test calls a model.

Each test names what it would catch:
  - an arm that cannot emit a neither, a qualified answer or a write-in  -> test_emit_*
  - an answer stored after the ask reaching the prompt                   -> test_boundary_*
  - a history longer than the budget, or one cut through an answer       -> test_budget_*
  - the switch changing today's behaviour                                -> test_switch_off_*
  - the labeller's reading reaching the prompt                           -> test_the_prompt_*
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import cosa.agents.prediction_engine.answer_history_forecast as ah
import cosa.agents.prediction_engine.episode_view as ev
import cosa.agents.prediction_engine.full_answer as fa
import cosa.agents.prediction_engine.principles_forecast as pf
from cosa.agents.prediction_engine.exposure import observation_view
from cosa.research.preference_replay import scratch_db  # noqa: F401  registers the one shared SQLite hooks for JSONB and Vector
from cosa.research.preference_replay.time_sliced_store import TimeSlicedDecisionStore
from cosa.rest.postgres_models import AnswerMeaning, Notification, PredictionArmForecast, PredictionLog

T0        = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
RECIPIENT = uuid.UUID( "00000000-0000-4000-8000-0000000000cc" )
OTHER     = uuid.UUID( "00000000-0000-4000-8000-0000000000dd" )
SENDER    = "claude.code@lupin.deepily.ai#ab12cd34"
SENTINEL  = "LABELLER-READING-SENTINEL"
PLAN_A    = "o1-ed5327"
CHOICES   = { "questions": [ { "header": "Plan", "question": "Which plan?", "options": [ { "label": "Plan A", "description": "the safe one" }, { "label": "Plan B (Recommended)" } ] } ] }
FREE      = { "questions": [ { "header": "Note", "input_type": "text" } ] }


def vec( x, y=0.0 ):
    """A 768-wide vector with two non-zero entries."""
    return [ float( x ), float( y ) ] + [ 0.0 ] * 766


class Embedder:
    """Every ask embeds to one vector."""

    def encode( self, text ):
        """Return the one vector."""
        return vec( 1, 0 )


class Failed( Exception ):
    """A failed model call, as the baseline's contract declares it."""


class Baseline:
    """A recording stand-in for the baseline job, reading replies with the real parser."""
    model             = "haiku-x"
    timeout_seconds   = 30
    errors            = ( Failed, )
    predictor_version = "c0-v1"

    def __init__( self, reply="{}" ):
        self.reply, self.calls = reply, []

    def build_prompts( self, episode ):
        """The baseline's own prompts: they depend on the card."""
        return "SYSTEM", f"USER prompt for {episode[ 'title' ]}"

    async def complete( self, model, system, user, timeout_seconds=None ):
        """Record the call and answer."""
        self.calls.append( { "model": model, "system": system, "user": user, "timeout": timeout_seconds } )
        return self.reply

    def parse( self, text, episode ):
        """Read the reply with the real full-answer parser."""
        return fa.parse_full_reply( text, episode )


@pytest.fixture
def factory( monkeypatch ):
    """Give a session factory over empty copies of the tables the arm uses."""
    engine = create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    for model in ( Notification, PredictionLog, PredictionArmForecast, AnswerMeaning ): model.__table__.create( engine )
    monkeypatch.setattr( ev, "pool_limit", lambda: 50 )
    yield lambda: Session( engine )
    engine.dispose()


def ask( factory, minutes=0, **extra ):
    """Insert one ask to the test recipient and return its id as text."""
    row = dict( id=uuid.uuid4(), sender_id=SENDER, recipient_id=RECIPIENT, title="Ship it?", message="Should the worker ship?", abstract="the plan",
                type="task", priority="medium", created_at=T0 + timedelta( minutes=minutes ), response_requested=True, response_type="yes_no" )
    row.update( extra )
    with factory() as db:
        db.add( Notification( **row ) )
        db.commit()
    return str( row[ "id" ] )


def answered( factory, minutes, answer="yes [comment: only with docs]", vector=None, annotated=None, source="human", owner=RECIPIENT, state="not_required", options=None, message=None, kind="yes_no" ):
    """
    Insert one earlier card with its answer and meaning record.

    Returns ( id, the store's case ). Minutes are relative to the module's first time stamp.
    The meaning record is annotated a minute after the answer unless annotated says otherwise.
    """
    extra = { "response_type": kind, "responded_at": T0 + timedelta( minutes=minutes ), "response_value": { "value": answer, "source": source, "answered_by": "rick" } }
    if options is not None: extra[ "response_options" ] = options
    if message is not None: extra[ "message" ] = message
    nid = ask( factory, minutes=minutes - 5, recipient_id=owner, **extra )
    with factory() as db:
        db.add( AnswerMeaning( notification_id=uuid.UUID( nid ), schema_version="v1", annotator="labeller", source="labeller", native_answer={ "reading": SENTINEL },
                               acts=[], conditions=[], alignment="unknown", unknowns=[], annotated_at=T0 + timedelta( minutes=minutes + 1 ) if annotated is None else annotated ) )
        db.commit()
    case = { "id": nid, "question": "q", "category": "c", "decision_value": answer if isinstance( answer, str ) else json.dumps( answer ), "ratification_state": state, "data_origin": "organic", "response_type": kind,
             "question_embedding": vector or vec( 1, 0.1 ), "created_at": "2026-11-01", "owner_user_id": str( owner ), "answer_source": source, "responded_at": T0 + timedelta( minutes=minutes ) }
    return nid, case


def run( factory, target, cases, reply="{}", budget=100000, enabled=True, gate=None, c0=None ):
    """Run the arm for one ask; return ( result, the baseline, the stored row or None )."""
    baseline = Baseline( reply ) if c0 is None else c0
    store    = TimeSlicedDecisionStore( cases )
    result   = asyncio.run( ah.run_answer_history( factory, target, baseline, store, Embedder(), budget, 30.0, gate or pf.CapGate( 2 ), enabled=enabled ) )
    with factory() as db:
        row = db.query( PredictionArmForecast ).filter( PredictionArmForecast.arm == ah.ARM ).first()
        if row is not None: db.expunge( row )
    return result, baseline, row


def reply( kind="yes_no", **edit ):
    """A full-answer reply the real parser accepts, edited by keyword."""
    body = { "acts": { act: 0.1 for act in fa.ACTS }, "qualification": { "probability": 0.1, "conditions": [] }, "gist": "g", "whole_card_probability": 0.6 }
    if kind == "yes_no": body[ "probabilities" ] = { "yes": 0.2, "no": 0.2, "neither": 0.6 }
    if kind == "multiple_choice": body[ "fields" ] = { "Plan": { "option_ids": [ PLAN_A ] } }
    body.update( edit )
    return json.dumps( body )


# ---- emit: the arm can produce each of the answers the old forecasters could not --------------------------------------------------------------

def test_emit_a_neither( factory ):
    """An arm that could only say yes or no would fail here."""
    nid, case = answered( factory, -60 )
    result, _, row = run( factory, ask( factory ), [ case ], reply() )
    assert result == { "status": "ran", "reason": None } and row.arm == "answer_history"
    assert row.forecast[ "value" ] == "neither" and row.evidence_ids == [ nid ]
    assert row.applicability is None, "this arm runs no applicability check, so its row reads NULL"


def test_emit_a_qualified_answer( factory ):
    """A forecast whose conditions are dropped would fail here."""
    _, case = answered( factory, -60 )
    body    = reply( probabilities={ "yes": 0.7, "no": 0.2, "neither": 0.1 }, qualification={ "probability": 0.8, "conditions": [ { "text": "leave the configuration alone", "modifies_option_id": None } ] } )
    _, _, row = run( factory, ask( factory ), [ case ], body )
    assert row.forecast[ "value" ] == "yes" and row.forecast[ "qualifier" ] == "leave the configuration alone"


def test_emit_a_write_in( factory ):
    """A choice card forecast that cannot name a write-in would fail here."""
    _, case = answered( factory, -60 )
    target  = ask( factory, response_type="multiple_choice", response_options=CHOICES )
    _, _, row = run( factory, target, [ case ], reply( "multiple_choice", fields={ "Plan": { "write_in": "Plan C" } } ) )
    assert row.forecast[ "fields" ] == { "Plan": { "write_in": "Plan C" } }


# ---- the prompt shows whole earlier answers and nothing the labeller read ---------------------------------------------------------------------

def test_the_prompt_shows_the_whole_earlier_answer_with_option_ids_and_never_the_labellers_reading( factory ):
    """A prompt with the meaning record, or without the options or ids, fails here."""
    nid, case = answered( factory, -60, answer={ "Plan": "Plan B (Recommended)", "Extra": "typed words" }, options=CHOICES, message="Which plan, earlier?", kind="multiple_choice" )
    _, baseline, row = run( factory, ask( factory ), [ case ], reply() )
    user = baseline.calls[ 0 ][ "user" ]
    assert user.startswith( "USER prompt for Ship it?\n\n" + ah.BLOCK_HEADING + "\nEarlier answer 1:\nQuestion: Which plan, earlier?" )
    assert '[Plan#o1] "Plan A"' in user and '"Plan B (Recommended)" (recommended by the asker)' in user
    assert 'Answer given: {"Extra": "typed words", "Plan": "Plan B (Recommended)"}' in user
    assert SENTINEL not in user, "the labeller's reading is never shown"
    assert baseline.calls[ 0 ][ "system" ] == "SYSTEM"
    assert row.evidence_ids == [ nid ]


def test_the_prompt_shows_a_comment_exactly_as_typed( factory ):
    """A comment cut off or reworded would fail here."""
    _, case = answered( factory, -60, answer="no [comment: not before the demo, and ask Maya]" )
    _, baseline, _ = run( factory, ask( factory ), [ case ], reply() )
    assert 'Answer given: "no [comment: not before the demo, and ask Maya]"' in baseline.calls[ 0 ][ "user" ]


def test_the_prompt_is_the_baselines_own_when_nothing_is_eligible( factory ):
    """An empty history must leave the baseline's prompt untouched."""
    _, baseline, _ = run( factory, ask( factory ), [], reply() )
    assert baseline.calls[ 0 ][ "user" ] == "USER prompt for Ship it?"


def test_render_answer_marks_a_free_text_field_and_survives_a_card_with_no_fields():
    """A free-text field and a bare card are both shown, never skipped or raised on."""
    free = observation_view( "open_ended", FREE, { "value": "words" }, T0, None, None )
    assert ah.render_answer( "Why?", free ) == 'Question: Why?\n- Note: (free text)\nAnswer given: "words"'
    bare = observation_view( "yes_no", None, None, T0, None, None )
    assert ah.render_answer( "Ship?", bare ) == "Question: Ship?\nAnswer given: null"


# ---- the ask-time boundary -------------------------------------------------------------------------------------------------------------------

def test_boundary_an_answer_stored_after_the_ask_is_never_retrieved( factory ):
    """A perfect match answered a minute after the ask never reaches the prompt."""
    early, early_case = answered( factory, -60, vector=vec( 1, 0.3 ) )
    late, late_case   = answered( factory, 1, vector=vec( 1, 0 ) )
    result, baseline, row = run( factory, ask( factory ), [ early_case, late_case ], reply() )
    assert row.evidence_ids == [ early ], "only the earlier answer is shown"
    assert late not in row.evidence_ids and baseline.calls[ 0 ][ "user" ].count( "Earlier answer" ) == 1


def test_boundary_an_answer_at_the_exact_ask_instant_counts( factory ):
    """The ask's own instant is inside the boundary, for the answer and its meaning record."""
    nid, case = answered( factory, 0, annotated=T0 )
    _, _, row = run( factory, ask( factory ), [ case ], reply() )
    assert row.evidence_ids == [ nid ]


def test_boundary_the_provider_checks_the_time_itself_when_the_store_would_let_one_through( factory ):
    """eligible_cases refuses an answer later than the ask even if the store handed it over."""
    _, case = answered( factory, 1, annotated=T0 - timedelta( minutes=5 ) )
    with factory() as db:
        assert ah.eligible_cases( db, [ case ], str( RECIPIENT ), T0 ) == []
        assert ah.eligible_cases( db, [ { **case, "responded_at": None } ], str( RECIPIENT ), T0 ) == []


def test_boundary_a_meaning_record_written_after_the_ask_makes_the_card_ineligible( factory ):
    """The card's meaning record must have existed at the ask."""
    _, case = answered( factory, -60, annotated=T0 + timedelta( minutes=5 ) )
    _, _, row = run( factory, ask( factory ), [ case ], reply() )
    assert row.evidence_ids == []


def test_a_card_is_ineligible_unless_a_human_of_this_owner_answered_and_it_was_not_thumbed_down( factory ):
    """Another owner, a proxy answer and a rejected answer are kept out."""
    good_id, good_case = answered( factory, -60 )
    _, proxy    = answered( factory, -50, source="proxy" )
    _, other    = answered( factory, -40, owner=OTHER )
    _, rejected = answered( factory, -30, state="Rejected" )
    _, _, row = run( factory, ask( factory ), [ good_case, proxy, other, rejected ], reply() )
    assert row.evidence_ids == [ good_id ]


def test_a_card_whose_notification_has_gone_is_skipped( factory ):
    """A neighbour with no notification row is left out and the rest still show."""
    kept, kept_case = answered( factory, -60 )
    gone, gone_case = answered( factory, -50 )
    with factory() as db:
        db.query( Notification ).filter( Notification.id == uuid.UUID( gone ) ).delete()
        db.commit()
    _, _, row = run( factory, ask( factory ), [ kept_case, gone_case ], reply() )
    assert row.evidence_ids == [ kept ]


# ---- the budget ------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize( "budget", [ 0, 1, 40, 80, 120, 1000 ] )
def test_budget_the_rendered_history_never_exceeds_it( factory, budget ):
    """A history longer than its budget would fail here, for every budget tried."""
    cases = [ answered( factory, -60 + n, answer=f"yes [comment: reason number {n} " + "x" * 30 + "]", vector=vec( 1, 0.1 * n ) )[ 1 ] for n in range( 6 ) ]
    with factory() as db:
        block = ah.history_provider( TimeSlicedDecisionStore( cases ), Embedder(), budget, 30.0 )( db, ev.episode_view( db, ask( factory ), limit=50 ) )
    appended = f"\n\n{block[ 'heading' ]}\n{block[ 'text' ]}" if block[ "text" ] else ""
    assert ah.approx_tokens( appended ) <= budget, "the heading line counts inside the budget"
    assert block[ "text" ].count( "Earlier answer" ) == len( block[ "principle_ids" ] )
    assert budget < 120 or len( block[ "principle_ids" ] ) > 1, "a generous budget shows more than one answer, so the test can see a budget biting"


def test_budget_an_answer_is_shown_whole_or_not_at_all_and_stops_at_the_first_that_does_not_fit():
    """A weaker short answer must not jump a stronger long one, and none is cut."""
    entries = [ ( "a", "A" * 40 ), ( "b", "B" * 400 ), ( "c", "C" * 4 ) ]
    laid    = ah.render_history( entries, 30 )
    assert laid[ "ids" ] == [ "a" ] and laid[ "text" ] == "Earlier answer 1:\n" + "A" * 40
    assert ah.render_history( entries, 5 ) == { "text": "", "ids": [] }


def test_budget_counts_with_the_counter_it_is_given():
    """The unit is the caller's: a counter of one per answer lets that many in."""
    laid = ah.render_history( [ ( "a", "x" ), ( "b", "y" ), ( "c", "z" ) ], 2, count_tokens=lambda text: text.count( "Earlier answer" ) )
    assert laid[ "ids" ] == [ "a", "b" ]


def test_approx_tokens_is_characters_over_four_rounded_up():
    """Pinned to literals."""
    assert [ ah.approx_tokens( t ) for t in ( "", "a", "abcd", "abcde" ) ] == [ 0, 1, 1, 2 ]


# ---- the switch ------------------------------------------------------------------------------------------------------------------------------

def test_switch_off_nothing_is_read_called_or_written( factory ):
    """With the switch off the arm leaves no call and no row."""
    _, case = answered( factory, -60 )
    result, baseline, row = run( factory, ask( factory ), [ case ], reply(), enabled=False )
    assert result == { "status": "not_run", "reason": "switch off" } and baseline.calls == [] and row is None


def test_switch_off_reads_the_ini_key_which_ships_off( monkeypatch, factory ):
    """enabled=None asks the INI switch by its exact key, and the shipped value is off."""
    asked = []
    monkeypatch.setattr( ah.principles_forecast, "switch_enabled", lambda key: asked.append( key ) or False )
    assert ah.answer_history_enabled() is False and asked == [ "principle learner answer history arm enabled" ]
    monkeypatch.undo()
    assert ah.answer_history_enabled() is False, "the shipped INI value is off"
    _, case = answered( factory, -60 )
    result, _, row = run( factory, ask( factory ), [ case ], reply(), enabled=None )
    assert result[ "status" ] == "not_run" and row is None


def test_the_principles_arm_prompt_is_unchanged_by_the_block_provider_hook( factory ):
    """with_principles keeps its own heading for a block that names none."""
    block = { "text": "T", "principle_ids": [] }
    assert pf.with_principles( "S", "U", block ) == ( "S", f"U\n\n{pf.BLOCK_HEADING}\nT" )
    assert pf.with_principles( "S", "U", { **block, "heading": "H" } ) == ( "S", "U\n\nH\nT" )


# ---- the version -----------------------------------------------------------------------------------------------------------------------------

def test_the_version_suffix_hashes_the_history_rendering_code( monkeypatch ):
    """Changing how the history is shown must start a new ledger."""
    before = ah.version_suffix()
    assert before.startswith( "+answer-history-" ) and len( before ) == len( "+answer-history-" ) + ah.HASH_LENGTH
    for name in ( "render_answer", "render_history", "eligible_cases", "history_provider", "observation_view", "fields_of" ):
        original = getattr( ah, name )
        def changed( *args, **kwargs ): return original( *args, **kwargs )
        monkeypatch.setattr( ah, name, changed )
        assert ah.version_suffix() != before, name
        monkeypatch.setattr( ah, name, original )
    monkeypatch.setattr( ah, "BLOCK_HEADING", "another heading" )
    assert ah.version_suffix() != before
    monkeypatch.undo()
    assert ah.version_suffix() == before


def test_the_row_carries_the_baselines_version_and_the_suffix( factory ):
    """The stored version is the baseline's plus this arm's own suffix."""
    _, case = answered( factory, -60 )
    _, _, row = run( factory, ask( factory ), [ case ], reply() )
    assert row.predictor_version == "c0-v1" + ah.version_suffix() and len( row.predictor_version ) <= 100


# ---- a reply captured from the real model ----------------------------------------------------------------------------------------------------

FIXTURE = json.loads( ( Path( __file__ ).resolve().parent.parent / "fixtures" / "answer_history" / "real-reply.json" ).read_text( encoding="utf-8" ) )


def test_the_real_models_reply_is_read_by_the_real_reader_and_stored_with_the_evidence_ids( factory ):
    """The captured Haiku reply, read by the real full-answer reader, is stored."""
    shown, case = answered( factory, -60, answer="no [comment: wait for Maya's review first]", message="Should the worker ship the parser change today?" )
    target      = ask( factory, title=FIXTURE[ "target_title" ], message=FIXTURE[ "target_message" ] )
    result, _, row = run( factory, target, [ case ], FIXTURE[ "reply" ] )
    assert FIXTURE[ "model" ].startswith( "claude-haiku" ), "the fixture is a real Haiku reply, captured through the arm on 24 Nov 2026"
    assert result == { "status": "ran", "reason": None } and row.evidence_ids == [ shown ]
    assert row.forecast[ "value" ] == "no" and row.forecast[ "qualifier" ] == "Maya's review of the parser change has already been completed"


def test_the_captured_prompt_carries_the_history_block_after_the_baselines_prompt():
    """The prompt the real model saw held the baseline text, the heading, then the answers."""
    user = FIXTURE[ "user_prompt" ]
    assert user.index( "Reply: {" ) < user.index( ah.BLOCK_HEADING ) < user.index( "Earlier answer 1:" ) < user.index( "Earlier answer 2:" )
    assert 'Answer given: "no [comment: wait for Maya\'s review first]"' in user
