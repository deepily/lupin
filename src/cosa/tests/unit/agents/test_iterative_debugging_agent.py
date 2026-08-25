"""
Unit tests for cosa.agents.iterative_debugging_agent.IterativeDebuggingAgent.

This AgentBase subclass walks a list of LLMs trying to fix code until one succeeds.
Tests stub AgentBase.__init__ (seeding config + prompt template) and mock the du /
util_code_runner boundaries plus the agent's own collaborator methods, so the LLM
loop and helpers run in isolation (no LLM / network / real file I/O):

- __init__ / _get_prompt / _load_available_llm_specs — minimalist + non-minimalist
- run_prompts          — the full attempt loop: minimalist success/fail, runnable vs
                         not, success vs fail, last-vs-not-last LLM, early-break, debug override
- _patch_code_in_response_dict — Pydantic vs baseline field names
- was_successfully_debugged / is_code_runnable
- serialize_to_json    — state filter + filename build + write + chmod
- restore_from_serialized_state — JSON load → reconstruct → set/skip attrs

Created 2026-05-31 (CoSA coverage campaign, remaining agents lane — Tiffany 💍). New file.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch, mock_open

from cosa.agents.iterative_debugging_agent import IterativeDebuggingAgent
from cosa.agents.agent_base import AgentBase

_TEMPLATE = "ERR={error_message}|CODE={formatted_code}"


def _seed_init( self_inner, *args, **kwargs ):
    """AgentBase.__init__ stub seeding what IterativeDebuggingAgent relies on."""
    self_inner.debug           = kwargs.get( "debug", False )
    self_inner.verbose         = kwargs.get( "verbose", False )
    self_inner.routing_command = kwargs.get( "routing_command", "agent router go to debugger" )
    self_inner.model_name      = "model_x"
    self_inner.prompt_template  = _TEMPLATE
    self_inner.do_not_serialize = [ "config_mgr" ]

    cfg = Mock()
    _lookup = lambda key, default=None, return_type=None: (
        [ "llm_key_1" ]    if key == "llm model keys for debugger"
        else "/tmpl/min.txt" if key == "agent prompt for debugger minimalist"
        else { "model": key }
    )
    cfg.get.side_effect = _lookup
    # get_required() answers the same way here. Without this the Mock hands back
    # a Mock and the concatenation at iterative_debugging_agent.py:114 fails —
    # which is the very crash row 3e4a4a4a is about, just wearing a test costume.
    cfg.get_required.side_effect = lambda key, silent=False, return_type=None: _lookup( key )
    self_inner.config_mgr = cfg


class TestIterativeDebuggingAgent( unittest.TestCase ):
    """
    Comprehensive unit tests for IterativeDebuggingAgent.

    Ensures:
        - Construction + prompt + LLM-spec loading across both modes
        - The full run_prompts attempt loop and its branches
        - Patch / serialize / restore / accessors all behave per contract
    """

    def _make_agent( self, minimalist=True, debug=False, verbose=False ):
        """Construct an IterativeDebuggingAgent with AgentBase + du boundaries mocked."""
        with patch.object( AgentBase, "__init__", _seed_init ), \
             patch( "cosa.agents.iterative_debugging_agent.du.get_project_root", return_value="/root" ), \
             patch( "cosa.agents.iterative_debugging_agent.du.get_file_as_source_code_with_line_numbers", return_value="1: code" ), \
             patch( "cosa.agents.iterative_debugging_agent.du.get_file_as_string", return_value=_TEMPLATE ):
            agent = IterativeDebuggingAgent(
                error_message="boom", path_to_code="/src/x.py",
                example="ex", returns="int", minimalist=minimalist, debug=debug, verbose=verbose
            )
        return agent

    # ------------------------------------------------------------------ #
    # __init__ / _get_prompt / _load_available_llm_specs                  #
    # ------------------------------------------------------------------ #

    def test_init_minimalist( self ):
        """
        Test minimalist construction wires the prompt, LLM specs, and minimalist tags.

        Ensures:
            - available_llms loaded from config
            - prompt formatted from the minimalist template
            - minimalist XML tags chosen; successfully_debugged starts False
        """
        agent = self._make_agent( minimalist=True, debug=True, verbose=True )

        self.assertEqual( agent.available_llms, [ { "model": "llm_key_1" } ] )
        self.assertIn( "ERR=boom", agent.prompt )
        self.assertEqual(
            agent.xml_response_tag_names,
            [ "thoughts", "line-number", "one-line-of-code", "success" ]
        )
        self.assertFalse( agent.successfully_debugged )

    def test_init_non_minimalist_uses_existing_template_and_tags( self ):
        """
        Test non-minimalist construction uses the seeded template + full tags.

        Ensures:
            - The else-branch of _get_prompt formats the existing prompt_template
            - Non-minimalist XML tags chosen
        """
        agent = self._make_agent( minimalist=False )

        self.assertIn( "ERR=boom", agent.prompt )
        self.assertEqual(
            agent.xml_response_tag_names,
            [ "thoughts", "code", "example", "returns", "explanation" ]
        )

    # ------------------------------------------------------------------ #
    # accessors                                                           #
    # ------------------------------------------------------------------ #

    def test_was_successfully_debugged_reflects_flag( self ):
        """Test was_successfully_debugged mirrors the internal flag."""
        agent = self._make_agent()
        self.assertFalse( agent.was_successfully_debugged() )
        agent.successfully_debugged = True
        self.assertTrue( agent.was_successfully_debugged() )

    def test_is_code_runnable_true_and_false( self ):
        """
        Test is_code_runnable across present vs empty code.

        Ensures:
            - Non-empty code → True; empty code → False (with diagnostic print)
        """
        agent = self._make_agent()

        agent.prompt_response_dict = { "code": [ "x = 1" ] }
        self.assertTrue( agent.is_code_runnable() )

        agent.prompt_response_dict = { "code": [] }
        self.assertFalse( agent.is_code_runnable() )

    # ------------------------------------------------------------------ #
    # _patch_code_in_response_dict (Pydantic vs baseline field names)     #
    # ------------------------------------------------------------------ #

    def _patch_with( self, agent, response_dict ):
        """Drive _patch_code_in_response_dict with du file boundaries mocked."""
        agent.debug      = True
        agent.print_code = Mock()
        with patch( "cosa.agents.iterative_debugging_agent.du.get_file_as_source_code_with_line_numbers", return_value="1: a" ), \
             patch( "cosa.agents.iterative_debugging_agent.du.get_file_as_list", return_value=[ "a", "b", "c" ] ):
            agent._patch_code_in_response_dict( response_dict )

    def test_patch_code_pydantic_field_names( self ):
        """
        Test _patch_code_in_response_dict with Pydantic field names.

        Ensures:
            - line_number (1-based) → 0-based index; one_line_of_code replaces that line
        """
        agent = self._make_agent()
        self._patch_with( agent, { "line_number": "2", "one_line_of_code": "FIXED" } )

        self.assertEqual( agent.prompt_response_dict[ "code" ], [ "a", "FIXED", "c" ] )

    def test_patch_code_baseline_field_names( self ):
        """
        Test _patch_code_in_response_dict with baseline (hyphenated) field names.

        Ensures:
            - line-number / one-line-of-code are honored when Pydantic keys are absent
        """
        agent = self._make_agent()
        self._patch_with( agent, { "line-number": "3", "one-line-of-code": "BUGGED" } )

        self.assertEqual( agent.prompt_response_dict[ "code" ], [ "a", "b", "BUGGED" ] )

    # ------------------------------------------------------------------ #
    # run_prompts — the attempt loop                                      #
    # ------------------------------------------------------------------ #

    def test_run_prompts_minimalist_success_then_break( self ):
        """
        Test a first-LLM success patches code, records success, and breaks the loop.

        Ensures (debug override on):
            - minimalist success path patches + sets example/returns
            - successful run sets self.code and stops before the 2nd LLM
        """
        agent = self._make_agent( minimalist=True )
        agent.available_llms              = [ { "model": "a" }, { "model": "b" } ]
        agent.run_prompt                  = Mock( return_value={ "success": "True", "code": [ "fixed" ] } )
        agent._patch_code_in_response_dict = Mock()
        agent.is_code_runnable            = Mock( return_value=True )
        agent.run_code                    = Mock( return_value={ "return_code": 0, "output": "ok" } )
        agent.code_ran_to_completion      = Mock( return_value=True )

        with patch( "cosa.agents.iterative_debugging_agent.ucr.initialize_code_response_dict", return_value={ "output": "" } ):
            result = agent.run_prompts( debug=True )

        self.assertTrue( agent.successfully_debugged )
        self.assertEqual( agent.code, [ "fixed" ] )
        self.assertEqual( agent.run_prompt.call_count, 1 )   # 2nd iteration broke early
        agent._patch_code_in_response_dict.assert_called_once()
        self.assertEqual( result[ "output" ], "ok" )

    def test_run_prompts_minimalist_fail_unrunnable( self ):
        """
        Test a minimalist failure empties the code and skips execution.

        Ensures (debug override off):
            - success != 'True' → code set to []; is_code_runnable False → no run
            - The un-runnable sentinel output is returned
        """
        agent = self._make_agent( minimalist=True )
        agent.available_llms = [ { "model": "a" } ]
        agent.run_prompt     = Mock( return_value={ "success": "False" } )

        with patch( "cosa.agents.iterative_debugging_agent.ucr.initialize_code_response_dict", return_value={ "output": "init" } ):
            result = agent.run_prompts()

        self.assertFalse( agent.successfully_debugged )
        self.assertEqual( agent.prompt_response_dict[ "code" ], [] )
        self.assertEqual( result[ "output" ], "Code was deemed un-runnable by iterative debugging agent" )

    def test_run_prompts_runnable_but_fails_across_all_llms( self ):
        """
        Test runnable code that fails on every LLM exercises the not-last + last arms.

        Ensures:
            - Each LLM runs; failure keeps successfully_debugged False
            - The 'moving on' (not last) and 'no more' (last) branches both run
        """
        agent = self._make_agent( minimalist=True )
        agent.available_llms              = [ { "model": "a" }, { "model": "b" } ]
        agent.run_prompt                  = Mock( return_value={ "success": "True", "code": [ "c" ] } )
        agent._patch_code_in_response_dict = Mock()
        agent.is_code_runnable            = Mock( return_value=True )
        agent.run_code                    = Mock( return_value={ "return_code": 1, "output": "err" } )
        agent.code_ran_to_completion      = Mock( return_value=False )

        with patch( "cosa.agents.iterative_debugging_agent.ucr.initialize_code_response_dict", return_value={ "output": "" } ):
            agent.run_prompts()

        self.assertFalse( agent.successfully_debugged )
        self.assertEqual( agent.run_prompt.call_count, 2 )

    def test_run_prompts_non_minimalist_success( self ):
        """
        Test the non-minimalist branch skips the minimalist success/fail handling.

        Ensures:
            - Neither minimalist branch runs; a runnable success sets the flag + code
        """
        agent = self._make_agent( minimalist=False )
        agent.available_llms         = [ { "model": "a" } ]
        agent.run_prompt             = Mock( return_value={ "code": [ "ok line" ] } )
        agent.is_code_runnable       = Mock( return_value=True )
        agent.run_code               = Mock( return_value={ "return_code": 0, "output": "done" } )
        agent.code_ran_to_completion = Mock( return_value=True )

        with patch( "cosa.agents.iterative_debugging_agent.ucr.initialize_code_response_dict", return_value={ "output": "" } ):
            agent.run_prompts()

        self.assertTrue( agent.successfully_debugged )
        self.assertEqual( agent.code, [ "ok line" ] )

    # ------------------------------------------------------------------ #
    # serialize_to_json / restore_from_serialized_state                   #
    # ------------------------------------------------------------------ #

    def test_serialize_to_json_writes_filtered_state( self ):
        """
        Test serialize_to_json writes the state (minus do_not_serialize) and chmods it.

        Ensures:
            - A timestamped file path is opened + json-dumped + chmod 0o666
        """
        agent = self._make_agent()
        now   = SimpleNamespace( year=2026, month=5, day=31, hour=10, minute=20, second=30 )

        m = mock_open()
        with patch( "cosa.agents.iterative_debugging_agent.du.get_project_root", return_value="/root" ), \
             patch( "cosa.agents.iterative_debugging_agent.open", m, create=True ), \
             patch( "cosa.agents.iterative_debugging_agent.os.chmod" ) as mock_chmod:
            agent.serialize_to_json( "code-debugging", now, run_descriptor="Run 1 of 1", model_id="phi_4" )

        self.assertTrue( m.called )
        opened_path = m.call_args[0][0]
        self.assertIn( "code-debugging", opened_path )
        self.assertIn( "run-1-of-1", opened_path )
        mock_chmod.assert_called_once()

    def test_restore_from_serialized_state_rebuilds_instance( self ):
        """
        Test restore_from_serialized_state reconstructs an agent and applies extras.

        Ensures:
            - JSON loaded; constructor keys consumed; extra keys set via setattr
        """
        data = {
            "error_message" : "boom",
            "path_to_code"  : "/src/x.py",
            "debug"         : False,
            "verbose"       : False,
            "successfully_debugged" : True,
        }

        with patch.object( AgentBase, "__init__", _seed_init ), \
             patch( "cosa.agents.iterative_debugging_agent.du.get_project_root", return_value="/root" ), \
             patch( "cosa.agents.iterative_debugging_agent.du.get_file_as_source_code_with_line_numbers", return_value="1: code" ), \
             patch( "cosa.agents.iterative_debugging_agent.du.get_file_as_string", return_value=_TEMPLATE ), \
             patch( "cosa.agents.iterative_debugging_agent.open", mock_open(), create=True ), \
             patch( "cosa.agents.iterative_debugging_agent.json.load", return_value=data ):
            restored = IterativeDebuggingAgent.restore_from_serialized_state( "/tmp/idbg_state.json" )

        self.assertIsInstance( restored, IterativeDebuggingAgent )
        self.assertTrue( restored.successfully_debugged )


if __name__ == "__main__":
    unittest.main()
