"""
Unit tests for cosa.agents.deep_research.api_client.

NEW FILE 2026-05-31 by Extra 2 🪨 (CoSA coverage campaign, deep_research SDK/network
tier). This is the FIREWALLED Anthropic SDK boundary. COST-SAFETY INVARIANT: every
test mocks `AsyncAnthropic` (and its `.messages.create`) at the boundary so ZERO real
API calls fire, and the firewalled key is NEVER read — clients are built with an
explicit `api_key="test-key"` param, or env tests patch os.environ with `clear=True`
so the real ANTHROPIC_API_KEY_FIREWALLED can never resolve.

Boundary mocks: AsyncAnthropic, WebSearchRateLimiter, ApiResourceManager.get_arm,
ConfigurationManager, cu.get_api_key, voice_io.notify, asyncio.sleep. Retry-loop
exceptions are injected by patching the module's `anthropic` reference with fake
RateLimitError / APIStatusError classes.

Must run via run-sdk-cov.sh (api_client imports the SDK chain).
"""

import json
import unittest
from contextlib import contextmanager, ExitStack
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, AsyncMock

import cosa.agents.deep_research.api_client as ac
from cosa.agents.deep_research.config import ResearchConfig
from cosa.agents.deep_research.cost_tracker import BudgetExceededError


# ---------------------------------------------------------------------------
# Fake retry-loop exception types (patched onto ac.anthropic in retry tests)
# ---------------------------------------------------------------------------
class FakeRateLimitError( Exception ):
    pass


class FakeAPIStatusError( Exception ):
    def __init__( self, status_code ):
        super().__init__( f"status {status_code}" )
        self.status_code = status_code


@contextmanager
def make_client(
    api_key="test-key", config=None, cost_tracker=None, debug=False, verbose=False,
    cfgmgr_raises=False, env=None,
):
    """Build a ResearchAPIClient with ALL SDK/config boundaries mocked."""
    with ExitStack() as stack:
        mock_async_cls = stack.enter_context( patch.object( ac, "AsyncAnthropic" ) )
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock()
        mock_client.close           = AsyncMock()
        mock_async_cls.return_value = mock_client

        mock_rl_cls = stack.enter_context( patch.object( ac, "WebSearchRateLimiter" ) )
        mock_rl = MagicMock()
        mock_rl.wait_if_needed = AsyncMock( return_value=0.0 )
        mock_rl.record_usage   = MagicMock()
        mock_rl_cls.return_value = mock_rl

        if cfgmgr_raises:
            stack.enter_context( patch(
                "cosa.config.configuration_manager.ConfigurationManager",
                side_effect=RuntimeError( "no cfg" ),
            ) )
        else:
            mock_cfg = MagicMock()
            mock_cfg.get.side_effect = lambda key, default, return_type: default
            stack.enter_context( patch(
                "cosa.config.configuration_manager.ConfigurationManager",
                return_value=mock_cfg,
            ) )

        if env is not None:
            stack.enter_context( patch.dict( ac.os.environ, env, clear=True ) )

        client = ac.ResearchAPIClient(
            api_key=api_key, config=config, cost_tracker=cost_tracker,
            debug=debug, verbose=verbose,
        )
        yield client, mock_client, mock_rl


def make_response( blocks, in_tok=10, out_tok=5, stop="end_turn" ):
    return SimpleNamespace(
        content     = blocks,
        usage       = SimpleNamespace( input_tokens=in_tok, output_tokens=out_tok ),
        stop_reason = stop,
    )


class TestAnthropicImportGuard( unittest.TestCase ):
    """Cover the `except ImportError` arm of the optional-dependency guard (30-32)."""

    def test_import_failure_sets_unavailable( self ):
        import importlib, sys
        try:
            with patch.dict( sys.modules, { "anthropic": None } ):
                importlib.reload( ac )
                self.assertFalse( ac.ANTHROPIC_AVAILABLE )
                self.assertIsNone( ac.AsyncAnthropic )
        finally:
            # Restore genuine module state for every later test in the process.
            importlib.reload( ac )
        self.assertTrue( ac.ANTHROPIC_AVAILABLE )


class TestInit( unittest.TestCase ):

    def test_raises_when_sdk_unavailable( self ):
        with patch.object( ac, "ANTHROPIC_AVAILABLE", False ):
            with self.assertRaises( ImportError ):
                ac.ResearchAPIClient( api_key="k" )

    def test_explicit_api_key_param_wins( self ):
        with make_client( api_key="param-key" ) as ( client, _c, _rl ):
            self.assertEqual( client.api_key, "param-key" )
            self.assertEqual( client.key_source, "parameter" )

    def test_env_var_key_source( self ):
        with make_client( api_key=None, env={ ac.ENV_VAR_NAME: "env-key" } ) as ( client, _c, _rl ):
            self.assertEqual( client.api_key, "env-key" )
            self.assertEqual( client.key_source, "environment" )

    def test_local_file_key_source( self ):
        with patch( "cosa.utils.util.get_api_key", return_value="file-key" ):
            with make_client( api_key=None, env={ } ) as ( client, _c, _rl ):
                self.assertEqual( client.api_key, "file-key" )
                self.assertEqual( client.key_source, "local file" )

    def test_missing_key_raises_value_error_with_debug( self ):
        # env cleared + local-file load raises → debug print (153-154) → ValueError.
        with patch( "cosa.utils.util.get_api_key", side_effect=Exception( "no file" ) ):
            with self.assertRaises( ValueError ):
                with make_client( api_key=None, env={ }, debug=True ):
                    pass

    def test_missing_key_raises_value_error_no_debug( self ):
        # debug=False covers the 153 false arm of the local-file-load except.
        with patch( "cosa.utils.util.get_api_key", side_effect=Exception( "no file" ) ):
            with self.assertRaises( ValueError ):
                with make_client( api_key=None, env={ }, debug=False ):
                    pass

    def test_explicit_config_object_used( self ):
        cfg = ResearchConfig()
        with make_client( config=cfg ) as ( client, _c, _rl ):
            self.assertIs( client.config, cfg )

    def test_default_config_created_when_none( self ):
        with make_client( config=None ) as ( client, _c, _rl ):
            self.assertIsInstance( client.config, ResearchConfig )

    def test_config_manager_unavailable_uses_defaults_with_debug( self ):
        # cfgmgr raises → except fallback (182-188) with debug print.
        with make_client( cfgmgr_raises=True, debug=True ) as ( client, _c, _rl ):
            self.assertIsNotNone( client._rate_limiter )

    def test_config_manager_unavailable_uses_defaults_no_debug( self ):
        # cfgmgr raises + debug=False covers the 184->186 `if self.debug` false arm.
        with make_client( cfgmgr_raises=True, debug=False ) as ( client, _c, _rl ):
            self.assertIsNotNone( client._rate_limiter )

    def test_debug_success_path_prints( self ):
        # debug=True success path covers the 198-201 init prints.
        with make_client( debug=True ) as ( client, _c, _rl ):
            self.assertEqual( client.key_source, "parameter" )


class TestRateLimitNotify( unittest.IsolatedAsyncioTestCase ):

    async def test_notify_via_voice_io( self ):
        with make_client() as ( client, _c, _rl ):
            with patch(
                "cosa.agents.deep_research.voice_io.notify", new=AsyncMock(),
            ) as mock_notify:
                await client._rate_limit_notify( "delaying", "high" )
            mock_notify.assert_awaited_once_with( "delaying", priority="high" )

    async def test_notify_falls_back_on_error_with_debug( self ):
        with make_client( debug=True ) as ( client, _c, _rl ):
            with patch(
                "cosa.agents.deep_research.voice_io.notify",
                new=AsyncMock( side_effect=RuntimeError( "no voice" ) ),
            ):
                # except arm (216-219) with debug print — must not raise.
                await client._rate_limit_notify( "delaying", "low" )

    async def test_notify_falls_back_on_error_no_debug( self ):
        with make_client( debug=False ) as ( client, _c, _rl ):
            with patch(
                "cosa.agents.deep_research.voice_io.notify",
                new=AsyncMock( side_effect=RuntimeError( "no voice" ) ),
            ):
                await client._rate_limit_notify( "delaying", "low" )


class TestGetRateLimiter( unittest.TestCase ):
    def test_returns_rate_limiter_instance( self ):
        with make_client() as ( client, _c, mock_rl ):
            self.assertIs( client.get_rate_limiter(), client._rate_limiter )


class TestCallLeadAgent( unittest.IsolatedAsyncioTestCase ):
    async def test_delegates_to_call_api_with_lead_model( self ):
        with make_client() as ( client, _c, _rl ):
            client._call_api = AsyncMock( return_value="sentinel" )
            result = await client.call_lead_agent(
                system_prompt="sys", user_message="msg",
                use_extended_thinking=True, max_tokens=123, temperature=0.5,
            )
        self.assertEqual( result, "sentinel" )
        kwargs = client._call_api.call_args.kwargs
        self.assertEqual( kwargs[ "model" ], client.config.lead_model )
        self.assertFalse( kwargs[ "use_web_search" ] )
        self.assertTrue( kwargs[ "use_extended_thinking" ] )


class TestCallSubagent( unittest.IsolatedAsyncioTestCase ):

    async def test_web_search_via_arm( self ):
        with make_client() as ( client, _c, _rl ):
            client._call_api = AsyncMock( return_value=SimpleNamespace( input_tokens=77 ) )
            mock_arm = MagicMock()
            mock_arm.acquire     = AsyncMock()
            mock_arm.record_call = MagicMock()
            with patch( "cosa.utils.api_resource_manager.get_arm", return_value=mock_arm ):
                resp = await client.call_subagent( "sys", "q", subquery_index=0, use_web_search=True )
            mock_arm.acquire.assert_awaited_once_with( provider="anthropic_web_search" )
            mock_arm.record_call.assert_called_once_with(
                provider="anthropic_web_search", tokens=77,
            )
            self.assertEqual( resp.input_tokens, 77 )

    async def test_web_search_arm_uninit_fallback_with_delay_print( self ):
        # get_arm raises RuntimeError → local limiter fallback; debug + delay>0 print.
        with make_client( debug=True ) as ( client, _c, mock_rl ):
            client._call_api = AsyncMock( return_value=SimpleNamespace( input_tokens=42 ) )
            mock_rl.wait_if_needed = AsyncMock( return_value=2.5 )
            with patch( "cosa.utils.api_resource_manager.get_arm", side_effect=RuntimeError ):
                await client.call_subagent( "sys", "q", subquery_index=1, use_web_search=True )
            mock_rl.wait_if_needed.assert_awaited_once()
            mock_rl.record_usage.assert_called_once_with( tokens=42, call_type="web_search" )

    async def test_web_search_arm_uninit_fallback_no_print( self ):
        # debug=False + delay 0.0 covers the 306 `if self.debug and delay > 0` false arm.
        with make_client( debug=False ) as ( client, _c, mock_rl ):
            client._call_api = AsyncMock( return_value=SimpleNamespace( input_tokens=1 ) )
            mock_rl.wait_if_needed = AsyncMock( return_value=0.0 )
            with patch( "cosa.utils.api_resource_manager.get_arm", side_effect=RuntimeError ):
                await client.call_subagent( "sys", "q", subquery_index=2, use_web_search=True )
            mock_rl.record_usage.assert_called_once()

    async def test_no_web_search_skips_rate_limiting( self ):
        with make_client() as ( client, _c, mock_rl ):
            client._call_api = AsyncMock( return_value=SimpleNamespace( input_tokens=5 ) )
            with patch( "cosa.utils.api_resource_manager.get_arm" ) as mock_get_arm:
                await client.call_subagent( "sys", "q", subquery_index=3, use_web_search=False )
            mock_get_arm.assert_not_called()
            mock_rl.record_usage.assert_not_called()


class TestCallWithJsonOutput( unittest.IsolatedAsyncioTestCase ):

    @contextmanager
    def _client_returning( self, content ):
        with make_client() as ( client, _c, _rl ):
            client._call_api = AsyncMock(
                return_value=SimpleNamespace( content=content )
            )
            yield client

    async def test_plain_json( self ):
        with self._client_returning( '{"a": 1}' ) as client:
            result = await client.call_with_json_output( "sys", "msg" )
        self.assertEqual( result, { "a": 1 } )

    async def test_json_fenced( self ):
        with self._client_returning( '```json\n{"a": 2}\n```' ) as client:
            result = await client.call_with_json_output( "sys", "msg" )
        self.assertEqual( result, { "a": 2 } )

    async def test_bare_fenced( self ):
        with self._client_returning( '```\n{"a": 3}\n```' ) as client:
            result = await client.call_with_json_output( "sys", "msg", model="m" )
        self.assertEqual( result, { "a": 3 } )

    async def test_malformed_raises_value_error( self ):
        with self._client_returning( 'not json {' ) as client:
            with self.assertRaises( ValueError ):
                await client.call_with_json_output( "sys", "msg" )


class TestCallApi( unittest.IsolatedAsyncioTestCase ):

    async def test_full_block_extraction_with_web_search_and_cost( self ):
        # Covers system_prompt-present, temperature-added, web-search-tool, debug
        # prints, every block-loop arm (text / tool_use / web_search w&w/o content /
        # neither-type fall-through), and cost recording.
        blocks = [
            SimpleNamespace( text="Hello " ),
            SimpleNamespace( text="World" ),
            SimpleNamespace( type="tool_use" ),
            SimpleNamespace( type="web_search_tool_result", content=[ { "r": 1 } ] ),
            SimpleNamespace( type="web_search_tool_result" ),   # no .content → 478 false
            SimpleNamespace( type="other_block" ),              # 474/476 false fall-through
            SimpleNamespace(),                                  # no text, no type → fall-through
        ]
        cost_tracker = MagicMock()
        with make_client( cost_tracker=cost_tracker, debug=True ) as ( client, _c, _rl ):
            client._call_with_retry = AsyncMock( return_value=make_response( blocks ) )
            resp = await client._call_api(
                model="m", system_prompt="sys", user_message="u",
                call_type="research", use_web_search=True, use_extended_thinking=False,
            )
        self.assertEqual( resp.content, "Hello World" )
        self.assertEqual( len( resp.tool_use ), 1 )
        self.assertEqual( resp.search_results, [ { "r": 1 } ] )
        self.assertEqual( resp.input_tokens, 10 )
        cost_tracker.record_from_response.assert_called_once()
        sent_kwargs = client._call_with_retry.call_args[ 0 ][ 0 ]
        self.assertIn( "tools", sent_kwargs )
        self.assertIn( "temperature", sent_kwargs )

    async def test_extended_thinking_omits_temperature_and_no_cost_tracker( self ):
        # system_prompt empty (438 false), extended thinking (442 false / 450 true),
        # no web search, cost_tracker None (skip), debug thinking print.
        with make_client( cost_tracker=None, debug=True ) as ( client, _c, _rl ):
            client._call_with_retry = AsyncMock(
                return_value=make_response( [ SimpleNamespace( text="x" ) ] )
            )
            await client._call_api(
                model="m", system_prompt="", user_message="u",
                use_web_search=False, use_extended_thinking=True,
            )
        sent_kwargs = client._call_with_retry.call_args[ 0 ][ 0 ]
        self.assertIn( "thinking", sent_kwargs )
        self.assertNotIn( "temperature", sent_kwargs )
        self.assertNotIn( "system", sent_kwargs )
        self.assertNotIn( "tools", sent_kwargs )

    async def test_no_debug_path( self ):
        # debug=False covers the 456/498 false arms.
        with make_client( debug=False ) as ( client, _c, _rl ):
            client._call_with_retry = AsyncMock(
                return_value=make_response( [ SimpleNamespace( text="y" ) ] )
            )
            resp = await client._call_api( model="m", system_prompt="s", user_message="u" )
        self.assertEqual( resp.content, "y" )

    async def test_budget_exceeded_propagates( self ):
        cost_tracker = MagicMock()
        cost_tracker.record_from_response.side_effect = BudgetExceededError( "over" )
        with make_client( cost_tracker=cost_tracker ) as ( client, _c, _rl ):
            client._call_with_retry = AsyncMock(
                return_value=make_response( [ SimpleNamespace( text="z" ) ] )
            )
            with self.assertRaises( BudgetExceededError ):
                await client._call_api( model="m", system_prompt="s", user_message="u" )


class TestCallWithRetry( unittest.IsolatedAsyncioTestCase ):

    @contextmanager
    def _retry_env( self, create_side_effect ):
        fake_anthropic = SimpleNamespace(
            RateLimitError=FakeRateLimitError, APIStatusError=FakeAPIStatusError,
        )
        with make_client() as ( client, mock_client, _rl ):
            mock_client.messages.create = AsyncMock( side_effect=create_side_effect )
            with patch.object( ac, "anthropic", fake_anthropic ), \
                 patch.object( ac.asyncio, "sleep", new=AsyncMock() ) as mock_sleep:
                yield client, mock_client, mock_sleep

    async def test_success_first_attempt( self ):
        good = make_response( [ SimpleNamespace( text="ok" ) ] )
        with self._retry_env( [ good ] ) as ( client, _c, mock_sleep ):
            result = await client._call_with_retry( { "model": "m" } )
        self.assertIs( result, good )
        mock_sleep.assert_not_awaited()

    async def test_web_search_config_branch( self ):
        good = make_response( [ SimpleNamespace( text="ok" ) ] )
        with self._retry_env( [ good ] ) as ( client, _c, _s ):
            result = await client._call_with_retry( { "model": "m" }, use_web_search=True )
        self.assertIs( result, good )

    async def test_rate_limit_exhausts_and_raises( self ):
        err = FakeRateLimitError( "rl" )
        with self._retry_env( err ) as ( client, _c, mock_sleep ):
            with self.assertRaises( FakeRateLimitError ):
                await client._call_with_retry( { "model": "m" }, max_retries=3 )
        # 3 sleeps (attempts 0,1,2); attempt 3 is the `attempt < max_retries` false arm.
        self.assertEqual( mock_sleep.await_count, 3 )

    async def test_server_error_5xx_exhausts_and_raises( self ):
        err = FakeAPIStatusError( 503 )
        with self._retry_env( err ) as ( client, _c, mock_sleep ):
            with self.assertRaises( FakeAPIStatusError ):
                await client._call_with_retry( { "model": "m" }, max_retries=2 )
        self.assertEqual( mock_sleep.await_count, 2 )

    async def test_client_error_4xx_raises_immediately( self ):
        err = FakeAPIStatusError( 404 )
        with self._retry_env( err ) as ( client, _c, mock_sleep ):
            with self.assertRaises( FakeAPIStatusError ):
                await client._call_with_retry( { "model": "m" } )
        mock_sleep.assert_not_awaited()

    async def test_generic_exception_exhausts_and_raises( self ):
        err = ValueError( "boom" )
        with self._retry_env( err ) as ( client, _c, mock_sleep ):
            with self.assertRaises( ValueError ):
                await client._call_with_retry( { "model": "m" }, max_retries=1 )
        self.assertEqual( mock_sleep.await_count, 1 )


class TestClose( unittest.IsolatedAsyncioTestCase ):

    async def test_close_awaits_client_close( self ):
        with make_client() as ( client, mock_client, _rl ):
            await client.close()
            mock_client.close.assert_awaited_once()

    async def test_close_noop_when_no_close_method( self ):
        with make_client() as ( client, _c, _rl ):
            client._client = SimpleNamespace()   # no .close attribute
            await client.close()                  # hasattr false → no-op, must not raise


class TestAPIResponseDataclass( unittest.TestCase ):
    def test_defaults( self ):
        r = ac.APIResponse(
            content="c", model="m", input_tokens=1, output_tokens=2, stop_reason="end_turn",
        )
        self.assertEqual( r.tool_use, [ ] )
        self.assertEqual( r.search_results, [ ] )
        self.assertIsNone( r.raw_response )


if __name__ == "__main__":
    unittest.main()
