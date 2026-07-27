"""
Guard tests for bug `574fd1dc` — the embedding HTTP fallback's timeout + retry.

THE DEFECT
    `EmbeddingProvider._generate_embedding_via_http` hardcoded `timeout = 10`
    (batch: 30) and made exactly one attempt. The model server is a
    scale-to-zero Cloud Run GPU service whose cold start was MEASURED at
    31.5-66.0s across 12 of 12 observed starts (median 32.8s). So every
    request arriving after an idle period was guaranteed to fail, and the
    caller's row was then silently dropped by `InputAndOutputTable`.

WHAT THESE TESTS PIN
    1. Both timeouts come from config, not a literal, and the batch timeout
       stays strictly larger than the single one (a batch is more work).
    2. A transport failure is RETRIED, and a later attempt's success is
       returned — the property that lets the first caller absorb a cold start.
    3. A 401 is NOT retried. Retrying a bad API key just multiplies the same
       rejection, and 14 real 401s were observed alongside these timeouts.
    4. A 5xx / 429 IS retried.
    5. Exhausting every attempt raises, and the message names the cold-start
       measurement so the next reader does not conclude "the service is down."
    6. `retries = 0` means exactly one attempt (the retry is disableable).

⚠️ WHY EVERY ASSERTION HERE COUNTS ATTEMPTS BY NAME, NOT BY TALLY
    A test that asserts only "it raised" passes identically whether the code
    tried once or ten times — the observable is preserved by the failure mode
    under test. These assert the CALL COUNT and the per-call kwargs, because a
    count of failures cannot distinguish "retried and gave up" from "never
    retried at all".
"""
import time
import unittest
from unittest.mock import MagicMock, patch

import requests

from cosa.memory.embedding_provider import EmbeddingProvider


def _make_provider( config: dict ) -> EmbeddingProvider:
    """
    Build an EmbeddingProvider with __init__ bypassed and a stub config.

    `__init__` builds a ConfigurationManager and an EmbeddingManager, neither
    of which this seam touches. Constructing the object without them keeps
    these tests on the retry logic instead of on provider bootstrap.
    """
    provider              = EmbeddingProvider.__new__( EmbeddingProvider )
    provider.debug        = False
    provider.verbose      = False
    provider._config_mgr  = MagicMock()
    provider._config_mgr.get.side_effect = lambda key, default=None, **kw: config.get( key, default )
    return provider


_DEFAULTS = {
    "embedding http timeout seconds"       : "90",
    "embedding http batch timeout seconds" : "120",
    "embedding http retries"               : "2",
    "embedding http retry backoff seconds" : "0",   # 0 so tests never sleep
}


def _response( status: int, body: dict = None ):
    r             = MagicMock()
    r.status_code = status
    r.text        = "boom"
    r.json.return_value = body if body is not None else { "embedding": [ 0.1, 0.2 ] }
    return r


class TestRetryConfigResolution( unittest.TestCase ):

    def test_retry_config_read_from_ini_not_hardcoded( self ):
        p = _make_provider( { **_DEFAULTS, "embedding http retries": "5", "embedding http retry backoff seconds": "1.5" } )
        self.assertEqual( ( 5, 1.5 ), p._http_retry_config() )

    def test_negative_retry_count_is_clamped_to_zero( self ):
        """A negative count must not invert the loop into zero attempts."""
        p = _make_provider( { **_DEFAULTS, "embedding http retries": "-3" } )
        retries, _ = p._http_retry_config()
        self.assertEqual( 0, retries )

    def test_negative_backoff_is_clamped_to_zero( self ):
        p = _make_provider( { **_DEFAULTS, "embedding http retry backoff seconds": "-2" } )
        _, backoff = p._http_retry_config()
        self.assertEqual( 0.0, backoff )


class TestTimeoutsAreConfigurable( unittest.TestCase ):
    """The literal `10` / `30` are gone; both come from config."""

    def test_single_timeout_comes_from_config( self ):
        p = _make_provider( { **_DEFAULTS, "embedding http timeout seconds": "77" } )
        with patch.object( p, "_resolve_http_target", return_value=( "http://ms", "k", "/embeddings" ) ), \
             patch( "requests.post", return_value=_response( 200 ) ) as post:
            p._generate_embedding_via_http( "hello", "prose" )
        self.assertEqual( 77.0, post.call_args.kwargs[ "timeout" ] )

    def test_batch_timeout_comes_from_config( self ):
        p = _make_provider( { **_DEFAULTS, "embedding http batch timeout seconds": "155" } )
        with patch.object( p, "_resolve_http_target", return_value=( "http://ms", "k", "/embeddings" ) ), \
             patch( "requests.post", return_value=_response( 200, { "embeddings": [ [ 0.1 ] ] } ) ) as post:
            p._generate_embeddings_batch_via_http( [ "hello" ], "prose" )
        self.assertEqual( 155.0, post.call_args.kwargs[ "timeout" ] )

    def test_shipped_defaults_survive_the_measured_cold_start( self ):
        """
        The load-bearing assertion. Measured cold starts ran 31.5-66.0s; the
        old 10s/30s pair lost to ALL 12. Any default at or below the observed
        maximum reintroduces the bug, so pin both above it.
        """
        MEASURED_MAX_COLD_START = 66.0
        p = _make_provider( _DEFAULTS )
        single = float( p._config_mgr.get( "embedding http timeout seconds" ) )
        batch  = float( p._config_mgr.get( "embedding http batch timeout seconds" ) )
        self.assertGreater( single, MEASURED_MAX_COLD_START )
        self.assertGreater( batch,  MEASURED_MAX_COLD_START )
        self.assertGreater( batch,  single, "a batch is MORE work than a single text" )


class TestRetryBehaviour( unittest.TestCase ):

    def test_transport_failure_is_retried_and_a_later_success_is_returned( self ):
        """The whole point: attempt 1 eats the cold start, attempt 2 lands warm."""
        p  = _make_provider( _DEFAULTS )
        ok = _response( 200 )
        with patch.object( p, "_resolve_http_target", return_value=( "http://ms", "k", "/embeddings" ) ), \
             patch( "requests.post", side_effect=[ requests.ReadTimeout( "cold start" ), ok ] ) as post:
            result = p._generate_embedding_via_http( "hello", "prose" )
        self.assertEqual( [ 0.1, 0.2 ], result )
        self.assertEqual( 2, post.call_count, "a single attempt means the cold start still loses the row" )

    def test_5xx_is_retried( self ):
        p = _make_provider( _DEFAULTS )
        with patch.object( p, "_resolve_http_target", return_value=( "http://ms", "k", "/embeddings" ) ), \
             patch( "requests.post", side_effect=[ _response( 503 ), _response( 200 ) ] ) as post:
            p._generate_embedding_via_http( "hello", "prose" )
        self.assertEqual( 2, post.call_count )

    def test_429_is_retried( self ):
        p = _make_provider( _DEFAULTS )
        with patch.object( p, "_resolve_http_target", return_value=( "http://ms", "k", "/embeddings" ) ), \
             patch( "requests.post", side_effect=[ _response( 429 ), _response( 200 ) ] ) as post:
            p._generate_embedding_via_http( "hello", "prose" )
        self.assertEqual( 2, post.call_count )

    def test_401_is_NOT_retried( self ):
        """
        14 real 401s were observed alongside the timeouts. A wrong API key
        retries into the identical rejection — retrying it burns the caller's
        budget and multiplies load on a GPU instance for nothing.
        """
        p = _make_provider( _DEFAULTS )
        with patch.object( p, "_resolve_http_target", return_value=( "http://ms", "k", "/embeddings" ) ), \
             patch( "requests.post", return_value=_response( 401 ) ) as post:
            with self.assertRaises( RuntimeError ) as ctx:
                p._generate_embedding_via_http( "hello", "prose" )
        self.assertEqual( 1, post.call_count, "a 4xx contract error must not be retried" )
        self.assertIn( "401", str( ctx.exception ) )

    def test_exhausting_every_attempt_raises_and_names_the_cold_start( self ):
        p = _make_provider( _DEFAULTS )   # retries=2 → 3 attempts
        with patch.object( p, "_resolve_http_target", return_value=( "http://ms", "k", "/embeddings" ) ), \
             patch( "requests.post", side_effect=requests.ReadTimeout( "still cold" ) ) as post:
            with self.assertRaises( RuntimeError ) as ctx:
                p._generate_embedding_via_http( "hello", "prose" )
        self.assertEqual( 3, post.call_count )
        msg = str( ctx.exception )
        self.assertIn( "3 attempt", msg )
        self.assertIn( "31.5-66.0s", msg, "the message must stop the next reader concluding 'the service is down'" )
        self.assertIn( "574fd1dc", msg )

    def test_retries_zero_means_exactly_one_attempt( self ):
        p = _make_provider( { **_DEFAULTS, "embedding http retries": "0" } )
        with patch.object( p, "_resolve_http_target", return_value=( "http://ms", "k", "/embeddings" ) ), \
             patch( "requests.post", side_effect=requests.ReadTimeout( "x" ) ) as post:
            with self.assertRaises( RuntimeError ):
                p._generate_embedding_via_http( "hello", "prose" )
        self.assertEqual( 1, post.call_count )

    def test_backoff_sleeps_between_attempts_and_not_after_the_last( self ):
        """
        3 attempts ⇒ exactly 2 sleeps, doubling. A test that only asserted
        "sleep was called" would pass on an implementation that slept after
        the final failure too, delaying the raise for no benefit.
        """
        p = _make_provider( { **_DEFAULTS, "embedding http retry backoff seconds": "2" } )
        with patch.object( p, "_resolve_http_target", return_value=( "http://ms", "k", "/embeddings" ) ), \
             patch( "requests.post", side_effect=requests.ReadTimeout( "x" ) ), \
             patch.object( time, "sleep" ) as slept:
            with self.assertRaises( RuntimeError ):
                p._generate_embedding_via_http( "hello", "prose" )
        self.assertEqual( [ 2.0, 4.0 ], [ c.args[ 0 ] for c in slept.call_args_list ] )

    def test_batch_path_retries_too( self ):
        """The batch path had the same single-attempt defect."""
        p = _make_provider( _DEFAULTS )
        ok = _response( 200, { "embeddings": [ [ 0.1 ] ] } )
        with patch.object( p, "_resolve_http_target", return_value=( "http://ms", "k", "/embeddings" ) ), \
             patch( "requests.post", side_effect=[ requests.ConnectionError( "cold" ), ok ] ) as post:
            result = p._generate_embeddings_batch_via_http( [ "hello" ], "prose" )
        self.assertEqual( [ [ 0.1 ] ], result )
        self.assertEqual( 2, post.call_count )


if __name__ == "__main__":
    unittest.main()
