"""
Unit tests for cosa.agents.raw_output_formatter.RawOutputFormatter.

Exercises the formatter against its CURRENT production contract:

- __init__        — thoughts/code XML-wrapping (present vs empty), XML-declaration
                    stripping, config-driven template + LLM-spec lookups, prompt build
- run_formatter   — LLM invocation, factory XML parse → rephrased-answer extraction,
                    and the debug+verbose prompt/response/parsed trace prints
- _get_prompt     — the routing-command fork (receptionist/math include thoughts+code;
                    everything else uses question+raw_output only)

Zero external dependencies — ConfigurationManager, LlmClientFactory, XmlParserFactory,
and the du file helpers are mocked at the boundary. No network / LLM / file I/O.
Debug-trace tests capture stdout and assert on the emitted content (agents standard).

Created 2026-05-31 (CoSA coverage campaign, agents lane — Tiffany 💍). New file.
"""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from cosa.agents.raw_output_formatter import RawOutputFormatter


class TestRawOutputFormatter( unittest.TestCase ):
    """
    Comprehensive unit tests for RawOutputFormatter.

    Ensures:
        - Construction wires thoughts/code/raw_output + template + LLM client
        - run_formatter returns the parsed rephrased-answer and traces under debug
        - _get_prompt forks correctly on the routing command
    """

    def _make_formatter( self, routing_command="agent router go to weather", thoughts="",
                         code="", raw_output="raw answer", template=None,
                         parsed=None, response="<response>x</response>",
                         debug=False, verbose=False ):
        """
        Construct a RawOutputFormatter with the full dependency chain mocked.

        Args:
            routing_command : drives the config keys + the _get_prompt fork
            thoughts / code : optional context fragments (XML-wrapped when non-empty)
            raw_output      : raw text to rephrase
            template        : format string; auto-selected to match the routing fork
                              (4-placeholder for receptionist/math, else 2-placeholder)
            parsed          : dict returned by the mocked XML parser
            response        : raw LLM response string
            debug / verbose : forwarded to the constructor

        Returns:
            Tuple of (formatter, mocks_dict).
        """
        if template is None:
            if routing_command in [ "agent router go to receptionist", "agent router go to math" ]:
                template = "Q={question} R={raw_output} T={thoughts} C={code}"
            else:
                template = "Q={question} R={raw_output}"

        mock_config = Mock()
        mock_config.get.side_effect = lambda key, default=None: (
            "/tmpl/path.txt" if key.startswith( "formatter template" ) else "model_spec_x"
        )

        mock_llm     = Mock()
        mock_llm.run.return_value = response
        mock_factory = Mock()
        mock_factory.get_client.return_value = mock_llm

        mock_parser  = Mock()
        mock_parser.parse_agent_response.return_value = parsed if parsed is not None else { "rephrased_answer": "REPHRASED" }
        mock_xml_factory = Mock( return_value=mock_parser )

        with patch( "cosa.agents.raw_output_formatter.ConfigurationManager", return_value=mock_config ), \
             patch( "cosa.agents.raw_output_formatter.LlmClientFactory", return_value=mock_factory ), \
             patch( "cosa.agents.raw_output_formatter.XmlParserFactory", mock_xml_factory ), \
             patch( "cosa.agents.raw_output_formatter.du.get_file_as_string", return_value=template ), \
             patch( "cosa.agents.raw_output_formatter.du.get_project_root", return_value="/root" ):

            formatter = RawOutputFormatter(
                question="What is it?",
                raw_output=raw_output,
                routing_command=routing_command,
                thoughts=thoughts,
                code=code,
                debug=debug,
                verbose=verbose,
            )

        mocks = {
            "config" : mock_config,
            "llm"    : mock_llm,
            "factory": mock_factory,
            "parser" : mock_parser,
        }
        return formatter, mocks

    # ------------------------------------------------------------------ #
    # __init__ / _get_prompt                                              #
    # ------------------------------------------------------------------ #

    def test_init_wraps_thoughts_and_code_for_receptionist( self ):
        """
        Test thoughts/code are XML-wrapped and folded into the prompt for receptionist.

        Ensures:
            - Non-empty thoughts/code wrapped in <thoughts>/<code> tags
            - The receptionist/math fork includes them in the formatted prompt
        """
        f, _ = self._make_formatter(
            routing_command="agent router go to receptionist",
            thoughts="my reasoning", code="print( 1 )"
        )

        self.assertEqual( f.thoughts, "<thoughts>my reasoning</thoughts>" )
        self.assertEqual( f.code, "<code>print( 1 )</code>" )
        self.assertIn( "<thoughts>my reasoning</thoughts>", f.prompt )
        self.assertIn( "<code>print( 1 )</code>", f.prompt )

    def test_init_empty_thoughts_and_code_for_other_routing( self ):
        """
        Test empty thoughts/code stay empty and the non-receptionist fork is used.

        Ensures:
            - Empty thoughts/code remain empty strings (no XML wrapping)
            - The else-branch prompt is built from question + raw_output only
        """
        f, _ = self._make_formatter( routing_command="agent router go to weather" )

        self.assertEqual( f.thoughts, "" )
        self.assertEqual( f.code, "" )
        self.assertEqual( f.prompt, "Q=What is it? R=raw answer" )

    def test_init_strips_xml_declaration_from_raw_output( self ):
        """
        Test the XML declaration is stripped from raw_output during construction.

        Ensures:
            - A leading <?xml ...?> declaration is removed from stored raw_output
        """
        f, _ = self._make_formatter(
            raw_output="<?xml version='1.0' encoding='utf-8'?>actual content"
        )

        self.assertEqual( f.raw_output, "actual content" )

    def test_get_prompt_math_branch_includes_context( self ):
        """
        Test the math routing also takes the thoughts/code-including fork.

        Ensures:
            - 'agent router go to math' formats with thoughts + code placeholders
        """
        f, _ = self._make_formatter(
            routing_command="agent router go to math",
            thoughts="t", code="c"
        )

        self.assertIn( "T=<thoughts>t</thoughts>", f.prompt )
        self.assertIn( "C=<code>c</code>", f.prompt )

    # ------------------------------------------------------------------ #
    # run_formatter                                                       #
    # ------------------------------------------------------------------ #

    def test_run_formatter_returns_parsed_rephrased_answer( self ):
        """
        Test run_formatter returns the parser's rephrased_answer field.

        Ensures:
            - The LLM is invoked with the built prompt
            - The factory parser is called for the rephrased-answer tag
            - The parsed rephrased_answer is returned
        """
        f, mocks = self._make_formatter( parsed={ "rephrased_answer": "Hello there!" } )

        result = f.run_formatter()

        self.assertEqual( result, "Hello there!" )
        mocks["llm"].run.assert_called_once_with( f.prompt )
        mocks["parser"].parse_agent_response.assert_called_once()

    def test_run_formatter_missing_field_defaults_empty( self ):
        """
        Test run_formatter defaults to an empty string when the field is absent.

        Ensures:
            - A parser result lacking 'rephrased_answer' yields ""
        """
        f, _ = self._make_formatter( parsed={} )

        self.assertEqual( f.run_formatter(), "" )

    def test_run_formatter_debug_verbose_traces_stdout( self ):
        """
        Test run_formatter emits prompt/response/parsed traces under debug+verbose.

        Ensures (capturing stdout — agents standard):
            - The built prompt is printed
            - The raw LLM response is printed
            - The parsed output is echoed
        """
        f, _ = self._make_formatter(
            parsed={ "rephrased_answer": "FINAL" },
            response="<response>FINAL</response>",
            debug=True, verbose=True,
        )

        buf = io.StringIO()
        with redirect_stdout( buf ):
            result = f.run_formatter()
        out = buf.getvalue()

        self.assertEqual( result, "FINAL" )
        self.assertIn( f.prompt, out )                       # FORMATTER LLM PROMPT block
        self.assertIn( "<response>FINAL</response>", out )    # FORMATTER LLM RAW RESPONSE block
        self.assertIn( "FINAL", out )                         # parsed-via-Pydantic echo


if __name__ == "__main__":
    unittest.main()
