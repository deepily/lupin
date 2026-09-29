"""
Unit tests for `cosa.agents.test_harness.mock_submit` (row 432511fd) and the two tiny v2
helpers it leans on, `cosa.rest.v2.request_context` and `cosa.rest.v2.refusal`.

The through-the-door behaviour is in tests/unit/test_v2_submit_mock_job_through_path.py;
these pin the pieces the door cannot reach: every keyword-matcher arm, both range checks,
the anonymous-caller fallbacks, and the factory returning nothing.
"""

import unittest
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from cosa.agents.test_harness import mock_submit as ms
from cosa.agents.test_harness.mock_submit import (
    MOCK_COMMAND, MockJobArgs, build_expeditor_test_job, build_plain_mock_job,
    match_voice_command, validate_ranges,
)
from cosa.rest.v2 import request_context as rc
from cosa.rest.v2.refusal import SubmitRefused


class TestMatchVoiceCommand( unittest.TestCase ):

    def test_keyword_match_skips_a_nonmatching_key_then_matches( self ):
        contracts = { "agent router go to podcast generator": 1, "agent router go to deep research": 1 }
        self.assertEqual( match_voice_command( "please run a deep research task", contracts ),
                          "agent router go to deep research" )

    def test_the_mock_command_never_matches_itself( self ):
        contracts = { MOCK_COMMAND: 1 }
        self.assertIsNone( match_voice_command( "run the mock job", contracts ) )

    def test_every_partial_match_arm( self ):
        cases = {
            "make a presentation from research" : "agent router go to research to presentation",
            "just make a presentation"          : "agent router go to presentation generator",
            "a podcast about my research"       : "agent router go to research to podcast",
            "just make a podcast"               : "agent router go to podcast generator",
            "go do some research"               : "agent router go to deep research",
        }
        for voice, expected in cases.items():
            self.assertEqual( match_voice_command( voice, { } ), expected, voice )

    def test_nothing_matches( self ):
        self.assertIsNone( match_voice_command( "tell me a joke", { } ) )


class TestValidateRanges( unittest.TestCase ):

    def test_valid_ranges_pass( self ):
        validate_ranges( MockJobArgs() )

    def test_inverted_iterations_named( self ):
        with self.assertRaises( ValueError ) as ctx:
            validate_ranges( MockJobArgs( iterations_min=8, iterations_max=3 ) )
        self.assertIn( "iterations_min", str( ctx.exception ) )

    def test_inverted_sleep_named( self ):
        with self.assertRaises( ValueError ) as ctx:
            validate_ranges( MockJobArgs( sleep_min=5.0, sleep_max=1.0 ) )
        self.assertIn( "sleep_min", str( ctx.exception ) )


class TestMockJobArgs( unittest.TestCase ):

    def test_force_failure_mode_rejects_garbage( self ):
        with self.assertRaises( ValidationError ):
            MockJobArgs( force_failure_mode="garbage" )

    def test_defaults( self ):
        args = MockJobArgs()
        self.assertIsNone( args.force_failure_mode )
        self.assertIsNone( args.voice_command )


class TestBuildPlainMockJob( unittest.TestCase ):

    def test_blank_email_falls_back_and_config_is_attached( self ):
        job = build_plain_mock_job( MockJobArgs( fixed_iterations=2, fixed_sleep=0.5 ), "u1", None, "sess" )
        self.assertEqual( job.user_email, "mock@test.com" )
        self.assertEqual( job.submit_details[ "config" ][ "estimated_duration" ], "1.0s" )


class TestBuildExpeditorTestJob( unittest.TestCase ):

    def _run( self, voice, answer, job="JOB", user_id="user-12345678", user_email="u@t.com" ):
        fake = MagicMock()
        fake.expedite.return_value = answer
        with patch( "cosa.agents.runtime_argument_expeditor.expeditor.RuntimeArgumentExpeditor", return_value=fake ), \
             patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=MagicMock() ), \
             patch( "cosa.rest.agentic_job_factory.create_agentic_job", return_value=job ) as factory:
            result = build_expeditor_test_job( MockJobArgs( voice_command=voice ), user_id, user_email, "tok" )
        return result, fake, factory

    def test_anonymous_caller_gets_the_placeholder_identity( self ):
        job = MagicMock()
        result, fake, factory = self._run( "run the test suite", { "k": "v" }, job=job, user_id=None, user_email=None )
        self.assertIs( result, job )
        kwargs = fake.expedite.call_args.kwargs
        self.assertEqual( kwargs[ "user_id" ], "test-user" )
        self.assertEqual( kwargs[ "user_email" ], "test@test.com" )
        self.assertEqual( kwargs[ "session_id" ], "expeditor-test" )
        self.assertEqual( factory.call_args.kwargs[ "user_id" ], "test-user" )

    def test_identified_caller_session_id_carries_the_uid_prefix( self ):
        _, fake, _ = self._run( "run the test suite", { "k": "v" }, job=MagicMock() )
        self.assertEqual( fake.expedite.call_args.kwargs[ "session_id" ], "expeditor-test-user-123" )

    def test_no_match_lists_the_choices_without_the_mock_command( self ):
        with self.assertRaises( ValueError ) as ctx:
            self._run( "tell me a joke", { "k": "v" } )
        self.assertIn( "Could not match", str( ctx.exception ) )
        self.assertNotIn( MOCK_COMMAND, str( ctx.exception ) )

    def test_cancel_raises_a_refusal_with_the_reason( self ):
        with self.assertRaises( SubmitRefused ) as ctx:
            self._run( "run the test suite", None )
        self.assertEqual( ctx.exception.route_reason, "expeditor_cancelled" )
        self.assertEqual( ctx.exception.details[ "config" ][ "result" ], "cancelled_or_timeout" )

    def test_a_factory_that_returns_nothing_is_an_error( self ):
        with self.assertRaises( ValueError ) as ctx:
            self._run( "run the test suite", { "k": "v" }, job=None )
        self.assertIn( "could not build", str( ctx.exception ) )


class TestRequestContext( unittest.TestCase ):

    def test_default_is_none_set_then_reset_restores( self ):
        self.assertIsNone( rc.get_bearer_token() )
        reset = rc.set_bearer_token( "abc" )
        self.assertEqual( rc.get_bearer_token(), "abc" )
        rc.reset_bearer_token( reset )
        self.assertIsNone( rc.get_bearer_token() )


class TestSubmitRefused( unittest.TestCase ):

    def test_carries_reason_message_and_details( self ):
        err = SubmitRefused( "why", "because", { "a": 1 } )
        self.assertEqual( ( err.route_reason, err.message, err.details, str( err ) ),
                          ( "why", "because", { "a": 1 }, "because" ) )

    def test_details_default_to_none( self ):
        self.assertIsNone( SubmitRefused( "why", "because" ).details )


if __name__ == "__main__":
    unittest.main()
