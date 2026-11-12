"""
The shared xml_models field checks: None to empty string, and refuse an empty field.
"""
import pytest
from pydantic import ValidationError

from cosa.agents.calculator.xml_models import CalcIntent
from cosa.agents.dm_compression.xml_models import DmCompressionResponse
from cosa.agents.dm_tutor.xml_models import DmTutorResponse
from cosa.agents.io_models.field_validators import none_to_empty, require_nonempty
from cosa.agents.io_models.xml_models import ReceptionistResponse
from cosa.crud_for_dataframes.xml_models import CRUDIntent


def test_none_becomes_an_empty_string_and_other_values_pass_through():
    assert none_to_empty( None ) == "" and none_to_empty( "x" ) == "x" and none_to_empty( "" ) == ""


def test_a_kept_field_stays_none_and_any_other_field_is_coerced():
    assert none_to_empty( None, "operation", keep_none=( "operation", ) ) is None
    assert none_to_empty( None, "reasoning", keep_none=( "operation", ) ) == ""


@pytest.mark.parametrize( "bad", [ None, "", "  \n\t" ] )
def test_an_empty_field_is_refused_with_the_given_message( bad ):
    with pytest.raises( ValueError, match="slot is empty" ): require_nonempty( bad, "slot is empty" )


def test_a_good_field_is_stripped_by_default_and_left_alone_when_strip_is_off():
    assert require_nonempty( "  hi \n", "m" ) == "hi"
    assert require_nonempty( "  hi \n", "m", strip=False ) == "  hi \n"


def test_the_models_keep_their_own_behaviour_through_the_helpers():
    assert CalcIntent.model_validate( { "operation": "arithmetic", "value_2": None } ).value_2 == ""
    with pytest.raises( ValueError, match="thoughts cannot be empty" ): ReceptionistResponse( thoughts="  ", answer="a" )
    with pytest.raises( ValueError, match="compressed body is empty" ): DmCompressionResponse( thoughts=None, compressed=" " )


def test_calculators_required_operation_stays_none_and_is_refused():
    with pytest.raises( ValidationError, match="operation" ): CalcIntent.model_validate( { "operation": None } )


def test_the_crud_required_operation_stays_none_and_is_refused():
    with pytest.raises( ValidationError, match="operation" ): CRUDIntent.model_validate( { "operation": None } )


def test_dm_compression_returns_a_padded_body_unstripped():
    assert DmCompressionResponse( thoughts="t", compressed="  body \n" ).compressed == "  body \n"


def test_dm_tutor_returns_padded_slots_unstripped():
    r = DmTutorResponse.model_validate( { "declaration-or-question": " q ", "supporting-statement-1st": " a\n", "supporting-statement-2nd": "\tb" } )
    assert ( r.declaration_or_question, r.supporting_1st, r.supporting_2nd ) == ( " q ", " a\n", "\tb" )
