"""
Regression tests for cosa.agents.utils.voice_io.notify() decoupling.

Bug context (2026-04-14, session 5a620729):
  notify() used to gate dispatcher-dispatch on `is_voice_available()`, which
  cached the result of a probe call. If the probe threw on a mis-configured
  test environment, every subsequent notify() call silently degraded to a
  bare print() — no DB persistence, no WebSocket fanout, no UI interaction
  history. BFE and TFE job cards showed "No interactions recorded for this
  job" for this reason.

Fix: voice_io.notify() now ALWAYS dispatches via _cosa_interface.notify_progress
(except when cosa_interface is None or _force_cli_mode is set). TTS availability
is decided per-subscriber downstream, not globally at the agent.

These tests pin the new contract:
  1. If cosa_interface is configured, notify() dispatches regardless of voice
     availability state.
  2. If cosa_interface is None, notify() prints only.
  3. If the dispatcher raises, notify() still prints as a fallback.
  4. is_voice_available() is NOT called by notify() (no probe-side-effect).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cosa.agents.utils import voice_io


@pytest.fixture( autouse=True )
def reset_voice_module_state():
    """Reset module-level voice_io state between tests."""
    voice_io.reset_voice_check()
    voice_io.set_cli_mode( False )
    voice_io.clear_job_id()
    yield
    voice_io.reset_voice_check()
    voice_io.set_cli_mode( False )
    voice_io.clear_job_id()


@pytest.mark.asyncio
async def test_notify_dispatches_when_cosa_interface_is_configured():
    """notify() must always call cosa_interface.notify_progress when configured."""
    mock_iface = MagicMock()
    mock_iface.__name__ = "mock_cosa_interface"  # voice_io.configure logs .__name__
    mock_iface.notify_progress = AsyncMock()
    voice_io.configure( mock_iface )

    await voice_io.notify( "hello world", priority="high", job_id="bfe-test-1" )

    mock_iface.notify_progress.assert_awaited_once()
    call_kwargs = mock_iface.notify_progress.await_args.kwargs
    assert call_kwargs[ "message" ]  == "hello world"
    assert call_kwargs[ "priority" ] == "high"
    assert call_kwargs[ "job_id" ]   == "bfe-test-1"


@pytest.mark.asyncio
async def test_notify_prints_only_when_cosa_interface_is_none():
    """If cosa_interface is None, notify() should not attempt dispatch."""
    # Reach into module state to set the interface to None directly;
    # voice_io.configure() doesn't accept None (logs .__name__).
    voice_io._cosa_interface = None
    # Should not raise; just prints.
    await voice_io.notify( "cli-only message" )


@pytest.mark.asyncio
async def test_notify_prints_only_when_cli_mode_is_forced():
    """set_cli_mode(True) must short-circuit to print, skipping dispatcher."""
    mock_iface = MagicMock()
    mock_iface.__name__ = "mock_cosa_interface"  # voice_io.configure logs .__name__
    mock_iface.notify_progress = AsyncMock()
    voice_io.configure( mock_iface )
    voice_io.set_cli_mode( True )

    await voice_io.notify( "silenced" )

    mock_iface.notify_progress.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_falls_back_to_print_when_dispatcher_raises():
    """If dispatcher raises, notify() must not propagate; fall back to print."""
    mock_iface = MagicMock()
    mock_iface.__name__ = "mock_cosa_interface"  # voice_io.configure logs .__name__
    mock_iface.notify_progress = AsyncMock( side_effect=RuntimeError( "dispatcher boom" ) )
    voice_io.configure( mock_iface )

    # Should not raise even though notify_progress blew up.
    await voice_io.notify( "dispatcher failure path" )

    mock_iface.notify_progress.assert_awaited_once()


@pytest.mark.asyncio
async def test_notify_does_not_invoke_is_voice_available_probe():
    """
    Regression: the pre-fix code called is_voice_available() from notify(),
    which ran a PROBE notify itself. That caused cached-False failures to
    silently drop all future notifies. notify() must not invoke the probe.
    """
    mock_iface = MagicMock()
    mock_iface.__name__ = "mock_cosa_interface"  # voice_io.configure logs .__name__
    mock_iface.notify_progress = AsyncMock()
    voice_io.configure( mock_iface )

    with patch.object( voice_io, "is_voice_available", new=AsyncMock() ) as probe:
        await voice_io.notify( "no probe please" )
        probe.assert_not_called()

    # One dispatch call: the real notify. No probe side-call.
    assert mock_iface.notify_progress.await_count == 1


@pytest.mark.asyncio
async def test_notify_dispatches_even_after_voice_available_cached_false():
    """
    The bug: _voice_available cached False made every subsequent notify print-only.
    Fix: notify() must still dispatch regardless of _voice_available state.
    """
    mock_iface = MagicMock()
    mock_iface.__name__ = "mock_cosa_interface"  # voice_io.configure logs .__name__
    mock_iface.notify_progress = AsyncMock()
    voice_io.configure( mock_iface )

    # Simulate the stuck-False cache that used to break everything.
    voice_io._voice_available = False

    await voice_io.notify( "should still persist" )

    mock_iface.notify_progress.assert_awaited_once()
