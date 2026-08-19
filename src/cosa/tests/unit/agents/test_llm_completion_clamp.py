#!/usr/bin/env python3
"""
Control for the max_tokens clamp wiring — row a203d91d.

model_window is unit-tested separately; this asserts the CLAMPED number actually
reaches the request body. Reverting the wiring in llm_completion.py sends the raw
4096 again and fails test_the_posted_budget_is_clamped.

Hermetic: the model server and the HTTP post are both stubbed.
"""

import json
import unittest
from unittest.mock import patch, MagicMock

from cosa.agents.llm_completion import LlmCompletion

BASE  = "http://192.168.1.21:3001/v1/completions"
MODEL = "kaitchup/Phi-4-AutoRound-GPTQ-4bit"


def _client():
    return LlmCompletion( base_url=BASE, model_name=MODEL, max_tokens=4096 )


def _posted_body( post_mock ):
    return json.loads( post_mock.call_args.kwargs[ "data" ] )


class TestClampWiring( unittest.TestCase ):

    def setUp( self ):
        self.ok = MagicMock( status_code=200 )
        self.ok.json.return_value = { "choices": [ { "text": "answer" } ] }

    def test_the_posted_budget_is_clamped( self ):
        """
        The reported defect, end to end: a 4,114-token prompt against an 8,192 window
        must NOT go out asking for 4,096 completion tokens.

        Ensures:
            - the body carries the shrunken budget, not the configured constant
            - prompt + budget stays inside the window
        """
        with patch( "cosa.agents.model_window.count_tokens", return_value=( 4114, 8192 ) ), \
             patch( "cosa.agents.llm_completion.requests.post", return_value=self.ok ) as post:
            _client().run( "a very long prompt" )

        self.assertEqual( _posted_body( post )[ "max_tokens" ], 8192 - 4114 - 64 )
        self.assertLess( _posted_body( post )[ "max_tokens" ], 4096 )

    def test_a_small_prompt_is_left_alone( self ):
        """Ensures: the clamp is not a blanket reduction — a fitting budget survives."""
        with patch( "cosa.agents.model_window.count_tokens", return_value=( 100, 8192 ) ), \
             patch( "cosa.agents.llm_completion.requests.post", return_value=self.ok ) as post:
            _client().run( "short" )

        self.assertEqual( _posted_body( post )[ "max_tokens" ], 4096 )

    def test_an_unreachable_tokenizer_sends_todays_behaviour( self ):
        """
        Ensures:
            - if the prompt cannot be sized, the request still goes out with the
              requested budget, so a tokenizer outage cannot take down a call that
              would otherwise have worked
        """
        with patch( "cosa.agents.model_window.count_tokens", side_effect=RuntimeError( "down" ) ), \
             patch( "cosa.agents.llm_completion.requests.post", return_value=self.ok ) as post:
            _client().run( "short" )

        self.assertEqual( _posted_body( post )[ "max_tokens" ], 4096 )


if __name__ == "__main__":
    unittest.main()
