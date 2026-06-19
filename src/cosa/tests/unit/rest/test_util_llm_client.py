"""
Unit tests for the in-memory LLM client helper (cosa.rest.util_llm_client).

Covers StopOnTokens.__init__ + __call__ (too-short / match / no-match) and
query_llm_in_memory (generation + decode + response cleanup) — to genuine 100%
line + branch + function.

torch runs on CPU only (device="cpu") with tiny tensors — NEVER cuda, no GPU
grab (per the never-grab-GPU mandate). The model + tokenizer are boundary-mocked;
no real model is loaded and model.generate is a Mock. ZERO GPU, ZERO model load.
"""

import unittest
from unittest.mock import MagicMock, Mock, patch

import torch

from cosa.rest import util_llm_client
from cosa.rest.util_llm_client import StopOnTokens, query_llm_in_memory


class TestStopOnTokens( unittest.TestCase ):
    def test_init_stores_fields( self ):
        s = StopOnTokens( stop_ids=[ 1, 2 ], device="cpu" )
        self.assertEqual( s.stop_ids, [ 1, 2 ] )
        self.assertEqual( s.device, "cpu" )

    def test_too_short_returns_false( self ):
        s = StopOnTokens( stop_ids=[ 1, 2 ], device="cpu" )
        self.assertFalse( s( torch.tensor( [ [ 1 ] ] ), torch.tensor( [ 0.0 ] ) ) )

    def test_match_returns_true( self ):
        s = StopOnTokens( stop_ids=[ 1, 2 ], device="cpu" )
        self.assertTrue( s( torch.tensor( [ [ 9, 1, 2 ] ] ), torch.tensor( [ 0.0 ] ) ) )

    def test_no_match_returns_false( self ):
        s = StopOnTokens( stop_ids=[ 1, 2 ], device="cpu" )
        self.assertFalse( s( torch.tensor( [ [ 9, 8, 7 ] ] ), torch.tensor( [ 0.0 ] ) ) )


class TestQueryLlmInMemory( unittest.TestCase ):
    def test_generates_and_cleans_response( self ):
        input_ids = MagicMock( name="input_ids" )
        input_ids.size.return_value = 2                       # input_length = 2
        inputs = { "input_ids": input_ids, "attention_mask": MagicMock() }

        tokenizer = MagicMock( name="tokenizer" )
        tokenizer.return_value.to.return_value = inputs        # tokenizer(prompt,...).to(device)
        tokenizer.encode.return_value = [ 5 ]                  # stop_ids
        tokenizer.eos_token_id = 0
        tokenizer.decode.return_value = "</s><s>foo</response>  <bar>"

        model = Mock( name="model" )
        model.generate.return_value = [ [ 10, 11, 12, 13 ] ]   # gen_output[0][2:] = [12, 13]

        # Boundary-mock the Stopwatch clock seam: a mocked instant run rounds
        # get_delta_ms() to 0, which would hit a div-by-zero on the (never-instant
        # in production) tokens/second line. Pin a deterministic nonzero delta.
        timer = MagicMock( name="timer" )
        timer.get_delta_ms.return_value = 100.0
        with patch.object( util_llm_client, "Stopwatch", return_value=timer ):
            out = query_llm_in_memory( model, tokenizer, "prompt text", device="cpu", silent=True )

        self.assertEqual( out, "foo</response><bar>" )         # </s><s> stripped + whitespace between tags collapsed
        model.generate.assert_called_once()
        tokenizer.decode.assert_called_once()


def isolated_unit_test():
    """
    Run the util_llm_client unit tests in isolation.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness
    """
    import time
    start_time = time.time()
    suite = unittest.TestLoader().loadTestsFromModule( __import__( __name__ ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = time.time() - start_time
    success = result.wasSuccessful()
    message = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} util_llm_client tests in {secs:.3f}s — {msg}" )
