#!/usr/bin/env python3
"""
Regression test for the module-scoped `_auto_proxy_for_module` fixture
defined in `src/tests/smoke/conftest.py`.

Background:
  Under pytest, the legacy `pre_run_hook` startup path never fires, so
  `--auto-proxy` was a no-op until 2026-05-07 when a module-scoped autouse
  fixture was added. This test verifies the fixture actually launches a
  notification proxy subprocess and that it WS-authenticates against the
  Lupin server.

Behavior:
  - When `--auto-proxy` is NOT set, the test SKIPS (the fixture is a no-op
    and there is nothing to assert).
  - When `--auto-proxy` IS set, the fixture should have launched a proxy
    BEFORE this test runs. The test polls `/api/debug/websocket-state` and
    asserts the `"auto proxy"` session is registered with a non-empty
    user mapping.

Sad-path verification:
  Run with deliberately-bad credentials (`LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD=wrong`)
  and `--auto-proxy` — the fixture's `_start_proxy` should raise
  `RuntimeError`, the fixture should call `pytest.fail(..., pytrace=False)`,
  and pytest should report a clear setup error WITHOUT this test body
  executing.

Origin:
  `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/01-design.md`
  §Phase 5 (added 2026-05-07 by session 6825e6af).
"""

import os

import pytest
import requests

from tests.smoke.utilities.embedded_proxy import EmbeddedProxyMixin


class AutoProxyFixtureProbe( EmbeddedProxyMixin ):
    """
    Marker class so the module-scoped `_auto_proxy_for_module` fixture
    finds an `EmbeddedProxyMixin` subclass to instantiate. The fixture's
    introspection picks the first subclass DEFINED in this module, so this
    class drives the proxy profile + strategy used during the test.

    `deep_research` is chosen because its profile is small + side-effect
    free at startup (proxy connects + waits for notifications; the test
    only checks the WS connection, never triggers a notification).
    """

    PROXY_PROFILE  = "deep_research"
    PROXY_STRATEGY = "llm_script"


def test_fixture_started_proxy( request ):
    """
    Assert the auto-proxy fixture launched and WS-authenticated a proxy.

    Requires:
        - `--auto-proxy` is set (else SKIP)
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/_PASSWORD env vars set
        - Lupin server reachable at LUPIN_API_URL (default http://localhost:7999)

    Ensures:
        - `/api/debug/websocket-state` reports `"auto proxy"` in
          `active_connections`
        - `session_to_user["auto proxy"]` is a non-empty UUID
    """
    if not request.config.getoption( "--auto-proxy", default=False ):
        pytest.skip( "--auto-proxy not set; fixture is a no-op" )

    base_url = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
    resp     = requests.get( f"{base_url}/api/debug/websocket-state", timeout=5 )
    assert resp.status_code == 200, f"websocket-state returned {resp.status_code}: {resp.text[ :200 ]}"

    state           = resp.json()
    active          = state.get( "active_connections", [] )
    session_to_user = state.get( "session_to_user", {} )

    assert "auto proxy" in active, (
        f"Expected 'auto proxy' session in active_connections (proxy not registered).\n"
        f"  active_connections: {active}\n"
        f"  session_to_user:    {session_to_user}"
    )

    user_uuid = session_to_user.get( "auto proxy", "" )
    assert user_uuid, (
        f"'auto proxy' session present but session_to_user mapping is empty — "
        f"proxy authenticated as anonymous? session_to_user={session_to_user}"
    )

    print( f"\n  Fixture verified: 'auto proxy' session registered as user UUID {user_uuid}" )


# ===========================================================================
# Bug f6627036 guard — the proxy launch command must carry an explicit --port
# ===========================================================================
class _ProxyCmdProbe( EmbeddedProxyMixin ):
    """Minimal subclass so _build_proxy_command is callable without a server."""
    PROXY_PROFILE  = "deep_research"
    PROXY_STRATEGY = "llm_script"


@pytest.mark.parametrize(
    "lupin_api_url,expected_host,expected_port",
    [
        ( "http://localhost:8000", "localhost", "8000" ),   # :8000 suite — must NOT fall back to :7999
        ( "http://localhost:7999", "localhost", "7999" ),   # dev server
        ( None,                    "localhost", "7999" ),   # unset → default base URL, still EXPLICIT
    ],
)
def test_embedded_proxy_command_always_carries_target_port(
    lupin_api_url, expected_host, expected_port, monkeypatch
):
    """
    Bug f6627036: the launch command omitted --port, so the proxy fell back to
    its own DEFAULT_SERVER_PORT (:7999) and a :8000 --auto-proxy suite auto-
    answered interactive gates on the shared dev box. This guard asserts the
    command ALWAYS carries an explicit --host/--port resolved from the suite's
    own LUPIN_API_URL, so the silent :7999 default can never be reached again.
    A pure command-build check — no subprocess, no server, runs anywhere.
    """
    if lupin_api_url is None:
        monkeypatch.delenv( "LUPIN_API_URL", raising=False )
    else:
        monkeypatch.setenv( "LUPIN_API_URL", lupin_api_url )

    cmd = _ProxyCmdProbe()._build_proxy_command( "deep_research", "llm_script" )

    assert "--port" in cmd, f"launch command carries no --port → would default to :7999. cmd={cmd}"
    assert cmd[ cmd.index( "--port" ) + 1 ] == expected_port
    assert "--host" in cmd, f"launch command carries no --host. cmd={cmd}"
    assert cmd[ cmd.index( "--host" ) + 1 ] == expected_host


def test_embedded_proxy_command_passes_optional_flags():
    """--debug / --email / --password thread through when supplied; absent otherwise."""
    probe = _ProxyCmdProbe()

    bare = probe._build_proxy_command( "deep_research", "llm_script" )
    assert "--debug" not in bare and "--email" not in bare and "--password" not in bare

    full = probe._build_proxy_command(
        "deep_research", "llm_script", debug=True, email="e@x.com", password="pw"
    )
    assert "--debug" in full
    assert full[ full.index( "--email" ) + 1 ]    == "e@x.com"
    assert full[ full.index( "--password" ) + 1 ] == "pw"
