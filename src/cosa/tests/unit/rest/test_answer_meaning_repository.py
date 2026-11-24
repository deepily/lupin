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
from cosa.rest.db.repositories.answer_meaning_repository import ( ALIGNMENTS, RELATION_ALIGNMENT, RELATIONS_V2, SCHEMA_VERSION, SCHEMA_VERSION_V2, AnswerMeaningRepository,
                                                                     MeaningAlreadyRecorded, kinds_in )
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


# Schema v2: the relations of the meaning labeller plan, sections 3, 3b and 3c.

def _v2_native( relation, **extra ):
    entry = dict( _NATIVE[ "Field" ], relation=relation )
    entry.update( extra )
    return { "Field": entry }


def _add_v2( repo, relation="agrees", **changes ):
    args = dict( schema_version=SCHEMA_VERSION_V2, native_answer=_v2_native( relation ), alignment=None )
    args.update( changes )
    return _add( repo, **args )


def test_the_v2_relations_are_the_thirteen_of_the_plan_and_match_the_labelling_vocabulary():
    from cosa.repo.labelling.packets import ANSWER_LABELS
    assert SCHEMA_VERSION_V2 == "answer-meaning-v2" and SCHEMA_VERSION_V2 != SCHEMA_VERSION
    assert len( RELATIONS_V2 ) == 13 and len( set( RELATIONS_V2 ) ) == 13
    assert set( RELATIONS_V2 ) == set( ANSWER_LABELS )


def test_every_relation_maps_to_one_alignment_and_every_alignment_is_a_known_one():
    assert set( RELATION_ALIGNMENT ) == set( RELATIONS_V2 )
    assert set( RELATION_ALIGNMENT.values() ) <= set( ALIGNMENTS )
    assert RELATION_ALIGNMENT[ "agrees" ] == "aligned"
    assert RELATION_ALIGNMENT[ "expands_recommendation" ] == "partial"
    assert RELATION_ALIGNMENT[ "expands_other_option" ] == RELATION_ALIGNMENT[ "chose_different_listed_option" ] == "diverges"
    assert RELATION_ALIGNMENT[ "no_recommendation_on_card" ] == "no_recommendation"
    assert [ r for r, a in RELATION_ALIGNMENT.items() if a == "unknown" ] == [ r for r in RELATIONS_V2 if r not in (
        "agrees", "expands_recommendation", "expands_other_option", "chose_different_listed_option", "no_recommendation_on_card" ) ]


@pytest.mark.parametrize( "relation", RELATIONS_V2 )
def test_a_v2_row_gets_its_alignment_from_the_relation( repo, relation ):
    row = _add_v2( repo, relation )
    assert row.alignment == RELATION_ALIGNMENT[ relation ]


def test_a_v1_row_and_a_v2_row_for_one_notification_coexist( repo ):
    _add( repo, alignment="aligned" )
    _add_v2( repo, "dissent" )
    repo.session.commit()
    assert [ row.schema_version for row in repo.versions( _NID ) ] == [ SCHEMA_VERSION, SCHEMA_VERSION_V2 ]


@pytest.mark.parametrize( "native", [
    _v2_native( "selects_other" ),
    _v2_native( "agrees", stance_source="guessed" ),
] )
def test_a_v2_relation_or_stance_source_off_its_list_is_refused_and_nothing_is_written( repo, native ):
    with pytest.raises( ValueError ): _add_v2( repo, native_answer=native )
    assert repo.versions( _NID ) == []


def test_a_v2_inferred_stance_source_is_kept( repo ):
    row = _add_v2( repo, native_answer=_v2_native( "support", stance_source="inferred" ) )
    assert row.native_answer[ "Field" ][ "stance_source" ] == "inferred"


def test_a_v2_row_may_carry_the_alignment_its_relation_gives_and_no_other( repo ):
    assert _add_v2( repo, "agrees", alignment="aligned" ).alignment == "aligned"
    with pytest.raises( ValueError, match="alignment" ): _add_v2( repo, "agrees", annotator="b", alignment="diverges" )


def test_a_v2_row_with_several_fields_takes_one_alignment_only_when_they_agree( repo ):
    entry  = lambda relation: dict( _NATIVE[ "Field" ], relation=relation )
    same   = _add_v2( repo, native_answer={ "A": entry( "agrees" ), "B": entry( "agrees" ) } )
    mixed  = _add_v2( repo, annotator="b", native_answer={ "A": entry( "agrees" ), "B": entry( "answers" ) } )
    empty  = _add_v2( repo, annotator="c", native_answer={}, unknowns=[ "unreadable_payload" ] )
    assert ( same.alignment, mixed.alignment, empty.alignment ) == ( "aligned", "unknown", "unknown" )


def test_a_v1_row_with_no_alignment_is_still_refused( repo ):
    with pytest.raises( ValueError ): _add( repo, alignment=None )
