"""
Unit tests for cosa.agents.agent_base.AgentBase (the ABC all agents subclass).

A concrete subclass implements the abstract restore hook; the heavy boundaries
(ConfigurationManager, XmlParserFactory, LlmClientFactory, PromptTemplateProcessor,
pandas/df, TwoWordIdGenerator, SolutionSnapshot, IterativeDebuggingAgent, RawOutputFormatter,
RunnableCode.run_code) are all mocked — no config / LLM / file / code-exec I/O.

Covers: __init__ (question/last fork, df-load, template-process success+failure,
empty-input guard), serialize_to_json (subtopic on/off), _update_response_dictionary,
run_prompt (raw on/off), run_code (success / auto-debug success / auto-debug fail→raise /
auto-debug crash→raise / no-auto-debug fall-through / df-path branch / explicit overrides),
is_format_output_runnable, run_formatter, formatter_ran_to_completion, job_type, created_date,
do_all, and the abstract restore stub body.

Created 2026-05-31 (CoSA coverage campaign, remaining agents lane — Tiffany 💍). New file.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch, mock_open

import pandas as pd

from cosa.agents.agent_base import AgentBase, CodeGenerationFailedException
from cosa.agents.runnable_code import RunnableCode


class _ConcreteAgent( AgentBase ):
    """Concrete AgentBase for testing; implements the abstract restore hook."""

    @staticmethod
    def restore_from_serialized_state( file_path: str ):
        return "restored"


def _super_run_code( return_code, output="out" ):
    """Build a RunnableCode.run_code replacement that seeds code_response_dict."""
    def _f( self, path_to_df=None, inject_bugs=False ):
        self.code_response_dict = { "return_code": return_code, "output": output, "example": "e" }
        return self.code_response_dict
    return _f


class TestAgentBase( unittest.TestCase ):
    """
    Comprehensive unit tests for AgentBase.

    Ensures every reachable branch of the central agent base class is exercised
    with discriminating assertions and full boundary isolation.
    """

    def _make_agent( self, df_path_key=None, question="what is 2+2?", last_question_asked="",
                     routing_command="agent router go to math", debug=False, verbose=False,
                     auto_debug=False, inject_bugs=False, template="TMPL {", processor_raises=False ):
        """
        Construct a _ConcreteAgent with the full __init__ dependency chain mocked.

        Returns (agent, mock_config). xml_response_tag_names is seeded post-construction.
        """
        mock_config = Mock()
        def cfg_get( key, default=None, return_type=None ):
            return {
                f"llm spec key for {routing_command}"      : "model_x",
                f"prompt template for {routing_command}"   : "/tmpl.txt",
                f"serialization topic for {routing_command}" : "math-topic",
                df_path_key                                : "/data.csv",
            }.get( key, default )
        mock_config.get.side_effect = cfg_get

        mock_proc = Mock()
        if processor_raises:
            mock_proc.process_template.side_effect = Exception( "proc boom" )
        else:
            mock_proc.process_template.side_effect = lambda tmpl, rc: tmpl

        with patch( "cosa.agents.agent_base.ConfigurationManager", return_value=mock_config ), \
             patch( "cosa.agents.agent_base.XmlParserFactory" ), \
             patch( "cosa.agents.agent_base.du.get_file_as_string", return_value=template ), \
             patch( "cosa.agents.agent_base.du.get_project_root", return_value="/root" ), \
             patch( "cosa.agents.io_models.utils.prompt_template_processor.PromptTemplateProcessor", return_value=mock_proc ), \
             patch( "cosa.agents.agent_base.pd.read_csv", return_value=pd.DataFrame( { "a": [ 1 ] } ) ), \
             patch( "cosa.agents.agent_base.dup.cast_to_datetime", side_effect=lambda df: df ), \
             patch( "cosa.agents.agent_base.TwoWordIdGenerator" ) as MockTwid, \
             patch( "cosa.agents.agent_base.ss.SolutionSnapshot" ) as MockSS:

            MockTwid.return_value.get_id.return_value     = "wise owl"
            MockSS.get_timestamp.return_value             = "2026-05-31-ts"
            MockSS.generate_id_hash.return_value          = "hash123"

            agent = _ConcreteAgent(
                df_path_key=df_path_key, question=question, last_question_asked=last_question_asked,
                routing_command=routing_command, debug=debug, verbose=verbose,
                auto_debug=auto_debug, inject_bugs=inject_bugs
            )

        agent.xml_response_tag_names = [ "thoughts", "code", "example", "returns", "explanation" ]
        return agent, mock_config

    # ------------------------------------------------------------------ #
    # __init__                                                            #
    # ------------------------------------------------------------------ #

    def test_init_question_only_with_df( self ):
        """
        Test construction from `question` only, with a df_path_key loading a DataFrame.

        Ensures:
            - last_question_asked defaults to question; question stored verbatim
            - df loaded; execution_state ends WAITING_TO_RUN; config-derived fields set
        """
        agent, _ = self._make_agent( df_path_key="path to math df", question="add 2 and 2" )

        self.assertEqual( agent.last_question_asked, "add 2 and 2" )
        self.assertEqual( agent.question, "add 2 and 2" )
        self.assertIsNotNone( agent.df )
        self.assertEqual( agent.execution_state, AgentBase.STATE_WAITING_TO_RUN )
        self.assertEqual( agent.model_name, "model_x" )
        self.assertEqual( agent.state.name, "PENDING" )

    def test_init_last_question_only_no_df( self ):
        """
        Test construction from `last_question_asked` only and no df.

        Ensures:
            - question defaults to last_question_asked; df stays None
        """
        agent, _ = self._make_agent( df_path_key=None, question="", last_question_asked="explain gravity" )

        self.assertEqual( agent.question, "explain gravity" )
        self.assertEqual( agent.last_question_asked, "explain gravity" )
        self.assertIsNone( agent.df )

    def test_init_both_empty_raises( self ):
        """
        Test construction raises when both question and last_question_asked are empty.

        Ensures:
            - ValueError is raised by the sanity guard
        """
        with self.assertRaises( ValueError ):
            self._make_agent( question="", last_question_asked="" )

    def test_init_template_processing_success_debug( self ):
        """
        Test the dynamic-XML template-processing success path (debug on).

        Ensures:
            - process_template result is stored; no exception
        """
        agent, _ = self._make_agent( debug=True )
        self.assertEqual( agent.prompt_template, "TMPL {" )

    def test_init_template_processing_failure_is_swallowed( self ):
        """
        Test a template-processing failure is caught and the original template kept.

        Ensures:
            - The except branch runs (debug on); construction still succeeds
        """
        agent, _ = self._make_agent( debug=True, processor_raises=True )
        self.assertEqual( agent.prompt_template, "TMPL {" )

    # ------------------------------------------------------------------ #
    # properties + simple methods                                         #
    # ------------------------------------------------------------------ #

    def test_init_template_processing_failure_no_debug( self ):
        """
        Test the template-processing failure path with debug off (no trace emitted).

        Ensures:
            - The except branch's debug-off arm runs; original template kept
        """
        agent, _ = self._make_agent( debug=False, processor_raises=True )
        self.assertEqual( agent.prompt_template, "TMPL {" )

    def test_job_type_and_created_date_properties( self ):
        """Test job_type returns the class name and created_date mirrors run_date."""
        agent, _ = self._make_agent()
        self.assertEqual( agent.job_type, "_ConcreteAgent" )
        self.assertEqual( agent.created_date, agent.run_date )

    def test_is_format_output_runnable_returns_false( self ):
        """Test the base is_format_output_runnable prints and returns False."""
        agent, _ = self._make_agent()
        self.assertFalse( agent.is_format_output_runnable() )

    def test_formatter_ran_to_completion( self ):
        """Test formatter-completion tracks answer_conversational presence."""
        agent, _ = self._make_agent()
        self.assertFalse( agent.formatter_ran_to_completion() )
        agent.answer_conversational = "x"
        self.assertTrue( agent.formatter_ran_to_completion() )

    def test_restore_abstract_stub_body( self ):
        """
        Test the abstract restore_from_serialized_state stub body is a no-op.

        Invokes the base class's bound abstract function directly (it is written
        without `self`), executing its `pass` body.
        """
        fn = AgentBase.__dict__[ "restore_from_serialized_state" ]
        self.assertIsNone( fn( "/some/path.json" ) )

    # ------------------------------------------------------------------ #
    # serialize_to_json                                                   #
    # ------------------------------------------------------------------ #

    def test_serialize_to_json_with_and_without_subtopic( self ):
        """
        Test serialize_to_json builds the path, writes JSON, and chmods (both subtopic arms).

        Ensures:
            - The topic (+optional subtopic) appears in the opened path
            - json.dump + os.chmod are invoked
        """
        agent, _ = self._make_agent()
        now = SimpleNamespace( year=2026, month=5, day=31, hour=10, minute=20, second=30 )

        for subtopic, marker in ( ( None, "math-topic-" ), ( "sub", "math-topic-sub-" ) ):
            with self.subTest( subtopic=subtopic ):
                m = mock_open()
                with patch( "cosa.agents.agent_base.du.get_project_root", return_value="/root" ), \
                     patch( "cosa.agents.agent_base.du.get_current_datetime_raw", return_value=now ), \
                     patch( "cosa.agents.agent_base.SolutionSnapshot.remove_non_alphanumerics", side_effect=lambda s: s ), \
                     patch( "cosa.agents.agent_base.open", m, create=True ), \
                     patch( "cosa.agents.agent_base.json.dump" ) as mock_dump, \
                     patch( "cosa.agents.agent_base.os.chmod" ) as mock_chmod:
                    agent.serialize_to_json( subtopic=subtopic )

                opened_path = m.call_args[0][0]
                self.assertIn( marker, opened_path )
                mock_dump.assert_called_once()
                mock_chmod.assert_called_once()

    # ------------------------------------------------------------------ #
    # _update_response_dictionary / run_prompt                            #
    # ------------------------------------------------------------------ #

    def test_update_response_dictionary_uses_factory( self ):
        """
        Test _update_response_dictionary delegates to the XML parser factory.

        Ensures (debug+verbose traces run):
            - parse_agent_response result is returned
        """
        agent, _ = self._make_agent( debug=True, verbose=True )
        agent.xml_parser_factory.parse_agent_response.return_value = { "answer": "4" }

        result = agent._update_response_dictionary( "<xml/>" )
        self.assertEqual( result, { "answer": "4" } )

    def test_run_prompt_without_raw_response( self ):
        """
        Test run_prompt runs the LLM, parses, and stores the response dict.

        Ensures:
            - prompt_response_dict is the parsed result; no raw-response keys added
        """
        agent, _ = self._make_agent( debug=True, verbose=True )
        agent.prompt = "PROMPT"
        agent.xml_parser_factory.parse_agent_response.return_value = { "code": [ "x" ] }

        with patch( "cosa.agents.agent_base.LlmClientFactory" ) as MockFactory:
            MockFactory.return_value.get_client.return_value.run.return_value = "<xml/>"
            result = agent.run_prompt()

        self.assertEqual( result, { "code": [ "x" ] } )
        self.assertNotIn( "xml_response", result )

    def test_run_prompt_with_raw_response( self ):
        """
        Test run_prompt appends the raw response + question when requested.

        Ensures:
            - xml_response and last_question_asked are added to the dict
        """
        agent, _ = self._make_agent()
        agent.prompt = "PROMPT"
        agent.xml_parser_factory.parse_agent_response.return_value = {}

        with patch( "cosa.agents.agent_base.LlmClientFactory" ) as MockFactory:
            MockFactory.return_value.get_client.return_value.run.return_value = "<raw/>"
            result = agent.run_prompt( include_raw_response=True )

        self.assertEqual( result[ "xml_response" ], "<raw/>" )
        self.assertIn( "last_question_asked", result )

    # ------------------------------------------------------------------ #
    # run_code                                                            #
    # ------------------------------------------------------------------ #

    def test_run_code_success_clears_error( self ):
        """
        Test run_code returns immediately and clears error on a clean run.

        Ensures:
            - return_code 0 → error None; the success path returns code_response_dict
            - df-path None branch taken
        """
        agent, _ = self._make_agent( df_path_key=None )

        with patch.object( RunnableCode, "run_code", _super_run_code( 0 ) ):
            result = agent.run_code()

        self.assertIsNone( agent.error )
        self.assertEqual( result[ "return_code" ], 0 )

    def test_run_code_failure_no_autodebug_falls_through( self ):
        """
        Test a failing run with auto_debug off falls through (returns None).

        Ensures:
            - return_code != 0 and auto_debug False → neither branch returns a dict
            - df-path branch (df_path_key set) is exercised
        """
        agent, _ = self._make_agent( df_path_key="path to math df", auto_debug=False )

        with patch.object( RunnableCode, "run_code", _super_run_code( 1 ) ):
            result = agent.run_code( auto_debug=False, inject_bugs=True )

        self.assertIsNone( result )

    def test_run_code_autodebug_success( self ):
        """
        Test auto-debug repairs failing code on the first (minimalist) attempt.

        Ensures:
            - A successful debug sets the corrected code + clears error and breaks
        """
        agent, _ = self._make_agent( auto_debug=True, debug=True )
        agent.prompt_response_dict = { "example": "e", "returns": "int" }
        agent.print_code = Mock()

        dbg = Mock()
        dbg.was_successfully_debugged.return_value = True
        dbg.code               = [ "fixed line" ]
        dbg.code_response_dict = { "return_code": 0, "output": "fixed" }

        with patch.object( RunnableCode, "run_code", _super_run_code( 1 ) ), \
             patch( "cosa.agents.iterative_debugging_agent.IterativeDebuggingAgent", return_value=dbg ):
            agent.run_code()

        self.assertIsNone( agent.error )
        self.assertEqual( agent.prompt_response_dict[ "code" ], [ "fixed line" ] )

    def test_run_code_autodebug_all_fail_raises( self ):
        """
        Test auto-debug failing on every model raises CodeGenerationFailedException.

        Ensures:
            - was_successfully_debugged False across both modes → final raise (debug on)
        """
        agent, _ = self._make_agent( auto_debug=True, debug=True )
        agent.prompt_response_dict = { "example": "e" }   # no 'returns' → .get default

        dbg = Mock()
        dbg.was_successfully_debugged.return_value = False

        with patch.object( RunnableCode, "run_code", _super_run_code( 1 ) ), \
             patch( "cosa.agents.iterative_debugging_agent.IterativeDebuggingAgent", return_value=dbg ):
            with self.assertRaises( CodeGenerationFailedException ):
                agent.run_code()

    def test_run_code_autodebug_crash_raises( self ):
        """
        Test an exception inside the debugging loop is logged then leads to the raise.

        Ensures:
            - IterativeDebuggingAgent raising is caught per-attempt (debug traceback)
            - With error still set, CodeGenerationFailedException is raised
        """
        agent, _ = self._make_agent( auto_debug=True, debug=True )
        agent.prompt_response_dict = { "example": "e", "returns": "str" }

        with patch.object( RunnableCode, "run_code", _super_run_code( 1 ) ), \
             patch( "cosa.agents.iterative_debugging_agent.IterativeDebuggingAgent",
                    side_effect=Exception( "debugger boom" ) ):
            with self.assertRaises( CodeGenerationFailedException ):
                agent.run_code()

    def test_run_code_autodebug_crash_no_debug_raises( self ):
        """
        Test the debugging-loop crash + final-raise with debug off (no traces).

        Ensures:
            - The except debug-off arm and the final-raise debug-off arm both run
            - CodeGenerationFailedException is still raised
        """
        agent, _ = self._make_agent( auto_debug=True, debug=False )
        agent.prompt_response_dict = { "example": "e", "returns": "str" }

        with patch.object( RunnableCode, "run_code", _super_run_code( 1 ) ), \
             patch( "cosa.agents.iterative_debugging_agent.IterativeDebuggingAgent",
                    side_effect=Exception( "debugger boom" ) ):
            with self.assertRaises( CodeGenerationFailedException ):
                agent.run_code()

    # ------------------------------------------------------------------ #
    # run_formatter / do_all                                              #
    # ------------------------------------------------------------------ #

    def test_run_formatter_delegates_to_raw_output_formatter( self ):
        """
        Test run_formatter builds a RawOutputFormatter and stores its result.

        Ensures:
            - answer_conversational is set from the formatter and returned
        """
        agent, _ = self._make_agent()
        agent.code_response_dict = { "output": "42" }

        mock_fmt = Mock()
        mock_fmt.run_formatter.return_value = "The answer is 42"
        with patch( "cosa.agents.agent_base.RawOutputFormatter", return_value=mock_fmt ):
            result = agent.run_formatter()

        self.assertEqual( result, "The answer is 42" )
        self.assertEqual( agent.answer_conversational, "The answer is 42" )

    def test_do_all_runs_full_pipeline( self ):
        """
        Test do_all runs prompt → code → formatter and returns the conversational answer.

        Ensures:
            - All three stages invoked; the final answer_conversational is returned
        """
        agent, _ = self._make_agent()
        agent.run_prompt    = Mock()
        agent.run_code      = Mock()
        agent.run_formatter = Mock( side_effect=lambda: setattr( agent, "answer_conversational", "final answer" ) )

        result = agent.do_all()

        self.assertEqual( result, "final answer" )
        agent.run_prompt.assert_called_once()
        agent.run_code.assert_called_once()
        agent.run_formatter.assert_called_once()


if __name__ == "__main__":
    unittest.main()
