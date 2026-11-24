"""
Census guard: every kind of meaning round-trips through the store.

The kinds come from one constant, the meaning kinds list.
Each fixture in real_archive_rows.json is a real answered notification, captured read-only, with a hand-written reading of it.
Two kinds had no archive row on the capture date: an explicit empty selection and an absent field.
They are named in the no-archive-row list, which must match the fixture file exactly.
So a kind cannot lose its row, or gain one, unnoticed.
"""
import json
import os
import uuid

import pytest

from cosa.research.preference_replay.scratch_db import scratch_session
from cosa.rest.db.repositories.answer_meaning_repository import MEANING_KINDS, NATIVE_KINDS, UNKNOWN_KINDS, AnswerMeaningRepository, kinds_in
from cosa.rest.postgres_models import AnswerMeaning

FIXTURE                  = os.path.join( os.path.dirname( __file__ ), "fixtures", "answer_meaning", "real_archive_rows.json" )
KINDS_WITH_NO_ARCHIVE_ROW = ( "empty_selection", "absent_field" )


def _fixtures():
    with open( FIXTURE ) as handle: return { f[ "kind" ]: f for f in json.load( handle )[ "fixtures" ] }


def _synthetic_meaning( kind ):
    """A meaning that shows a kind no archive row holds: the repository must still carry it."""
    native = { "kind": kind, "selected_option_ids": [], "empty_selection": kind == "empty_selection", "write_in_text": None, "referred_option_ids": [], "text": None }
    if kind in NATIVE_KINDS: return { "native_answer": { "Field": native }, "acts": [], "conditions": [], "alignment": "unknown", "unknowns": [], "uncertainty": None }
    return { "native_answer": {}, "acts": [], "conditions": [], "alignment": "unknown", "unknowns": [ kind ], "uncertainty": None }


def test_the_list_of_kinds_is_not_empty_and_is_the_native_kinds_then_the_unknowns():
    assert MEANING_KINDS, "a guard over an empty list passes everything"
    assert MEANING_KINDS == NATIVE_KINDS + UNKNOWN_KINDS
    assert len( set( MEANING_KINDS ) ) == len( MEANING_KINDS )


def test_every_kind_has_a_fixture_and_the_fixtures_name_no_other_kind():
    assert set( _fixtures() ) == set( MEANING_KINDS )


def test_the_kinds_without_an_archive_row_are_exactly_the_ones_listed():
    assert tuple( sorted( k for k, f in _fixtures().items() if not f[ "archive_row" ] ) ) == tuple( sorted( KINDS_WITH_NO_ARCHIVE_ROW ) )


def test_every_archive_fixture_is_a_real_answered_row():
    rows = [ f for f in _fixtures().values() if f[ "archive_row" ] ]
    assert len( rows ) == len( MEANING_KINDS ) - len( KINDS_WITH_NO_ARCHIVE_ROW )
    for fixture in rows:
        assert str( uuid.UUID( fixture[ "notification_id" ] ) ) == fixture[ "notification_id" ], fixture[ "kind" ]
        assert fixture[ "response_value" ][ "value" ], fixture[ "kind" ]
        assert "answered_by" not in fixture[ "response_value" ], "the actor is removed from a committed fixture"
        assert fixture[ "kind" ] in kinds_in( fixture[ "meaning" ] ), f"{fixture[ 'kind' ]}: the reading must show the kind it stands for"


@pytest.mark.parametrize( "kind", MEANING_KINDS )
def test_every_meaning_kind_round_trips( kind ):
    fixture = _fixtures()[ kind ]
    meaning = fixture[ "meaning" ] if fixture[ "archive_row" ] else _synthetic_meaning( kind )
    assert kind in kinds_in( meaning )
    notification = fixture.get( "notification_id", str( uuid.uuid4() ) )
    with scratch_session() as session:
        AnswerMeaning.__table__.create( session.get_bind(), checkfirst=True )
        repo = AnswerMeaningRepository( session )
        repo.add( notification, "fixture-reader", "human", meaning[ "native_answer" ], meaning[ "acts" ], meaning[ "conditions" ],
                  meaning[ "alignment" ], meaning[ "unknowns" ], uncertainty=meaning[ "uncertainty" ] )
        session.commit()
        stored = repo.get( notification, "answer-meaning-v1", "fixture-reader" )
        assert { "native_answer": stored.native_answer, "acts": stored.acts, "conditions": stored.conditions, "alignment": stored.alignment,
                 "unknowns": stored.unknowns, "uncertainty": stored.uncertainty } == meaning
        assert kind in kinds_in( { "native_answer": stored.native_answer, "unknowns": stored.unknowns } )
