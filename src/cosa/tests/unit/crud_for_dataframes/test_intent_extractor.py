"""
Unit tests for cosa.crud_for_dataframes.intent_extractor.

The Claude Code headless fallback for CRUD intent extraction. build_claude_prompt
is a pure string builder (tested with and without available lists);
extract_intent_via_claude_code shells out to `claude -p`, so subprocess.run is
mocked to drive every exit path: success, non-zero return code, empty stdout,
timeout, and a parse failure caught by the catch-all.

Assertions harvested + extended from the module's quick_smoke_test(), marked
for deletion once this replacement is green.

Created 2026-06-03 (CoSA coverage campaign — Cheech 🌿). New file.
"""

import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cosa.crud_for_dataframes.intent_extractor import (
    build_claude_prompt,
    extract_intent_via_claude_code,
)


class TestBuildClaudePrompt( unittest.TestCase ):
    """
    build_claude_prompt — query + lists embedding, empty-list fallback.
    """

    def test_includes_query_lists_and_xml_example( self ):
        """Ensures the prompt embeds the query, the lists text, and the <intent> example."""
        prompt = build_claude_prompt( "add buy milk to my groceries list", "- groceries (todo, 3 items)" )
        self.assertIn( "add buy milk", prompt )
        self.assertIn( "groceries", prompt )
        self.assertIn( "<intent>", prompt )
        self.assertIn( "Available operations:", prompt )

    def test_empty_lists_fallback_text( self ):
        """Ensures an empty lists string renders the '(no lists yet)' placeholder."""
        prompt = build_claude_prompt( "create a new grocery list", "" )
        self.assertIn( "(no lists yet)", prompt )


class TestExtractIntentViaClaudeCode( unittest.TestCase ):
    """
    extract_intent_via_claude_code — all subprocess exit paths.
    """

    _VALID_XML = "<intent><operation>add</operation><target_list>groceries</target_list></intent>"

    def test_success_returns_parsed_intent( self ):
        """Ensures a clean claude -p run yields a parsed CRUDIntent."""
        completed = SimpleNamespace( returncode=0, stdout=self._VALID_XML )
        with patch( "cosa.crud_for_dataframes.intent_extractor.subprocess.run", return_value=completed ):
            intent = extract_intent_via_claude_code( "add milk", "- groceries", debug=True )
        self.assertIsNotNone( intent )
        self.assertEqual( intent.operation, "add" )
        self.assertEqual( intent.target_list, "groceries" )

    def test_nonzero_return_code_yields_none( self ):
        """Ensures a non-zero claude -p exit code yields None."""
        completed = SimpleNamespace( returncode=1, stdout="" )
        with patch( "cosa.crud_for_dataframes.intent_extractor.subprocess.run", return_value=completed ):
            self.assertIsNone( extract_intent_via_claude_code( "add milk", "", debug=True ) )

    def test_empty_stdout_yields_none( self ):
        """Ensures an empty stdout (returncode 0) yields None."""
        completed = SimpleNamespace( returncode=0, stdout="   " )
        with patch( "cosa.crud_for_dataframes.intent_extractor.subprocess.run", return_value=completed ):
            self.assertIsNone( extract_intent_via_claude_code( "add milk", "", debug=True ) )

    def test_timeout_yields_none( self ):
        """Ensures a subprocess timeout is caught and yields None."""
        with patch(
            "cosa.crud_for_dataframes.intent_extractor.subprocess.run",
            side_effect=subprocess.TimeoutExpired( cmd="claude", timeout=30 )
        ):
            self.assertIsNone( extract_intent_via_claude_code( "add milk", "", debug=True ) )

    def test_unparseable_response_yields_none( self ):
        """Ensures a response with no <intent> block is caught by the catch-all → None."""
        completed = SimpleNamespace( returncode=0, stdout="I could not understand that." )
        with patch( "cosa.crud_for_dataframes.intent_extractor.subprocess.run", return_value=completed ):
            self.assertIsNone( extract_intent_via_claude_code( "add milk", "", debug=True ) )

    def test_unparseable_response_no_debug( self ):
        """Ensures the catch-all path also works with debug disabled (branch parity)."""
        completed = SimpleNamespace( returncode=0, stdout="garbage" )
        with patch( "cosa.crud_for_dataframes.intent_extractor.subprocess.run", return_value=completed ):
            self.assertIsNone( extract_intent_via_claude_code( "add milk", "", debug=False ) )


if __name__ == "__main__":
    unittest.main()
