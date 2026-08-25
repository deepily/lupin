"""
Unit tests for the Claude Code runaway-memory watcher (store row df5c3696).

The point of the watcher is attribution: on 2026-08-22 two sessions were killed
at 229 GB and 124 GB and nobody could say WHICH sessions, because the listener
logs do not record the owner pid in a form that greps back. These tests pin the
resolution chain that closes that gap, and the alert policy that keeps the
resulting log readable.
"""

import re
import subprocess

import pytest

from cosa.utils import cc_memory_watch as watch
from cosa.utils.cc_memory_watch import (
    AlertTracker,
    KB_PER_GB,
    Sample,
    collect_samples,
    format_alert_line,
    is_claude_process,
    is_listener_process,
    main,
    parse_listener_owner_map,
    parse_scope_unit,
    parse_tmux_pane,
    parse_vm_rss_kb,
    resolve_tmux_session,
    run_once,
    _flag_value,
    _read,
    _read_argv,
    iter_pids,
)


LISTENER_ARGV = [
    "python3", "-m", "lupin_cli.claude_code.hooks.lib.cc_notification_listener",
    "--session-id", "0b7675fc", "--owner-pid", "751918",
    "--log-file", "/home/x/.claude/sessions/cc-listener-0b7675fc.log",
]


# ── parsers ──────────────────────────────────────────────────────────────────

def test_vm_rss_is_read_from_a_status_block():

    status = "Name:\tclaude\nVmPeak:\t 263893348 kB\nVmRSS:\t 229468532 kB\nThreads:\t12\n"

    assert parse_vm_rss_kb( status ) == 229468532


def test_a_status_block_without_vm_rss_yields_none_rather_than_zero():
    """A kernel thread reported at 0 GB is noise; absent is absent."""

    assert parse_vm_rss_kb( "Name:\tkthreadd\nThreads:\t1\n" ) is None


def test_the_cap_scope_resolves_back_to_a_session_name():

    cgroup = "0::/user.slice/user-1001.slice/user@1001.service/app.slice/lupin-cc-cc-reviewer-maria-1-772946.scope\n"

    unit, session = parse_scope_unit( cgroup )

    assert unit    == "lupin-cc-cc-reviewer-maria-1-772946"
    assert session == "cc-reviewer-maria-1"


def test_a_process_outside_a_cap_scope_resolves_to_nothing():

    unit, session = parse_scope_unit( "0::/user.slice/user-1001.slice/session-3.scope\n" )

    assert ( unit, session ) == ( None, None )


def test_tmux_pane_is_read_out_of_the_environment():

    environ = "TMUX=/tmp/tmux-1001/default,749117,2\nTMUX_PANE=%2\nSHELL=/bin/bash\n"

    assert parse_tmux_pane( environ ) == "%2"


def test_a_process_with_no_pane_resolves_to_nothing():

    assert parse_tmux_pane( "SHELL=/bin/bash\n" ) is None


# ── the attribution fix ──────────────────────────────────────────────────────

def test_the_listener_argv_maps_an_owner_pid_to_a_session_id():
    """
    THIS is the gap closed. The listener LOG never carried the owner pid in a
    greppable form — its command line always did.
    """

    assert parse_listener_owner_map( [ LISTENER_ARGV ] ) == { 751918: "0b7675fc" }


def test_equals_form_flags_are_understood_too():

    argv = [ "python3", "-m", "cc_notification_listener", "--session-id=abcd1234", "--owner-pid=99" ]

    assert parse_listener_owner_map( [ argv ] ) == { 99: "abcd1234" }


@pytest.mark.parametrize( "argv", [
    [ "python3", "-m", "cc_notification_listener", "--owner-pid", "99" ],          # no session id
    [ "python3", "-m", "cc_notification_listener", "--session-id", "abcd" ],       # no owner pid
    [ "python3", "-m", "cc_notification_listener", "--session-id", "a", "--owner-pid", "notanumber" ],
    [ "python3", "-m", "cc_notification_listener", "--session-id" ],               # flag with no value
] )
def test_a_listener_missing_either_id_is_skipped_never_guessed_at( argv ):

    assert parse_listener_owner_map( [ argv ] ) == {}


def test_flag_value_returns_none_when_the_flag_is_absent():

    assert _flag_value( [ "a", "b" ], "--missing" ) is None


# ── which processes count ────────────────────────────────────────────────────

def test_a_real_claude_session_is_recognised():

    assert is_claude_process( "claude\n", [ "claude", "--model", "claude-opus-5" ] )


@pytest.mark.parametrize( "comm,argv", [
    ( "claude-monitor", [ "/home/x/.local/bin/claude-monitor" ] ),   # the monitor UI
    ( "grep",           [ "grep", "claude" ] ),                      # a grep for the word
    ( "claude",         [] ),                                        # vanished mid-read
    ( "claude",         [ "/usr/bin/node", "claude.js" ] ),          # argv0 is not claude
] )
def test_look_alikes_are_not_alerted_on( comm, argv ):
    """A watcher that cries about the wrong process teaches people to ignore it."""

    assert not is_claude_process( comm, argv )


def test_a_listener_is_recognised_by_its_module_name():

    assert is_listener_process( LISTENER_ARGV )
    assert not is_listener_process( [ "claude", "--model", "x" ] )


# ── alert policy ─────────────────────────────────────────────────────────────

def test_nothing_is_said_below_the_threshold():

    tracker = AlertTracker( threshold_kb=100, restep_kb=50 )

    assert tracker.should_alert( 1, 99 ) is False


def test_the_crossing_is_reported_once():

    tracker = AlertTracker( threshold_kb=100, restep_kb=50 )

    assert tracker.should_alert( 1, 100 ) is True
    assert tracker.should_alert( 1, 120 ) is False   # still climbing, not far enough


def test_further_growth_re_alerts():

    tracker = AlertTracker( threshold_kb=100, restep_kb=50 )

    tracker.should_alert( 1, 100 )

    assert tracker.should_alert( 1, 150 ) is True


def test_dropping_back_below_the_threshold_re_arms_the_crossing():

    tracker = AlertTracker( threshold_kb=100, restep_kb=50 )

    tracker.should_alert( 1, 100 )

    assert tracker.should_alert( 1, 10 )  is False
    assert tracker.should_alert( 1, 100 ) is True


def test_a_pid_that_disappears_is_forgotten_so_a_recycled_pid_starts_clean():

    tracker = AlertTracker( threshold_kb=100, restep_kb=50 )

    tracker.should_alert( 1, 100 )
    tracker.forget_absent( { 2 } )

    assert tracker.should_alert( 1, 100 ) is True


def test_forgetting_leaves_live_pids_alone():

    tracker = AlertTracker( threshold_kb=100, restep_kb=50 )

    tracker.should_alert( 1, 100 )
    tracker.forget_absent( { 1 } )

    assert tracker.should_alert( 1, 100 ) is False


# ── the line itself ──────────────────────────────────────────────────────────

def test_an_alert_line_carries_pid_rss_and_the_resolved_session():

    sample = Sample(
        pid=765583, rss_kb=int( 21.4 * KB_PER_GB ), cmdline=[ "claude", "--model", "claude-opus-5" ],
        session_id="645d5fed", scope_unit="lupin-cc-cc-reviewer-maria-1-765583", tmux_session="cc-reviewer-maria-1",
    )

    line = format_alert_line( sample, int( 16 * KB_PER_GB ), "2026-08-22T12:55:18-0400" )

    assert "\n" not in line
    assert "pid=765583"                 in line
    assert "rss_gb=21.4"                in line
    assert "threshold_gb=16.0"          in line
    assert "session=645d5fed"           in line
    assert "tmux=cc-reviewer-maria-1"   in line
    assert "scope=lupin-cc-cc-reviewer-maria-1-765583" in line


def test_an_unresolved_session_reads_as_a_gap_not_as_a_blank():
    """The 08-22 failure was silence. An unknown owner must LOOK unknown."""

    line = format_alert_line( Sample( pid=1, rss_kb=1024, cmdline=[ "claude" ] ), 512, "T" )

    assert "session=unresolved" in line
    assert "tmux=unresolved"    in line
    assert "scope=none"         in line


def test_a_huge_command_line_is_truncated_and_newlines_removed():
    """A brief pasted into argv must not turn one alert into a hundred lines."""

    sample = Sample( pid=1, rss_kb=1024, cmdline=[ "claude", "a\nb" + "x" * 500 ] )

    line = format_alert_line( sample, 512, "T" )

    assert "\n" not in line
    assert len( line ) < 400


# ── tmux resolution ──────────────────────────────────────────────────────────

class FakeCompleted:

    def __init__( self, returncode, stdout ):

        self.returncode = returncode
        self.stdout     = stdout


def test_a_pane_resolves_to_its_tmux_session_name():

    def runner( argv, **kwargs ):

        assert argv[ :3 ] == [ "tmux", "display-message", "-p" ]
        return FakeCompleted( 0, "cc-reviewer-maria-1\n" )

    assert resolve_tmux_session( "%2", runner=runner ) == "cc-reviewer-maria-1"


def test_no_pane_means_no_lookup():

    def runner( argv, **kwargs ):

        raise AssertionError( "should not have shelled out" )

    assert resolve_tmux_session( None, runner=runner ) is None


@pytest.mark.parametrize( "outcome", [ "nonzero", "empty", "oserror", "timeout" ] )
def test_tmux_failing_is_a_missing_label_never_a_crash( outcome ):

    def runner( argv, **kwargs ):

        if outcome == "nonzero": return FakeCompleted( 1, "" )
        if outcome == "empty":   return FakeCompleted( 0, "  \n" )
        if outcome == "oserror": raise OSError( "no tmux" )
        raise subprocess.TimeoutExpired( cmd="tmux", timeout=5 )

    assert resolve_tmux_session( "%2", runner=runner ) is None


# ── proc IO ──────────────────────────────────────────────────────────────────

def test_reading_a_vanished_proc_file_returns_none_rather_than_raising():

    assert _read( "/proc/999999999/status" ) is None
    assert _read_argv( 999999999 ) is None


def test_reading_a_real_proc_file_works():

    assert "Name:" in _read( f"/proc/{__import__( 'os' ).getpid()}/status" )
    assert _read_argv( __import__( "os" ).getpid() )


def test_iter_pids_yields_only_numbers_and_includes_this_process():

    pids = list( iter_pids() )

    assert all( isinstance( pid, int ) for pid in pids )
    assert __import__( "os" ).getpid() in pids


# ── the scan, with the process table faked ───────────────────────────────────

@pytest.fixture
def fake_proc( monkeypatch ):
    """Install a synthetic process table: one claude, one listener, one impostor."""

    table = {
        751918: { "comm": "claude\n",         "argv": [ "claude" ] },
        752070: { "comm": "python3\n",        "argv": LISTENER_ARGV },
        14030:  { "comm": "claude-monitor\n", "argv": [ "/home/x/.local/bin/claude-monitor" ] },
    }

    monkeypatch.setattr( watch, "iter_pids", lambda: iter( table.keys() ) )
    monkeypatch.setattr( watch, "_read_argv", lambda pid: table[ pid ][ "argv" ] )
    monkeypatch.setattr( watch, "resolve_tmux_session", lambda pane, **kw: "cc-tmux-session-f587a06c" )

    def fake_read( path ):

        pid  = int( path.split( "/" )[ 2 ] )
        leaf = path.rsplit( "/", 1 )[ -1 ]

        if leaf == "comm":    return table[ pid ][ "comm" ]
        if leaf == "status":  return f"VmRSS:\t {int( 30 * KB_PER_GB )} kB\n"
        if leaf == "cgroup":  return "0::/user.slice/lupin-cc-worker-751918.scope\n"
        if leaf == "environ": return "TMUX_PANE=%2\0"

        return None

    monkeypatch.setattr( watch, "_read", fake_read )

    return table


def test_the_scan_finds_the_session_attributes_it_and_ignores_the_impostor( fake_proc ):

    samples = collect_samples()

    assert len( samples ) == 1

    sample = samples[ 0 ]

    assert sample.pid          == 751918
    assert sample.session_id   == "0b7675fc"          # from the listener's argv
    assert sample.scope_unit   == "lupin-cc-worker-751918"
    assert sample.tmux_session == "cc-tmux-session-f587a06c"
    assert round( sample.rss_gb ) == 30


def test_a_process_that_exits_mid_scan_is_skipped_not_reported_at_zero( monkeypatch, fake_proc ):

    monkeypatch.setattr( watch, "_read", lambda path: None if path.endswith( "status" ) else "claude\n" )

    assert collect_samples() == []


def test_a_process_whose_comm_vanishes_mid_scan_is_skipped( monkeypatch, fake_proc ):

    monkeypatch.setattr( watch, "_read", lambda path: None )

    assert collect_samples() == []


def test_a_process_with_no_argv_is_skipped( monkeypatch, fake_proc ):

    monkeypatch.setattr( watch, "_read_argv", lambda pid: None )

    assert collect_samples() == []


def test_run_once_emits_for_a_process_over_the_threshold( fake_proc ):

    lines   = []
    tracker = AlertTracker( threshold_kb=int( 16 * KB_PER_GB ), restep_kb=int( 8 * KB_PER_GB ) )

    samples = run_once( tracker, lines.append, now="2026-08-22T00:00:00-0400" )

    assert len( samples ) == 1
    assert len( lines )   == 1
    assert "session=0b7675fc" in lines[ 0 ]


def test_run_once_stays_silent_under_the_threshold( fake_proc ):

    lines = []

    run_once( AlertTracker( threshold_kb=int( 99 * KB_PER_GB ), restep_kb=1 ), lines.append )

    assert lines == []


def test_run_once_stamps_a_timestamp_when_none_is_supplied( fake_proc ):

    lines = []

    run_once( AlertTracker( threshold_kb=1, restep_kb=1 ), lines.append )

    assert lines[ 0 ].startswith( "20" )


# ── CLI ──────────────────────────────────────────────────────────────────────

def test_once_takes_a_single_pass_and_exits_clean( fake_proc, capsys ):

    assert main( [ "--once", "--threshold-gb", "1" ] ) == 0
    assert "[CC-MEM]" in capsys.readouterr().out


def test_report_lists_everything_seen_not_just_alerts( fake_proc, capsys ):

    main( [ "--once", "--report", "--threshold-gb", "999" ] )

    out = capsys.readouterr().out

    assert "[CC-MEM]" not in out          # nothing crossed
    assert "pid=751918" in out            # but the pass is still visible


def test_alerts_also_land_in_the_log_file( fake_proc, tmp_path, capsys ):

    log = tmp_path / "cc-memory.log"

    main( [ "--once", "--threshold-gb", "1", "--log", str( log ) ] )

    assert "[CC-MEM]" in log.read_text()


def test_a_nonsense_threshold_is_rejected_loudly( fake_proc ):

    with pytest.raises( SystemExit ):
        main( [ "--once", "--threshold-gb", "0" ] )


def test_the_loop_sleeps_between_passes_and_stops_on_interrupt( fake_proc, monkeypatch, capsys ):

    calls = []

    def fake_sleep( seconds ):

        calls.append( seconds )
        raise KeyboardInterrupt

    monkeypatch.setattr( watch.time, "sleep", fake_sleep )

    assert main( [ "--threshold-gb", "1", "--interval", "3" ] ) == 0
    assert calls == [ 3.0 ]


def test_sample_repr_names_the_session():

    assert "645d5fed" in repr( Sample( pid=1, rss_kb=2, cmdline=[], session_id="645d5fed" ) )


def test_a_status_block_with_no_vm_rss_field_is_skipped( monkeypatch, fake_proc ):
    """
    A kernel-thread-shaped status (present, but carrying no VmRSS) must drop the
    process rather than report it at 0 GB — a zero reads as 'healthy', which is
    the opposite of 'unknown'.
    """

    real_read = watch._read

    def read_without_rss( path ):

        if path.endswith( "status" ): return "Name:\tclaude\nThreads:\t12\n"

        return real_read( path )

    monkeypatch.setattr( watch, "_read", read_without_rss )

    assert collect_samples() == []


# ── The report stream carries time (row df5c3696, 2026-08-25) ─────────────────
# WHY THESE EXIST. The --report stream ran 20.9 hours with no timestamp on any line.
# Every line was true and the file could not answer the question it was collected
# for: peak RSS per process, yes — but no concurrency, no growth curve, no "what else
# was running when this one climbed". A box-level total derived from it came out at
# 1,164 concurrent processes and 698 GB, because with no time axis a pass boundary is
# only a heuristic. The number was withheld rather than defended, and the fix was one
# f-string plus a seam that already existed: run_once has always taken `now` and it
# was simply never passed, which is exactly why the ALERT lines carried time and the
# REPORT lines did not.

_TS_RE = re.compile( r"\bts=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}\b" )


@pytest.fixture
def two_claudes( monkeypatch ):
    """
    TWO claude processes, deliberately — `fake_proc` installs only one, and a single
    report line cannot disagree with itself about the time. A pass-grouping assertion
    over one line is vacuous: it passes against a per-line clock read just as happily
    as against a per-pass one, which is a test that cannot fail for the reason it was
    written. Measured: with one process the mutation went 3-passed; with two it goes red.
    """
    table = {
        751918: { "comm": "claude\n", "argv": [ "claude" ] },
        751919: { "comm": "claude\n", "argv": [ "claude" ] },
    }

    monkeypatch.setattr( watch, "iter_pids", lambda: iter( table.keys() ) )
    monkeypatch.setattr( watch, "_read_argv", lambda pid: table[ pid ][ "argv" ] )
    monkeypatch.setattr( watch, "resolve_tmux_session", lambda pane, **kw: "cc-tmux-session-f587a06c" )

    def fake_read( path ):
        pid  = int( path.split( "/" )[ 2 ] )
        leaf = path.rsplit( "/", 1 )[ -1 ]
        if leaf == "comm":    return table[ pid ][ "comm" ]
        if leaf == "status":  return f"VmRSS:\t {int( 30 * KB_PER_GB )} kB\n"
        if leaf == "cgroup":  return "0::/user.slice/lupin-cc-worker-751918.scope\n"
        if leaf == "environ": return "TMUX_PANE=%2\0"
        return None

    monkeypatch.setattr( watch, "_read", fake_read )
    return table


def _report_lines( capsys ):
    main( [ "--once", "--report", "--threshold-gb", "999" ] )
    return [ line for line in capsys.readouterr().out.splitlines() if "pid=" in line ]


def test_every_report_line_carries_an_iso_timestamp( fake_proc, capsys ):
    """
    THE RED against the pre-fix module: not one report line matched, because none
    carried a stamp at all.
    """
    lines = _report_lines( capsys )

    assert lines, "no report lines emitted at all"
    for line in lines:
        assert _TS_RE.search( line ), f"report line is time-blind: {line!r}"


def test_one_pass_shares_a_single_stamp( two_claudes, capsys ):
    """
    A pass must group by stamp EQUALITY. Reading the clock per line instead of per
    pass would still satisfy the test above while making a pass unreconstructable —
    which is the same defect wearing a timestamp. Proven to bite: with the clock read
    moved inside the loop, this goes red and the other stays green.
    """
    stamps = { _TS_RE.search( line ).group() for line in _report_lines( capsys ) }

    assert len( stamps ) == 1, f"one pass emitted {len( stamps )} distinct stamps: {stamps}"
