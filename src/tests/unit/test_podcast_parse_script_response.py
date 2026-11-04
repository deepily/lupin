#!/usr/bin/env python3
"""
Unit tests for `parse_script_response`.

An unparseable script raises a ValueError that names the saved raw-response file.
"""

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cosa.agents.podcast_generator.prompts.script_generation import parse_script_response


class TestParseScriptResponse( unittest.TestCase ):

    def setUp( self ):
        self.tmp = tempfile.TemporaryDirectory()
        patcher  = patch( "cosa.utils.util.get_project_root", return_value=self.tmp.name )
        patcher.start()
        self.addCleanup( patcher.stop )
        self.addCleanup( self.tmp.cleanup )

    def test_valid_script_gets_default_title_and_segments( self ):
        self.assertEqual(
            parse_script_response( '{"key_topics": []}' ),
            { "key_topics": [], "segments": [], "title": "Untitled Podcast" }
        )

    def test_valid_script_keeps_its_own_title_and_segments( self ):
        parsed = parse_script_response( '{"title": "T", "segments": [{"speaker": "A"}]}' )
        self.assertEqual( parsed[ "title" ], "T" )
        self.assertEqual( len( parsed[ "segments" ] ), 1 )

    def test_unparseable_script_raises_naming_the_saved_file( self ):
        raw = "not json " * 1000
        with self.assertLogs( "cosa.agents.io_models.utils.json_object_recovery", level="ERROR" ):
            with self.assertRaises( ValueError ) as ctx:
                parse_script_response( raw, label="podcast-1234abcd" )
        message = str( ctx.exception )
        self.assertIn( "no recoverable JSON object", message )
        path = message.split( "Raw response saved to: " )[ 1 ]
        self.assertTrue( path.endswith( "-podcast-1234abcd.txt" ) )
        self.assertEqual( Path( path ).read_text(), raw )

    def test_non_object_json_also_raises( self ):
        # A JSON list parses, so nothing was dumped and the message says so.
        with self.assertRaises( ValueError ) as ctx:
            parse_script_response( "[1, 2]" )
        self.assertIn( "Raw response saved to: None", str( ctx.exception ) )


if __name__ == "__main__":
    logging.basicConfig( level=logging.ERROR )
    unittest.main()
