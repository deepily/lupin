"""
Unit tests for cosa.agents.receptionist_agent.ReceptionistAgent.

ReceptionistAgent is an AgentBase subclass that answers from conversational memory.
These tests stub AgentBase.__init__ (seeding a format-able prompt template + config)
and mock the memory table + downstream formatter so the subclass logic runs alone:

- __init__                      — super delegation, memory table, prompt, XML tags, flag
- _get_prompt / _get_df_metadata— memory-fragment formatting + (date, entries)
- run_prompt                    — parent delegation, answer extraction, optional serialize
- is_code_runnable / run_code / code_ran_to_completion — the no-code receptionist contract
- run_formatter                 — benign (skip) vs non-benign (RawOutputFormatter) paths
- restore_from_serialized_state — JSON load → reconstruct → set/skip attributes

No real AgentBase init, memory/LLM/file I/O.

Created 2026-05-31 (CoSA coverage campaign, user-facing agents lane — Tiffany 💍). New file.
"""

import unittest
from unittest.mock import Mock, patch, mock_open

from cosa.agents.receptionist_agent import ReceptionistAgent
from cosa.agents.agent_base import AgentBase


def _fake_agent_base_init( serialize_prompt=False ):
    """Build an AgentBase.__init__ stub seeding the attributes ReceptionistAgent needs."""
    def fake_init( self_inner, *args, **kwargs ):
        self_inner.prompt_template     = "Q={query}|D={date_today}|E={entries}"
        self_inner.last_question_asked = kwargs.get( "last_question_asked", "" )
        self_inner.routing_command     = kwargs.get( "routing_command", "agent router go to receptionist" )
        self_inner.debug               = kwargs.get( "debug", False )
        self_inner.verbose             = kwargs.get( "verbose", False )

        cfg = Mock()
        cfg.get.side_effect = lambda key, default=None, return_type=None: {
            "agent receptionist serialize prompt to json" : serialize_prompt,
        }.get( key, default )
        self_inner.config_mgr = cfg

    return fake_init


class TestReceptionistAgent( unittest.TestCase ):
    """
    Comprehensive unit tests for ReceptionistAgent.

    Ensures:
        - Construction wires memory table + prompt + tags + serialize flag
        - Memory metadata + prompt formatting behave per contract
        - run_prompt / no-code interface / category-gated formatter all covered
        - restore_from_serialized_state rebuilds an instance from JSON
    """

    def _make_agent( self, serialize_prompt=False, rows=None, debug=False, verbose=False,
                     question="what is your name?" ):
        """Construct a ReceptionistAgent with AgentBase + InputAndOutputTable mocked."""
        if rows is None:
            rows = [
                { "date": "2026-01-01", "input": "hi",     "output_final": "hello"   },
                { "date": "2026-01-02", "input": "bye",    "output_final": "goodbye" },
            ]
        mock_io = Mock()
        mock_io.get_all_qnr.return_value = rows

        with patch.object( AgentBase, "__init__", _fake_agent_base_init( serialize_prompt ) ), \
             patch( "cosa.agents.receptionist_agent.InputAndOutputTable", return_value=mock_io ):
            agent = ReceptionistAgent( question=question, last_question_asked=question, debug=debug, verbose=verbose )

        agent._mock_io = mock_io
        return agent

    # ------------------------------------------------------------------ #
    # __init__ / metadata                                                 #
    # ------------------------------------------------------------------ #

    def test_init_builds_prompt_tags_and_flag( self ):
        """
        Test construction wires the prompt, XML tags, and serialize flag.

        Ensures:
            - The prompt embeds the query + memory fragments
            - xml_response_tag_names matches the receptionist contract
            - serialize_prompt_to_json reflects config (False here)
        """
        agent = self._make_agent( question="who are you?" )

        self.assertIn( "who are you?", agent.prompt )
        self.assertIn( "<memory-fragment>", agent.prompt )
        self.assertEqual( agent.xml_response_tag_names, [ "thoughts", "category", "answer" ] )
        self.assertFalse( agent.serialize_prompt_to_json )

    def test_get_df_metadata_formats_fragments( self ):
        """
        Test _get_df_metadata returns the date and newline-joined memory fragments.

        Ensures:
            - One <memory-fragment> per memory row, carrying input + output_final
            - A current-date string is returned
        """
        agent = self._make_agent()

        date_today, entries = agent._get_df_metadata()

        self.assertIsInstance( date_today, str )
        self.assertTrue( len( date_today ) > 0 )
        self.assertEqual( entries.count( "<memory-fragment>" ), 2 )
        self.assertIn( "hello", entries )
        self.assertIn( "goodbye", entries )

    def test_get_df_metadata_empty_memory( self ):
        """
        Test _get_df_metadata handles an empty memory table.

        Ensures:
            - No rows → empty entries string (the loop-not-entered path)
        """
        agent = self._make_agent( rows=[] )

        _, entries = agent._get_df_metadata()
        self.assertEqual( entries, "" )

    # ------------------------------------------------------------------ #
    # run_prompt                                                          #
    # ------------------------------------------------------------------ #

    def test_run_prompt_extracts_answer_without_serialize( self ):
        """
        Test run_prompt stores the response and extracts the conversational answer.

        Ensures:
            - answer_conversational is set from results['answer']
            - serialize_to_json NOT called when the flag is off
        """
        agent = self._make_agent( serialize_prompt=False )
        agent.serialize_to_json = Mock()

        with patch.object( AgentBase, "run_prompt",
                           return_value={ "answer": "I am Rio", "category": "benign" } ):
            results = agent.run_prompt()

        self.assertEqual( agent.answer_conversational, "I am Rio" )
        self.assertEqual( agent.prompt_response_dict, results )
        agent.serialize_to_json.assert_not_called()

    def test_run_prompt_serializes_when_enabled( self ):
        """
        Test run_prompt serializes the prompt when the flag is enabled.

        Ensures:
            - serialize_to_json is called with 'prompt'
        """
        agent = self._make_agent( serialize_prompt=True )
        agent.serialize_to_json = Mock()

        with patch.object( AgentBase, "run_prompt",
                           return_value={ "answer": "hi", "category": "benign" } ):
            agent.run_prompt()

        agent.serialize_to_json.assert_called_once_with( "prompt" )

    # ------------------------------------------------------------------ #
    # no-code interface                                                   #
    # ------------------------------------------------------------------ #

    def test_is_code_runnable_always_false( self ):
        """Test the receptionist never reports runnable code."""
        self.assertFalse( self._make_agent().is_code_runnable() )

    def test_run_code_is_noop_success( self ):
        """
        Test run_code returns a benign success dict without executing anything.

        Ensures:
            - return_code 0 + informative output; code_response_dict stored
        """
        agent = self._make_agent()

        result = agent.run_code()

        self.assertEqual( result[ "return_code" ], 0 )
        self.assertIn( "receptionist", result[ "output" ] )
        self.assertEqual( agent.code_response_dict, result )

    def test_code_ran_to_completion_always_true( self ):
        """Test the interface-satisfying completion flag is always True."""
        self.assertTrue( self._make_agent().code_ran_to_completion() )

    # ------------------------------------------------------------------ #
    # run_formatter (category-gated)                                      #
    # ------------------------------------------------------------------ #

    def test_run_formatter_benign_skips_reformatting( self ):
        """
        Test run_formatter leaves benign answers untouched.

        Ensures:
            - A 'benign' category returns answer_conversational unchanged (no formatter)
        """
        agent = self._make_agent()
        agent.prompt_response_dict = { "category": "benign", "thoughts": "t" }
        agent.answer_conversational = "plain answer"

        self.assertEqual( agent.run_formatter(), "plain answer" )

    def test_run_formatter_non_benign_reformats( self ):
        """
        Test run_formatter reroutes non-benign answers through RawOutputFormatter.

        Ensures:
            - A non-benign category invokes the formatter and adopts its output
        """
        agent = self._make_agent()
        agent.prompt_response_dict = { "category": "humorous", "thoughts": "be funny" }
        agent.answer_conversational = "raw answer"

        mock_formatter = Mock()
        mock_formatter.run_formatter.return_value = "polished answer"
        with patch( "cosa.agents.receptionist_agent.RawOutputFormatter", return_value=mock_formatter ):
            result = agent.run_formatter()

        self.assertEqual( result, "polished answer" )
        self.assertEqual( agent.answer_conversational, "polished answer" )

    # ------------------------------------------------------------------ #
    # restore_from_serialized_state                                       #
    # ------------------------------------------------------------------ #

    def test_restore_from_serialized_state_rebuilds_instance( self ):
        """
        Test restore_from_serialized_state reconstructs an agent and applies extra attrs.

        Ensures:
            - JSON loaded; constructor keys consumed; extra keys set via setattr
        """
        data = {
            "question"    : "restored q",
            "debug"       : False,
            "verbose"     : False,
            "auto_debug"  : False,
            "inject_bugs" : False,
            "answer_conversational" : "restored answer",
        }
        mock_io = Mock()
        mock_io.get_all_qnr.return_value = []

        with patch.object( AgentBase, "__init__", _fake_agent_base_init() ), \
             patch( "cosa.agents.receptionist_agent.InputAndOutputTable", return_value=mock_io ), \
             patch( "cosa.agents.receptionist_agent.open", mock_open(), create=True ), \
             patch( "cosa.agents.receptionist_agent.json.load", return_value=data ):
            restored = ReceptionistAgent.restore_from_serialized_state( "/tmp/recep_state.json" )

        self.assertIsInstance( restored, ReceptionistAgent )
        self.assertEqual( restored.answer_conversational, "restored answer" )


if __name__ == "__main__":
    unittest.main()
