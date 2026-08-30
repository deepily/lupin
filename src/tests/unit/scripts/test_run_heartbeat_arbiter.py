"""
Coverage ramp for `src/scripts/run-heartbeat-arbiter.py` — a straggler at zero on the
coverage-gate frame (unit + cosa, one data file), claimed in
`src/rnd/v0.2.1/2026.08.30-coverage-straggler-claim-ledger.md`.

LOAD MECHANISM: by-path `importlib.util.spec_from_file_location`, matching the other dashed
scripts in this directory. By-path load is what makes the module RE-loadable, which is the
only way to reach a bootstrap branch that has already run before any test starts.

🔴 THE THING THIS SCRIPT CAN DO WRONG IS PING THE REAL FLEET. `--live` hands the arbiter a
real `LupinArbiterGateway`, and a poll then sends real DMs and real surface posts to real
peers. The dry-run default is the SAFETY, so it is the thing most worth pinning, and these
tests pin it from both sides:

  · `_DryGateway` is exercised directly — `send_to` and `post` must LOG and return, never
    reach the inner gateway. A test asserts the inner object records nothing.
  · `main` is exercised for both flags, and the test for `--live` asserts the arbiter is
    handed the RAW gateway while the default hands it a `_DryGateway` WRAPPING that gateway.
    Asserting only "dry-run is the default" would pass if `--live` were also wired to the
    wrapper, which is the mistake that would make the flag silently do nothing.

🔴 NOTHING HERE CONSTRUCTS A REAL GATEWAY OR A REAL ARBITER. `mod.LupinArbiterGateway` and
`mod.ArbiterConsumerJob` are replaced at the MODULE attribute, so a missed patch surfaces as
an error rather than as a session reading `~/.claude/heartbeat-events/` and posting to
commons. `LupinArbiterGateway.from_environment` is itself marked `pragma: no cover` as a
production IO boundary — that is the seam, and this suite stops at it.

⚠️ NO REAL LOOPING. `do_all()` never returns on its own in production. The fake arbiter runs
a fixed number of polls and returns, so the loop's per-poll summary line is measured without
anything spinning.
"""

import importlib.util
import os
import sys

import pytest


_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
_PATH = os.path.join( _ROOT, "src", "scripts", "run-heartbeat-arbiter.py" )
_NAME = "run_heartbeat_arbiter_under_test"


def _load():
    """Import the dashed-filename script by path and return its namespace."""
    spec   = importlib.util.spec_from_file_location( _NAME, _PATH )
    module = importlib.util.module_from_spec( spec )
    sys.modules[ _NAME ] = module
    spec.loader.exec_module( module )
    return module


@pytest.fixture
def mod( monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", _ROOT )
    return _load()


# ── doubles ───────────────────────────────────────────────────────────────────

SUMMARY = { "sessions": 5, "edges": 1, "cycles": 0, "pings_fired": 0, "roster": 3 }


class _InnerGateway:
    """
    A stand-in for the real `LupinArbiterGateway`. It RECORDS what reaches it, so a test can
    show that the dry wrapper's `send_to`/`post` never arrive here — the whole safety claim.
    """

    def __init__( self ):
        self.who_calls = [ ]
        self.sent      = [ ]
        self.posted    = [ ]

    def who( self, retention_hours=24 ):
        self.who_calls.append( retention_hours )
        return [ { "persona": "Pocholo" } ]

    def send_to( self, recipient, body ):
        self.sent.append( ( recipient, body ) )

    def post( self, topic, body ):
        self.posted.append( ( topic, body ) )


class _FakeArbiter:
    """
    A stand-in for `ArbiterConsumerJob`: records its construction kwargs, and `do_all` runs a
    fixed number of polls through whatever `_poll_once` currently is — which is how the
    script's per-poll wrapper gets measured without an infinite loop.
    """

    instances = [ ]
    polls     = 2
    do_all_raises = None

    def __init__( self, **kwargs ):
        self.kwargs      = kwargs
        self.poll_count  = 0
        _FakeArbiter.instances.append( self )

    def _poll_once( self ):
        self.poll_count += 1
        return dict( SUMMARY )

    def do_all( self ):
        if _FakeArbiter.do_all_raises is not None: raise _FakeArbiter.do_all_raises
        for _ in range( _FakeArbiter.polls ):
            self._poll_once()


@pytest.fixture
def wired( mod, monkeypatch ):
    """Seams at the module attribute: no real gateway, no real arbiter, no real polling."""
    _FakeArbiter.instances     = [ ]
    _FakeArbiter.polls         = 2
    _FakeArbiter.do_all_raises = None

    inner = _InnerGateway()
    seen  = { "from_environment": [ ] }

    class _GatewayFactory:
        @staticmethod
        def from_environment( sender_session_id, persona_name="heartbeat-arbiter" ):
            seen[ "from_environment" ].append( ( sender_session_id, persona_name ) )
            return inner

    monkeypatch.setattr( mod, "LupinArbiterGateway", _GatewayFactory )
    monkeypatch.setattr( mod, "ArbiterConsumerJob", _FakeArbiter )
    monkeypatch.setattr( sys, "argv", [ "run-heartbeat-arbiter.py" ] )
    return { "inner": inner, "seen": seen, "arbiters": _FakeArbiter.instances }


def _last( wired ):
    return _FakeArbiter.instances[ -1 ]


# ── Module bootstrap ──────────────────────────────────────────────────────────

class TestBootstrap:

    def test_lupin_root_from_the_environment_is_used_when_it_is_set( self, monkeypatch ):
        monkeypatch.setenv( "LUPIN_ROOT", _ROOT )
        module = _load()
        assert module._lupin_root == _ROOT

    def test_an_unset_lupin_root_falls_back_to_the_scripts_own_repo_root( self, monkeypatch ):
        """
        The `or` arm. Unlike the other scripts in this directory this one does NOT refuse
        without the variable — it derives the root from its own location, so a bare
        `python src/scripts/run-heartbeat-arbiter.py` works. The fallback must land on the
        same repo, not on a parent directory.
        """
        monkeypatch.delenv( "LUPIN_ROOT", raising=False )

        module = _load()

        assert os.path.isdir( os.path.join( module._lupin_root, "src", "scripts" ) )
        assert os.path.samefile( module._lupin_root,
                                 os.path.dirname( os.path.dirname( os.path.dirname( _PATH ) ) ) )

    def test_an_empty_lupin_root_takes_the_fallback_rather_than_becoming_an_empty_path( self, monkeypatch ):
        """
        `or` and not `is None` on purpose. `LUPIN_ROOT=""` would otherwise make `_src_path`
        the RELATIVE `"src"`, which resolves against the caller's cwd — a different tree.
        """
        monkeypatch.setenv( "LUPIN_ROOT", "" )

        module = _load()

        assert module._lupin_root != ""
        assert os.path.isabs( module._src_path )

    def test_a_path_without_src_gets_it_inserted_at_the_front( self, monkeypatch ):
        """`insert( 0, … )`, not append — src must win over anything already on the path."""
        monkeypatch.setenv( "LUPIN_ROOT", _ROOT )
        src = os.path.join( _ROOT, "src" )
        monkeypatch.setattr( sys, "path", [ p for p in sys.path if p != src ] )

        _load()

        assert sys.path[ 0 ] == src

    def test_reloading_with_src_already_present_does_not_duplicate_it( self, monkeypatch ):
        """The guard's FALSE half — an unconditional insert would grow sys.path per import."""
        monkeypatch.setenv( "LUPIN_ROOT", _ROOT )
        src    = os.path.join( _ROOT, "src" )
        before = sys.path.count( src )
        assert before >= 1, "precondition: this test session already put src on the path"

        _load()

        assert sys.path.count( src ) == before


# ── _DryGateway — the safety ──────────────────────────────────────────────────

class TestDryGateway:

    def test_who_reads_through_to_the_real_gateway( self, mod ):
        """
        The roster and dependency graph must be REAL or the observation is worthless. Only
        the write side is suppressed, which is what makes this an observe mode rather than a
        simulation.
        """
        inner = _InnerGateway()

        assert mod._DryGateway( inner ).who() == [ { "persona": "Pocholo" } ]
        assert inner.who_calls == [ 24 ]

    def test_who_passes_the_retention_window_through_rather_than_defaulting_it_again( self, mod ):
        inner = _InnerGateway()

        mod._DryGateway( inner ).who( retention_hours=6 )

        assert inner.who_calls == [ 6 ]

    def test_send_to_logs_and_never_reaches_the_fleet( self, mod, capsys ):
        inner = _InnerGateway()

        mod._DryGateway( inner ).send_to( "Tiberius", "you are blocking three rows" )

        out = capsys.readouterr().out
        assert "[DRY] would PING" in out
        assert "Tiberius"         in out
        assert inner.sent == [ ], "a dry-run send reached the real gateway"

    def test_a_long_ping_body_is_truncated_in_the_log_line( self, mod, capsys ):
        """`body[ :140 ]` — one poll can intend many pings, and an untruncated dump buries them."""
        inner = _InnerGateway()

        mod._DryGateway( inner ).send_to( "Rio", "x" * 500 )

        printed = capsys.readouterr().out
        assert "x" * 140       in printed
        assert "x" * 141 not in printed

    def test_post_logs_and_never_reaches_the_fleet( self, mod, capsys ):
        inner = _InnerGateway()

        mod._DryGateway( inner ).post( "coordination", "roster" )

        out = capsys.readouterr().out
        assert "[DRY] would POST" in out
        assert "coordination"     in out
        assert inner.posted == [ ], "a dry-run post reached the real gateway"

    def test_a_multiline_post_body_is_indented_under_its_header( self, mod, capsys ):
        """Without the re-indent a multi-line surface post breaks the poll log's alignment."""
        inner = _InnerGateway()

        mod._DryGateway( inner ).post( "coordination", "line one\nline two" )

        assert "\n          line two" in capsys.readouterr().out


class TestLog:

    def test_the_notify_callback_prefixes_every_line_so_arbiter_output_is_attributable( self, mod, capsys ):
        mod._log( "escalating a deadlock" )
        assert "[arbiter] escalating a deadlock" in capsys.readouterr().out


# ── main ──────────────────────────────────────────────────────────────────────

class TestMainGatewayChoice:

    def test_the_default_wraps_the_real_gateway_in_the_dry_one( self, mod, wired ):
        mod.main()

        handed = _last( wired ).kwargs[ "commons" ]
        assert isinstance( handed, mod._DryGateway )
        assert handed._inner is wired[ "inner" ]

    def test_live_hands_the_arbiter_the_raw_gateway_not_the_wrapper( self, mod, wired, monkeypatch ):
        """
        The other half of the pair. A `--live` still wired to `_DryGateway` would leave the
        flag doing nothing while every test about the default kept passing.
        """
        monkeypatch.setattr( sys, "argv", [ "run-heartbeat-arbiter.py", "--live", "--once" ] )

        mod.main()

        assert _last( wired ).kwargs[ "commons" ] is wired[ "inner" ]

    def test_the_gateway_is_built_once_under_a_named_sender_and_persona( self, mod, wired ):
        mod.main()
        assert wired[ "seen" ][ "from_environment" ] == [ ( "arbiter-runner", "heartbeat-arbiter" ) ]

    def test_the_banner_says_which_mode_is_running( self, mod, wired, capsys ):
        mod.main()

        out = capsys.readouterr().out
        assert "DRY-RUN" in out
        assert "LIVE"    not in out

    def test_the_live_banner_says_it_is_pinging_the_fleet( self, mod, wired, monkeypatch, capsys ):
        monkeypatch.setattr( sys, "argv", [ "run-heartbeat-arbiter.py", "--live", "--once" ] )

        mod.main()

        assert "LIVE" in capsys.readouterr().out


class TestMainArguments:

    def test_the_defaults_match_the_ruled_thresholds( self, mod, wired ):
        """quiet=300, alive=600 — María's 2026-06-05 ruling, and the F3 invariant quiet < alive."""
        mod.main()

        kwargs = _last( wired ).kwargs
        assert kwargs[ "quiet_threshold_seconds" ] == 300
        assert kwargs[ "alive_threshold_seconds" ] == 600
        assert kwargs[ "quiet_threshold_seconds" ] < kwargs[ "alive_threshold_seconds" ]
        assert kwargs[ "poll_seconds" ]      == 60
        assert kwargs[ "manager_recipient" ] == "Tiberius"

    def test_every_flag_reaches_the_arbiter_as_an_int_or_a_name( self, mod, wired, monkeypatch ):
        monkeypatch.setattr( sys, "argv", [ "run-heartbeat-arbiter.py", "--once",
                                            "--poll-seconds", "15", "--quiet", "120",
                                            "--alive", "900", "--manager", "Mr Radio" ] )

        mod.main()

        kwargs = _last( wired ).kwargs
        assert kwargs[ "poll_seconds" ]            == 15
        assert kwargs[ "quiet_threshold_seconds" ] == 120
        assert kwargs[ "alive_threshold_seconds" ] == 900
        assert kwargs[ "manager_recipient" ]       == "Mr Radio"

    def test_the_resilient_hold_reader_is_wired_in_rather_than_left_to_the_default( self, mod, wired ):
        """
        Row `011f1f90`: a hand-written hold lands in the repo root where the plain reader does
        not look, so the session parks invisibly and the poke keeps coming. This runner must
        pass the resilient reader or it reproduces that blindness.
        """
        mod.main()

        assert _last( wired ).kwargs[ "hold_reader_fn" ] is mod.read_hold_via_bridge

    def test_the_arbiters_own_logging_is_routed_through_the_prefixing_callback( self, mod, wired ):
        mod.main()
        assert _last( wired ).kwargs[ "notify_fn" ] is mod._log


class TestMainPolling:

    def test_once_runs_a_single_poll_and_prints_its_summary( self, mod, wired, monkeypatch, capsys ):
        monkeypatch.setattr( sys, "argv", [ "run-heartbeat-arbiter.py", "--once" ] )

        mod.main()

        assert _last( wired ).poll_count == 1
        assert "poll summary" in capsys.readouterr().out

    def test_the_loop_prints_one_numbered_line_per_poll_with_the_counts( self, mod, wired ):
        mod.main()
        assert _last( wired ).poll_count == 2

    def test_the_loop_line_carries_every_field_an_operator_reads( self, mod, wired, capsys ):
        _FakeArbiter.polls = 1

        mod.main()

        out = capsys.readouterr().out
        assert "poll #1"       in out
        assert "sessions=5"    in out
        assert "edges=1"       in out
        assert "cycles=0"      in out
        assert "pings_fired=0" in out
        assert "roster=3"      in out

    def test_the_poll_counter_advances_rather_than_reprinting_one( self, mod, wired, capsys ):
        """The `n[ 0 ] += 1` closure. A stuck counter makes a live loop look like one poll."""
        _FakeArbiter.polls = 3

        mod.main()

        out = capsys.readouterr().out
        assert "poll #1" in out and "poll #2" in out and "poll #3" in out

    def test_the_wrapper_returns_the_summary_so_the_arbiters_own_caller_still_gets_it( self, mod, wired ):
        """
        The wrapper replaces `_poll_once` on the instance. Swallowing its return value would
        starve any caller inside the arbiter that reads the poll result.
        """
        mod.main()

        assert _last( wired )._poll_once() == SUMMARY

    def test_ctrl_c_stops_cleanly_instead_of_dumping_a_traceback( self, mod, wired, capsys ):
        """A watcher is stopped by hand every time; a traceback on Ctrl-C would be its normal exit."""
        _FakeArbiter.do_all_raises = KeyboardInterrupt()

        mod.main()

        assert "stopped." in capsys.readouterr().out

    def test_ctrl_c_during_a_single_poll_is_caught_too( self, mod, wired, monkeypatch, capsys ):
        """The `try` wraps BOTH arms; catching only the loop would leave `--once` unguarded."""
        monkeypatch.setattr( sys, "argv", [ "run-heartbeat-arbiter.py", "--once" ] )

        def _interrupt( self ): raise KeyboardInterrupt()
        monkeypatch.setattr( _FakeArbiter, "_poll_once", _interrupt )

        mod.main()

        assert "stopped." in capsys.readouterr().out
