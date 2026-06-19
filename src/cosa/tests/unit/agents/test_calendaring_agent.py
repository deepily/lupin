"""
Unit tests for cosa.agents.calendaring_agent.CalendaringAgent.

CalendaringAgent is a thin AgentBase subclass. These tests stub AgentBase.__init__
(the heavy config / DataFrame-load / prompt-template boundary) with a lightweight
seeder that installs a small real pandas DataFrame + a format-able prompt template,
so the subclass's own logic runs for real:

- __init__                      — delegates to super, builds the prompt, sets XML tags
- _get_prompt                   — formats the template with question + df metadata
- _get_metadata                 — column names, unique event types, head+tail XML sample
- restore_from_serialized_state — always NotImplementedError

No real AgentBase init, config, LLM, or file I/O.

Created 2026-05-31 (CoSA coverage campaign, user-facing agents lane — Tiffany 💍). New file.
"""

import unittest
from unittest.mock import patch

import pandas as pd

from cosa.agents.calendaring_agent import CalendaringAgent
from cosa.agents.agent_base import AgentBase


class TestCalendaringAgent( unittest.TestCase ):
    """
    Comprehensive unit tests for CalendaringAgent.

    Ensures:
        - Construction wires the prompt + XML response tags via the subclass logic
        - Metadata extraction reflects the events DataFrame
        - The unimplemented restore hook fails loudly
    """

    def _make_agent( self, question="What is on my calendar?", df=None ):
        """
        Construct a CalendaringAgent with AgentBase.__init__ stubbed.

        The stub seeds the attributes the subclass relies on (df, prompt_template,
        last_question_asked, debug/verbose) so _get_prompt / _get_metadata operate on
        a real (small) DataFrame without touching config / file / LLM boundaries.
        """
        if df is None:
            df = pd.DataFrame( {
                "event_type" : [ "meeting", "birthday", "meeting", "appointment" ],
                "start_date" : [ "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04" ],
                "name"       : [ "standup", "alice", "review", "dentist" ],
            } )

        def fake_init( self_inner, *args, **kwargs ):
            self_inner.df                  = df
            self_inner.prompt_template     = "Q={question}|COLS={column_names}|TYPES={unique_event_types}|HEAD={head}"
            self_inner.last_question_asked = kwargs.get( "last_question_asked", "" )
            self_inner.debug               = kwargs.get( "debug", False )
            self_inner.verbose             = kwargs.get( "verbose", False )

        with patch.object( AgentBase, "__init__", fake_init ):
            agent = CalendaringAgent( question=question, last_question_asked=question, question_gist=question )

        return agent

    def test_init_builds_prompt_and_xml_tags( self ):
        """
        Test construction formats the prompt and sets the XML response tags.

        Ensures:
            - The prompt embeds the question + column names + event types + XML head
            - xml_response_tag_names matches the calendar contract
        """
        agent = self._make_agent( question="What meetings do I have?" )

        self.assertIn( "What meetings do I have?", agent.prompt )
        self.assertIn( "event_type", agent.prompt )
        self.assertIn( "meeting", agent.prompt )
        self.assertIn( "<events>", agent.prompt )
        self.assertEqual(
            agent.xml_response_tag_names,
            [ "question", "thoughts", "code", "example", "returns", "explanation" ]
        )

    def test_get_metadata_extracts_columns_types_and_xml( self ):
        """
        Test _get_metadata returns column names, unique event types, and an XML sample.

        Ensures:
            - column_names lists the DataFrame columns
            - unique_event_types are de-duplicated
            - The XML sample uses the <events> root and drops the XML declaration
        """
        agent = self._make_agent()

        column_names, unique_event_types, head = agent._get_metadata()

        self.assertEqual( column_names, [ "event_type", "start_date", "name" ] )
        self.assertCountEqual( unique_event_types, [ "meeting", "birthday", "appointment" ] )
        self.assertIn( "<events>", head )
        self.assertNotIn( "<?xml", head )

    def test_restore_from_serialized_state_raises_not_implemented( self ):
        """
        Test restore_from_serialized_state is explicitly unimplemented.

        Ensures:
            - Calling it raises NotImplementedError naming the file path
        """
        agent = self._make_agent()

        with self.assertRaises( NotImplementedError ):
            agent.restore_from_serialized_state( "/tmp/state.json" )


if __name__ == "__main__":
    unittest.main()
