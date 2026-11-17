"""
The shared JSON field reader and the shared fallback fields of the two expediters.
"""
import pytest

from cosa.agents.bug_fix_expediter.orchestrator import BFEOrchestrator
from cosa.agents.calculator.xml_models import CalcIntent
from cosa.agents.io_models.utils.json_fields import json_or_empty
from cosa.agents.shared.diagnosis_json import fallback_diagnosis_fields
from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator
from cosa.crud_for_dataframes.xml_models import CRUDIntent


@pytest.mark.parametrize( "text,kind,expected", [
    ( '[1, "a"]',       list, [ 1, "a" ] ),
    ( '{"k": 2}',       dict, { "k": 2 }  ),
    ( ' [ ] ',          list, []          ),
    ( "{}",             dict, {}          ),
] )
def test_json_of_the_asked_kind_is_returned( text, kind, expected ):
    assert json_or_empty( text, kind ) == expected


@pytest.mark.parametrize( "text", [ None, "", "   ", "not json", "[1,", 5, '{"k": 1}', '"text"', "null" ] )
def test_anything_else_gives_an_empty_list_for_list( text ):
    assert json_or_empty( text, list ) == []


@pytest.mark.parametrize( "text", [ None, "", "   ", "not json", "{", 5, "[1, 2]", '"text"', "null" ] )
def test_anything_else_gives_an_empty_dict_for_dict( text ):
    assert json_or_empty( text, dict ) == {}


def test_an_empty_result_is_a_new_object_each_time():
    assert json_or_empty( "", list ) is not json_or_empty( "", list )


def test_the_models_read_their_json_fields_through_it():
    assert CalcIntent( operation="compare_prices", items='[{"name": "a"}]' ).get_items_list() == [ { "name": "a" } ]
    assert CalcIntent( operation="arithmetic", operands="[1, 2.5]" ).get_operands_list() == [ 1.0, 2.5 ]
    assert CalcIntent( operation="arithmetic", operands='[1, "x"]' ).get_operands_list() == []
    assert CRUDIntent( operation="read", filters='{"a": 1}' ).get_filters_dict() == { "a": 1 }
    assert CRUDIntent( operation="read", filters="[1]" ).get_filters_dict() == {}


def test_the_fallback_fields_are_the_low_confidence_unknown_diagnosis():
    assert fallback_diagnosis_fields( "why" ) == {
        "root_cause": "why", "error_category": "unknown", "confidence": 0.1,
        "evidence": [ "Failed to parse structured diagnosis" ], "affected_components": [], "is_transient": False,
    }


def test_the_fallback_fields_share_no_list_between_calls():
    a, b = fallback_diagnosis_fields( "x" ), fallback_diagnosis_fields( "x" )
    assert a[ "evidence" ] is not b[ "evidence" ] and a[ "affected_components" ] is not b[ "affected_components" ]


def test_both_expediters_build_their_fallback_from_them():
    common = fallback_diagnosis_fields( "why" )
    bfe, tfe = BFEOrchestrator._fallback_diagnosis( "why" ), TFEOrchestrator._fallback_diagnosis( "C5", "why" )
    for name, value in common.items():
        assert getattr( bfe, name ) == value and getattr( tfe, name ) == value
    assert tfe.cluster_id == "C5" and tfe.test_symptoms == []


def test_a_diagnosis_with_a_field_its_type_refuses_falls_back_in_both_expediters():
    raw = '{"root_cause": "r", "not_a_field": 1}'
    bfe = BFEOrchestrator.__new__( BFEOrchestrator )._parse_diagnosis_result( raw )
    tfe = TFEOrchestrator.__new__( TFEOrchestrator )._parse_diagnosis_result( raw, "C5" )
    assert ( bfe.confidence, tfe.confidence, tfe.cluster_id ) == ( 0.1, 0.1, "C5" )
    assert raw[ :20 ] in bfe.root_cause and raw[ :20 ] in tfe.root_cause
