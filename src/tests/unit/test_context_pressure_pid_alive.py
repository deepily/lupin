#!/usr/bin/env python3
"""
context_pressure._pid_alive reads kill -0 through the hook library's probe.

Pins the answers for a live pid, a dead pid, a pid that is not ours, and the pids that are no process at all.

Venue: :7999-eligible / local, pure.
"""
import ast
import inspect
import os
import subprocess
import sys

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter import context_pressure as cp
from lupin_cli.claude_code.hooks.lib import stale_buffer_janitor as janitor


def test_this_process_is_alive():
    assert cp._pid_alive( os.getpid() ) is True


def test_a_finished_child_is_not_alive():
    child = subprocess.Popen( [ sys.executable, "-c", "pass" ] )
    child.wait()
    assert cp._pid_alive( child.pid ) is False


def test_a_pid_that_exists_but_is_not_ours_counts_as_alive( monkeypatch ):
    def refuse( pid, sig ): raise PermissionError( 1, "Operation not permitted" )
    monkeypatch.setattr( os, "kill", refuse )
    assert cp._pid_alive( 4242 ) is True


def test_none_text_and_floats_are_not_alive_even_when_they_name_a_live_process():
    assert cp._pid_alive( None ) is False
    assert cp._pid_alive( "123" ) is False
    assert cp._pid_alive( str( os.getpid() ) ) is False
    assert cp._pid_alive( float( os.getpid() ) ) is False


def test_zero_and_negative_pids_are_not_alive_because_kill_would_signal_a_process_group( monkeypatch ):
    def never( pid, sig ): raise AssertionError( "os.kill must not be called for a non-positive pid" )
    monkeypatch.setattr( os, "kill", never )
    assert cp._pid_alive( 0 ) is False
    assert cp._pid_alive( -1 ) is False


def test_a_pid_too_big_for_the_kernel_is_not_alive_and_does_not_raise():
    assert cp._pid_alive( 10 ** 30 ) is False


def test_assess_liveness_is_dead_only_when_neither_pid_answers( monkeypatch ):
    live = { 111 }
    def kill( pid, sig ):
        if pid not in live: raise ProcessLookupError( 3, "No such process" )
    monkeypatch.setattr( os, "kill", kill )
    assert cp.assess_liveness( 999, 100.0, now=101.0, cc_pid=111 ) == cp.Liveness.ACTIVE
    assert cp.assess_liveness( 111, 0.0, now=100000.0 ) == cp.Liveness.IDLE
    assert cp.assess_liveness( 999, 100.0, now=101.0, cc_pid=998 ) == cp.Liveness.DEAD


def test_a_probe_that_raises_some_other_oserror_reads_as_not_alive( monkeypatch ):
    def broken( pid, sig ): raise OSError( 22, "Invalid argument" )
    monkeypatch.setattr( os, "kill", broken )
    assert cp._pid_alive( 42 ) is False


def test_the_one_kill_behind_the_probe_is_signal_zero():
    tree  = ast.parse( inspect.getsource( janitor.is_pid_alive ) )
    kills = [ n for n in ast.walk( tree ) if isinstance( n, ast.Call ) and isinstance( n.func, ast.Attribute ) and n.func.attr == "kill" ]
    assert len( kills ) == 1
    assert isinstance( kills[ 0 ].args[ 1 ], ast.Constant ) and kills[ 0 ].args[ 1 ].value == 0
