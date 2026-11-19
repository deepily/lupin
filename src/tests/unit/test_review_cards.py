"""
The review card: the split step, the cap, the card as sent, and the ruling it writes.

Real SQL on in-memory SQLite for the rows; a recorded double for the model; a fixed clock for the cap.
All rows are synthetic. Ids carry a letter other than "e", because SQLite reads an all-digit id back as a number.
"""

import asyncio
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cosa.agents.prediction_engine.principle_status import CONTESTED, ESTABLISHED, HYPOTHESIS, RETRACTED, derive_statuses
from cosa.agents.prediction_engine.review_card import is_review_card
from cosa.agents.principle_learner import review_cards as rc
from cosa.agents.principle_learner.extractor_job import PrincipleExtractorJob
from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher
from cosa.rest.postgres_models import Notification, PredictionLog, PreferenceEvidence, PreferencePrinciple
from lupin_cli.notifications.notification_models import NotificationResponse

OWNER = uuid.UUID( "00000000-0000-4000-8000-0000000000aa" )
OTHER = uuid.UUID( "00000000-0000-4000-8000-0000000000bb" )
T0    = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
NOW   = T0 + timedelta( hours=2 )


@compiles( JSONB, "sqlite" )
def _jsonb_as_json( element, compiler, **kw ):
    """Render JSONB as JSON on SQLite."""
    return "JSON"


@compiles( Vector, "sqlite" )
def _vector_as_text( element, compiler, **kw ):
    """Render a pgvector column as text on SQLite."""
    return "TEXT"


@pytest.fixture
def db():
    """Yield a session over empty in-memory copies of the tables the card touches."""
    engine = create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    for model in ( Notification, PredictionLog, PreferencePrinciple, PreferenceEvidence ): model.__table__.create( engine )
    with Session( engine ) as session:
        yield session
    engine.dispose()


def _item( number=1 ):
    """A contested item as the planner takes it."""
    return { "principle_id": f"00000000-0000-4000-8000-00000000c0a{number}", "statement": f"Statement {number}.",
             "answer_a": f"yes {number}", "answer_b": f"no {number}" }


def _principle( db, number=1 ):
    """Insert a principle whose id matches _item( number ), and return its row."""
    row = PreferencePrinciple( id=uuid.UUID( _item( number )[ "principle_id" ] ), owner_id=str( OWNER ), kind="decision", dimension="ask.x",
                               statement=f"Statement {number}.", scope="global", embedding=None, encoder_version="enc", extractor_version="ext" )
    db.add( row )
    db.commit()
    return row


def _evidence( db, principle, relation, notification, condition=None, minutes=0 ):
    """Insert one extractor evidence row for the principle."""
    db.add( PreferenceEvidence( id=uuid.uuid4(), principle_id=principle.id, notification_id=notification, field_key="answer", relation=relation,
                                condition=condition, answered_at=T0 + timedelta( minutes=minutes ), extracted_at=T0 + timedelta( minutes=minutes + 1 ),
                                extractor_version="ext", source="extractor" ) )
    db.commit()


def _contested_principle( db, number=1 ):
    """A principle holding one supporting and one contradicting row under the same condition."""
    principle = _principle( db, number )
    _evidence( db, principle, "supports", uuid.uuid4(), minutes=1 )
    _evidence( db, principle, "contradicts", uuid.uuid4(), minutes=2 )
    return principle


def _card( db, answers, items=( 1, ), marked=True, minutes=30, responded=True ):
    """
    Insert a review card and its stored answer, and return its id.

    Ensures:
        - the ask carries the marker and the header-to-principle map unless marked is False
        - the stored answer is { value: <json of answers>, source: ui }
    """
    questions, extras = rc.build_card( [ _item( n ) for n in items ] )
    options = { "questions": questions, **( extras if marked else {} ) }
    row = dict( id=uuid.uuid4(), sender_id="claude.code@lupin.deepily.ai#ab12cd34", recipient_id=OWNER, message="Which should win?", title="Review",
                type="task", priority="low", created_at=T0 + timedelta( minutes=minutes ), response_requested=True, response_type="multiple_choice",
                response_options=options )
    if responded: row.update( responded_at=T0 + timedelta( minutes=minutes + 1 ), response_value={ "value": json.dumps( { "answers": answers } ), "source": "ui",
                                                                                                    "answered_by": { "user_id": str( OWNER ) } } )
    db.add( Notification( **row ) )
    db.commit()
    return row[ "id" ]


def _statuses( db, asked_at=NOW ):
    """Derive every principle's status at asked_at over all rows."""
    return derive_statuses( db.query( PreferencePrinciple ).all(), db.query( PreferenceEvidence ).all(), asked_at, "ext", lambda nid: None )


# ---- the split step ----------------------------------------------------------------------------

def test_a_feature_that_separates_the_two_sets_gives_each_side_a_condition():
    """The category differs between the sets, so each side gets a condition on it."""
    a = [ { "category": "permission", "kind": "yes_no" }, { "category": "permission", "kind": "yes_no" } ]
    b = [ { "category": "confirmation", "kind": "yes_no" } ]
    found = rc.resolve_conflict( a, b )
    assert found == { "outcome": "split", "feature": "category", "condition_a": "category is permission", "condition_b": "category is confirmation" }


def test_two_sets_no_feature_separates_are_marked_contested_and_nothing_is_decided():
    """Every shared feature has a value on both sides, so the principle is contested."""
    a = [ { "category": "permission", "kind": "yes_no" }, { "category": "confirmation", "kind": "open" } ]
    b = [ { "category": "permission", "kind": "open" }, { "category": "confirmation", "kind": "yes_no" } ]
    assert rc.resolve_conflict( a, b ) == { "outcome": "contested" }


def test_a_feature_missing_from_one_episode_cannot_separate_and_the_first_separating_name_wins():
    """Only features every episode has are tried, in name order, and several values join with or."""
    a = [ { "alpha": "x", "beta": "1" }, { "alpha": "y", "beta": "2", "only_here": "q" } ]
    b = [ { "alpha": "z", "beta": "3" } ]
    found = rc.split_step( a, b )
    assert found[ "feature" ] == "alpha" and found[ "condition_a" ] == "alpha is x or y" and found[ "condition_b" ] == "alpha is z"
    assert rc.split_step( [ { "only_here": "q" } ], b ) is None


def test_an_empty_side_has_nothing_to_separate():
    """Either set empty gives None."""
    assert rc.split_step( [], [ { "a": 1 } ] ) is None and rc.split_step( [ { "a": 1 } ], [] ) is None


# ---- the cap, with a fixed clock ---------------------------------------------------------------

def test_the_window_is_rolling_and_a_card_exactly_24_hours_old_no_longer_counts():
    """Boundary at 24 hours, on both sides, and a card in the future never counts."""
    sent = [ NOW - timedelta( hours=24 ), NOW - timedelta( hours=24 ) + timedelta( seconds=1 ), NOW, NOW + timedelta( seconds=1 ) ]
    assert rc.cards_in_window( sent, NOW ) == 2


def test_at_most_three_cards_go_out_in_any_rolling_24_hours_and_the_fourth_waits_for_the_first_to_age_out():
    """Hourly attempts send three, defer the fourth, and reopen when the first card is a day old."""
    sent = []
    outcomes = []
    for hour in range( 0, 30 ):
        plan = rc.plan_card( [ _item() ], sent, T0 + timedelta( hours=hour ), cap=3 )
        outcomes.append( bool( plan[ "send" ] ) )
        if plan[ "send" ]: sent.append( T0 + timedelta( hours=hour ) )
    assert [ hour for hour, ok in enumerate( outcomes ) if ok ] == [ 0, 1, 2, 24, 25, 26 ]


def test_a_zero_cap_sends_nothing_and_a_full_batch_is_cut_at_the_batch_size_with_the_rest_deferred():
    """Cap 0 defers everything; otherwise one card holds batch_max items in order."""
    items = [ _item( n ) for n in range( 1, 8 ) ]
    assert rc.plan_card( items, [], NOW, cap=0 )[ "send" ] == [] and len( rc.plan_card( items, [], NOW, cap=0 )[ "deferred" ] ) == 7
    plan = rc.plan_card( items, [], NOW, cap=3, batch_max=5 )
    assert [ i[ "statement" ] for i in plan[ "send" ] ] == [ f"Statement {n}." for n in range( 1, 6 ) ]
    assert [ i[ "statement" ] for i in plan[ "deferred" ] ] == [ "Statement 6.", "Statement 7." ]
    assert rc.plan_card( [], [], NOW, cap=3 )[ "send" ] == []


def test_the_cap_comes_from_the_ini_file_as_an_integer():
    """The shipped key is read through the real manager."""
    assert rc.review_card_cap() == 3


# ---- sending through present_choices -----------------------------------------------------------

def test_the_card_goes_out_through_the_real_present_choices_with_the_marker_in_response_options():
    """The dispatcher's request carries the questions, the marker and the header map."""
    captured = []
    def fake_notify( request ):
        captured.append( request )
        return NotificationResponse( exit_code=0, response_value=json.dumps( { "answers": { "P1": OPTION } } ), response_type="multiple_choice" )
    OPTION = rc.OPTION_ONE
    dispatcher = AgentNotificationDispatcher( agent_type="principle.learner" )
    dispatcher.target_user = "owner@example.com"
    with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync", side_effect=fake_notify ):
        result = asyncio.run( rc.send_review_card( dispatcher, [ _item( 1 ), _item( 2 ) ], [], NOW, cap=3 ) )
    options = captured[ 0 ].response_options
    assert is_review_card( options ) and options[ "principle_ids" ] == { "P1": _item( 1 )[ "principle_id" ], "P2": _item( 2 )[ "principle_id" ] }
    assert [ q[ "header" ] for q in options[ "questions" ] ] == [ "P1", "P2" ]
    assert [ o[ "label" ] for o in options[ "questions" ][ 0 ][ "options" ] ] == [ rc.OPTION_ONE, rc.OPTION_OTHER, rc.OPTION_BOTH, rc.OPTION_RETRACT ]
    assert result[ "sent" ] is True and result[ "answers" ] == { "answers": { "P1": rc.OPTION_ONE } }


def test_an_ordinary_present_choices_call_adds_no_marker():
    """With no extra keys the ask holds the questions alone."""
    captured = []
    def fake_notify( request ):
        captured.append( request )
        return NotificationResponse( exit_code=0, response_value=json.dumps( { "answers": { "P1": "x" } } ), response_type="multiple_choice" )
    dispatcher = AgentNotificationDispatcher( agent_type="principle.learner" )
    questions, _ = rc.build_card( [ _item() ] )
    with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync", side_effect=fake_notify ):
        asyncio.run( dispatcher.present_choices( questions ) )
    assert list( captured[ 0 ].response_options ) == [ "questions" ] and not is_review_card( captured[ 0 ].response_options )


def test_at_the_cap_the_dispatcher_is_never_called():
    """A full window sends nothing and calls nothing."""
    class Spy:
        calls = 0
        async def present_choices( self, *args, **kwargs ): Spy.calls += 1
    sent = [ NOW - timedelta( hours=h ) for h in ( 1, 2, 3 ) ]
    result = asyncio.run( rc.send_review_card( Spy(), [ _item() ], sent, NOW, cap=3 ) )
    assert Spy.calls == 0 and result[ "sent" ] is False and result[ "answers" ] is None and len( result[ "deferred" ] ) == 1


def test_review_card_times_lists_only_marked_asks_to_that_owner_inside_the_window( db ):
    """A recent marked ask counts; an unmarked one, an old one and another owner's do not."""
    _card( db, {}, minutes=60 * 12, responded=False )
    _card( db, {}, marked=False, minutes=60 * 12 + 20, responded=False )
    _card( db, {}, minutes=-60 * 30, responded=False )
    other = _card( db, {}, minutes=60 * 12 + 30, responded=False )
    db.query( Notification ).filter( Notification.id == other ).update( { "recipient_id": OTHER } )
    db.commit()
    now = T0 + timedelta( hours=13 )
    assert rc.review_card_times( db, OWNER, now ) == [ T0 + timedelta( hours=12 ) ]


# ---- the answer ---------------------------------------------------------------------------------

def test_answering_a_card_writes_one_ruling_row_and_clears_contested( db ):
    """Contested before the ruling, standing after it, with the evidence rows untouched."""
    principle = _contested_principle( db )
    assert _statuses( db )[ principle.id ][ "status" ] == CONTESTED
    before = db.query( PreferenceEvidence ).count()
    card = _card( db, { "P1": rc.OPTION_ONE } )
    report = rc.record_card_answer( db, card, NOW )
    db.commit()
    assert report == { "rulings_written": 1, "existing": 0, "rejected": [] }
    rows = db.query( PreferenceEvidence ).filter_by( source="review_card" ).all()
    assert len( rows ) == 1 and rows[ 0 ].relation == "supports" and rows[ 0 ].field_key == "P1" and rows[ 0 ].principle_id == principle.id
    assert db.query( PreferenceEvidence ).count() == before + 1
    after = _statuses( db )[ principle.id ]
    assert after[ "status" ] in ( HYPOTHESIS, ESTABLISHED ) and after[ "ruled" ] is True


@pytest.mark.parametrize( "choice, relation, condition, status", [
    ( rc.OPTION_ONE, "supports", None, HYPOTHESIS ),
    ( rc.OPTION_OTHER, "contradicts", None, RETRACTED ),
    ( rc.OPTION_RETRACT, "contradicts", None, RETRACTED ),
    ( rc.OPTION_BOTH + ": when the answer names a budget", "refines", "when the answer names a budget", HYPOTHESIS ),
] )
def test_each_choice_maps_to_its_ruling_and_the_derived_status( db, choice, relation, condition, status ):
    """Each of the four options gives its relation, and the written condition rides along."""
    principle = _contested_principle( db )
    rc.record_card_answer( db, _card( db, { "P1": choice } ), NOW )
    db.commit()
    row = db.query( PreferenceEvidence ).filter_by( source="review_card" ).one()
    assert ( row.relation, row.condition ) == ( relation, condition )
    result = _statuses( db )[ principle.id ]
    assert result[ "status" ] == status
    if condition: assert condition in result[ "conditions" ]


def test_a_batched_card_writes_one_ruling_per_answered_principle_and_a_list_answer_is_read( db ):
    """Two answered questions give two rows, each on its own principle."""
    first, second = _principle( db, 1 ), _principle( db, 2 )
    report = rc.record_card_answer( db, _card( db, { "P1": [ rc.OPTION_RETRACT ], "P2": rc.OPTION_ONE }, items=( 1, 2 ) ), NOW )
    db.commit()
    assert report[ "rulings_written" ] == 2
    by_principle = { row.principle_id: row.relation for row in db.query( PreferenceEvidence ).filter_by( source="review_card" ) }
    assert by_principle == { first.id: "contradicts", second.id: "supports" }


def test_answering_twice_writes_nothing_the_second_time( db ):
    """The evidence key refuses a repeat, and the report says it existed."""
    _principle( db )
    card = _card( db, { "P1": rc.OPTION_ONE } )
    rc.record_card_answer( db, card, NOW )
    db.commit()
    again = rc.record_card_answer( db, card, NOW + timedelta( hours=1 ) )
    assert again[ "rulings_written" ] == 0 and again[ "existing" ] == 1
    assert db.query( PreferenceEvidence ).filter_by( source="review_card" ).count() == 1


@pytest.mark.parametrize( "answers, reason", [
    ( { "P9": "x" }, "header_not_on_card" ),
    ( { "P1": "something else" }, "answer_is_not_an_option_or_has_no_condition" ),
    ( { "P1": rc.OPTION_BOTH }, "answer_is_not_an_option_or_has_no_condition" ),
    ( { "P1": rc.OPTION_BOTH + ":   " }, "answer_is_not_an_option_or_has_no_condition" ),
    ( { "P1": 5 }, "answer_is_not_an_option_or_has_no_condition" ),
] )
def test_an_answer_that_is_no_option_or_names_no_condition_writes_nothing_and_says_why( db, answers, reason ):
    """A stray header, free text, a missing condition or a non-text value is rejected."""
    _principle( db )
    report = rc.record_card_answer( db, _card( db, answers ), NOW )
    assert report[ "rulings_written" ] == 0 and [ r[ "reason" ] for r in report[ "rejected" ] ] == [ reason ]
    assert db.query( PreferenceEvidence ).count() == 0


def test_an_unmarked_ask_an_unanswered_card_and_a_missing_row_write_nothing( db ):
    """Only an answered, marked ask is a card answer."""
    _principle( db )
    empty = { "rulings_written": 0, "existing": 0, "rejected": [] }
    assert rc.record_card_answer( db, _card( db, { "P1": rc.OPTION_ONE }, marked=False ), NOW ) == empty
    assert rc.record_card_answer( db, _card( db, {}, responded=False ), NOW ) == empty
    assert rc.record_card_answer( db, uuid.uuid4(), NOW ) == empty
    assert db.query( PreferenceEvidence ).count() == 0


def test_a_json_string_for_the_options_and_an_answer_stored_as_a_bare_dict_are_both_read( db ):
    """The options may come back as text, and the answer as a bare dict."""
    _principle( db )
    card = _card( db, { "P1": rc.OPTION_ONE } )
    row = db.get( Notification, card )
    row.response_options = json.dumps( row.response_options )
    row.response_value   = { "answers": { "P1": rc.OPTION_ONE }, "source": "ui", "answered_by": { "user_id": str( OWNER ) } }
    db.commit()
    assert rc.record_card_answer( db, card, NOW )[ "rulings_written" ] == 1


# ---- isolation: the answer leaves no extractor input --------------------------------------------

class _Model:
    """A model double that records its prompts and replies with no fields."""

    def __init__( self ): self.sent = []

    async def __call__( self, prompt, options ):
        self.sent.append( prompt )
        text = json.dumps( { "fields": [] } )
        yield AssistantMessage( content=[ TextBlock( text=text ) ], model="test-model" )
        yield ResultMessage( subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s", result=text )


def _factory( db ):
    """Wrap a session as the factory the extractor job takes."""
    @contextmanager
    def factory():
        yield db
        db.commit()
    return factory


def _extract( db, notification_id, model ):
    """Run the real extractor job over a notification and return its summary."""
    job = PrincipleExtractorJob( notification_id, str( OWNER ), "owner@example.com", query_fn=model, embed_fn=lambda text: [ 0.0 ] * 768,
                                 session_factory=_factory( db ), model="test-model", timeout_seconds=30, encoder="enc", clock=lambda: NOW )
    return json.loads( asyncio.run( job._execute() ) )


def test_answering_a_marked_card_yields_one_ruling_row_and_zero_extractor_input_rows( db ):
    """The extractor skips the marked answer: no model call, no principle, no extractor evidence."""
    _principle( db )
    card  = _card( db, { "P1": rc.OPTION_ONE } )
    model = _Model()
    rc.record_card_answer( db, card, NOW )
    db.commit()
    summary = _extract( db, str( card ), model )
    assert summary[ "status" ] == "skipped_review_card" and model.sent == []
    assert db.query( PreferenceEvidence ).filter_by( source="review_card" ).count() == 1
    assert db.query( PreferenceEvidence ).filter_by( source="extractor" ).count() == 0
    assert db.query( PreferencePrinciple ).count() == 1
    assert db.query( PredictionLog ).count() == 0


def test_the_same_answer_on_an_unmarked_ask_does_reach_the_extractor_as_a_control( db ):
    """The skip is the marker's doing: the unmarked twin is read and the model is called."""
    card  = _card( db, { "P1": rc.OPTION_ONE }, marked=False )
    model = _Model()
    summary = _extract( db, str( card ), model )
    assert summary[ "status" ] != "skipped_review_card" and len( model.sent ) == 1


def test_the_answer_door_helper_writes_and_commits_the_ruling_through_the_real_get_db( db, monkeypatch ):
    """The helper opens its own session, records the answer and commits it."""
    import cosa.rest.routers.notifications as notif
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setattr( "cosa.rest.db.database.SessionLocal", sessionmaker( bind=db.get_bind() ) )
    principle = _principle( db )
    card      = _card( db, { "P1": rc.OPTION_RETRACT } )
    report    = notif._record_review_ruling_sync( str( card ) )
    assert report[ "rulings_written" ] == 1
    db.expire_all()
    row = db.query( PreferenceEvidence ).filter_by( source="review_card" ).one()
    assert row.principle_id == principle.id and row.relation == "contradicts" and row.extracted_at is not None



# ---- only the owner's own answer is a ruling ---------------------------------------------------------

def _answer_as( db, stored ):
    """Insert a marked card whose stored answer is `stored`, and return its id."""
    _principle( db )
    card = _card( db, { "P1": rc.OPTION_ONE } )
    row  = db.get( Notification, card )
    row.response_value = stored
    db.commit()
    return card


_ANSWERS = { "P1": rc.OPTION_ONE }
_OWNER   = { "user_id": str( OWNER ) }


@pytest.mark.parametrize( "stored", [
    { "value": json.dumps( { "answers": _ANSWERS } ), "source": "timeout_default" },
    { "value": json.dumps( { "answers": _ANSWERS } ), "source": "proxy", "answered_by": _OWNER },
    { "value": json.dumps( { "answers": _ANSWERS } ), "source": "ui", "answered_by": { "user_id": str( OTHER ) } },
    { "value": json.dumps( { "answers": _ANSWERS } ), "source": "ui" },
    "not a dict",
] )
def test_an_answer_that_is_not_the_owners_own_from_their_screen_writes_no_ruling( db, stored ):
    """A timeout default, a proxy, another account, no user or a bare string writes nothing."""
    card   = _answer_as( db, stored )
    report = rc.record_card_answer( db, card, NOW )
    assert report == { "rulings_written": 0, "existing": 0, "rejected": [ { "header": None, "reason": "not_the_owners_answer" } ] }
    assert db.query( PreferenceEvidence ).count() == 0


def test_the_owners_own_screen_answer_still_writes_its_ruling( db ):
    """The control: the same card answered by its owner from the screen writes one ruling."""
    card = _answer_as( db, { "value": json.dumps( { "answers": _ANSWERS } ), "source": "ui", "answered_by": _OWNER } )
    assert rc.record_card_answer( db, card, NOW )[ "rulings_written" ] == 1


def test_the_both_option_tells_the_owner_what_to_type():
    """A click alone records nothing, so the option says what to type."""
    questions, _ = rc.build_card( [ _item() ] )
    both = next( o for o in questions[ 0 ][ "options" ] if o[ "label" ] == rc.OPTION_BOTH )
    assert f"Type: {rc.OPTION_BOTH}: your condition" in both[ "description" ] and "A click alone records nothing" in both[ "description" ]
