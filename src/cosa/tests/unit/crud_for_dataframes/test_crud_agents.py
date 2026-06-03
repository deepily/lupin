"""
Unit tests for the thin domain CRUD agents.

TodoCrudAgent and CalendarCrudAgent are one-attribute subclasses of
CrudForDataFramesAgent that pin a default schema type. These tests stub
AgentBase.__init__ and DataFrameStorage (so the inherited construction runs
hermetically) and assert the class-level constant, the instance-level
default_schema_type set in __init__, and the inheritance contract.

Created 2026-06-03 (CoSA coverage campaign — Cheech 🌿). New file.
"""

import unittest
from unittest.mock import patch, MagicMock

from cosa.agents.agent_base import AgentBase
from cosa.crud_for_dataframes.agent import CrudForDataFramesAgent
from cosa.crud_for_dataframes.todo_crud_agent import TodoCrudAgent
from cosa.crud_for_dataframes.calendar_crud_agent import CalendarCrudAgent


def _construct( agent_cls ):
    """
    Build a domain CRUD agent with AgentBase.__init__ and storage stubbed.

    Requires:
        - agent_cls is a CrudForDataFramesAgent subclass

    Ensures:
        - Returns a fully constructed instance with no real config/LLM/parquet I/O
    """
    mock_storage = MagicMock()
    mock_storage.get_all_lists_metadata.return_value = []

    def fake_init( self_inner, *args, **kwargs ):
        self_inner.config_mgr          = MagicMock()
        self_inner.prompt_template     = "Q={query}|LISTS={available_lists}"
        self_inner.last_question_asked = kwargs.get( "last_question_asked", "" )
        self_inner.model_name          = "fake-model"
        self_inner.user_email          = kwargs.get( "user_email", "test@example.com" )
        self_inner.debug               = kwargs.get( "debug", False )
        self_inner.verbose             = kwargs.get( "verbose", False )

    with patch.object( AgentBase, "__init__", fake_init ), \
         patch( "cosa.crud_for_dataframes.agent.DataFrameStorage", return_value=mock_storage ):
        return agent_cls( last_question_asked="do a thing", user_email="test@example.com" )


class TestTodoCrudAgent( unittest.TestCase ):
    """
    TodoCrudAgent — todo default schema + inheritance.
    """

    def test_class_constant_is_todo( self ):
        """Ensures the class-level default schema constant is 'todo'."""
        self.assertEqual( TodoCrudAgent.DEFAULT_SCHEMA_TYPE, "todo" )

    def test_instance_default_schema_type( self ):
        """Ensures construction sets the instance default_schema_type to 'todo'."""
        agent = _construct( TodoCrudAgent )
        self.assertEqual( agent.default_schema_type, "todo" )

    def test_inherits_base_agent( self ):
        """Ensures TodoCrudAgent subclasses CrudForDataFramesAgent."""
        self.assertTrue( issubclass( TodoCrudAgent, CrudForDataFramesAgent ) )


class TestCalendarCrudAgent( unittest.TestCase ):
    """
    CalendarCrudAgent — calendar default schema + inheritance.
    """

    def test_class_constant_is_calendar( self ):
        """Ensures the class-level default schema constant is 'calendar'."""
        self.assertEqual( CalendarCrudAgent.DEFAULT_SCHEMA_TYPE, "calendar" )

    def test_instance_default_schema_type( self ):
        """Ensures construction sets the instance default_schema_type to 'calendar'."""
        agent = _construct( CalendarCrudAgent )
        self.assertEqual( agent.default_schema_type, "calendar" )

    def test_inherits_base_agent( self ):
        """Ensures CalendarCrudAgent subclasses CrudForDataFramesAgent."""
        self.assertTrue( issubclass( CalendarCrudAgent, CrudForDataFramesAgent ) )


if __name__ == "__main__":
    unittest.main()
