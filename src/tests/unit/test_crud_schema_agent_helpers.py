"""
Unit tests for the shared pieces of the domain CRUD agents.

get_columns_by_dtype backs three schema readers. smoke_check_schema_agent backs the smoke block of
both domain agents and reports a failure by printing it and returning False. The base agent carries
the schema constant that each domain subclass overrides.
"""
import pytest

from cosa.crud_for_dataframes import calendar_crud_agent, schemas, todo_crud_agent
from cosa.crud_for_dataframes.agent import CrudForDataFramesAgent, smoke_check_schema_agent
from cosa.crud_for_dataframes.calendar_crud_agent import CalendarCrudAgent
from cosa.crud_for_dataframes.todo_crud_agent import TodoCrudAgent


@pytest.mark.parametrize( "schema_type", [ "todo", "calendar" ] )
@pytest.mark.parametrize( "dtype, reader", [ ( "date", schemas.get_date_columns ), ( "time", schemas.get_time_columns ), ( "datetime", schemas.get_datetime_columns ) ] )
def test_each_dtype_reader_is_the_shared_reader_with_its_dtype( schema_type, dtype, reader ):
    expected = [ col for col, meta in schemas.get_schema( schema_type )[ "columns" ].items() if meta[ "dtype" ] == dtype ]
    assert reader( schema_type ) == schemas.get_columns_by_dtype( schema_type, dtype ) == expected


def test_the_three_date_like_readers_find_something_to_read_in_at_least_one_schema():
    found = [ schemas.get_columns_by_dtype( t, d ) for t in ( "todo", "calendar" ) for d in ( "date", "time", "datetime" ) ]
    assert any( found ), "every reader returned [], so the parity test above proves nothing"


def test_the_calendar_schema_dtypes_read_back_as_the_literal_columns():
    assert schemas.get_date_columns( "calendar" ) == [ "start_date", "end_date" ]
    assert schemas.get_time_columns( "calendar" ) == [ "start_time", "end_time" ]
    assert schemas.get_datetime_columns( "todo" ) == [ "created_at" ]


def test_a_dtype_no_column_has_gives_an_empty_list():
    assert schemas.get_columns_by_dtype( "todo", "no-such-dtype" ) == []


def test_the_base_agent_names_no_schema_and_each_domain_agent_names_its_own():
    assert CrudForDataFramesAgent.DEFAULT_SCHEMA_TYPE is None
    assert TodoCrudAgent.DEFAULT_SCHEMA_TYPE == "todo" and CalendarCrudAgent.DEFAULT_SCHEMA_TYPE == "calendar"
    assert "__init__" not in vars( TodoCrudAgent ) and "__init__" not in vars( CalendarCrudAgent )


@pytest.mark.parametrize( "agent_cls, schema_type", [ ( TodoCrudAgent, "todo" ), ( CalendarCrudAgent, "calendar" ) ] )
def test_the_smoke_check_passes_for_a_matching_domain_agent( agent_cls, schema_type, capsys ):
    assert smoke_check_schema_agent( agent_cls, schema_type ) is True
    out = capsys.readouterr().out
    assert f"Testing {agent_cls.__name__} module..." in out and f"DEFAULT_SCHEMA_TYPE is '{schema_type}'" in out
    assert f"{agent_cls.__name__} module smoke test PASSED" in out


def test_the_smoke_check_reports_a_wrong_schema_instead_of_raising( capsys ):
    assert smoke_check_schema_agent( TodoCrudAgent, "calendar" ) is False
    captured = capsys.readouterr()
    assert "TodoCrudAgent module smoke test FAILED" in captured.out and "AssertionError" in captured.err


def test_the_smoke_check_reports_a_class_outside_the_base_agent( capsys ):
    class Stranger:
        DEFAULT_SCHEMA_TYPE = "todo"

    assert smoke_check_schema_agent( Stranger, "todo" ) is False
    assert "Stranger module smoke test FAILED" in capsys.readouterr().out


@pytest.mark.parametrize( "module", [ todo_crud_agent, calendar_crud_agent ] )
def test_each_domain_module_smoke_block_returns_the_check_result( module ):
    assert module.quick_smoke_test() is True
