"""
The extractor writes three evidence keys, each behind its own switch.

Each test names what it would catch:
  - a key written with its switch off                        -> the switch-off pin
  - two equal conditions that get two keys                   -> the fixture test
  - a copy of one card that gets a second source key         -> the source key test
  - a standing quote lost, or stored for an inferred refusal -> the quote tests
  - a key step that blocks the job's event loop              -> the fixture test, which runs inside the job
"""
import json
from pathlib import Path

import pytest

from cosa.agents.principle_learner import extractor_store
from cosa.agents.principle_learner.extractor_store import evidence_keys, source_key_for
from cosa.rest.postgres_models import PreferenceEvidence
from tests.unit.test_principle_extractor_job import NOW, OWNER, Model, _ask, _hyp, _principle, _reply, _result, _run, db  # noqa: F401  (db is a fixture)
import uuid

FIXTURE = json.loads( ( Path( __file__ ).resolve().parents[ 1 ] / "fixtures" / "principle_status" / "condition_key_writer_replies.json" ).read_text() )


@pytest.fixture
def switches( monkeypatch ):
    """Turn the two switches on or off by key name, as a test asks."""
    state = { "principle learner condition keys enabled": False, "principle learner source dedup enabled": False }
    monkeypatch.setattr( extractor_store, "switch_on", lambda key: state[ key ] )
    return state


def _rows( db ):
    return db.query( PreferenceEvidence ).order_by( PreferenceEvidence.field_key ).all()


def test_with_both_switches_off_no_key_is_written_and_no_model_call_is_made( db, switches ):
    """Switch-off pin: one model call, and all three columns stay NULL."""
    model = Model( _reply( _result( hypotheses=[ _hyp( condition="approval", grounded_in="card" ) ] ) ) )
    _run( db, _ask( db, answer="no" ), model )
    row = _rows( db )[ 0 ]
    assert len( model.sent ) == 1 and ( row.condition_key, row.source_key, row.standing_quote ) == ( None, None, None )


def test_the_condition_key_is_the_one_in_the_recorded_real_reply_and_the_job_makes_the_call_itself( db, switches ):
    """
    A recorded real writer reply, through the job's own event loop.

    The stored key is the key that reply carried, and the model was asked twice: the extractor, then the key step.
    """
    switches[ "principle learner condition keys enabled" ] = True
    call  = FIXTURE[ "pairs" ][ "equal" ][ "calls" ][ 0 ]
    model = Model( _reply( _result( hypotheses=[ _hyp( condition="approval", grounded_in="card" ) ] ) ), call[ "reply" ] )
    _run( db, _ask( db, answer="no" ), model )
    row = _rows( db )[ 0 ]
    assert row.condition == "approval"
    assert row.condition_key == json.loads( call[ "reply" ] )[ "key" ] and len( model.sent ) == 2
    assert row.source_key is None


def test_evidence_keys_reuses_a_stored_key_and_falls_back_without_a_model( db, switches ):
    """With a model the key comes from it; with none, the normalised condition."""
    switches[ "principle learner condition keys enabled" ] = True
    class Principle:
        id = None
    offered = []
    def complete( system, user ):
        offered.append( user )
        return json.dumps( { "same_as": None, "key": "Fresh Key." } )
    assert evidence_keys( db, Principle, "  Needs LINK. ", None, "s", complete ) == { "condition_key": "fresh key" } and len( offered ) == 1
    assert evidence_keys( db, Principle, "  Needs LINK. ", None, "s", None ) == { "condition_key": "needs link" }
    assert evidence_keys( db, Principle, None, None, "s", complete ) == {} and len( offered ) == 1


def test_source_key_is_one_for_a_card_asked_twice_and_two_for_different_cards():
    """Case, spacing and end punctuation never split a source; a new card does."""
    assert source_key_for( "Re-spin the agent?", "Yes, always." ) == source_key_for( "  re-spin   the agent", "yes, always" )
    assert source_key_for( "Re-spin the agent?", "yes" ) != source_key_for( "Delete the branch?", "yes" )
    assert source_key_for( "Re-spin the agent?", "yes" ) != source_key_for( "Re-spin the agent?", "no" )
    assert len( source_key_for( None, None ) ) == 32


def test_the_source_switch_stores_the_source_key_and_the_standing_quote_or_none( db, switches ):
    """A quote is stored stripped, its absence as None; the source key always."""
    switches[ "principle learner source dedup enabled" ] = True
    class Principle:
        id = None
    quoted = evidence_keys( db, Principle, None, { "standing_quote": "  always ask before re-spinning  " }, "src-1", None )
    plain  = evidence_keys( db, Principle, None, { "standing_quote": "   " }, "src-1", None )
    none   = evidence_keys( db, Principle, None, None, "src-1", None )
    assert quoted == { "source_key": "src-1", "standing_quote": "always ask before re-spinning" }
    assert plain == none == { "source_key": "src-1", "standing_quote": None }


def test_a_written_row_carries_the_source_key_the_job_computed( db, switches ):
    """Through the job, the row carries a 32-digit source key and no quote."""
    switches[ "principle learner source dedup enabled" ] = True
    model = Model( _reply( _result( hypotheses=[ _hyp( condition="approval", grounded_in="card" ) ] ) ) )
    _run( db, _ask( db, answer="no" ), model )
    row = _rows( db )[ 0 ]
    assert row.source_key is not None and len( row.source_key ) == 32 and row.standing_quote is None


def test_a_key_already_stored_for_the_principle_is_offered_and_reused( db, switches ):
    """
    Two stored rows, one keyed and one not; the model names the stored key as the same.

    Only a query that returns the keyed row offers it, so the reply's same_as resolves to it and not to the new key.
    """
    switches[ "principle learner condition keys enabled" ] = True
    principle = _principle( db )
    for note, key in ( ( "n1", "stored key" ), ( "n2", None ) ):
        db.add( PreferenceEvidence( id=uuid.uuid4(), principle_id=principle.id, notification_id=uuid.uuid4(), field_key=note, relation="supports", condition="x",
                                    answered_at=NOW, extracted_at=NOW, extractor_version="v", source="extractor", condition_key=key ) )
    db.commit()
    offered = []
    def complete( system, user ):
        offered.append( json.loads( user ) )
        return json.dumps( { "same_as": "stored key", "key": "a brand new key" } )
    keys = evidence_keys( db, principle, "worded some other way", None, "s", complete )
    assert offered[ 0 ][ "existing_keys" ] == [ "stored key" ]
    assert keys == { "condition_key": "stored key" }
