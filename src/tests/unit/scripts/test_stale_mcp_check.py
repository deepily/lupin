"""
Unit tests for `src/scripts/stale_mcp_check.py` — the check that runs OUTSIDE the
cosa-voice MCP processes and flags any whose start time predates a watched module.

WHY OUTSIDE: the in-process guard (row b5035039, merged 9f760b2a) runs inside the
process it is judging, so a stale process runs a stale guard. Only an outside reader
of /proc can see the process start time and the module mtimes at once.

HOW THE READS ARE INJECTED: every /proc read takes `proc_root`, so the tests build a
FAKE /proc tree in tmp_path and the real parser reads it — no hand-built dicts stand
in for `stat`, `cmdline`, `environ` or the `cwd` symlink. Module mtimes are set with
`os.utime` on real files. The tmux pane list is a callable passed in.

LOAD MECHANISM: `importlib.import_module( "stale_mcp_check" )` with `src/scripts` on
`sys.path`, matching `test_bridge_pin_sweep.py`.
"""

import importlib
import json
import os
import runpy
import subprocess
import sys

import pytest

# Bootstrap rule: a missing LUPIN_ROOT fails loudly. A cwd fallback would silently
# import the script from whichever tree the run happened to start in.
_ROOT = os.environ.get( "LUPIN_ROOT" )
if _ROOT is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
for _p in ( os.path.join( _ROOT, "src", "scripts" ), os.path.join( _ROOT, "src" ) ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

smc = importlib.import_module( "stale_mcp_check" )

SCRIPT_PATH = os.path.join( _ROOT, "src", "scripts", "stale_mcp_check.py" )

CLK_TCK   = 100
BOOT_TIME = 1_789_000_000
EDIT_TIME = BOOT_TIME + 10_000   # when the watched modules last changed
NOW       = BOOT_TIME + 50_000   # the injected wall clock


# ---------------------------------------------------------------------------
# fixture builders
# ---------------------------------------------------------------------------

def _make_tree( root, mtime=EDIT_TIME ):
    """
    Build a repo tree carrying the three watched modules, all stamped `mtime`.

    Requires:
        - root is an existing directory
    Ensures:
        - returns the tree's `src` directory
        - every WATCHED_MODULES file exists with that mtime
    """
    src = os.path.join( root, "src" )
    for rel in smc.WATCHED_MODULES:
        path = os.path.join( src, rel )
        os.makedirs( os.path.dirname( path ), exist_ok=True )
        with open( path, "w" ) as fh: fh.write( "# watched\n" )
        os.utime( path, ( mtime, mtime ) )
    return src


def _make_proc( proc_root, boot_time=BOOT_TIME ):
    """
    Create an empty fake /proc carrying `uptime` and a `stat` whose btime is truncated.

    Requires:
        - proc_root is a path that may not exist yet
    Ensures:
        - proc_root/uptime reads NOW - boot_time, as the kernel formats it
        - proc_root/stat carries btime truncated to whole seconds, as the kernel does,
          so a reader that used it would be caught by the fractional-boot test
    """
    os.makedirs( proc_root, exist_ok=True )
    with open( os.path.join( proc_root, "uptime" ), "w" ) as fh:
        fh.write( f"{NOW - boot_time:.2f} 1234.56\n" )
    with open( os.path.join( proc_root, "stat" ), "w" ) as fh:
        fh.write( f"cpu  1 2 3\nbtime {int( boot_time )}\nprocesses 9\n" )


def _add_pid( proc_root, pid, ppid, argv, start_epoch, cwd="/work", environ=None, comm="python", boot_time=BOOT_TIME ):
    """
    Add one fake process to the fake /proc.

    Requires:
        - _make_proc has run on proc_root
        - start_epoch >= BOOT_TIME
    Ensures:
        - proc_root/<pid>/{stat,cmdline,environ,cwd} exist in the kernel's formats
    """
    d = os.path.join( proc_root, str( pid ) )
    os.makedirs( d, exist_ok=True )
    ticks  = int( round( ( start_epoch - boot_time ) * CLK_TCK ) )
    # fields 3..21 then starttime as field 22; the rest padded
    fields = [ "S", str( ppid ) ] + [ "0" ] * 17 + [ str( ticks ) ] + [ "0" ] * 10
    with open( os.path.join( d, "stat" ), "w" ) as fh:
        fh.write( f"{pid} ({comm}) " + " ".join( fields ) + "\n" )
    with open( os.path.join( d, "cmdline" ), "wb" ) as fh:
        fh.write( b"\0".join( a.encode() for a in argv ) + b"\0" )
    env = environ if environ is not None else {}
    with open( os.path.join( d, "environ" ), "wb" ) as fh:
        fh.write( b"".join( f"{k}={v}".encode() + b"\0" for k, v in env.items() ) )
    os.symlink( cwd, os.path.join( d, "cwd" ) )


def _mcp_argv( src ):
    return [ "/venv/bin/python", os.path.join( src, "lupin_mcp", "cosa_voice_mcp.py" ) ]


def _no_panes():
    return {}


@pytest.fixture
def world( tmp_path ):
    """A fake /proc plus a repo tree whose watched modules changed at EDIT_TIME."""
    proc = str( tmp_path / "proc" )
    _make_proc( proc )
    src  = _make_tree( str( tmp_path / "repo" ) )
    return { "proc": proc, "src": src, "tmp": tmp_path }


def _census( world, **kw ):
    kw.setdefault( "self_pid", 99999 )
    kw.setdefault( "pane_lister", _no_panes )
    kw.setdefault( "clk_tck", CLK_TCK )
    kw.setdefault( "now", NOW )
    return smc.census( proc_root=world[ "proc" ], **kw )


# ---------------------------------------------------------------------------
# the defect: a process older than the code it loaded
# ---------------------------------------------------------------------------

class TestTheCheck:

    def test_a_process_started_before_a_watched_module_changed_is_STALE( self, world ):
        """The motivating case: pid 118385, up since 12:09, merge landed 14:20."""
        env = { "PYTHONPATH": world[ "src" ], "TMUX_PANE": "%3" }
        _add_pid( world[ "proc" ], 500, 400, _mcp_argv( world[ "src" ] ), EDIT_TIME - 3600, cwd="/seat/a", environ=env )
        _add_pid( world[ "proc" ], 400, 1, [ "claude", "--model", "x" ], EDIT_TIME - 3601, comm="claude" )

        panes = lambda: { 400: ( "cc-tmux-session-65ba404f", "%3" ) }
        [ rec ] = _census( world, pane_lister=panes )

        assert rec[ "pid" ] == 500
        assert rec[ "stale" ] is True
        assert rec[ "cwd" ] == "/seat/a"
        assert rec[ "pane_pid" ] == 400
        assert rec[ "tmux_session" ] == "cc-tmux-session-65ba404f"
        assert rec[ "tmux_pane" ] == "%3"
        assert sorted( m[ "rel" ] for m in rec[ "newer_modules" ] ) == sorted( smc.WATCHED_MODULES )

    def test_NEGATIVE_CONTROL_a_process_started_after_every_change_is_NOT_flagged( self, world ):
        env = { "PYTHONPATH": world[ "src" ] }
        _add_pid( world[ "proc" ], 501, 1, _mcp_argv( world[ "src" ] ), EDIT_TIME + 60, environ=env )

        [ rec ] = _census( world )

        assert rec[ "stale" ] is False
        assert rec[ "newer_modules" ] == []
        assert rec[ "unresolved" ] == []

    def test_ONE_newer_module_is_enough_and_is_the_one_named( self, world ):
        env  = { "PYTHONPATH": world[ "src" ] }
        core = os.path.join( world[ "src" ], "lupin_mcp", "self_respin_core.py" )
        os.utime( core, ( EDIT_TIME + 500, EDIT_TIME + 500 ) )
        _add_pid( world[ "proc" ], 502, 1, _mcp_argv( world[ "src" ] ), EDIT_TIME + 60, environ=env )

        [ rec ] = _census( world )

        assert rec[ "stale" ] is True
        assert [ m[ "rel" ] for m in rec[ "newer_modules" ] ] == [ "lupin_mcp/self_respin_core.py" ]

    def test_start_time_is_read_from_proc_stat_ticks_and_btime( self, world ):
        _add_pid( world[ "proc" ], 503, 1, _mcp_argv( world[ "src" ] ), BOOT_TIME + 1234.5 )
        [ rec ] = _census( world )
        assert rec[ "start_epoch" ] == pytest.approx( BOOT_TIME + 1234.5 )

    def test_a_FRACTIONAL_boot_time_does_not_make_a_fresh_process_read_as_stale( self, tmp_path ):
        """Live false positive 2026-09-16 21:53: btime truncation read a start 0.2s early.

        Boot at .70 of a second; modules written at start-0.3s. A reader using btime
        would compute the start 0.7s early — before the edit — and flag it.
        """
        boot = BOOT_TIME + 0.7
        proc = str( tmp_path / "proc" )
        _make_proc( proc, boot_time=boot )
        start = boot + 20_000.0
        src   = _make_tree( str( tmp_path / "repo" ), mtime=start - 0.3 )
        _add_pid( proc, 505, 1, _mcp_argv( src ), start, environ={ "PYTHONPATH": src }, boot_time=boot )

        [ rec ] = smc.census( proc_root=proc, self_pid=1, pane_lister=_no_panes, clk_tck=CLK_TCK, now=NOW )

        assert rec[ "start_epoch" ] == pytest.approx( start, abs=0.02 )
        assert rec[ "stale" ] is False

    def test_a_comm_with_spaces_and_parens_does_not_break_stat_parsing( self, world ):
        _add_pid( world[ "proc" ], 504, 7, _mcp_argv( world[ "src" ] ), BOOT_TIME + 42, comm="py (thon) x" )
        assert smc.read_stat( 504, world[ "proc" ] ) == ( 7, 42 * CLK_TCK )


# ---------------------------------------------------------------------------
# which processes are counted
# ---------------------------------------------------------------------------

class TestTheCensus:

    def test_the_census_excludes_its_own_process_and_its_own_shell( self, world ):
        """The row's recorded false positive: the sweep's own bash matched the pattern."""
        src = world[ "src" ]
        # a real MCP, and a "self" chain whose ancestors would match a naive pattern
        _add_pid( world[ "proc" ], 600, 1, _mcp_argv( src ), EDIT_TIME + 5 )
        _add_pid( world[ "proc" ], 700, 1, [ "/usr/bin/python", os.path.join( src, "lupin_mcp", "cosa_voice_mcp.py" ) ], EDIT_TIME - 5 )
        _add_pid( world[ "proc" ], 701, 700, [ "/bin/bash", "-c", "python stale_mcp_check.py cosa_voice_mcp.py" ], EDIT_TIME - 4 )
        _add_pid( world[ "proc" ], 702, 701, [ "/usr/bin/python3", "stale_mcp_check.py" ], EDIT_TIME - 3 )

        recs = _census( world, self_pid=702 )

        assert [ r[ "pid" ] for r in recs ] == [ 600 ]

    def test_a_process_that_merely_MENTIONS_the_file_in_an_argument_is_not_an_MCP( self, world ):
        """claude's prompt argv and a `bash -c` string both contain the name as a substring."""
        _add_pid( world[ "proc" ], 610, 1, [ "/home/u/.local/bin/claude", "--model", "x", "build a check for cosa_voice_mcp.py" ], EDIT_TIME - 9 )
        _add_pid( world[ "proc" ], 611, 1, [ "/bin/bash", "-c", "pgrep -f cosa_voice_mcp.py" ], EDIT_TIME - 9 )
        _add_pid( world[ "proc" ], 612, 1, [ "/usr/bin/vim", "/x/src/lupin_mcp/cosa_voice_mcp.py" ], EDIT_TIME - 9 )
        assert _census( world ) == []

    def test_other_python_launches_are_not_MCPs( self ):
        assert smc.mcp_launch( [ "python3", "stale_mcp_check.py" ], "/w" ) is None
        assert smc.mcp_launch( [ "python3", "-m", "pytest" ], "/w" ) is None
        assert smc.mcp_launch( [ "python3", "-m" ], "/w" ) is None
        assert smc.mcp_launch( [ "python3" ], "/w" ) is None
        assert smc.mcp_launch( [ "python3", "-c", "import x", "cosa_voice_mcp.py" ], "/w" ) is None
        assert smc.mcp_launch( [ "python3", "-", "cosa_voice_mcp.py" ], "/w" ) is None

    def test_the_path_as_an_ARGUMENT_to_another_python_program_is_not_an_MCP( self ):
        """Review finding (Krishna): any argv element named cosa_voice_mcp.py used to qualify."""
        path = "/x/src/lupin_mcp/cosa_voice_mcp.py"
        assert smc.mcp_launch( [ "python3", "-m", "py_compile", path ], "/w" ) is None
        assert smc.mcp_launch( [ "python3", "-m", "pytest", path ], "/w" ) is None
        assert smc.mcp_launch( [ "python3", "lint.py", path ], "/w" ) is None
        assert smc.mcp_launch( [ "python3", "-u", "lint.py", path ], "/w" ) is None

    def test_interpreter_options_before_the_script_are_skipped( self ):
        path = "/x/src/lupin_mcp/cosa_voice_mcp.py"
        assert smc.mcp_launch( [ "python3", "-u", "-B", path ], "/w" ) == ( True, path )
        assert smc.mcp_launch( [ "python3", "-X", "dev", "-W", "error", path ], "/w" ) == ( True, path )
        assert smc.mcp_launch( [ "python3", "-u", "-m", "lupin_mcp.cosa_voice_mcp" ], "/w" ) == ( True, None )
        # an option value is not the script, even when it is spelled like one
        assert smc.mcp_launch( [ "python3", "-X", "cosa_voice_mcp.py" ], "/w" ) is None

    def test_a_py_compile_of_the_MCP_in_the_live_census_is_not_counted( self, world ):
        path = os.path.join( world[ "src" ], "lupin_mcp", "cosa_voice_mcp.py" )
        _add_pid( world[ "proc" ], 670, 1, [ "/venv/bin/python", "-m", "py_compile", path ], EDIT_TIME - 9 )
        _add_pid( world[ "proc" ], 671, 1, [ "/venv/bin/python", "-m", "pytest", path ], EDIT_TIME - 9 )
        assert _census( world ) == []

    def test_a_relative_script_with_no_readable_cwd_is_kept_as_given( self ):
        assert smc.mcp_launch( [ "python", "src/lupin_mcp/cosa_voice_mcp.py" ], None ) == ( True, "src/lupin_mcp/cosa_voice_mcp.py" )

    def test_an_empty_or_garbled_uptime_refuses( self, world ):
        path = os.path.join( world[ "proc" ], "uptime" )
        with open( path, "w" ): pass
        with pytest.raises( ValueError, match="empty" ):
            _census( world )
        with open( path, "w" ) as fh: fh.write( "abc 1.0\n" )
        with pytest.raises( ValueError ):
            _census( world )

    def test_module_form_launch_is_recognised( self, world ):
        env = { "PYTHONPATH": world[ "src" ] }
        _add_pid( world[ "proc" ], 620, 1, [ "python3.13", "-m", "lupin_mcp.cosa_voice_mcp" ], EDIT_TIME - 1, environ=env )
        [ rec ] = _census( world )
        assert rec[ "script" ] is None
        assert rec[ "stale" ] is True
        assert len( rec[ "newer_modules" ] ) == 3

    def test_a_relative_script_path_resolves_against_the_process_cwd( self, world ):
        repo = os.path.dirname( world[ "src" ] )
        _add_pid( world[ "proc" ], 630, 1, [ "python", "src/lupin_mcp/cosa_voice_mcp.py" ], EDIT_TIME + 1, cwd=repo )
        [ rec ] = _census( world )
        assert rec[ "script" ] == os.path.join( repo, "src", "lupin_mcp", "cosa_voice_mcp.py" )
        assert rec[ "stale" ] is False
        assert rec[ "unresolved" ] == []

    def test_a_process_that_exits_mid_census_is_skipped_not_crashed( self, world ):
        _add_pid( world[ "proc" ], 640, 1, _mcp_argv( world[ "src" ] ), EDIT_TIME + 1 )
        os.remove( os.path.join( world[ "proc" ], "640", "stat" ) )
        assert _census( world ) == []

    def test_non_pid_entries_and_unreadable_cmdlines_are_ignored( self, world ):
        os.makedirs( os.path.join( world[ "proc" ], "self_not_a_pid" ) )
        os.makedirs( os.path.join( world[ "proc" ], "650" ) )   # no cmdline at all
        assert _census( world ) == []

    def test_an_empty_cmdline_kernel_thread_is_ignored( self, world ):
        _add_pid( world[ "proc" ], 660, 2, [], EDIT_TIME )
        with open( os.path.join( world[ "proc" ], "660", "cmdline" ), "wb" ): pass
        assert _census( world ) == []


# ---------------------------------------------------------------------------
# resolving which files the process actually imports
# ---------------------------------------------------------------------------

class TestModuleResolution:

    def test_imports_follow_the_process_PYTHONPATH_not_the_caller_tree( self, world, tmp_path ):
        """A seat launched against tree B imports B's modules even if the script sits in A."""
        other = _make_tree( str( tmp_path / "other" ), mtime=BOOT_TIME + 1 )
        env   = { "PYTHONPATH": "/nonexistent:" + other }
        _add_pid( world[ "proc" ], 700, 1, _mcp_argv( world[ "src" ] ), BOOT_TIME + 100, environ=env )

        [ rec ] = _census( world )

        by_rel = { m[ "rel" ]: m[ "path" ] for m in rec[ "modules" ] }
        assert by_rel[ "lupin_mcp/self_respin_core.py" ].startswith( other )
        # the script itself is the argv path, whatever PYTHONPATH says
        assert by_rel[ "lupin_mcp/cosa_voice_mcp.py" ].startswith( world[ "src" ] )
        assert [ m[ "rel" ] for m in rec[ "newer_modules" ] ] == [ "lupin_mcp/cosa_voice_mcp.py" ]

    def test_without_PYTHONPATH_the_script_tree_is_the_fallback( self, world ):
        _add_pid( world[ "proc" ], 710, 1, _mcp_argv( world[ "src" ] ), EDIT_TIME - 1 )
        [ rec ] = _census( world )
        assert all( m[ "path" ].startswith( world[ "src" ] ) for m in rec[ "modules" ] )
        assert rec[ "stale" ] is True

    def test_LUPIN_ROOT_of_the_process_is_a_fallback_for_module_form( self, world ):
        repo = os.path.dirname( world[ "src" ] )
        _add_pid( world[ "proc" ], 715, 1, [ "python", "-m", "lupin_mcp.cosa_voice_mcp" ], EDIT_TIME + 1, environ={ "LUPIN_ROOT": repo } )
        [ rec ] = _census( world )
        assert rec[ "unresolved" ] == []
        assert rec[ "stale" ] is False

    def test_a_module_found_nowhere_is_UNRESOLVED_not_fresh( self, world ):
        _add_pid( world[ "proc" ], 720, 1, [ "python", "-m", "lupin_mcp.cosa_voice_mcp" ], EDIT_TIME + 1, environ={ "PYTHONPATH": "/nowhere" } )
        [ rec ] = _census( world )
        assert rec[ "stale" ] is False
        assert sorted( rec[ "unresolved" ] ) == sorted( smc.WATCHED_MODULES )

    def test_a_script_deleted_since_launch_is_UNRESOLVED_not_a_crash( self, world, tmp_path ):
        gone = str( tmp_path / "reaped" / "src" / "lupin_mcp" / "cosa_voice_mcp.py" )
        _add_pid( world[ "proc" ], 722, 1, [ "python", gone ], EDIT_TIME + 1, environ={ "PYTHONPATH": world[ "src" ] } )
        [ rec ] = _census( world )
        assert rec[ "unresolved" ] == [ "lupin_mcp/cosa_voice_mcp.py" ]
        assert len( rec[ "modules" ] ) == 2

    def test_an_unreadable_environ_still_measures_via_the_script_tree( self, world ):
        _add_pid( world[ "proc" ], 725, 1, _mcp_argv( world[ "src" ] ), EDIT_TIME - 1 )
        os.remove( os.path.join( world[ "proc" ], "725", "environ" ) )
        [ rec ] = _census( world )
        assert rec[ "stale" ] is True
        assert rec[ "tmux_pane" ] is None

    def test_an_unreadable_cwd_is_reported_as_None( self, world ):
        _add_pid( world[ "proc" ], 730, 1, _mcp_argv( world[ "src" ] ), EDIT_TIME + 1 )
        os.remove( os.path.join( world[ "proc" ], "730", "cwd" ) )
        [ rec ] = _census( world )
        assert rec[ "cwd" ] is None


# ---------------------------------------------------------------------------
# pane / tmux lookup
# ---------------------------------------------------------------------------

class TestPaneLookup:

    def test_the_pane_is_the_nearest_ancestor_that_tmux_lists( self, world ):
        src = world[ "src" ]
        _add_pid( world[ "proc" ], 800, 1, [ "tmux" ], BOOT_TIME + 1 )
        _add_pid( world[ "proc" ], 801, 800, [ "bash" ], BOOT_TIME + 2 )
        _add_pid( world[ "proc" ], 802, 801, [ "claude" ], BOOT_TIME + 3 )
        _add_pid( world[ "proc" ], 803, 802, _mcp_argv( src ), EDIT_TIME + 1 )
        panes = lambda: { 801: ( "cc-author-x", "%9" ), 800: ( "wrong", "%0" ) }

        [ rec ] = _census( world, pane_lister=panes )

        assert ( rec[ "pane_pid" ], rec[ "tmux_session" ], rec[ "tmux_pane" ] ) == ( 801, "cc-author-x", "%9" )

    def test_no_tmux_ancestor_leaves_session_None_and_keeps_the_environ_pane( self, world ):
        _add_pid( world[ "proc" ], 810, 1, _mcp_argv( world[ "src" ] ), EDIT_TIME + 1, environ={ "TMUX_PANE": "%4" } )
        [ rec ] = _census( world )
        assert ( rec[ "pane_pid" ], rec[ "tmux_session" ], rec[ "tmux_pane" ] ) == ( None, None, "%4" )

    def test_an_ancestor_cycle_does_not_hang( self, world ):
        _add_pid( world[ "proc" ], 820, 821, [ "a" ], BOOT_TIME + 1 )
        _add_pid( world[ "proc" ], 821, 820, [ "b" ], BOOT_TIME + 1 )
        assert smc.ancestors( 820, world[ "proc" ] ) == [ 821 ]

    def test_default_tmux_lister_parses_list_panes( self, monkeypatch ):
        seen = {}

        def fake_run( cmd, **kw ):
            seen[ "cmd" ] = cmd
            out = "118310\tcc-tmux-session-65ba404f\t%3\ngarbage line\nnotapid\tx\t%1\n"
            return subprocess.CompletedProcess( cmd, 0, stdout=out, stderr="" )

        monkeypatch.setattr( smc.subprocess, "run", fake_run )
        assert smc.list_tmux_panes() == { 118310: ( "cc-tmux-session-65ba404f", "%3" ) }
        assert seen[ "cmd" ][ :3 ] == [ "tmux", "list-panes", "-a" ]

    def test_default_tmux_lister_returns_empty_when_tmux_is_absent_or_fails( self, monkeypatch ):
        def missing( cmd, **kw ): raise FileNotFoundError( "tmux" )
        monkeypatch.setattr( smc.subprocess, "run", missing )
        assert smc.list_tmux_panes() == {}

        def failing( cmd, **kw ): return subprocess.CompletedProcess( cmd, 1, stdout="", stderr="no server" )
        monkeypatch.setattr( smc.subprocess, "run", failing )
        assert smc.list_tmux_panes() == {}


# ---------------------------------------------------------------------------
# report and exit codes
# ---------------------------------------------------------------------------

class TestReport:

    def test_the_report_names_pid_start_pane_cwd_and_says_SEAT_RESTART_not_clear( self, world ):
        env = { "PYTHONPATH": world[ "src" ], "TMUX_PANE": "%3" }
        _add_pid( world[ "proc" ], 900, 1, _mcp_argv( world[ "src" ] ), EDIT_TIME - 60, cwd="/seat/radio", environ=env )
        recs = _census( world )
        text = smc.render_text( recs )

        assert "pid 900" in text
        assert "/seat/radio" in text
        assert "%3" in text
        assert smc.format_epoch( EDIT_TIME - 60 ) in text
        assert "SEAT RESTART" in text
        assert "/clear does NOT reload" in text
        assert "lupin_mcp/self_respin_core.py" in text

    def test_a_clean_report_states_the_denominator( self, world ):
        _add_pid( world[ "proc" ], 910, 1, _mcp_argv( world[ "src" ] ), EDIT_TIME + 60 )
        text = smc.render_text( _census( world ) )
        assert "1 live cosa_voice_mcp.py process(es), 0 stale" in text
        assert "SEAT RESTART" not in text

    def test_an_unresolved_module_is_named_in_the_report( self, world ):
        _add_pid( world[ "proc" ], 920, 1, [ "python", "-m", "lupin_mcp.cosa_voice_mcp" ], EDIT_TIME, environ={ "PYTHONPATH": "/nowhere" } )
        text = smc.render_text( _census( world ) )
        assert "UNRESOLVED" in text
        assert "1 unmeasured" in text

    def test_exit_codes( self ):
        fresh = { "stale": False, "unresolved": [] }
        stale = { "stale": True,  "unresolved": [] }
        unres = { "stale": False, "unresolved": [ "x" ] }
        assert smc.exit_code( [] ) == 0
        assert smc.exit_code( [ fresh ] ) == 0
        assert smc.exit_code( [ fresh, unres ] ) == 2
        assert smc.exit_code( [ unres, stale ] ) == 1

    def test_main_text_and_json_and_a_missing_proc( self, world, monkeypatch, capsys ):
        _add_pid( world[ "proc" ], 930, 1, _mcp_argv( world[ "src" ] ), EDIT_TIME - 1 )
        monkeypatch.setattr( smc, "list_tmux_panes", _no_panes )

        assert smc.main( [], proc_root=world[ "proc" ], clk_tck=CLK_TCK, now=NOW ) == 1
        assert "STALE" in capsys.readouterr().out

        assert smc.main( [ "--json" ], proc_root=world[ "proc" ], clk_tck=CLK_TCK, now=NOW ) == 1
        payload = json.loads( capsys.readouterr().out )
        assert payload[ "stale_count" ] == 1
        assert payload[ "processes" ][ 0 ][ "pid" ] == 930
        assert "SEAT RESTART" in payload[ "remedy" ]

        assert smc.main( [], proc_root=str( world[ "tmp" ] / "no-proc" ) ) == 2
        assert "cannot read" in capsys.readouterr().err

    def test_main_never_signals_or_spawns_anything( self, world, monkeypatch ):
        """Read-only: kill and every process-spawning door are booby-trapped."""
        _add_pid( world[ "proc" ], 940, 1, _mcp_argv( world[ "src" ] ), EDIT_TIME - 1 )

        def trap( *a, **k ): raise AssertionError( "the check must be read-only" )
        for name in ( "kill", "killpg", "system", "execv", "execvp", "fork" ):
            monkeypatch.setattr( smc.os, name, trap )
        monkeypatch.setattr( smc, "list_tmux_panes", _no_panes )

        assert smc.main( [], proc_root=world[ "proc" ], clk_tck=CLK_TCK, now=NOW ) == 1

    def test_the_real_clock_tick_default_is_used_when_not_injected( self, world, monkeypatch ):
        monkeypatch.setattr( smc.os, "sysconf", lambda name: CLK_TCK )
        _add_pid( world[ "proc" ], 950, 1, _mcp_argv( world[ "src" ] ), EDIT_TIME + 7 )
        monkeypatch.setattr( smc.time, "time", lambda: NOW )
        [ rec ] = smc.census( proc_root=world[ "proc" ], self_pid=1, pane_lister=_no_panes )
        assert rec[ "start_epoch" ] == pytest.approx( EDIT_TIME + 7 )

    def test_census_defaults_to_its_own_pid_and_the_real_tmux_lister( self, world, monkeypatch ):
        monkeypatch.setattr( smc, "list_tmux_panes", lambda: { 961: ( "s", "%1" ) } )
        _add_pid( world[ "proc" ], os.getpid(), 1, _mcp_argv( world[ "src" ] ), EDIT_TIME - 1 )
        _add_pid( world[ "proc" ], 961, 1, [ "claude" ], EDIT_TIME - 2 )
        _add_pid( world[ "proc" ], 960, 961, _mcp_argv( world[ "src" ] ), EDIT_TIME - 1 )
        recs = smc.census( proc_root=world[ "proc" ], clk_tck=CLK_TCK, now=NOW )
        assert [ r[ "pid" ] for r in recs ] == [ 960 ]
        assert recs[ 0 ][ "tmux_session" ] == "s"

    def test_dunder_main_exits_with_the_code( self, monkeypatch ):
        monkeypatch.setattr( sys, "argv", [ SCRIPT_PATH, "--proc-root", "/definitely/not/proc" ] )
        with pytest.raises( SystemExit ) as exc:
            runpy.run_path( SCRIPT_PATH, run_name="__main__" )
        assert exc.value.code == 2
