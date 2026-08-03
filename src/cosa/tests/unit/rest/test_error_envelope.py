"""
Unit tests for the unhandled-exception envelope (row b101a60b).

WHAT THIS EXISTS TO PREVENT
---------------------------
On 2026-07-21 a mid-refactor save on the `--reload` :7999 served a state where a
call existed and its def did not. Five DMs 500'd, four seats each diagnosed their
OWN side, and `/health` returned 200 throughout — correctly, because it is a
liveness probe and says so. The exception class lived only in the container log:
measured, an unhandled 500 returns the 21-byte string "Internal Server Error"
with `debug=False` and no registered handler. A caller could not tell "my request
is malformed" from "the server is mid-reload".

THE ENVELOPE ANSWERS EXACTLY THAT QUESTION AND NO OTHER:
    exception_class    — a caller reading `NameError` knows instantly it is not
                         their request. This is the "not my problem" signal.
    server_started_at  — captured at MODULE IMPORT, so every reload re-stamps it.
                         A start time seconds old says "you hit a reload window."

DELIBERATELY ABSENT: `str(e)`. Ruled out 2026-07-21 because nobody has audited
what an exception message leaks on an authenticated fleet. A class name plus a
fresh start time carry the whole signal; the message carries the unmeasured risk.
Adding it later is additive against a shipped handler — that ordering is the
point, and a test below pins the absence so it cannot drift back in unnoticed.
"""

import unittest


class TestErrorEnvelope( unittest.TestCase ):

    def setUp( self ):
        from cosa.rest.error_envelope import build_error_envelope
        self.build = build_error_envelope

    def test_names_the_exception_class( self ):
        """The whole point: a caller reads `NameError` and stops diagnosing itself."""
        env = self.build( NameError( "name '_make_sender_id_builder' is not defined" ), "2026-07-21T15:00:00" )
        self.assertEqual( env[ "exception_class" ], "NameError" )

    def test_carries_the_server_start_instant( self ):
        """The reload-generation marker — a fresh value means you hit a reload window."""
        env = self.build( RuntimeError( "boom" ), "2026-07-21T15:00:00" )
        self.assertEqual( env[ "server_started_at" ], "2026-07-21T15:00:00" )

    def test_omits_the_exception_message_entirely( self ):
        """
        RULED 2026-07-21: no `str(e)` until someone audits what it leaks. This test
        is the guard on that ruling — it fails if a message field is ever added
        back, rather than letting the omission quietly erode.
        """
        env = self.build( ValueError( "SECRET-TOKEN-abc123" ), "2026-07-21T15:00:00" )
        self.assertNotIn( "SECRET-TOKEN-abc123", str( env ) )
        self.assertNotIn( "message", env )

    def test_keeps_the_generic_detail_string( self ):
        """`detail` stays exactly what callers already parse — the envelope ADDS, it does not replace."""
        env = self.build( RuntimeError( "boom" ), "2026-07-21T15:00:00" )
        self.assertEqual( env[ "detail" ], "Internal Server Error" )

    def test_class_name_tracks_the_exception_not_a_constant( self ):
        """
        CONTROL — an envelope that hardcoded "NameError" would pass the first test.
        Two different exception types must produce two different values, or the
        assertions above are checking a literal.
        """
        a = self.build( NameError( "x" ),   "t" )[ "exception_class" ]
        b = self.build( TypeError( "x" ),   "t" )[ "exception_class" ]
        self.assertNotEqual( a, b )
        self.assertEqual( ( a, b ), ( "NameError", "TypeError" ) )


class TestHandlerFactory( unittest.TestCase ):
    """The factory binds ONE start instant for the process's lifetime."""

    def setUp( self ):
        from cosa.rest.error_envelope import make_unhandled_exception_handler
        self.make = make_unhandled_exception_handler

    def test_handler_returns_a_500_carrying_the_envelope( self ):
        import json
        handler  = self.make( "2026-07-21T15:00:00" )
        response = handler( None, NameError( "boom" ) )
        self.assertEqual( response.status_code, 500 )
        payload = json.loads( response.body )
        self.assertEqual( payload[ "exception_class" ], "NameError" )
        self.assertEqual( payload[ "server_started_at" ], "2026-07-21T15:00:00" )

    def test_the_bound_start_instant_is_the_one_reported( self ):
        """
        CONTROL — a handler ignoring its bound argument (reading a module global,
        say) would still emit a plausible timestamp and pass a shape check. Two
        handlers bound to different instants must disagree.
        """
        import json
        first  = json.loads( self.make( "T-ONE" )( None, RuntimeError( "x" ) ).body )
        second = json.loads( self.make( "T-TWO" )( None, RuntimeError( "x" ) ).body )
        self.assertEqual( first[ "server_started_at" ],  "T-ONE" )
        self.assertEqual( second[ "server_started_at" ], "T-TWO" )


if __name__ == "__main__":
    unittest.main()
