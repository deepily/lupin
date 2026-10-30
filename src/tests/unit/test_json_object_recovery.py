#!/usr/bin/env python3
"""
Unit tests for the shared JSON-object recovery helper
`cosa.agents.io_models.utils.json_object_recovery` (P0 4317efd1 de-dup).

Full branch coverage of both `extract_json_object` (last-balanced recovery,
unchanged) and `recover_json_object` (fence-preference + loud-None logging).
"""

import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cosa.agents.io_models.utils.json_object_recovery import (
    extract_json_object,
    recover_json_object,
    save_raw_response,
)

_FIXTURE_DIR = Path( __file__ ).parent / "fixtures"

_ROOT_PATCH = "cosa.utils.util.get_project_root"


def setUpModule():
    """Point every failure dump at a temp root so the suite never writes into the real io/."""
    global _TMP, _PATCHER
    _TMP     = tempfile.TemporaryDirectory()
    _PATCHER = patch( _ROOT_PATCH, return_value=_TMP.name )
    _PATCHER.start()


def tearDownModule():
    _PATCHER.stop()
    _TMP.cleanup()


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


class TestBareQuotesInBreakTags( unittest.TestCase ):
    """A break tag copied with bare quotes inside a JSON string."""

    BARE = '{"text": "Wait. <break time="1.5s"/> Now. <break time="1.0s"/> Go."}'

    def test_bare_quotes_in_a_break_tag_are_recovered( self ):
        self.assertEqual( recover_json_object( self.BARE ), { "text": 'Wait. <break time="1.5s"/> Now. <break time="1.0s"/> Go.' } )

    def test_escaped_quotes_are_left_alone( self ):
        escaped = '{"text": "Wait. <break time=\\"1.5s\\"/> Go."}'
        self.assertEqual( recover_json_object( escaped ), { "text": 'Wait. <break time="1.5s"/> Go.' } )

    def test_other_corruption_still_fails_loudly( self ):
        self.assertIsNone( recover_json_object( '{"text": "Wait. <break time="1.5s"/> Go." "next": }' ) )

    def test_an_unrelated_bare_quote_is_not_guessed_at( self ):
        self.assertIsNone( recover_json_object( '{"text": "He said "hello" to me."}' ) )


class TestWhitespaceGatedRecovery( unittest.TestCase ):
    """
    Regression for bug e0bb5a94 defect A: a bounded-CC podcast script completion
    in which the model emitted a LITERAL newline (0x0a) inside a "text" dialogue
    string value. Strict `json.loads` rejects it ("Invalid control character");
    the whole script then read as "no recoverable JSON object" and the user saw
    "please try again in a few minutes".

    The fix relaxes `strict` ONLY when the sole control chars present are benign
    whitespace (\\n \\r \\t) — never structure, never any other control char — so
    a completion that is well-formed apart from an unescaped newline is recovered,
    while genuinely-corrupt output still fails loudly.
    """

    def test_real_captured_body_exhibits_the_newline_defect( self ):
        """
        Reality anchor — REAL model bytes, not synthetic. The committed fixture is
        the visible head of the actual failing completion (run bdv6onuqm, captured
        via recover_json_object's ERROR log). It must trip the exact strict error
        the bug filed, and its ONLY control char must be whitespace — the premise
        the whitespace gate relies on. No fix involved; this characterizes the
        input so the repair test below is anchored to something that really
        happened. Full provenance: row e0bb5a94.
        """
        head = ( _FIXTURE_DIR / "e0bb5a94-newline-in-string-real-head.txt" ).read_text( encoding="utf-8" )
        with self.assertRaises( json.JSONDecodeError ) as ctx:
            json.loads( head )
        self.assertIn( "Invalid control character", str( ctx.exception ) )
        control_chars = { c for c in head if ord( c ) < 0x20 }
        self.assertTrue( control_chars <= set( "\n\r\t" ) )   # whitespace-only premise holds
        self.assertIn( "\n", control_chars )                  # the offending newline is present

    def test_recover_repairs_unescaped_newline_in_string_value( self ):
        """
        The repair. A COMPLETE object whose only defect is an unescaped newline in
        a "text" value — the exact shape observed on real output above. Strict
        parsing fails; the gate recognizes the sole control char is whitespace,
        retries strict=False, recovers the object, and logs at WARNING naming the
        repaired char. RED before the fix (recover returned None → the script read
        as unrecoverable), GREEN after.
        """
        body = (
            '{"segments": [{"speaker": "Mr. Radio", "role": "expert", '
            '"text": "So methodologically: pre-post observational,\n'
            'no control condition, no randomization."}], '
            '"title": "T", "estimated_duration_minutes": 10}'
        )
        with self.assertLogs(
            "cosa.agents.io_models.utils.json_object_recovery", level="WARNING"
        ) as cm:
            out = recover_json_object( body )
        self.assertIsInstance( out, dict )
        self.assertEqual( out[ "title" ], "T" )
        self.assertEqual( len( out[ "segments" ] ), 1 )
        self.assertIn( "\n", out[ "segments" ][ 0 ][ "text" ] )   # the newline is preserved, not stripped
        self.assertTrue( any( "unescaped whitespace" in line for line in cm.output ) )

    def test_recover_stays_loud_on_non_whitespace_control_char( self ):
        """
        Gate discrimination — the anti-over-recovery guard. A NUL (0x00) inside a
        string is NOT benign whitespace: the gate must refuse to relax, so recovery
        stays None and logs the loud ERROR. Widening the gate to swallow this would
        be defect B's disease (a loud failure traded for a silent wrong answer).
        Exercises the `if offending: raise` arm.
        """
        body = '{"text": "a\x00b"}'   # NUL control char inside the string value
        with self.assertLogs(
            "cosa.agents.io_models.utils.json_object_recovery", level="ERROR"
        ) as cm:
            self.assertIsNone( recover_json_object( body ) )
        self.assertTrue( any( "unrecoverable JSON" in line for line in cm.output ) )

    def test_recover_stays_loud_on_structural_error_with_only_whitespace( self ):
        """
        The gate relaxes whitespace, NOT structure. A body with only benign
        whitespace control chars but a genuine structural fault (a trailing comma)
        must still fail: strict=False does not repair structure, so recovery stays
        None. Exercises the `offending`-empty arm where the strict=False retry
        itself raises.
        """
        body = '{"a": 1,\n"b": 2,}'   # trailing comma → structural; only \n as control char
        with self.assertLogs(
            "cosa.agents.io_models.utils.json_object_recovery", level="ERROR"
        ):
            self.assertIsNone( recover_json_object( body ) )


class TestRawResponseDump( unittest.TestCase ):
    """An unrecoverable response is saved in full; the path is logged and returned."""

    LOGGER = "cosa.agents.io_models.utils.json_object_recovery"

    def test_failure_saves_the_full_body_and_reports_the_path( self ):
        big  = "y" * 9000
        info = {}
        with self.assertLogs( self.LOGGER, level="ERROR" ) as cm:
            self.assertIsNone( recover_json_object( big, label="podcast-abc", dump_info=info ) )
        path = info[ "path" ]
        self.assertTrue( path.startswith( f"{_TMP.name}/io/json-recovery-failures/" ) )
        self.assertTrue( path.endswith( "-podcast-abc.txt" ) )
        self.assertEqual( Path( path ).read_text(), big )     # all 9000 chars, not the bounded 4000
        self.assertTrue( any( path in line for line in cm.output ) )

    def test_recovered_body_writes_nothing( self ):
        info = {}
        self.assertEqual( recover_json_object( '{"a": 1}', dump_info=info ), { "a": 1 } )
        self.assertEqual( info, {} )

    def test_dump_info_is_optional( self ):
        with self.assertLogs( self.LOGGER, level="ERROR" ):
            self.assertIsNone( recover_json_object( "no json", label="x" ) )

    def test_no_label_means_no_file( self ):
        info = {}
        with tempfile.TemporaryDirectory() as fresh, patch( _ROOT_PATCH, return_value=fresh ):
            with self.assertLogs( self.LOGGER, level="ERROR" ):
                self.assertIsNone( recover_json_object( "no json", dump_info=info ) )
            self.assertEqual( os.listdir( fresh ), [] )        # not even the io/ directory was made
        self.assertEqual( info, {} )

    def test_label_is_made_filename_safe( self ):
        path = save_raw_response( "body", "a/b c" )
        self.assertTrue( path.endswith( "-a-b-c.txt" ) )

    def test_unwritable_target_returns_none_and_logs( self ):
        with patch( "os.makedirs", side_effect=OSError( "disk full" ) ):
            with self.assertLogs( self.LOGGER, level="ERROR" ) as cm:
                self.assertIsNone( save_raw_response( "body", "x" ) )
        self.assertTrue( any( "disk full" in line for line in cm.output ) )

    def test_unwritable_target_still_returns_none_from_recover_and_reports_none( self ):
        info = {}
        with patch( "os.makedirs", side_effect=OSError( "disk full" ) ):
            with self.assertLogs( self.LOGGER, level="ERROR" ):
                self.assertIsNone( recover_json_object( "no json", label="x", dump_info=info ) )
        self.assertIsNone( info[ "path" ] )


if __name__ == "__main__":
    logging.basicConfig( level=logging.ERROR )
    unittest.main()
