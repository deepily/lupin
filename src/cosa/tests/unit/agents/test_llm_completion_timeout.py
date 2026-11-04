#!/usr/bin/env python3
"""
Control for the completion-call timeout wiring — row abe4188d.

The defect: `LlmCompletion.run` called `requests.post` with no timeout, so an
unroutable base_url blocked the caller for about two minutes. Measured before the
fix against a server that accepts the connection and never answers: `run` had not
returned after 120 seconds. Measured after: `TimeoutError` at 5.00 seconds.

Three things have to hold together, and each is its own test below, because any one
of them alone still leaves the caller blocked:

  1. the bound reaches `requests.post`
  2. it ALSO reaches the tokenize probe, which `run` calls first and which carries
     its own 20-second default — a bound that skips it is not a bound
  3. what comes out is the BUILTIN `TimeoutError`. `requests.exceptions.Timeout` is
     not a subclass of it (measured, see test below), so an `except TimeoutError`
     upstream — which is exactly what the commons disambiguator already had — would
     miss an untranslated one.

Hermetic: the model server and the HTTP post are both stubbed. Nothing here opens a
socket.
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import requests

from cosa.agents.completion_client import CompletionClient
from cosa.agents.llm_completion import LlmCompletion

BASE  = "http://192.168.1.21:3001/v1/completions"
MODEL = "kaitchup/Phi-4-AutoRound-GPTQ-4bit"


def _client():
    return LlmCompletion( base_url=BASE, model_name=MODEL, max_tokens=64 )


class TestTheTransportExceptionIsNotTheBuiltin( unittest.TestCase ):
    """
    The premise the translation rests on, asserted rather than assumed.

    If a future requests release makes Timeout a subclass of the builtin, the
    translation becomes redundant — and this test is where that shows up, instead
    of the translation quietly surviving as cargo.
    """

    def test_requests_timeout_is_not_a_builtin_timeout_error( self ):
        self.assertFalse( issubclass( requests.exceptions.Timeout,        TimeoutError ) )
        self.assertFalse( issubclass( requests.exceptions.ConnectTimeout, TimeoutError ) )


class TestRemaining( unittest.TestCase ):
    """The deadline arithmetic, exercised directly — the three answers it can give."""

    def test_no_deadline_means_unbounded( self ):
        self.assertIsNone( _client()._remaining( None ) )

    def test_a_future_deadline_yields_what_is_left( self ):
        with patch( "cosa.agents.llm_completion.time.monotonic", return_value=100.0 ):
            self.assertAlmostEqual( _client()._remaining( 104.5 ), 4.5 )

    def test_a_passed_deadline_raises_the_builtin( self ):
        with patch( "cosa.agents.llm_completion.time.monotonic", return_value=100.0 ):
            with self.assertRaises( TimeoutError ) as caught:
                _client()._remaining( 100.0 )
        self.assertIn( BASE, str( caught.exception ) )


class TestTheBoundReachesTheWire( unittest.TestCase ):

    def setUp( self ):
        self.ok = MagicMock( status_code=200 )
        self.ok.json.return_value = { "choices": [ { "text": "answer" } ] }

    def test_the_post_carries_the_timeout( self ):
        """
        Ensures:
            - a `timeout` given to run() arrives at requests.post as a positive bound

        This is the assertion the fix exists for. Dropping `timeout=` from the post
        call reddens it.
        """
        with patch( "cosa.agents.model_window.count_tokens", return_value=( 10, 8192 ) ), \
             patch( "cosa.agents.llm_completion.requests.post", return_value=self.ok ) as post:
            _client().run( "hello", timeout=5.0 )

        sent = post.call_args.kwargs[ "timeout" ]
        self.assertIsNotNone( sent )
        self.assertGreater( sent, 0 )
        self.assertLessEqual( sent, 5.0 )

    def test_no_timeout_leaves_the_post_unbounded( self ):
        """
        Ensures:
            - the default is today's behaviour, not a new implicit bound

        Every other caller of this client passes no timeout; silently bounding them
        would be a behaviour change smuggled in under a bug fix.
        """
        with patch( "cosa.agents.model_window.count_tokens", return_value=( 10, 8192 ) ), \
             patch( "cosa.agents.llm_completion.requests.post", return_value=self.ok ) as post:
            _client().run( "hello" )

        self.assertIsNone( post.call_args.kwargs[ "timeout" ] )

    def test_the_tokenize_probe_carries_the_timeout_too( self ):
        """
        Ensures:
            - the bound reaches the FIRST of the two HTTP calls as well

        The probe's own default is 20s. With the bound skipped, `timeout=5` still
        spends 20 seconds here before the post is even built — which is the same
        defect one door along. Removing the `timeout` kwarg from the count_tokens
        call reddens this and nothing else.
        """
        with patch( "cosa.agents.model_window.count_tokens", return_value=( 10, 8192 ) ) as count, \
             patch( "cosa.agents.llm_completion.requests.post", return_value=self.ok ):
            _client().run( "hello", timeout=5.0 )

        self.assertIn( "timeout", count.call_args.kwargs )
        self.assertLessEqual( count.call_args.kwargs[ "timeout" ], 5.0 )

    def test_no_timeout_leaves_the_probe_on_its_own_default( self ):
        """Ensures: unbounded callers do not start passing timeout=None to the probe."""
        with patch( "cosa.agents.model_window.count_tokens", return_value=( 10, 8192 ) ) as count, \
             patch( "cosa.agents.llm_completion.requests.post", return_value=self.ok ):
            _client().run( "hello" )

        self.assertNotIn( "timeout", count.call_args.kwargs )


class TestWhatComesOutOnTimeout( unittest.TestCase ):

    def test_a_transport_timeout_surfaces_as_the_builtin( self ):
        """
        Ensures:
            - requests.exceptions.Timeout is translated, not propagated
            - the original is chained, so the transport detail is not lost

        Deleting the translation leaves a requests.exceptions.Timeout escaping, which
        the commons disambiguator's `except ( TimeoutError, … )` does not catch.
        """
        with patch( "cosa.agents.model_window.count_tokens", return_value=( 10, 8192 ) ), \
             patch( "cosa.agents.llm_completion.requests.post",
                    side_effect=requests.exceptions.ConnectTimeout( "blackhole" ) ):
            with self.assertRaises( TimeoutError ) as caught:
                _client().run( "hello", timeout=5.0 )

        self.assertIn( BASE, str( caught.exception ) )
        self.assertIsInstance( caught.exception.__cause__, requests.exceptions.Timeout )

    def test_a_probe_that_eats_the_whole_budget_stops_before_posting( self ):
        """
        Ensures:
            - when the tokenize probe burns the entire deadline, run() raises rather
              than starting a second unbounded-feeling call
            - requests.post is never reached

        This is the arm the live probe actually took: against a server that accepts
        and never answers, the probe consumed all 5 seconds and the post never fired.
        """
        clock = iter( [ 100.0, 105.0 ] )  # deadline set at 100; probe returns at 105

        with patch( "cosa.agents.llm_completion.time.monotonic", side_effect=lambda: next( clock ) ), \
             patch( "cosa.agents.model_window.count_tokens", side_effect=RuntimeError( "no answer" ) ), \
             patch( "cosa.agents.llm_completion.requests.post" ) as post:
            with self.assertRaises( TimeoutError ):
                _client().run( "hello", timeout=5.0 )

        post.assert_not_called()

    def test_a_non_timeout_transport_error_is_left_alone( self ):
        """
        Ensures:
            - only timeouts are translated

        A refused connection is a different failure with a different remedy;
        relabelling it as a timeout would send the next reader to the wrong place.
        """
        with patch( "cosa.agents.model_window.count_tokens", return_value=( 10, 8192 ) ), \
             patch( "cosa.agents.llm_completion.requests.post",
                    side_effect=requests.exceptions.ConnectionError( "refused" ) ):
            with self.assertRaises( requests.exceptions.ConnectionError ):
                _client().run( "hello", timeout=5.0 )


class TestCompletionClientThreadsItThrough( unittest.TestCase ):
    """
    The hop that made the INI key inert.

    `CompletionClient.run_async` rebuilds the generation arguments by hand from a
    fixed list, so anything arriving in **kwargs and not on that list is dropped
    without a word. A `timeout` passed as a bare kwarg therefore vanished between
    the caller and the transport. These assert it now arrives.
    """

    def setUp( self ):
        self.client = CompletionClient( base_url=BASE, model_name=MODEL, max_tokens=64 )
        self.client.model = MagicMock()
        self.client.model.run = MagicMock( return_value="answer" )

    def test_the_timeout_reaches_the_model( self ):
        self.client.run( "hello", timeout=5.0 )
        self.assertEqual( self.client.model.run.call_args.kwargs[ "timeout" ], 5.0 )

    def test_no_timeout_passes_none( self ):
        self.client.run( "hello" )
        self.assertIsNone( self.client.model.run.call_args.kwargs[ "timeout" ] )

    def test_the_generation_arguments_still_arrive( self ):
        """Ensures: threading the bound did not displace what was already being sent."""
        self.client.run( "hello", timeout=5.0, max_tokens=17 )
        self.assertEqual( self.client.model.run.call_args.kwargs[ "max_tokens" ], 17 )


class TestTheStreamingDoorIsBoundedToo( unittest.IsolatedAsyncioTestCase ):
    """
    The same defect one door along, raised by Rio on review.

    `_stream_async` opened an `aiohttp.ClientSession` with no `ClientTimeout`, so a
    caller that streams had no bound at all. It is not on the commons disambiguator's
    route today — CLIENT_DEFAULT_PARAMS carries no `stream` key, which is why the live
    frame landed on the requests POST — but one config flip would put it there.

    No translation is asserted here, and that asymmetry is the point: aiohttp's
    timeouts already ARE the builtin `TimeoutError` (measured below), while requests'
    are not.
    """

    async def asyncSetUp( self ):
        """
        Stub the tokenize probe. `_stream_async` calls `_clamped_max_tokens` first, which POSTs to
        `BASE` — a real LAN host — unless `count_tokens` is patched, as every other test in this
        file already does. Unpatched, four streaming tests opened a real socket to
        192.168.1.21:3001 and the cosa tier's network guard (block mode) failed the run, while the
        module docstring promised "Nothing here opens a socket".
        """
        probe = patch( "cosa.agents.model_window.count_tokens", return_value=( 10, 8192 ) )
        probe.start()
        self.addCleanup( probe.stop )

    async def test_aiohttp_timeouts_already_are_the_builtin( self ):
        """The premise that lets the streaming path skip a translation."""
        import asyncio

        import aiohttp

        self.assertIs( asyncio.TimeoutError, TimeoutError )
        self.assertTrue( issubclass( aiohttp.ServerTimeoutError, TimeoutError ) )

    async def test_the_session_is_opened_with_the_bound( self ):
        """
        Ensures:
            - the timeout reaches aiohttp as a ClientTimeout total

        Dropping `timeout=` from the ClientSession construction reddens this.
        """
        import aiohttp

        seen = { }
        real = aiohttp.ClientSession

        def _capture( *a, **kw ):
            seen[ "total" ] = kw.get( "timeout" )
            raise RuntimeError( "stop here — the session construction is the subject" )

        with patch( "cosa.agents.llm_completion.aiohttp.ClientSession", _capture ):
            with self.assertRaises( RuntimeError ):
                async for _ in _client()._stream_async( "hello", timeout=5.0 ):
                    pass

        self.assertIsNotNone( seen[ "total" ] )
        self.assertEqual( seen[ "total" ].total, 5.0 )
        self.assertIs( real, aiohttp.ClientSession )  # restore control

    async def test_no_timeout_leaves_the_session_unbounded( self ):
        """Ensures: an untimed streaming caller keeps aiohttp's own default."""
        import aiohttp

        seen = { }

        def _capture( *a, **kw ):
            seen[ "total" ] = kw.get( "timeout" )
            raise RuntimeError( "stop here" )

        with patch( "cosa.agents.llm_completion.aiohttp.ClientSession", _capture ):
            with self.assertRaises( RuntimeError ):
                async for _ in _client()._stream_async( "hello" ):
                    pass

        self.assertIsNone( seen[ "total" ].total )

    async def test_run_stream_carries_the_bound_into_the_context( self ):
        """Ensures: the bound survives the context-manager hop, not just the call."""
        ctx = _client().run_stream( "hello", timeout=5.0 )
        self.assertEqual( ctx.timeout, 5.0 )


class TestCompletionClientInsideARunningLoop( unittest.IsolatedAsyncioTestCase ):
    """
    `run()` has two paths — a running event loop and none — and they pass the bound
    on separately. The sync path is covered above; this is the other one.
    """

    async def test_the_timeout_reaches_the_model_from_async_context( self ):
        client = CompletionClient( base_url=BASE, model_name=MODEL, max_tokens=64 )
        client.model = MagicMock()
        client.model.run = MagicMock( return_value="answer" )

        # run() detects the running loop and hands the work to a worker thread.
        client.run( "hello", timeout=5.0 )

        self.assertEqual( client.model.run.call_args.kwargs[ "timeout" ], 5.0 )


if __name__ == "__main__":
    unittest.main()


# ══════════════════════════════════════════════════════════════════════════════
# Coverage of the two gaps Rio's review named — llm_completion.py at 98%.
# Measured independently before writing these: line 114 and branch 298->exit,
# `pytest --cov=cosa.agents.llm_completion --cov-branch`, same two.
# Neither is unreachable, so neither gets a pragma.
# ══════════════════════════════════════════════════════════════════════════════

class TestTheClampAnnouncesItself( unittest.TestCase ):
    """
    Line 114 — the clamp's debug print. It needs BOTH conditions in one call:
    `self.debug` true AND the budget actually moved. A debug-on test where the
    budget fits, or a clamping test with debug off, leaves it uncovered, which is
    how it survived.
    """

    def setUp( self ):
        self.ok = MagicMock( status_code=200 )
        self.ok.json.return_value = { "choices": [ { "text": "answer" } ] }

    def test_a_clamped_budget_is_announced_when_debug_is_on( self ):
        """Ensures: the operator is told the budget shrank, with both numbers."""
        client = LlmCompletion( base_url=BASE, model_name=MODEL, max_tokens=4096, debug=True )

        with patch( "cosa.agents.model_window.count_tokens", return_value=( 4114, 8192 ) ), \
             patch( "cosa.agents.llm_completion.requests.post", return_value=self.ok ), \
             patch( "builtins.print" ) as printed:
            client.run( "a very long prompt" )

        said = " ".join( str( c.args[ 0 ] ) for c in printed.call_args_list if c.args )
        self.assertIn( "[CLAMP]", said )
        self.assertIn( "4114", said )                      # the prompt it measured
        self.assertIn( str( 8192 - 4114 - 64 ), said )     # the budget it landed on

    def test_an_unclamped_budget_stays_quiet_even_with_debug_on( self ):
        """
        Ensures: the print is conditional on the budget MOVING, not on debug alone.

        Without this, a test could cover line 114 while the `clamped != requested`
        half of the condition went unexercised — green coverage over a guard nobody
        checked.
        """
        client = LlmCompletion( base_url=BASE, model_name=MODEL, max_tokens=64, debug=True )

        with patch( "cosa.agents.model_window.count_tokens", return_value=( 100, 8192 ) ), \
             patch( "cosa.agents.llm_completion.requests.post", return_value=self.ok ), \
             patch( "builtins.print" ) as printed:
            client.run( "short" )

        said = " ".join( str( c.args[ 0 ] ) for c in printed.call_args_list if c.args )
        self.assertNotIn( "[CLAMP] prompt=", said )


class _FakeContent:
    """An async byte-line iterator standing in for aiohttp's response.content."""

    def __init__( self, lines ):
        self._lines = list( lines )

    def __aiter__( self ):
        return self

    async def __anext__( self ):
        if not self._lines: raise StopAsyncIteration
        return self._lines.pop( 0 )


class _FakeCM:
    """Minimal async context manager — aiohttp's session and response are both one."""

    def __init__( self, value ):
        self._value = value

    async def __aenter__( self ):
        return self._value

    async def __aexit__( self, *exc ):
        return False


class TestTheStreamEndsWithoutADoneMarker( unittest.IsolatedAsyncioTestCase ):
    """
    Branch 298->exit — the `async for` over the response body completing NORMALLY.

    Every existing streaming test ends on `data: [DONE]`, which leaves by the `break`,
    so the loop's other exit — the body simply running out — was never taken. A server
    that closes without the marker is not exotic; it is what a truncated or
    non-conforming response looks like, and the generator must still finish cleanly
    rather than hang or raise.
    """

    async def asyncSetUp( self ):
        """
        Stub the tokenize probe. `_stream_async` calls `_clamped_max_tokens` first, which POSTs to
        `BASE` — a real LAN host — unless `count_tokens` is patched, as every other test in this
        file already does. Unpatched, four streaming tests opened a real socket to
        192.168.1.21:3001 and the cosa tier's network guard (block mode) failed the run, while the
        module docstring promised "Nothing here opens a socket".
        """
        probe = patch( "cosa.agents.model_window.count_tokens", return_value=( 10, 8192 ) )
        probe.start()
        self.addCleanup( probe.stop )

    def _session_yielding( self, lines, status=200 ):
        response = MagicMock()
        response.status  = status
        response.content = _FakeContent( lines )
        response.text    = AsyncMock( return_value="upstream said no" )  # awaited on the error path
        session = MagicMock()
        session.post = MagicMock( return_value=_FakeCM( response ) )
        return MagicMock( return_value=_FakeCM( session ) )

    async def test_a_body_that_just_runs_out_ends_the_stream_cleanly( self ):
        """
        Ensures:
            - the loop exits by exhaustion, no [DONE] marker involved
            - the chunks decoded before the end are still yielded
        """
        lines = [
            b'data: {"choices":[{"text":"one"}]}',
            b'',                                        # blank line — the `continue` arm
            b'not a data line',                         # no "data: " prefix — skipped
            b'data: {oh dear',                          # invalid JSON — the except arm
            b'data: {"choices":[{"text":"two"}]}',
        ]

        chunks = [ ]
        with patch( "cosa.agents.llm_completion.aiohttp.ClientSession",
                    self._session_yielding( lines ) ):
            async for chunk in _client()._stream_async( "hello", timeout=5.0 ):
                chunks.append( chunk )

        self.assertEqual( chunks, [ "one", "two" ] )

    async def test_a_non_200_still_raises( self ):
        """Ensures: covering the clean exit did not soften the error path beside it."""
        with patch( "cosa.agents.llm_completion.aiohttp.ClientSession",
                    self._session_yielding( [ ], status=500 ) ):
            with self.assertRaises( Exception ) as caught:
                async for _ in _client()._stream_async( "hello" ):
                    pass

        self.assertIn( "Error requesting completion stream", str( caught.exception ) )
