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
import tests.smoke.utilities.embedded_proxy as embedded_proxy_module


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
# Values used by the credential guards below. Deliberately NOT real credentials, and
# deliberately distinctive so an assertion failure names something greppable rather than
# printing whatever the operator's environment happens to hold.
#
# THE ANGLE BRACKETS ARE LOAD-BEARING. My first draft used `s3cr3t-not-a-real-password`,
# which reads as obviously fake to a human and which the repo's own pre-commit scanner
# (src/scripts/secret_scan.py) correctly flagged as a credential value — it judges shape,
# not intent, which is exactly what makes it useful. `<...>` is a form that scanner
# recognises as a placeholder, so this fixture cannot trip it now or in any future sweep.
# A test decoy that trips the credential scanner trains people to pass --no-verify, which
# costs more than the decoy is worth.
_TEST_EMAIL    = "guard-account@example.invalid"
_TEST_PASSWORD = "<placeholder-not-a-real-password>"


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
    """--debug threads through when supplied; absent otherwise."""
    probe = _ProxyCmdProbe()

    bare = probe._build_proxy_command( "deep_research", "llm_script" )
    assert "--debug" not in bare

    full = probe._build_proxy_command( "deep_research", "llm_script", debug=True )
    assert "--debug" in full


# ===========================================================================
# Row 4996e41c guard — the launch command must never carry a credential
# ===========================================================================
#
# This test replaces one that asserted the OPPOSITE. The previous version read
#
#     assert full[ full.index( "--password" ) + 1 ] == "pw"
#
# and passed for months, because it was written to describe the code rather than to
# constrain it. A credential in argv is readable by anyone on the box via `ps` and
# /proc/<pid>/cmdline, is captured by any transcript of the invocation, and outlives
# the process in scrollback. The suite was pinning that in place and calling it green.
#
# The fix is not "remember not to do it": the credential now travels in the child's
# environment, where only the process owner can read it, and these assertions fail if
# anything ever puts it back.


def test_launch_argv_never_carries_a_credential( monkeypatch ):
    """
    Ensures:
        - the argv actually handed to subprocess.Popen carries neither credential value
        - nor a --password / --email flag

    ⚠️ THIS ASSERTS THE REAL LAUNCH, NOT THE BUILDER, AND THE DIFFERENCE IS THE WHOLE
    TEST. My first version called _build_proxy_command directly with no credentials and
    asserted the flags were absent — which PASSED against the very implementation it was
    meant to catch, because that implementation only appended the flags when a caller
    supplied them. A guard that cannot fail against the defect it names is a comment.

    So this drives the same entry point the fixture drives, WITH credentials, and reads
    the argv off the intercepted Popen call. Against the argv implementation the password
    is right there in the command and this goes red.
    """
    captured = {}

    class _Sentinel( Exception ):
        pass

    def fake_popen( cmd, **kwargs ):
        captured[ "cmd" ] = cmd
        captured[ "env" ] = kwargs.get( "env" )
        raise _Sentinel( "intercepted before any process was started" )

    monkeypatch.setattr( embedded_proxy_module.subprocess, "Popen", fake_popen )

    probe = _ProxyCmdProbe()
    with pytest.raises( RuntimeError ):
        probe._start_proxy( email=_TEST_EMAIL, password=_TEST_PASSWORD )

    cmd    = captured[ "cmd" ]
    joined = " ".join( cmd )

    assert _TEST_PASSWORD not in joined, (
        "the password reached the launch argv, where `ps`, /proc/<pid>/cmdline and any "
        f"session transcript can read it (row 4996e41c). cmd={cmd}"
    )
    assert _TEST_EMAIL not in joined, f"the account email reached the launch argv. cmd={cmd}"
    for flag in ( "--password", "--email" ):
        assert flag not in cmd, f"{flag} is back in the launch argv. cmd={cmd}"


def test_launch_env_carries_the_credential_instead( monkeypatch ):
    """
    Ensures:
        - the values removed from argv actually reach the child, in its environment

    The other half of the pair. Without it, the argv guard above is satisfied by a change
    that simply drops the credentials on the floor — every proxy-backed suite would then
    fail to authenticate, and the guard would still be green.
    """
    captured = {}

    class _Sentinel( Exception ):
        pass

    def fake_popen( cmd, **kwargs ):
        captured[ "env" ] = kwargs.get( "env" )
        raise _Sentinel( "intercepted before any process was started" )

    monkeypatch.setattr( embedded_proxy_module.subprocess, "Popen", fake_popen )

    probe = _ProxyCmdProbe()
    with pytest.raises( RuntimeError ):
        probe._start_proxy( email=_TEST_EMAIL, password=_TEST_PASSWORD )

    env = captured[ "env" ]

    # ⚠️ COMPARE FIRST, ASSERT ON THE BOOLEAN — never `assert env[ ... ] == _TEST_PASSWORD`.
    # pytest rewrites a bare comparison and prints BOTH sides on failure. When this test
    # fails, the left side is whatever the ambient environment holds — which on a
    # developer box or in the test container is the REAL test-account password. Writing
    # it the obvious way makes this guard a printer of the exact credential row 4996e41c
    # exists to stop leaking, and it fired that way once while being written: the failure
    # output carried the live 16-character value into a session transcript.
    #
    # Collapsing the comparison to a bool BEFORE the assert keeps the diff at
    # `assert False` and the secret out of the log, at the cost of a message that says
    # what went wrong instead of showing it. That is the correct trade for a credential.
    password_matched = env.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" ) == _TEST_PASSWORD
    email_matched    = env.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL"    ) == _TEST_EMAIL

    assert password_matched, (
        "the supplied password did not reach the child environment — value withheld "
        "deliberately; re-run with the launch env printed under a mask if you need detail"
    )
    assert email_matched, "the supplied email did not reach the child environment"


def test_credentials_reach_the_child_through_the_environment():
    """
    Ensures:
        - an explicitly supplied email/password lands in the child's env
        - it OVERRIDES an ambient value, which is what passing it used to mean
        - the caller's env dict is not mutated

    Removing the flags is only safe if the values still arrive. Without this, the
    argv guard above could be satisfied by a change that simply drops the credential
    on the floor and leaves every proxy-backed suite failing to authenticate.
    """
    probe    = _ProxyCmdProbe()
    # NOTE the closing brace on its own line. secret_scan.py's placeholder rule requires the
    # WHOLE extracted value to be `<...>`, and a trailing ` }` on the same line rides along
    # inside it, so the rule misses and a placeholder is reported as a credential. Cheap to
    # sidestep here; raised with Chloé as a scanner false positive rather than worked around
    # silently, because the next person will hit it and reach for --no-verify.
    ambient  = {
        "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL"    : "<ambient-email-placeholder>",
        "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" : "<ambient-placeholder>",
    }
    env      = probe._build_proxy_env( ambient, email="e@x.com", password=_TEST_PASSWORD )

    assert env[ "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL"    ] == "e@x.com"
    assert env[ "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" ] == _TEST_PASSWORD
    assert ambient[ "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" ] == "<ambient-placeholder>", "caller env was mutated"


def test_absent_credentials_leave_the_ambient_environment_alone():
    """
    Ensures:
        - passing no credentials does not blank out what the parent already had

    The fallback path: `base_config.get_credentials` reads these same variables from
    the inherited environment, so overwriting them with None would break every caller
    that relies on the ambient value rather than passing one.
    """
    probe   = _ProxyCmdProbe()
    ambient = { "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" : "<ambient-placeholder>" }
    env     = probe._build_proxy_env( ambient )

    assert env[ "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" ] == "<ambient-placeholder>"
