"""
Row 204911ca §9(a) — the SessionStart banner must NAME the server's condition.

WHAT THIS GUARDS. `:7999` runs `uvicorn --reload`. The reloader parent keeps the
listening socket bound across a restart, so during a reload the kernel ACCEPTS a
connection that nothing is there to answer: the client hangs and eventually
raises TimeoutError. A STOPPED server behaves differently — nothing holds the
port, so the kernel refuses instantly with URLError(ConnectionRefusedError).

The old banner flattened both into the single word "unreachable". That string is
what misdirected this row across two sessions: a reader saw "unreachable",
concluded the server was DOWN, and went looking for a dead server that was in
fact mid-restart and would have answered a few seconds later. The two conditions
demand opposite fixes ("start it" vs "wait"), so the banner now reports them
separately.

🔴 WHY THE BLACKHOLE SOCKET, AND WHY NOT A CLOSED PORT.
A closed port CANNOT exercise the hang path — it refuses instantly, which is the
OTHER branch. A test that reached for one would drive the refused arm while
believing it had tested the timeout arm, and would pass for the wrong reason.
The honest lever is a socket that binds and listens but never accept()s: the
handshake completes from the backlog, the request goes out, and no response ever
comes. That is the reload shape.

🔴 THE CONTROLS MUST BE ABLE TO FAIL.
`TestDiscriminatorCanFail` mutates the classifier's input to the WRONG condition
and asserts each arm goes RED. A discriminator only ever observed agreeing is
indistinguishable from one that cannot discriminate at all — so the red is
demonstrated, not assumed.
"""

import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert( 0, str( Path( __file__ ).resolve().parents[ 3 ] ) )

from lupin_cli.claude_code.hooks import register_session


URL = "http://127.0.0.1:7999"


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures — the two real conditions, produced rather than simulated
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def blackhole_url():
    """
    A URL pointing at a socket that LISTENS and never ACCEPTS.

    Reproduces the RELOAD condition: connection completes from the kernel
    backlog, request is written, no response ever arrives => TimeoutError.
    A closed port would give ConnectionRefusedError instead and would exercise
    the wrong branch entirely.
    """
    sock = socket.socket( socket.AF_INET, socket.SOCK_STREAM )
    sock.bind( ( "127.0.0.1", 0 ) )
    sock.listen( 8 )
    try:
        yield f"http://127.0.0.1:{sock.getsockname()[ 1 ]}"
    finally:
        sock.close()


@pytest.fixture
def closed_port_url():
    """
    A URL pointing at a port with nothing bound to it.

    Reproduces the STOPPED-SERVER condition: the kernel replies RST and urlopen
    raises URLError(ConnectionRefusedError) essentially instantly.
    """
    sock = socket.socket( socket.AF_INET, socket.SOCK_STREAM )
    sock.bind( ( "127.0.0.1", 0 ) )
    port = sock.getsockname()[ 1 ]
    sock.close()                                    # bound, then released
    return f"http://127.0.0.1:{port}"


def _probe( url, timeout ):
    """Issue the same HEAD /docs probe the banner issues; return the exception."""
    req = urllib.request.Request( f"{url}/docs", method="HEAD" )
    try:
        urllib.request.urlopen( req, timeout=timeout )
    except Exception as e:                          # noqa: BLE001 - we want the object
        return e
    pytest.fail( "probe unexpectedly succeeded — fixture did not produce a failure" )


# ═════════════════════════════════════════════════════════════════════════════
# The two conditions, end to end through a real socket
# ═════════════════════════════════════════════════════════════════════════════

class TestRealSocketConditions:

    def test_reload_shape_is_reported_as_maybe_restarting( self, blackhole_url ):
        """A bound-but-unanswering socket must NOT be called 'unreachable'."""
        exc    = _probe( blackhole_url, timeout=1 )
        status = register_session._classify_server_probe_error( exc, blackhole_url, 1 )

        assert "may be restarting" in status
        assert "no response in 1s" in status
        # The exact word that misdirected the row must not appear for this case.
        assert "unreachable" not in status
        assert "not running" not in status

    def test_stopped_server_is_reported_as_not_running( self, closed_port_url ):
        """A closed port must be named as a stopped server, not a slow one."""
        exc    = _probe( closed_port_url, timeout=1 )
        status = register_session._classify_server_probe_error( exc, closed_port_url, 1 )

        assert "not running" in status
        assert "connection refused" in status
        assert "may be restarting" not in status

    def test_the_two_conditions_render_differently( self, blackhole_url, closed_port_url ):
        """
        The whole point of the split. If these ever collapse to the same string
        the banner is back to being undiagnosable, whatever the wording says.
        """
        hung    = register_session._classify_server_probe_error(
            _probe( blackhole_url, timeout=1 ), blackhole_url, 1 )
        stopped = register_session._classify_server_probe_error(
            _probe( closed_port_url, timeout=1 ), closed_port_url, 1 )

        assert hung != stopped


# ═════════════════════════════════════════════════════════════════════════════
# 🔴 THE CONTROLS — each arm driven to RED against the wrong condition
# ═════════════════════════════════════════════════════════════════════════════

class TestDiscriminatorCanFail:
    """
    Feed each arm the OTHER condition's exception and assert the expected string
    does NOT appear. If any of these passes, the classifier is not classifying —
    it is returning one answer regardless of input, and every green above is
    green for the wrong reason.
    """

    def test_timeout_arm_goes_red_when_given_a_refusal( self ):
        refused = urllib.error.URLError( ConnectionRefusedError( 111, "refused" ) )
        status  = register_session._classify_server_probe_error( refused, URL, 3 )
        assert "may be restarting" not in status, (
            "the timeout wording fired on a REFUSAL — the arm does not discriminate"
        )

    def test_refused_arm_goes_red_when_given_a_timeout( self ):
        status = register_session._classify_server_probe_error( TimeoutError(), URL, 3 )
        assert "not running" not in status, (
            "the not-running wording fired on a TIMEOUT — the arm does not discriminate"
        )

    def test_reachable_arm_goes_red_when_given_a_transport_failure( self ):
        status = register_session._classify_server_probe_error( TimeoutError(), URL, 3 )
        assert "reachable (" not in status, (
            "a transport failure was reported as reachable"
        )


# ═════════════════════════════════════════════════════════════════════════════
# Branch coverage — every arm of the classifier, including both timeout shapes
# ═════════════════════════════════════════════════════════════════════════════

class TestClassifierBranches:

    def test_http_error_counts_as_reachable( self ):
        """The server ANSWERED. HEAD /docs may legitimately 405; that is not down."""
        exc = urllib.error.HTTPError( f"{URL}/docs", 405, "Method Not Allowed", {}, None )
        assert register_session._classify_server_probe_error( exc, URL, 3 ) == f"reachable ({URL})"

    def test_bare_timeout_is_recognised( self ):
        """The C1 shape: a timeout while READING propagates unwrapped."""
        status = register_session._classify_server_probe_error( TimeoutError(), URL, 3 )
        assert status == f"no response in 3s — may be restarting ({URL})"

    def test_wrapped_timeout_is_recognised( self ):
        """urllib wraps connect-phase OSErrors in URLError; unwrap before testing."""
        status = register_session._classify_server_probe_error(
            urllib.error.URLError( TimeoutError() ), URL, 3 )
        assert status == f"no response in 3s — may be restarting ({URL})"

    def test_wrapped_refusal_is_recognised( self ):
        status = register_session._classify_server_probe_error(
            urllib.error.URLError( ConnectionRefusedError( 111, "refused" ) ), URL, 3 )
        assert status == f"not running — connection refused ({URL})"

    def test_bare_refusal_is_recognised( self ):
        status = register_session._classify_server_probe_error(
            ConnectionRefusedError( 111, "refused" ), URL, 3 )
        assert status == f"not running — connection refused ({URL})"

    def test_unknown_condition_names_the_exception_instead_of_flattening( self ):
        """
        The fallback still says "unreachable" — but it NAMES the exception, so an
        unrecognised condition stays diagnosable instead of becoming one word.
        """
        status = register_session._classify_server_probe_error(
            urllib.error.URLError( OSError( "no route to host" ) ), URL, 3 )
        assert status == f"unreachable — OSError ({URL})"

    def test_timeout_budget_is_interpolated_not_hardcoded( self ):
        """The reported budget must track the constant, or the message goes stale."""
        status = register_session._classify_server_probe_error( TimeoutError(), URL, 17 )
        assert "no response in 17s" in status


# ═════════════════════════════════════════════════════════════════════════════
# The sizing constants — pinned to their derivation, not to a bare number
# ═════════════════════════════════════════════════════════════════════════════

OBSERVED_MAX_RELOAD_SECONDS = 18.76      # row 204911ca §5.0, current-config slice, n=143
OBSERVED_MIN_RELOAD_SECONDS = 6.59       # same slice — the shortest window ever observed
CALLS_PER_ATTEMPT           = 2          # login (:889) then /allocate (:920), same rung each


class TestBudgetSizing:

    def test_allocate_ladder_outlasts_the_observed_reload_maximum( self ):
        """
        FLOOR GUARD — stops anyone shrinking the ladder below the window.

        🔴 This is NOT evidence the resize was needed, and an earlier version of
        this test implied it was. It asserted `sum(ladder) > 18.76`, which the
        old (2,4,8) failed at 14 — but 14 was the wrong number. Each attempt
        makes TWO calls at the same rung, so the old ladder's wall clock was
        **28s** and already cleared 18.76s. Asserting on the tuple sum encoded
        the very arithmetic error F2 corrected. It now measures wall clock, and
        it passes for both ladders — which is the honest result.
        """
        wall_clock = sum( register_session._ALLOCATE_TIMEOUT_LADDER_SECONDS ) * CALLS_PER_ATTEMPT
        assert wall_clock > OBSERVED_MAX_RELOAD_SECONDS

    def test_most_rungs_can_outlast_the_shortest_observed_window( self ):
        """
        🔴 THE ACTUAL IMPROVEMENT THE RESIZE BUYS, stated so it can be checked.

        A rung whose budget is below the SHORTEST observed reload window (6.59s)
        can never succeed during any reload — that attempt is spent before the
        server could possibly answer. Under (2,4,8) only ONE rung cleared 6.59s,
        so two of three attempts were structurally wasted. Under (5,10,15) TWO
        clear it. A real gain, and a smaller one than "14s cannot cover 18.76s".
        """
        useful = [ r for r in register_session._ALLOCATE_TIMEOUT_LADDER_SECONDS
                   if r > OBSERVED_MIN_RELOAD_SECONDS ]
        assert len( useful ) >= 2

    def test_allocate_ladder_carries_stated_headroom( self ):
        """
        Headroom is stated as a multiplier over the observed max, never as a
        coverage figure.

        🔴 Measured on the WALL CLOCK, which is 2x the tuple sum: each attempt
        makes two calls (login, then /allocate) and both take the same rung's
        timeout. Asserting on `sum(ladder)` alone would encode the 30s figure
        that F2 corrected to 60s.
        """
        calls_per_attempt = 2
        wall_clock        = sum( register_session._ALLOCATE_TIMEOUT_LADDER_SECONDS ) * calls_per_attempt
        assert wall_clock / OBSERVED_MAX_RELOAD_SECONDS >= 1.5

    def test_first_attempt_pair_is_the_thing_that_covers_the_window( self ):
        """
        The contract is "cover an 18.76s window", not "finish inside N seconds".
        By the end of the second attempt-pair the elapsed budget must already
        exceed the observed max — i.e. coverage does not depend on spending the
        whole ladder.
        """
        ladder   = register_session._ALLOCATE_TIMEOUT_LADDER_SECONDS
        two_pair = ( ladder[ 0 ] + ladder[ 1 ] ) * 2
        assert two_pair > OBSERVED_MAX_RELOAD_SECONDS

    def test_ladder_attempts_increase( self ):
        """Each rung must be at least as generous as the last, or it is not a ladder."""
        ladder = register_session._ALLOCATE_TIMEOUT_LADDER_SECONDS
        assert list( ladder ) == sorted( ladder )

    def test_release_budget_outlasts_the_observed_reload_maximum( self ):
        assert register_session._SERVER_TRANSPORT_TIMEOUT_SECONDS > OBSERVED_MAX_RELOAD_SECONDS

    def test_banner_probe_stays_short_on_purpose( self ):
        """
        🔴 This assertion is the INVERSE of the others and that is deliberate.
        The banner probe runs on the session-boot path; sizing it like a
        transaction would stall EVERY boot by ~30s whenever the server is
        genuinely down. Its fix was the wording, not the number. If someone
        "completes" the reload-window sweep by bumping this too, this fails.
        """
        assert register_session._BANNER_PROBE_TIMEOUT_SECONDS < OBSERVED_MAX_RELOAD_SECONDS
        assert register_session._BANNER_PROBE_TIMEOUT_SECONDS != \
            register_session._SERVER_TRANSPORT_TIMEOUT_SECONDS


# ═════════════════════════════════════════════════════════════════════════════
# The banner itself — the wording has to survive the trip to the rendered block
# ═════════════════════════════════════════════════════════════════════════════

class TestRenderedBanner:
    """
    The classifier is only useful if its verdict reaches the block the session
    actually reads. These drive `_check_cosa_voice_status` end to end with the
    probe stubbed, so a regression that fixes the classifier but drops its result
    on the floor still fails.
    """

    def _banner_with_probe_raising( self, monkeypatch, exc ):
        def fake_urlopen( req, timeout=None ):
            raise exc
        monkeypatch.setattr( register_session.urllib.request, "urlopen", fake_urlopen )
        return register_session._check_cosa_voice_status()

    def test_banner_reports_restarting_for_a_timeout( self, monkeypatch ):
        block = self._banner_with_probe_raising( monkeypatch, TimeoutError() )
        assert "may be restarting" in block
        assert "Server  :" in block

    def test_banner_reports_not_running_for_a_refusal( self, monkeypatch ):
        block = self._banner_with_probe_raising(
            monkeypatch, urllib.error.URLError( ConnectionRefusedError( 111, "refused" ) ) )
        assert "not running" in block

    def test_banner_reports_reachable_on_success( self, monkeypatch ):
        monkeypatch.setattr(
            register_session.urllib.request, "urlopen", lambda req, timeout=None: object() )
        block = register_session._check_cosa_voice_status()
        assert "reachable" in block
        assert "may be restarting" not in block

    def test_banner_never_raises_on_an_unexpected_probe_error( self, monkeypatch ):
        """The banner is boot-path decoration; it must degrade, never abort."""
        block = self._banner_with_probe_raising( monkeypatch, RuntimeError( "boom" ) )
        assert "unreachable — RuntimeError" in block
