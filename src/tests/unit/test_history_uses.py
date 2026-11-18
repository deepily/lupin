"""
Each derived example gets the use its evidence supports, and none joins the frozen cohort.
"""

import pytest

from cosa.agents.prediction_engine.history_uses import CONTEXT_STATES, USES, assign_use, assign_uses


def example( tier="recipient", kind="stance", id="n1" ):
    """One derived example, built so a test names only what it varies."""
    return { "notification_id": id, "attribution_tier": tier, "answer": { "kind": kind } }


@pytest.mark.parametrize( "tier, kind, state, use, reason", [
    ( "none",            "none",   "reconstructed", "vocabulary_only", "unanswered" ),
    ( "recipient",       "none",   "reconstructed", "vocabulary_only", "unanswered" ),
    ( "timeout_default", "stance", "reconstructed", "vocabulary_only", "timeout default, no human label" ),
    ( "recipient",       "unread", "reconstructed", "sensitivity",     "answer could not be read" ),
    ( "unknown_actor",   "stance", "reconstructed", "sensitivity",     "actor not established: unknown_actor" ),
    ( "other_account",   "fields", "reconstructed", "sensitivity",     "actor not established: other_account" ),
    ( "recipient",       "stance", "reconstructed", "train_or_test",   "recipient answer, context reconstructed" ),
    ( "recipient",       "fields", "ambiguous_only", "prompt_only",    "recipient answer, context ambiguous_only" ),
    ( "recipient",       "text",   "no_context",    "prompt_only",     "recipient answer, context no_context" ),
] )
def test_the_first_rule_that_applies_decides_the_use( tier, kind, state, use, reason ):
    got = assign_use( example( tier, kind ), state )
    assert ( got[ "use" ], got[ "reason" ] ) == ( use, reason )


def test_no_assignment_joins_the_frozen_cohort():
    got = [ assign_use( example( t, k ), s ) for t in ( "recipient", "unknown_actor", "timeout_default" ) for k in ( "stance", "none" ) for s in ( "reconstructed", "no_context" ) ]
    assert len( got ) == 12 and [ a for a in got if a[ "frozen_cohort" ] is not False ] == []


def test_the_counts_are_by_use_then_reason_and_every_use_is_present():
    rows   = [ example( id="a" ), example( id="b", tier="unknown_actor" ), example( id="c", kind="none", tier="none" ) ]
    states = { "a": "reconstructed", "b": "reconstructed", "c": "no_context" }
    assignments, counts = assign_uses( rows, states )
    assert [ a[ "use" ] for a in assignments ] == [ "train_or_test", "sensitivity", "vocabulary_only" ]
    assert set( counts ) == set( USES ) and counts[ "prompt_only" ] == {}
    assert counts[ "sensitivity" ] == { "actor not established: unknown_actor": 1 }


def test_the_same_reason_is_counted_together():
    _, counts = assign_uses( [ example( id="a" ), example( id="b" ) ], { "a": "reconstructed", "b": "reconstructed" } )
    assert counts[ "train_or_test" ] == { "recipient answer, context reconstructed": 2 }


def test_an_example_with_no_context_state_is_refused_by_id():
    with pytest.raises( KeyError, match="missing-id" ):
        assign_uses( [ example( id="missing-id" ) ], {} )


@pytest.mark.parametrize( "state", [ "reconstucted", "", None, "RECONSTRUCTED" ] )
def test_a_context_state_outside_the_three_is_refused_by_value( state ):
    with pytest.raises( ValueError, match="context_state must be one of" ):
        assign_use( example(), state )


def test_the_three_context_states_are_the_ones_rebuild_context_names():
    assert CONTEXT_STATES == ( "reconstructed", "ambiguous_only", "no_context" )


@pytest.mark.parametrize( "tier", [ "unknown_actor", "other_account" ] )
def test_an_unread_answer_from_a_weak_actor_is_reported_as_unread_not_by_actor( tier ):
    got = assign_use( example( tier, "unread" ), "reconstructed" )
    assert ( got[ "use" ], got[ "reason" ] ) == ( "sensitivity", "answer could not be read" )


def test_a_timeout_default_that_is_also_unread_is_reported_as_a_default():
    assert assign_use( example( "timeout_default", "unread" ), "reconstructed" )[ "reason" ] == "timeout default, no human label"
