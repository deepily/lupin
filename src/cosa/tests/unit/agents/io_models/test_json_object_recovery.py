#!/usr/bin/env python3
"""
Unit tests for the shared JSON-object recovery helper
`cosa.agents.io_models.utils.json_object_recovery` (P0 4317efd1 de-dup).

Full branch coverage of both `extract_json_object` (last-balanced recovery,
unchanged) and `recover_json_object` (fence-preference + loud-None logging).
"""

import logging
import unittest

from cosa.agents.io_models.utils.json_object_recovery import (
    extract_json_object,
    recover_json_object,
)


class TestExtractJsonObject( unittest.TestCase ):

    def test_clean_object( self ):
        self.assertEqual( extract_json_object( '{"a": 1}' ), '{"a": 1}' )

    def test_embedded_in_prose_returns_last( self ):
        self.assertEqual( extract_json_object( 'Here: {"a": 1} cheers' ), '{"a": 1}' )

    def test_nested_braces_returns_outermost( self ):
        # Inner `{` decrements depth to 1 (not 0) so the walk continues to the
        # true outer opening brace.
        self.assertEqual( extract_json_object( 'x {"a": {"b": 2}} y' ), '{"a": {"b": 2}}' )

    def test_no_closing_brace_returns_none( self ):
        self.assertIsNone( extract_json_object( "no braces at all" ) )

    def test_dangling_close_without_open_returns_none( self ):
        # `}` present but no balancing `{` → loop exhausts → None.
        self.assertIsNone( extract_json_object( "dangling } brace" ) )


class TestRecoverJsonObject( unittest.TestCase ):

    def test_direct_object( self ):
        self.assertEqual( recover_json_object( '{"a": 1}' ), { "a": 1 } )

    def test_fenced_json_with_newline( self ):
        self.assertEqual( recover_json_object( '```json\n{"a": 1}\n```' ), { "a": 1 } )

    def test_bare_fence_with_newline( self ):
        self.assertEqual( recover_json_object( '```\n{"b": 2}\n```' ), { "b": 2 } )

    def test_fence_preference_drops_trailing_prose( self ):
        # P0 4317efd1: prose AFTER the closing fence — containing a brace — must
        # NOT defeat recovery. Before the fix this returned None (empty podcast).
        resp = (
            '```json\n{"title": "T", "segments": [{"speaker": "A"}]}\n```\n\n'
            '### Explanation:\nEach segment is a `{speaker, role, text}` object.\n'
        )
        out = recover_json_object( resp )
        self.assertEqual( out[ "title" ], "T" )
        self.assertEqual( len( out[ "segments" ] ), 1 )

    def test_fence_without_newline_strips_marker( self ):
        # No newline after the opening fence → the `content[3:]` branch.
        self.assertEqual( recover_json_object( '```{"c": 3}```' ), { "c": 3 } )

    def test_fence_without_closing_fence( self ):
        # Opening fence, no closing fence → the `closing == -1` branch.
        self.assertEqual( recover_json_object( '```json\n{"d": 4}' ), { "d": 4 } )

    def test_prose_recovery_via_extract( self ):
        # No fence; direct parse fails; extract recovers the object.
        self.assertEqual( recover_json_object( 'Sure! {"e": 5} done.' ), { "e": 5 } )

    def test_extracted_but_invalid_returns_none_and_logs( self ):
        # extract returns "{not valid}" → second json.loads fails → None + LOUD log.
        with self.assertLogs(
            "cosa.agents.io_models.utils.json_object_recovery", level="ERROR"
        ) as cm:
            self.assertIsNone( recover_json_object( "prefix {not valid json} suffix" ) )
        self.assertTrue( any( "unrecoverable JSON" in line for line in cm.output ) )
        self.assertTrue( any( "prefix {not valid json} suffix" in line for line in cm.output ) )

    def test_no_json_returns_none_and_logs_raw_body( self ):
        with self.assertLogs(
            "cosa.agents.io_models.utils.json_object_recovery", level="ERROR"
        ) as cm:
            self.assertIsNone( recover_json_object( "absolutely no json here" ) )
        # The raw body is captured verbatim so the malformed completion is never lost.
        self.assertTrue( any( "absolutely no json here" in line for line in cm.output ) )

    def test_long_unrecoverable_body_is_bounded_in_log( self ):
        # A multi-thousand-token completion must not flood the log: the raw body is
        # bounded head+tail, and the total length + omitted count are reported.
        big = "x" * 9000   # no JSON object; exceeds the 4000-char cap
        with self.assertLogs(
            "cosa.agents.io_models.utils.json_object_recovery", level="ERROR"
        ) as cm:
            self.assertIsNone( recover_json_object( big ) )
        joined = "\n".join( cm.output )
        self.assertIn( "9000 chars", joined )          # full length reported
        self.assertIn( "5000 chars omitted", joined )  # 9000 - 4000 cap
        self.assertNotIn( "x" * 5000, joined )         # the middle is not logged


if __name__ == "__main__":
    logging.basicConfig( level=logging.ERROR )
    unittest.main()
