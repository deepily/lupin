"""
Unit tests for cosa.agents.confirmation_dialog.ConfirmationDialogue.

ConfirmationDialogue is a standalone (non-AgentBase) yes/no classifier. These tests
mock its boundaries — ConfigurationManager, LlmClientFactory, YesNoResponse, and the
du file helpers — so no config / LLM / file I/O occurs:

- __init__   — config_mgr provided vs created, model_name from arg vs config, debug
               trace, prompt-template load
- confirmed  — prompt build + LLM call + Pydantic parse, then yes/no/default/ambiguous
               classification, plus the XMLParsingError and generic-exception → ValueError
               fallbacks

Created 2026-05-31 (CoSA coverage campaign, user-facing agents lane — Tiffany 💍). New file.
"""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from cosa.agents.confirmation_dialog import ConfirmationDialogue
from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError


class TestConfirmationDialogue( unittest.TestCase ):
    """
    Comprehensive unit tests for ConfirmationDialogue.

    Ensures:
        - Construction resolves config + model + template per contract
        - confirmed() classifies yes/no/default/ambiguous and degrades parse errors
    """

    def _make_dialog( self, debug=False, verbose=False ):
        """
        Build a ConfirmationDialogue with config + du file helpers mocked.

        Returns a dialog whose prompt_template is "ANSWER {utterance}" and whose
        model_name comes from the mocked config.
        """
        mock_config = Mock()
        mock_config.get.side_effect = lambda key, default=None: {
            "llm spec key for confirmation dialog"      : "model_x",
            "prompt template for confirmation dialog"   : "/tmpl/confirm.txt",
        }.get( key, default )

        with patch( "cosa.agents.confirmation_dialog.ConfigurationManager", return_value=mock_config ), \
             patch( "cosa.agents.confirmation_dialog.du.get_file_as_string", return_value="ANSWER {utterance}" ), \
             patch( "cosa.agents.confirmation_dialog.du.get_project_root", return_value="/root" ):
            dialog = ConfirmationDialogue( debug=debug, verbose=verbose )

        return dialog

    def _run_confirmed( self, dialog, answer=None, from_xml_exc=None, default=None,
                        utterance="shall we proceed?" ):
        """
        Invoke dialog.confirmed() with the LLM + YesNoResponse boundaries mocked.

        Args:
            answer       : the parsed YesNoResponse.answer (when no exception)
            from_xml_exc : exception instance to raise from YesNoResponse.from_xml
            default      : default forwarded to confirmed()
        """
        with patch( "cosa.agents.confirmation_dialog.LlmClientFactory" ) as MockFactory, \
             patch( "cosa.agents.confirmation_dialog.YesNoResponse" ) as MockYN:
            MockFactory.return_value.get_client.return_value.run.return_value = "<response/>"
            if from_xml_exc is not None:
                MockYN.from_xml.side_effect = from_xml_exc
            else:
                MockYN.from_xml.return_value.answer = answer
            return dialog.confirmed( utterance, default=default )

    # ------------------------------------------------------------------ #
    # __init__                                                            #
    # ------------------------------------------------------------------ #

    def test_init_creates_config_and_loads_template_with_debug( self ):
        """
        Test construction defaults: builds a config, reads the model + template.

        Ensures:
            - model_name is taken from config when not provided
            - prompt_template is loaded; debug trace emitted
        """
        buf = io.StringIO()
        with redirect_stdout( buf ):
            dialog = self._make_dialog( debug=True )

        self.assertEqual( dialog.model_name, "model_x" )
        self.assertEqual( dialog.prompt_template, "ANSWER {utterance}" )
        self.assertIsNone( dialog.prompt )
        self.assertIn( "Pydantic XML parsing", buf.getvalue() )

    def test_init_uses_provided_config_and_model( self ):
        """
        Test construction honors an explicit config_mgr and model_name.

        Ensures:
            - The provided config object is reused (not recreated)
            - The explicit model_name is kept (no config lookup for it)
        """
        provided = Mock()
        provided.get.return_value = "/tmpl/confirm.txt"

        with patch( "cosa.agents.confirmation_dialog.ConfigurationManager" ) as MockCfg, \
             patch( "cosa.agents.confirmation_dialog.du.get_file_as_string", return_value="ANSWER {utterance}" ), \
             patch( "cosa.agents.confirmation_dialog.du.get_project_root", return_value="/root" ):
            dialog = ConfirmationDialogue( model_name="explicit-model", config_mgr=provided )

        self.assertIs( dialog.config_mgr, provided )
        self.assertEqual( dialog.model_name, "explicit-model" )
        MockCfg.assert_not_called()

    # ------------------------------------------------------------------ #
    # confirmed                                                           #
    # ------------------------------------------------------------------ #

    def test_confirmed_yes_returns_true( self ):
        """
        Test an affirmative parse yields True (and the debug+verbose trace runs).

        Ensures:
            - answer 'Yes' → True; prompt is formatted with the utterance
        """
        dialog = self._make_dialog( debug=True, verbose=True )
        result = self._run_confirmed( dialog, answer="Yes" )

        self.assertTrue( result )
        self.assertEqual( dialog.prompt, "ANSWER shall we proceed?" )

    def test_confirmed_no_returns_false( self ):
        """
        Test a negative parse yields False.

        Ensures:
            - answer 'No' → False
        """
        dialog = self._make_dialog()
        self.assertFalse( self._run_confirmed( dialog, answer="No" ) )

    def test_confirmed_ambiguous_with_default_returns_default( self ):
        """
        Test an ambiguous parse returns the supplied default.

        Ensures:
            - A non-yes/no answer with default=True → True
        """
        dialog = self._make_dialog()
        self.assertTrue( self._run_confirmed( dialog, answer="maybe", default=True ) )

    def test_confirmed_ambiguous_without_default_raises( self ):
        """
        Test an ambiguous parse with no default raises ValueError.

        Ensures:
            - A non-yes/no answer and default=None → ValueError
        """
        dialog = self._make_dialog()
        with self.assertRaises( ValueError ):
            self._run_confirmed( dialog, answer="perhaps", default=None )

    def test_confirmed_xml_parsing_error_raises_value_error( self ):
        """
        Test an XMLParsingError during parse is converted to ValueError.

        Ensures:
            - YesNoResponse.from_xml raising XMLParsingError → ValueError (debug trace)
        """
        dialog = self._make_dialog( debug=True )
        with self.assertRaises( ValueError ):
            self._run_confirmed( dialog, from_xml_exc=XMLParsingError( "bad xml" ) )

    def test_confirmed_generic_exception_raises_value_error( self ):
        """
        Test an unexpected error during parse is converted to ValueError.

        Ensures:
            - YesNoResponse.from_xml raising a generic error → ValueError (debug trace)
        """
        dialog = self._make_dialog( debug=True )
        with self.assertRaises( ValueError ):
            self._run_confirmed( dialog, from_xml_exc=RuntimeError( "boom" ) )


if __name__ == "__main__":
    unittest.main()
