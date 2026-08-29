#!/usr/bin/env python3
"""
Tests for cosa.agents.model_window — row a203d91d.

The defect: kaitchup/phi_4_14b carried max_tokens=4096 in config against a server
window of 8192. The server checks prompt + completion against the window, so any
prompt over ~4096 tokens was a hard 400 before generation started.

These are hermetic — every server call is stubbed, so no model server is required.
Venue: :7999-eligible.
"""

import json
import io
import unittest
from unittest.mock import patch

from cosa.agents import model_window
from cosa.agents.model_window import (
    _server_root, clamp_max_tokens, count_tokens, get_context_window,
)

BASE = "http://192.168.1.21:3001/v1/completions"
MODEL = "kaitchup/Phi-4-AutoRound-GPTQ-4bit"


class _Reply:
    """Minimal stand-in for the file-like object urlopen returns."""
    def __init__( self, payload ): self._payload = json.dumps( payload ).encode()
    def read( self ): return self._payload
    def __enter__( self ): return io.BytesIO( self._payload )
    def __exit__( self, *a ): return False


class TestServerRoot( unittest.TestCase ):

    def test_strips_the_path_and_keeps_scheme_and_host( self ):
        """Ensures: a completions URL yields just scheme://host:port."""
        self.assertEqual( _server_root( BASE ), "http://192.168.1.21:3001" )
        self.assertEqual( _server_root( "https://h/x/y" ), "https://h" )


class TestClamp( unittest.TestCase ):

    def test_a_budget_that_already_fits_is_untouched( self ):
        """Ensures: no clamping when prompt + requested + margin is inside the window."""
        self.assertEqual( clamp_max_tokens( requested=256, prompt_tokens=100, window=8192 ), 256 )

    def test_the_reported_defect_shrinks_instead_of_400ing( self ):
        """
        The exact numbers from the row: 4096 requested, 4114-token prompt, 8192 window.

        Ensures:
            - the budget drops to what actually fits rather than being sent as-is
            - prompt + clamped + margin lands on the window, not past it
        """
        clamped = clamp_max_tokens( requested=4096, prompt_tokens=4114, window=8192, margin=64 )
        self.assertEqual( clamped, 8192 - 4114 - 64 )
        self.assertLessEqual( 4114 + clamped + 64, 8192 )

    def test_a_prompt_that_leaves_no_room_still_returns_a_positive_budget( self ):
        """
        Ensures:
            - a prompt at or past the window yields 1, never 0 or negative, so the
              caller gets the server's own complaint about the PROMPT rather than a
              zero-length request that reads as a different bug
        """
        self.assertEqual( clamp_max_tokens( requested=4096, prompt_tokens=8192, window=8192 ), 1 )
        self.assertEqual( clamp_max_tokens( requested=4096, prompt_tokens=99999, window=8192 ), 1 )


class TestCountTokens( unittest.TestCase ):

    def setUp( self ): model_window._WINDOW_CACHE.clear()

    def test_returns_count_and_window_from_one_call( self ):
        """Ensures: both numbers come back, and the window is cached for later."""
        with patch( "urllib.request.urlopen", return_value=_Reply( { "count": 4114, "max_model_len": 8192 } ) ):
            count, window = count_tokens( BASE, MODEL, "some prompt" )
        self.assertEqual( ( count, window ), ( 4114, 8192 ) )
        self.assertEqual( model_window._WINDOW_CACHE[ "http://192.168.1.21:3001" ][ MODEL ], 8192 )

    def test_a_reply_missing_the_fields_is_an_error_not_a_guess( self ):
        """Ensures: a malformed reply raises rather than inventing a number."""
        with patch( "urllib.request.urlopen", return_value=_Reply( { "tokens": [ 1, 2 ] } ) ):
            with self.assertRaises( RuntimeError ) as ctx:
                count_tokens( BASE, MODEL, "x" )
        self.assertIn( "count/max_model_len", str( ctx.exception ) )

    def test_an_unreachable_server_raises_naming_the_url( self ):
        """Ensures: the failure says which endpoint did not answer."""
        with patch( "urllib.request.urlopen", side_effect=OSError( "connection refused" ) ):
            with self.assertRaises( RuntimeError ) as ctx:
                count_tokens( BASE, MODEL, "x" )
        self.assertIn( "/tokenize", str( ctx.exception ) )


class TestGetContextWindow( unittest.TestCase ):

    def setUp( self ): model_window._WINDOW_CACHE.clear()

    def test_reads_the_window_from_the_server( self ):
        """Ensures: max_model_len comes from /v1/models, not from config."""
        listing = { "data": [ { "id": MODEL, "max_model_len": 8192 } ] }
        with patch( "urllib.request.urlopen", return_value=_Reply( listing ) ):
            self.assertEqual( get_context_window( BASE, MODEL ), 8192 )

    def test_a_second_call_does_no_network_io( self ):
        """Ensures: the window is cached per server and model."""
        listing = { "data": [ { "id": MODEL, "max_model_len": 8192 } ] }
        with patch( "urllib.request.urlopen", return_value=_Reply( listing ) ) as opened:
            get_context_window( BASE, MODEL )
            get_context_window( BASE, MODEL )
        self.assertEqual( opened.call_count, 1 )

    def test_an_unlisted_model_raises_and_names_what_was_listed( self ):
        """Ensures: the error is actionable — it says which models the server has."""
        listing = { "data": [ { "id": "some/other-model", "max_model_len": 4096 } ] }
        with patch( "urllib.request.urlopen", return_value=_Reply( listing ) ):
            with self.assertRaises( RuntimeError ) as ctx:
                get_context_window( BASE, MODEL )
        self.assertIn( "some/other-model", str( ctx.exception ) )

    def test_a_model_listed_without_a_window_is_not_accepted( self ):
        """Ensures: an entry lacking max_model_len does not silently become a window."""
        listing = { "data": [ { "id": MODEL } ] }
        with patch( "urllib.request.urlopen", return_value=_Reply( listing ) ):
            with self.assertRaises( RuntimeError ):
                get_context_window( BASE, MODEL )

    def test_an_unreachable_server_raises_naming_the_url( self ):
        """Ensures: the failure says which endpoint did not answer."""
        with patch( "urllib.request.urlopen", side_effect=OSError( "refused" ) ):
            with self.assertRaises( RuntimeError ) as ctx:
                get_context_window( BASE, MODEL )
        self.assertIn( "/v1/models", str( ctx.exception ) )


if __name__ == "__main__":
    unittest.main()
