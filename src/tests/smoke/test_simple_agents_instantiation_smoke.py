"""
Constructor-only smoke tests for classic high-traffic agents.

Tests CalendaringAgent, DateAndTimeAgent, and TodoListAgent constructors
to catch config key renames and DataFrame loading failures. No LLM calls
are made — only instantiation and metadata checks.

These agents have inline quick_smoke_test() functions that require LLM
access. This pytest version tests only the constructor path (offline).

Created: 2026-02-17 (Session 221 — Smoke Test Coverage Audit)
Converted to Pattern A: 2026-02-17 (Session 222 — Consistency Cleanup)
"""

from cosa.agents.calendaring_agent import CalendaringAgent
from cosa.agents.date_and_time_agent import DateAndTimeAgent
from cosa.agents.todo_list_agent import TodoListAgent
from cosa.agents.agent_base import AgentBase


def quick_smoke_test():
    """
    Quick smoke test for classic agent instantiation (offline).

    Requires:
        - cosa.agents package importable
        - Config files present for CalendaringAgent and TodoListAgent DataFrames

    Ensures:
        - CalendaringAgent, DateAndTimeAgent, TodoListAgent all instantiate
        - All are AgentBase subclasses
        - CalendaringAgent and TodoListAgent load DataFrames
        - All agents have prompt, xml_response_tag_names, config_mgr, routing_command
        - Returns True on success
    """
    print( "\n" + "=" * 70 )
    print( "  Simple Agents Instantiation Smoke Test" )
    print( "=" * 70 )

    try:
        # 1. CalendaringAgent
        print( "\n1. CalendaringAgent..." )
        cal = CalendaringAgent(
            question="What events do I have this week?",
            last_question_asked="What events do I have this week?",
            question_gist="weekly events",
            debug=False, verbose=False, auto_debug=False,
        )
        assert isinstance( cal, AgentBase )
        assert cal.question == "What events do I have this week?"
        assert cal.prompt is not None and len( cal.prompt ) > 0
        assert hasattr( cal, "xml_response_tag_names" ) and len( cal.xml_response_tag_names ) > 0
        assert cal.df is not None and len( cal.df ) > 0
        assert cal.config_mgr is not None
        assert cal.routing_command is not None and len( cal.routing_command ) > 0
        print( "   PASS: CalendaringAgent created with DataFrame and metadata" )

        # 2. DateAndTimeAgent
        print( "2. DateAndTimeAgent..." )
        dt = DateAndTimeAgent( question="What time is it?", debug=False, verbose=False )
        assert isinstance( dt, AgentBase )
        assert dt.question == "What time is it?"
        assert dt.prompt is not None and len( dt.prompt ) > 0
        assert "code" in dt.xml_response_tag_names
        assert dt.config_mgr is not None
        assert dt.routing_command is not None and len( dt.routing_command ) > 0
        print( "   PASS: DateAndTimeAgent created with prompt and metadata" )

        # 3. TodoListAgent
        print( "3. TodoListAgent..." )
        todo = TodoListAgent( question="What's on my to do list?", debug=False, verbose=False )
        assert isinstance( todo, AgentBase )
        assert todo.question == "What's on my to do list?"
        assert todo.prompt is not None and len( todo.prompt ) > 0
        assert "code" in todo.xml_response_tag_names
        assert todo.df is not None and len( todo.df ) > 0
        assert "list_name" in todo.df.columns.tolist()
        assert todo.config_mgr is not None
        assert todo.routing_command is not None and len( todo.routing_command ) > 0
        print( "   PASS: TodoListAgent created with DataFrame and metadata" )

        print( "\n  ALL SIMPLE AGENT INSTANTIATION SMOKE TESTS PASSED (3/3)" )
        return True

    except Exception as e:
        print( f"\n  FAIL: {e}" )
        import traceback
        traceback.print_exc()
        return False


def test_simple_agents_instantiation():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    quick_smoke_test()
