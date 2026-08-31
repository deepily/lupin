"""
`src/scripts/bounce_dev_warn.py` — the host-side warning broadcaster for the managed
`:7999` bounce. Previously at ZERO coverage, and not by accident of the census: the
coverage instrument itself said so —

    CoverageWarning: Module src/scripts/bounce_dev_warn.py was never imported.

⚠️ WHY A STEM GREP SAID OTHERWISE, since it is the trap that nearly cost this file its
turn. `git grep bounce_dev_warn -- src/tests` returns FOUR hits, which reads as covered.
All four are tests writing a FAKE `bounce_dev_warn.py` into a temp dir to stand in for
this one (`test_bounce_dev_server_busy_guard.py:66`, `_dirty_tree.py:56`,
`_warn_split.py:36`). The name appears most often exactly where the real code is being
AVOIDED. Empty is conclusive; a hit proves nothing. (Clayton 😎, 2026-08-30.)

WHAT IS WORTH ASSERTING HERE. This file is the I/O boundary — the poll and dedupe logic
lives in `cosa.rest.managed_bounce_broadcast` and is measured there. So these tests are
about the three exit codes, the branch that picks each one, and the two decisions the
source itself flags as easy to get wrong:

  - it must wait on `recipients` (pushes actually SCHEDULED), never on a session count.
    The source carries a "do not helpfully change this" comment; a test that cannot tell
    those apart leaves the comment as the only guard.
  - a config failure must fall back and still bounce, never raise.

🔴 FIXTURE DISCIPLINE. Every number below is DISTINCT from every other, and distinct from
the module's own defaults. Two interchangeable values cannot reveal a swap between them
(row `9ad838d6`): if `recipients` and `expected_recipients` were both 3, feeding the
poller the wrong one would change nothing observable and this file would pass on a broken
build. Same reason the config timings are 5.0/0.1 rather than the 8.0/0.25 defaults —
otherwise "read from config" and "fell back to defaults" are the same assertion.
"""
import importlib.util
import os
from pathlib import Path

import pytest


lupin_root  = os.environ[ "LUPIN_ROOT" ]
script_path = Path( lupin_root ) / "src" / "scripts" / "bounce_dev_warn.py"

spec            = importlib.util.spec_from_file_location( "bounce_dev_warn", script_path )
bounce_dev_warn = importlib.util.module_from_spec( spec )
spec.loader.exec_module( bounce_dev_warn )


# Deliberately unlike each other AND unlike the module defaults (8.0 / 0.25).
CONFIG_DEADLINE = 5.0
CONFIG_POLL     = 0.1

# recipients is what the poller must be keyed on. The other two exist so that keying on
# the wrong one produces a DIFFERENT number, not the same one.
RECIPIENTS          = 3
SESSIONS_COUNT      = 11
EXPECTED_RECIPIENTS = 99


def _ok_body( **over ):
    body = {
        "broadcast_id"        : "bc-2026-08-30",
        "recipients"          : RECIPIENTS,
        "expected_recipients" : EXPECTED_RECIPIENTS,
        "sessions"            : [ f"s{i}" for i in range( SESSIONS_COUNT ) ],
        "filtered_out"        : [ "someone" ],
    }
    body.update( over )
    return body


@pytest.fixture
def wired( monkeypatch ):
    """
    Replaces the three real boundaries — HTTP, the commons store, and the clock —
    and RECORDS what each was asked for, so a test can assert on the REQUEST rather
    than only on the exit code. An exit code alone cannot distinguish "waited on the
    right number" from "waited on the wrong number and got lucky".
    """
    seen = { "post": None, "poll": None }

    def fake_request( method, url, api_key, timeout=None, body=None ):
        seen[ "post" ] = { "method": method, "url": url, "body": body, "timeout": timeout }
        return True, 200, _ok_body()

    def fake_poll( **kw ):
        seen[ "poll" ] = kw
        return { "satisfied": True, "acked": RECIPIENTS, "elapsed": 0.4 }

    monkeypatch.setattr( bounce_dev_warn, "read_api_key",           lambda: "k-abc" )
    monkeypatch.setattr( bounce_dev_warn, "_request",               fake_request )
    monkeypatch.setattr( bounce_dev_warn, "poll_acks_until_satisfied", fake_poll )
    monkeypatch.setattr( bounce_dev_warn, "CommonsStore",           lambda root: object() )
    monkeypatch.setattr( bounce_dev_warn, "_ack_timing",            lambda: ( CONFIG_DEADLINE, CONFIG_POLL ) )
    monkeypatch.delenv( "BOUNCE_DIRTY_FILES", raising=False )
    monkeypatch.delenv( "BOUNCE_REASON",      raising=False )
    return seen


# ── the three exit codes ─────────────────────────────────────────────────────────

def test_every_recipient_acked_exits_zero( wired ):
    assert bounce_dev_warn.main() == 0


def test_a_partial_reach_exits_one_so_the_caller_can_say_how_many( monkeypatch, wired ):
    """
    1, not 0: the bounce proceeds either way, so the exit code is the ONLY channel that
    distinguishes "warned everybody" from "warned two of three and killed the server".
    """
    monkeypatch.setattr(
        bounce_dev_warn, "poll_acks_until_satisfied",
        lambda **kw: { "satisfied": False, "acked": 2, "elapsed": CONFIG_DEADLINE },
    )
    assert bounce_dev_warn.main() == 1


def test_a_failed_post_exits_two_and_never_polls( monkeypatch, wired ):
    """2 means the server is likely wedged — and nothing may wait on acks that cannot come."""
    polled = []
    monkeypatch.setattr( bounce_dev_warn, "_request", lambda *a, **kw: ( False, 503, "boom" ) )
    monkeypatch.setattr( bounce_dev_warn, "poll_acks_until_satisfied",
                         lambda **kw: polled.append( kw ) or { "satisfied": True, "acked": 0, "elapsed": 0 } )

    assert bounce_dev_warn.main() == 2
    assert polled == [], "polled for acks after failing to post the warning"


def test_a_two_hundred_carrying_a_non_dict_body_is_also_a_transport_failure( monkeypatch, wired ):
    """
    Distinct branch, same exit code, and worth its own test: `if not ok or not
    isinstance( body, dict )`. A test that only ever drove `ok=False` would leave the
    second half of that condition unmeasured while the code read as covered.
    """
    monkeypatch.setattr( bounce_dev_warn, "_request", lambda *a, **kw: ( True, 200, "not-a-dict" ) )
    assert bounce_dev_warn.main() == 2


def test_no_active_sessions_is_success_not_an_error( monkeypatch, wired ):
    """
    `recipients == 0` is a real, expected state (the server's own "no-active-sessions"),
    so it exits 0 -- warning nobody is not a failure to warn.
    """
    monkeypatch.setattr( bounce_dev_warn, "_request",
                         lambda *a, **kw: ( True, 200, _ok_body( recipients=0 ) ) )
    assert bounce_dev_warn.main() == 0


def test_zero_recipients_does_not_build_a_commons_store( monkeypatch, wired ):
    """The early return must happen BEFORE the filesystem is touched."""
    built = []
    monkeypatch.setattr( bounce_dev_warn, "_request",
                         lambda *a, **kw: ( True, 200, _ok_body( recipients=0 ) ) )
    monkeypatch.setattr( bounce_dev_warn, "CommonsStore", lambda root: built.append( root ) )

    bounce_dev_warn.main()

    assert built == []


# ── the decision the source flags as easy to get wrong ───────────────────────────

def test_the_wait_is_keyed_on_recipients_not_on_a_session_count( wired ):
    """
    The source says "do not helpfully change this to len(sessions)". This is what makes
    that comment enforceable: the body carries three DIFFERENT counts, so keying on the
    wrong one produces a different number rather than the same one.
    """
    bounce_dev_warn.main()

    assert wired[ "poll" ][ "expected_recipients" ] == RECIPIENTS
    assert wired[ "poll" ][ "expected_recipients" ] not in ( SESSIONS_COUNT, EXPECTED_RECIPIENTS )


def test_the_poll_inherits_the_resolved_timings_rather_than_the_defaults( wired ):
    """If these read 8.0/0.25, the config resolution was computed and then discarded."""
    bounce_dev_warn.main()

    assert wired[ "poll" ][ "deadline_seconds" ]      == CONFIG_DEADLINE
    assert wired[ "poll" ][ "poll_interval_seconds" ] == CONFIG_POLL


def test_the_broadcast_id_is_carried_into_the_wait( wired ):
    """Acks are matched by broadcast id; a dropped id would match another bounce's acks."""
    bounce_dev_warn.main()

    assert wired[ "poll" ][ "broadcast_id" ] == "bc-2026-08-30"


def test_the_warning_asks_for_acks( wired ):
    """`require_ack` is what makes the listeners write the acks this script waits on."""
    bounce_dev_warn.main()

    assert wired[ "post" ][ "body" ][ "require_ack" ] is True
    assert wired[ "post" ][ "method" ] == "POST"
    assert wired[ "post" ][ "url" ].endswith( bounce_dev_warn.BROADCAST_PATH )


# ── the two env-var seams, which exist to tell a human something ─────────────────

def test_the_dirty_file_list_reaches_the_message( monkeypatch, wired ):
    """
    This is how the owner of an uncommitted file learns their work is about to deploy.
    Asserted on the message the script BUILDS, since a non-TTY bouncer skips the prompt
    and the broadcast is the only place that fact appears.
    """
    monkeypatch.setenv( "BOUNCE_DIRTY_FILES", " M src/cosa/rest/queues.py" )
    seen = {}
    monkeypatch.setattr( bounce_dev_warn, "build_bounce_message",
                         lambda kind, dirty_files=None, reason=None:
                             seen.update( dirty_files=dirty_files, reason=reason ) or "msg" )

    bounce_dev_warn.main()

    assert seen[ "dirty_files" ] == " M src/cosa/rest/queues.py"


def test_the_reason_reaches_the_message( monkeypatch, wired ):
    """A peer holding armed probes needs to tell a needed bounce from a casual one."""
    monkeypatch.setenv( "BOUNCE_REASON", "picking up the replay user_id fix" )
    seen = {}
    monkeypatch.setattr( bounce_dev_warn, "build_bounce_message",
                         lambda kind, dirty_files=None, reason=None:
                             seen.update( dirty_files=dirty_files, reason=reason ) or "msg" )

    bounce_dev_warn.main()

    assert seen[ "reason" ] == "picking up the replay user_id fix"


@pytest.mark.parametrize( "var", [ "BOUNCE_DIRTY_FILES", "BOUNCE_REASON" ] )
def test_an_empty_env_var_becomes_none_rather_than_an_empty_string( monkeypatch, wired, var ):
    """
    `os.environ.get( x ) or None` — the `or None` is load-bearing. An empty string would
    render as a dirty-file section listing nothing, or a reason line saying nothing.
    """
    monkeypatch.setenv( var, "" )
    seen = {}
    monkeypatch.setattr( bounce_dev_warn, "build_bounce_message",
                         lambda kind, dirty_files=None, reason=None:
                             seen.update( dirty_files=dirty_files, reason=reason ) or "msg" )

    bounce_dev_warn.main()

    key = "dirty_files" if var == "BOUNCE_DIRTY_FILES" else "reason"
    assert seen[ key ] is None


def test_the_base_url_is_overridable( monkeypatch, wired ):
    """The bounce script points this at a non-default host in some environments."""
    monkeypatch.setenv( "LUPIN_BOUNCE_BASE_URL", "http://elsewhere:9999" )

    bounce_dev_warn.main()

    assert wired[ "post" ][ "url" ].startswith( "http://elsewhere:9999" )


# ── _ack_timing: a boundary whose whole job is to never raise ────────────────────

def test_config_timings_win_when_config_is_readable( monkeypatch ):
    monkeypatch.setattr( bounce_dev_warn, "resolve_ack_timing",
                         lambda cfg, default_deadline, default_poll: ( CONFIG_DEADLINE, CONFIG_POLL ) )
    assert bounce_dev_warn._ack_timing() == ( CONFIG_DEADLINE, CONFIG_POLL )


def test_a_broken_config_falls_back_instead_of_blocking_the_bounce( monkeypatch, capsys ):
    """
    The failure mode this guards is a bounce that cannot happen because config plumbing
    raised. It must fall back to the defaults AND say so on stderr — a silent fallback
    would leave a wrong timing looking like a deliberate one.
    """
    def explode( cfg, default_deadline, default_poll ):
        raise RuntimeError( "config is unreadable" )

    monkeypatch.setattr( bounce_dev_warn, "resolve_ack_timing", explode )

    assert bounce_dev_warn._ack_timing() == (
        bounce_dev_warn.DEFAULT_ACK_DEADLINE_S,
        bounce_dev_warn.DEFAULT_ACK_POLL_S,
    )
    assert "config unavailable" in capsys.readouterr().err


# ── the bootstrap, which runs at IMPORT and so cannot be reached by calling main() ──
#
# These three lines are the entry-point exception every `src/scripts` file carries: they
# run before `cosa` is importable. Importing the module once at the top of this file
# executes only the paths that were true for THIS process — LUPIN_ROOT set, `src` already
# on sys.path — so the failure branch and the insert are invisible to every test above.
# Re-executing the source under different conditions is the only way to reach them without
# a subprocess, and a subprocess would not be traced by this run's coverage.

def _exec_bootstrap_fresh( monkeypatch, *, lupin_root_value, path ):
    """Run the module's source top-to-bottom in a namespace we control."""
    import sys as _sys

    if lupin_root_value is None:
        monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    else:
        monkeypatch.setenv( "LUPIN_ROOT", lupin_root_value )
    monkeypatch.setattr( _sys, "path", path )

    fresh = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( fresh )
    return fresh


def test_a_missing_lupin_root_exits_two_before_importing_anything( monkeypatch, capsys ):
    """
    Exit 2, matching the transport-failure code, because from the bounce script's side
    both mean the same thing: the warning did not go out, so do not treat the bounce as
    warned. A bare traceback here would be an unhandled crash inside a shell pipeline.
    """
    with pytest.raises( SystemExit ) as exit_info:
        _exec_bootstrap_fresh( monkeypatch, lupin_root_value=None, path=list( __import__( "sys" ).path ) )

    assert exit_info.value.code == 2
    assert "LUPIN_ROOT not set" in capsys.readouterr().err


def test_src_is_put_on_the_path_when_it_is_missing( monkeypatch, tmp_path ):
    """
    The insert is skipped in a normal test run because `src` is already on sys.path — so
    it needs a path that genuinely lacks it. Pointing LUPIN_ROOT at a tmp dir makes the
    computed `src` a location nothing has added, which is the real condition, not a mock
    of it. `monkeypatch.setattr` restores the real sys.path afterwards.
    """
    import sys as _sys

    scratch = tmp_path / "fake-repo"
    ( scratch / "src" ).mkdir( parents=True )
    expected = os.path.join( str( scratch ), "src" )

    # A path list that still lets the cosa imports resolve, but lacks the computed entry.
    working = [ p for p in _sys.path if p != expected ]
    assert expected not in working

    _exec_bootstrap_fresh( monkeypatch, lupin_root_value=str( scratch ), path=working )

    assert working[ 0 ] == expected, "the bootstrap did not prepend the computed src path"
