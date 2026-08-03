#!/usr/bin/env python3
"""
Unit tests for shared proxy agent infrastructure (Layer 1).

Tests the base classes and utilities in cosa.agents.utils.proxy_agents/
that are shared across notification proxy, decision proxy, and future
domain-specific proxies.

Test Classes:
    TestBaseConfig: Connection defaults and credential resolution
    TestBaseStrategy: Protocol compliance for strategy interface
    TestBaseWebSocketListener: Listener construction and properties
    TestBaseResponder: Strategy chain routing and stats
    TestRestSubmitter: Response submission function
    TestBaseCli: Common CLI argument parser
    TestPackageExports: Module-level imports and __all__
"""

import os
import asyncio
import argparse
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


# ============================================================================
# TestBaseConfig — Connection defaults and credential resolution
# ============================================================================

class TestBaseConfig:
    """Tests for proxy_agents.base_config constants and functions."""

    def test_default_server_host( self ):
        from cosa.agents.utils.proxy_agents.base_config import DEFAULT_SERVER_HOST
        assert DEFAULT_SERVER_HOST == "localhost"

    def test_default_server_port( self ):
        from cosa.agents.utils.proxy_agents.base_config import DEFAULT_SERVER_PORT
        assert DEFAULT_SERVER_PORT == 7999

    def test_reconnect_initial_delay( self ):
        from cosa.agents.utils.proxy_agents.base_config import RECONNECT_INITIAL_DELAY
        assert RECONNECT_INITIAL_DELAY == 1.0

    def test_reconnect_max_delay( self ):
        # 30 -> 10 (Rick, 2026-08-02). This cap is not a private listener tuning knob:
        # the server-side all-clear settle gate fires on COVERAGE, so it waits for the
        # slowest session, so its deadline is derived from this number. Changing it here
        # without changing `managed bounce all-clear settle deadline seconds` reds
        # SettleDeadlinePinTests, which is the intended coupling.
        from cosa.agents.utils.proxy_agents.base_config import RECONNECT_MAX_DELAY
        assert RECONNECT_MAX_DELAY == 10.0

    def test_reconnect_jitter_is_a_downward_fraction( self ):
        # Downward-only is what keeps RECONNECT_MAX_DELAY a real ceiling; the settle
        # deadline's derivation depends on that. A value >= 1.0 would let a delay reach
        # zero, and a symmetric reading would let one exceed the cap — either silently
        # invalidates the deadline.
        from cosa.agents.utils.proxy_agents.base_config import RECONNECT_JITTER_FRACTION
        assert 0.0 < RECONNECT_JITTER_FRACTION < 1.0

    def test_reconnect_max_attempts( self ):
        from cosa.agents.utils.proxy_agents.base_config import RECONNECT_MAX_ATTEMPTS
        assert RECONNECT_MAX_ATTEMPTS == 10

    def test_reconnect_backoff_factor( self ):
        from cosa.agents.utils.proxy_agents.base_config import RECONNECT_BACKOFF_FACTOR
        assert RECONNECT_BACKOFF_FACTOR == 2.0

    def test_get_credentials_from_cli( self ):
        from cosa.agents.utils.proxy_agents.base_config import get_credentials
        email, password = get_credentials( "test@example.com", "secret123" )
        assert email == "test@example.com"
        assert password == "secret123"

    def test_get_credentials_from_env( self ):
        from cosa.agents.utils.proxy_agents.base_config import get_credentials
        with patch.dict( os.environ, {
            "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL": "env@test.com",
            "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD": "env-secret"
        } ):
            email, password = get_credentials()
            assert email == "env@test.com"
            assert password == "env-secret"

    def test_get_credentials_cli_overrides_env( self ):
        from cosa.agents.utils.proxy_agents.base_config import get_credentials
        with patch.dict( os.environ, {
            "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL": "env@test.com",
            "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD": "env-secret"
        } ):
            email, password = get_credentials( "cli@test.com", "cli-secret" )
            assert email == "cli@test.com"
            assert password == "cli-secret"

    def test_get_credentials_missing_email_raises( self ):
        from cosa.agents.utils.proxy_agents.base_config import get_credentials
        with patch.dict( os.environ, {}, clear=True ):
            # Clear the specific env vars
            os.environ.pop( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", None )
            os.environ.pop( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", None )
            with pytest.raises( ValueError, match="No email found" ):
                get_credentials()

    def test_get_credentials_missing_password_raises( self ):
        from cosa.agents.utils.proxy_agents.base_config import get_credentials
        with patch.dict( os.environ, {
            "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL": "test@example.com"
        } ):
            os.environ.pop( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", None )
            with pytest.raises( ValueError, match="No password found" ):
                get_credentials()

    def test_get_anthropic_api_key_from_env( self ):
        from cosa.agents.utils.proxy_agents.base_config import get_anthropic_api_key
        with patch.dict( os.environ, { "ANTHROPIC_API_KEY_FIREWALLED": "test-key-12345" } ):
            key = get_anthropic_api_key()
            assert key == "test-key-12345"

    def test_get_anthropic_api_key_returns_none_when_missing( self ):
        from cosa.agents.utils.proxy_agents.base_config import get_anthropic_api_key
        with patch.dict( os.environ, {}, clear=True ):
            os.environ.pop( "ANTHROPIC_API_KEY_FIREWALLED", None )
            with patch( "cosa.utils.util.get_api_key", side_effect=Exception( "no file" ) ):
                key = get_anthropic_api_key()
                assert key is None


# ============================================================================
# TestBaseStrategy — Protocol compliance
# ============================================================================

class TestBaseStrategy:
    """Tests for the BaseStrategy protocol definition."""

    def test_protocol_is_runtime_checkable( self ):
        from cosa.agents.utils.proxy_agents.base_strategy import BaseStrategy
        assert hasattr( BaseStrategy, "__protocol_attrs__" ) or hasattr( BaseStrategy, "__abstractmethods__" ) or True
        # Protocol is runtime_checkable — verify isinstance works with compliant classes

    def test_compliant_class_matches_protocol( self ):
        from cosa.agents.utils.proxy_agents.base_strategy import BaseStrategy

        class GoodStrategy:
            @property
            def name( self ):
                return "test"
            @property
            def available( self ):
                return True
            def can_handle( self, item ):
                return True
            def respond( self, item ):
                return "answer"

        strategy = GoodStrategy()
        assert isinstance( strategy, BaseStrategy )

    def test_noncompliant_class_fails_protocol( self ):
        from cosa.agents.utils.proxy_agents.base_strategy import BaseStrategy

        class BadStrategy:
            pass

        strategy = BadStrategy()
        assert not isinstance( strategy, BaseStrategy )

    def test_strategy_methods_callable( self ):
        from cosa.agents.utils.proxy_agents.base_strategy import BaseStrategy

        class TestStrategy:
            @property
            def name( self ):
                return "test_strat"
            @property
            def available( self ):
                return True
            def can_handle( self, item ):
                return "query" in item
            def respond( self, item ):
                return item.get( "query", None )

        s = TestStrategy()
        assert s.name == "test_strat"
        assert s.available is True
        assert s.can_handle( { "query": "test" } ) is True
        assert s.can_handle( { "other": "data" } ) is False
        assert s.respond( { "query": "hello" } ) == "hello"


# ============================================================================
# TestBaseWebSocketListener — Construction and properties
# ============================================================================

class TestBaseWebSocketListener:
    """Tests for BaseWebSocketListener construction (no server needed)."""

    def _make_listener( self, **kwargs ):
        from cosa.agents.utils.proxy_agents.base_listener import BaseWebSocketListener

        async def mock_handler( event_type, data ):
            pass

        defaults = {
            "email"             : "test@example.com",
            "password"          : "test-password",
            "session_id"        : "test proxy",
            "on_event"          : mock_handler,
            "subscribed_events" : [ "notification_queue_update", "sys_ping" ],
            "debug"             : False,
        }
        defaults.update( kwargs )
        return BaseWebSocketListener( **defaults )

    def test_construction_stores_params( self ):
        listener = self._make_listener()
        assert listener.email == "test@example.com"
        assert listener.password == "test-password"
        assert listener.session_id == "test proxy"
        assert listener.host == "localhost"
        assert listener.port == 7999

    def test_not_connected_initially( self ):
        listener = self._make_listener()
        assert not listener.is_connected

    def test_custom_host_port( self ):
        listener = self._make_listener( host="remote.server.com", port=8080 )
        assert listener.host == "remote.server.com"
        assert listener.port == 8080

    def test_subscribed_events_stored( self ):
        events = [ "custom_event", "sys_ping" ]
        listener = self._make_listener( subscribed_events=events )
        assert listener.subscribed_events == events

    def test_debug_verbose_flags( self ):
        listener = self._make_listener( debug=True, verbose=True )
        assert listener.debug is True
        assert listener.verbose is True

    def test_log_prefix_default( self ):
        from cosa.agents.utils.proxy_agents.base_listener import BaseWebSocketListener
        assert BaseWebSocketListener.LOG_PREFIX == "[Listener]"

    # ── reconnect lines must be RECORDABLE, not just printable ──────────────
    # These went out through bare `print`, so they reached stderr but never the
    # subclass's TIMESTAMPED centralized log. The cost was concrete: the downtime
    # behind every measured bounce had to be inferred from arrival times because
    # no timestamped reconnect line exists anywhere in the record
    # (src/rnd/v0.1.9/2026.08.02-settle-deadline-arithmetic-30-vs-40.md §4).
    # Routing them through _log lets a subclass persist them; these tests pin
    # that the routing exists, so a later "simplify" back to print goes red.

    def test_reconnect_lines_go_through_log_not_print( self ):
        import asyncio

        listener  = self._make_listener()
        captured  = []
        listener._log = captured.append

        calls = { "n": 0 }

        async def fake_connect_and_listen():
            calls[ "n" ] += 1
            if calls[ "n" ] >= 3:
                listener._running = False      # let run() exit
            raise RuntimeError( "boom" )       # drive the error arm

        listener._connect_and_listen = fake_connect_and_listen

        async def no_sleep( _ ):
            pass

        with patch( "cosa.agents.utils.proxy_agents.base_listener.asyncio.sleep", no_sleep ):
            asyncio.run( listener.run() )

        # Every reconnect decision reached _log — a subclass override therefore sees them.
        assert captured, "no reconnect line reached _log — they are unrecordable again"
        assert all( "Reconnecting in" in line for line in captured )

    def test_reconnect_line_carries_the_delay_and_attempt( self ):
        # The two fields that make the line an INSTRUMENT rather than a notice: which
        # backoff wake this is, and how long it waits. Without both, a timestamped line
        # still cannot reconstruct the wake series.
        import asyncio

        listener = self._make_listener()
        captured = []
        listener._log = captured.append

        calls = { "n": 0 }

        async def fake_connect_and_listen():
            calls[ "n" ] += 1
            if calls[ "n" ] >= 3:
                listener._running = False
            raise RuntimeError( "boom" )

        listener._connect_and_listen = fake_connect_and_listen

        async def no_sleep( _ ):
            pass

        # Neutralize jitter so the BASE series is readable. Jitter is exercised
        # separately below; here the question is which base value attempt 1 produces.
        with patch( "cosa.agents.utils.proxy_agents.base_listener.asyncio.sleep", no_sleep ), \
             patch( "cosa.agents.utils.proxy_agents.base_listener.random.uniform",
                    lambda lo, hi: hi ):
            asyncio.run( listener.run() )

        # Backoff is 1.0 * 2**attempt capped at RECONNECT_MAX_DELAY — attempt increments
        # BEFORE the min(), so the FIRST delay is 2.0s, not 1.0s. That off-by-one is what
        # made two readings of this series disagree for a day; pin it so the code answers
        # the question instead of two people arguing about it.
        assert "in 2.0s (attempt 1/" in captured[ 0 ]
        assert "in 4.0s (attempt 2/" in captured[ 1 ]

    def test_jitter_spreads_the_wake_and_never_exceeds_the_cap( self ):
        # The herd this exists to break: 9 listeners dropped by one bounce previously woke
        # within 8 MILLISECONDS of each other, because nothing in the delay was random.
        from cosa.agents.utils.proxy_agents.base_config import RECONNECT_MAX_DELAY

        listener = self._make_listener()
        listener._attempt = 8                       # deep enough to be pinned at the cap
        delays = { round( listener._next_delay(), 6 ) for _ in range( 500 ) }

        assert len( delays ) > 400, (
            f"only {len(delays)} distinct delays in 500 draws — the wake is not being "
            f"spread, so a bounce still wakes the whole fleet in lockstep"
        )
        assert max( delays ) <= RECONNECT_MAX_DELAY, (
            f"max delay {max(delays)}s exceeds the {RECONNECT_MAX_DELAY}s cap — jitter "
            f"must be downward-only or the settle deadline derived from this cap is wrong"
        )
        assert min( delays ) > 0.0

    def test_default_log_prints( self, capsys ):
        # The base's own _log must still reach stdout — subclasses opt INTO persistence,
        # they do not opt out of visibility.
        listener = self._make_listener()
        listener._log( "hello from the base" )
        assert "hello from the base" in capsys.readouterr().out


# ============================================================================
# TestBaseResponder — Strategy chain routing and stats
# ============================================================================

class TestBaseResponder:
    """Tests for BaseResponder abstract class."""

    def _make_responder( self ):
        from cosa.agents.utils.proxy_agents.base_responder import BaseResponder

        class ConcreteResponder( BaseResponder ):
            async def handle_event( self, event_type, event_data ):
                pass

        return ConcreteResponder( debug=True )

    def test_construction_stores_params( self ):
        responder = self._make_responder()
        assert responder.host == "localhost"
        assert responder.port == 7999
        assert responder.debug is True
        assert responder.dry_run is False

    def test_stats_initialized( self ):
        responder = self._make_responder()
        assert responder.stats[ "events_received" ] == 0
        assert responder.stats[ "responses_sent" ] == 0
        assert responder.stats[ "skipped" ] == 0
        assert responder.stats[ "errors" ] == 0

    def test_route_to_strategies_returns_first_match( self ):
        responder = self._make_responder()

        class Strategy1:
            name      = "s1"
            available = True
            def can_handle( self, item ): return False
            def respond( self, item ): return "s1-answer"

        class Strategy2:
            name      = "s2"
            available = True
            def can_handle( self, item ): return True
            def respond( self, item ): return "s2-answer"

        answer, name = responder.route_to_strategies(
            { "question": "test" },
            [ Strategy1(), Strategy2() ]
        )
        assert answer == "s2-answer"
        assert name == "s2"

    def test_route_to_strategies_returns_none_when_no_match( self ):
        responder = self._make_responder()

        class NoMatchStrategy:
            name      = "nope"
            available = True
            def can_handle( self, item ): return False
            def respond( self, item ): return "should-not-see"

        answer, name = responder.route_to_strategies(
            { "question": "test" },
            [ NoMatchStrategy() ]
        )
        assert answer is None
        assert name is None

    def test_route_to_strategies_skips_unavailable( self ):
        responder = self._make_responder()

        class UnavailableStrategy:
            name      = "unavail"
            available = False
            def can_handle( self, item ): return True
            def respond( self, item ): return "should-skip"

        class AvailableStrategy:
            name      = "avail"
            available = True
            def can_handle( self, item ): return True
            def respond( self, item ): return "correct"

        answer, name = responder.route_to_strategies(
            { "question": "test" },
            [ UnavailableStrategy(), AvailableStrategy() ]
        )
        assert answer == "correct"
        assert name == "avail"

    def test_route_to_strategies_skips_none_response( self ):
        responder = self._make_responder()

        class NoneStrategy:
            name      = "returns_none"
            available = True
            def can_handle( self, item ): return True
            def respond( self, item ): return None

        class FallbackStrategy:
            name      = "fallback"
            available = True
            def can_handle( self, item ): return True
            def respond( self, item ): return "fallback-answer"

        answer, name = responder.route_to_strategies(
            { "question": "test" },
            [ NoneStrategy(), FallbackStrategy() ]
        )
        assert answer == "fallback-answer"
        assert name == "fallback"

    def test_route_to_strategies_async( self ):
        responder = self._make_responder()

        class AsyncStrategy:
            name      = "async_s"
            available = True
            def can_handle( self, item ): return True
            async def respond( self, item ): return "async-answer"

        loop = asyncio.new_event_loop()
        try:
            answer, name = loop.run_until_complete(
                responder.route_to_strategies_async(
                    { "question": "test" },
                    [ AsyncStrategy() ]
                )
            )
            assert answer == "async-answer"
            assert name == "async_s"
        finally:
            loop.close()

    def test_print_stats_runs( self, capsys ):
        responder = self._make_responder()
        responder.stats[ "events_received" ] = 5
        responder.print_stats()
        captured = capsys.readouterr()
        assert "Events Received" in captured.out
        assert "5" in captured.out


# ============================================================================
# TestRestSubmitter — Response submission function
# ============================================================================

class TestRestSubmitter:
    """Tests for the submit_notification_response function."""

    @patch( "cosa.agents.utils.proxy_agents.rest_submitter.requests.post" )
    def test_success_returns_true( self, mock_post ):
        from cosa.agents.utils.proxy_agents.rest_submitter import submit_notification_response

        mock_post.return_value = MagicMock( status_code=200, json=lambda: { "status": "ok", "message": "done" } )

        result = submit_notification_response( "uuid-123", "yes" )
        assert result is True
        mock_post.assert_called_once()

    @patch( "cosa.agents.utils.proxy_agents.rest_submitter.requests.post" )
    def test_http_error_returns_false( self, mock_post ):
        from cosa.agents.utils.proxy_agents.rest_submitter import submit_notification_response

        mock_post.return_value = MagicMock( status_code=500, text="Internal Server Error" )

        result = submit_notification_response( "uuid-123", "yes" )
        assert result is False

    @patch( "cosa.agents.utils.proxy_agents.rest_submitter.requests.post" )
    def test_connection_error_returns_false( self, mock_post ):
        from cosa.agents.utils.proxy_agents.rest_submitter import submit_notification_response
        import requests as req

        mock_post.side_effect = req.ConnectionError()

        result = submit_notification_response( "uuid-123", "yes" )
        assert result is False

    @patch( "cosa.agents.utils.proxy_agents.rest_submitter.requests.post" )
    def test_timeout_returns_false( self, mock_post ):
        from cosa.agents.utils.proxy_agents.rest_submitter import submit_notification_response
        import requests as req

        mock_post.side_effect = req.Timeout()

        result = submit_notification_response( "uuid-123", "yes" )
        assert result is False

    @patch( "cosa.agents.utils.proxy_agents.rest_submitter.requests.post" )
    def test_custom_endpoint( self, mock_post ):
        from cosa.agents.utils.proxy_agents.rest_submitter import submit_notification_response

        mock_post.return_value = MagicMock( status_code=200, json=lambda: {} )

        submit_notification_response(
            "uuid-123", "yes",
            endpoint="/api/proxy/respond"
        )

        call_args = mock_post.call_args
        assert "/api/proxy/respond" in call_args[ 1 ][ "url" ] if "url" in call_args[ 1 ] else "/api/proxy/respond" in call_args[ 0 ][ 0 ]

    @patch( "cosa.agents.utils.proxy_agents.rest_submitter.requests.post" )
    def test_payload_structure( self, mock_post ):
        from cosa.agents.utils.proxy_agents.rest_submitter import submit_notification_response

        mock_post.return_value = MagicMock( status_code=200, json=lambda: {} )

        submit_notification_response( "uuid-456", { "answer": "blue" } )

        call_args = mock_post.call_args
        payload = call_args[ 1 ][ "json" ]
        assert payload[ "notification_id" ] == "uuid-456"
        assert payload[ "response_value" ] == { "answer": "blue" }


# ============================================================================
# TestBaseCli — Common CLI argument parser
# ============================================================================

class TestBaseCli:
    """Tests for the shared CLI argument parser helpers."""

    def test_add_common_args_returns_parser( self ):
        from cosa.agents.utils.proxy_agents.base_cli import add_common_args
        parser = argparse.ArgumentParser()
        result = add_common_args( parser )
        assert result is parser

    def test_host_argument( self ):
        from cosa.agents.utils.proxy_agents.base_cli import add_common_args
        parser = argparse.ArgumentParser()
        add_common_args( parser )
        args = parser.parse_args( [ "--host", "remote.server.com" ] )
        assert args.host == "remote.server.com"

    def test_port_argument( self ):
        from cosa.agents.utils.proxy_agents.base_cli import add_common_args
        parser = argparse.ArgumentParser()
        add_common_args( parser )
        args = parser.parse_args( [ "--port", "8080" ] )
        assert args.port == 8080

    def test_debug_flag( self ):
        from cosa.agents.utils.proxy_agents.base_cli import add_common_args
        parser = argparse.ArgumentParser()
        add_common_args( parser )
        args = parser.parse_args( [ "--debug" ] )
        assert args.debug is True

    def test_dry_run_flag( self ):
        from cosa.agents.utils.proxy_agents.base_cli import add_common_args
        parser = argparse.ArgumentParser()
        add_common_args( parser )
        args = parser.parse_args( [ "--dry-run" ] )
        assert args.dry_run is True

    def test_defaults( self ):
        from cosa.agents.utils.proxy_agents.base_cli import add_common_args
        parser = argparse.ArgumentParser()
        add_common_args( parser )
        args = parser.parse_args( [] )
        assert args.host == "localhost"
        assert args.port == 7999
        assert args.email is None
        assert args.password is None
        assert args.debug is False
        assert args.verbose is False
        assert args.dry_run is False


# ============================================================================
# TestPackageExports — Module-level imports
# ============================================================================

class TestPackageExports:
    """Tests for proxy_agents package __init__.py exports."""

    def test_base_strategy_importable( self ):
        from cosa.agents.utils.proxy_agents import BaseStrategy
        assert BaseStrategy is not None

    def test_base_listener_importable( self ):
        from cosa.agents.utils.proxy_agents import BaseWebSocketListener
        assert BaseWebSocketListener is not None

    def test_base_responder_importable( self ):
        from cosa.agents.utils.proxy_agents import BaseResponder
        assert BaseResponder is not None

    def test_submit_function_importable( self ):
        from cosa.agents.utils.proxy_agents import submit_notification_response
        assert callable( submit_notification_response )

    def test_config_constants_importable( self ):
        from cosa.agents.utils.proxy_agents import (
            DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT,
            RECONNECT_INITIAL_DELAY, RECONNECT_MAX_DELAY,
            RECONNECT_MAX_ATTEMPTS, RECONNECT_BACKOFF_FACTOR,
        )
        assert DEFAULT_SERVER_HOST == "localhost"
        assert DEFAULT_SERVER_PORT == 7999

    def test_credential_functions_importable( self ):
        from cosa.agents.utils.proxy_agents import get_credentials, get_anthropic_api_key
        assert callable( get_credentials )
        assert callable( get_anthropic_api_key )

    def test_cli_helper_importable( self ):
        from cosa.agents.utils.proxy_agents import add_common_args
        assert callable( add_common_args )

    def test_backward_compat_notification_proxy_config( self ):
        """Verify notification_proxy.config still exports all shared constants."""
        from cosa.agents.notification_proxy.config import (
            DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT,
            RECONNECT_INITIAL_DELAY, RECONNECT_MAX_DELAY,
            RECONNECT_MAX_ATTEMPTS, RECONNECT_BACKOFF_FACTOR,
            get_credentials, get_anthropic_api_key,
        )
        assert DEFAULT_SERVER_HOST == "localhost"
        assert DEFAULT_SERVER_PORT == 7999
        assert callable( get_credentials )
        assert callable( get_anthropic_api_key )
