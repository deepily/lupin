"""
Unit tests for AnswerMeaningRepository.

They run over a real in-memory SQLite copy of the answer_meaning table.

Each test names what it would catch:
  - an update or delete door on an append-only store          -> the no-update-no-delete test
  - a second version that replaces the first                  -> the second-version test
  - a duplicate key that overwrites                           -> the duplicate test
  - a kind, act, alignment or source off its list             -> the refusal tests
  - a condition that drops the link to its option             -> the modifies_option_id tests
"""
import json
import os
import uuid

import pytest

from cosa.research.preference_replay.scratch_db import scratch_session
from cosa.rest.db.repositories.answer_meaning_repository import SCHEMA_VERSION, AnswerMeaningRepository, MeaningAlreadyRecorded, kinds_in
from cosa.rest.postgres_models import AnswerMeaning

_NID     = str( uuid.uuid4() )
_FIXTURE = os.path.join( os.path.dirname( __file__ ), "..", "..", "..", "..", "tests", "unit", "fixtures", "answer_meaning", "real_archive_rows.json" )

_NATIVE  = { "Field": { "kind": "selected_options", "selected_option_ids": [ "Field#o1" ], "empty_selection": False, "write_in_text": None, "referred_option_ids": [], "text": None } }


@pytest.fixture
def repo():
    with scratch_session() as session:
        AnswerMeaning.__table__.create( session.get_bind(), checkfirst=True )
        yield AnswerMeaningRepository( session )


def _add( repo, **changes ):
    args = dict( notification_id=_NID, annotator="a", source="human", native_answer=_NATIVE, acts=[ { "act": "approve", "depends_on": [] } ],
                 conditions=[], alignment="aligned", unknowns=[] )
    args.update( changes )
    return repo.add( **args )


def test_the_repository_has_no_update_and_no_delete_door():
    assert not [ name for name in dir( AnswerMeaningRepository ) if name.startswith( ( "update", "delete", "remove", "set_" ) ) ]


def test_a_second_schema_version_is_a_new_row_and_the_first_survives( repo ):
    first  = _add( repo, schema_version="v1", alignment="aligned" )
    second = _add( repo, schema_version="v2", alignment="diverges" )
    repo.session.commit()
    assert first.id != second.id
    assert repo.get( _NID, "v1", "a" ).alignment == "aligned"
    assert repo.get( _NID, "v2", "a" ).alignment == "diverges"
    assert [ row.schema_version for row in repo.versions( _NID ) ] == [ "v1", "v2" ]


def test_a_second_annotator_is_a_new_row( repo ):
    _add( repo, annotator="a" )
    _add( repo, annotator="b", source="labeller" )
    assert sorted( row.annotator for row in repo.versions( _NID ) ) == [ "a", "b" ]


def test_a_duplicate_key_is_refused_and_the_stored_row_is_left_as_it_was( repo ):
    _add( repo, alignment="aligned" )
    with pytest.raises( MeaningAlreadyRecorded ): _add( repo, alignment="diverges" )
    assert repo.get( _NID, SCHEMA_VERSION, "a" ).alignment == "aligned"
    assert len( repo.versions( _NID ) ) == 1


def test_get_and_versions_return_nothing_for_an_unknown_notification( repo ):
    assert repo.get( _NID, SCHEMA_VERSION, "a" ) is None
    assert repo.versions( _NID ) == []


def test_annotated_at_defaults_to_now_and_a_given_time_is_kept( repo ):
    assert _add( repo ).annotated_at is not None
    stamp = _add( repo, annotator="b" ).annotated_at
    assert _add( repo, annotator="c", annotated_at=stamp ).annotated_at == stamp


@pytest.mark.parametrize( "change", [
    { "source": "robot" },
    { "native_answer": { "F": { "kind": "mystery" } } },
    { "acts": [ { "act": "shrug", "depends_on": [] } ] },
    { "alignment": "sideways" },
    { "unknowns": [ "mystery" ] },
] )
def test_a_value_off_its_list_is_refused_and_nothing_is_written( repo, change ):
    with pytest.raises( ValueError ): _add( repo, **change )
    assert repo.versions( _NID ) == []


def test_a_condition_without_modifies_option_id_is_refused( repo ):
    with pytest.raises( ValueError, match="modifies_option_id" ): _add( repo, conditions=[ { "text": "only if", "scope": "x" } ] )


def test_modifies_option_id_round_trips_for_a_whole_answer_and_for_an_option( repo ):
    conditions = [ { "text": "whole", "modifies_option_id": None }, { "text": "one option", "modifies_option_id": "Field#o1" } ]
    _add( repo, conditions=conditions )
    repo.session.commit()
    assert repo.get( _NID, SCHEMA_VERSION, "a" ).conditions == conditions


def test_a_comment_on_a_multiple_choice_card_keeps_its_link_to_the_option_it_changes( repo ):
    with open( _FIXTURE ) as handle: fixture = [ f for f in json.load( handle )[ "fixtures" ] if f[ "kind" ] == "write_in_text" ][ 0 ]
    assert fixture[ "response_type" ] == "multiple_choice"
    meaning = fixture[ "meaning" ]
    option  = meaning[ "conditions" ][ 0 ][ "modifies_option_id" ]
    assert option in { f"Ruling 1#o{i + 1}" for i, _ in enumerate( fixture[ "response_options" ][ "questions" ][ 0 ][ "options" ] ) }, "the id names an option the card showed"
    _add( repo, notification_id=fixture[ "notification_id" ], native_answer=meaning[ "native_answer" ], acts=meaning[ "acts" ],
          conditions=meaning[ "conditions" ], alignment=meaning[ "alignment" ], unknowns=meaning[ "unknowns" ] )
    repo.session.commit()
    assert repo.get( fixture[ "notification_id" ], SCHEMA_VERSION, "a" ).conditions[ 0 ][ "modifies_option_id" ] == option


def test_kinds_in_joins_the_field_kinds_and_the_unknowns():
    assert kinds_in( { "native_answer": _NATIVE, "unknowns": [ "cancellation" ] } ) == { "selected_options", "cancellation" }
    assert kinds_in( { "native_answer": {}, "unknowns": [] } ) == set()


def test_a_meaning_row_describes_itself_by_notification_version_and_annotator( repo ):
    text = repr( _add( repo, schema_version="v7", annotator="reader-b" ) )
    assert _NID in text and "v7" in text and "reader-b" in text
