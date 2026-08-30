"""
`src/scripts/thread_attribution_plugin.py` — the per-thread line recorder, covered without
tracing this process.

A straggler from Rio's two-tier census at `cc336880` (36 statements, 6 branches). Claimed by
the SOUND direction: `git grep -l -- thread_attribution_plugin -- src/tests src/cosa/tests`
was EMPTY at `0f61dd85`, and empty is conclusive.

🔴 WHAT THIS FILE IS CAREFUL ABOUT — and one of these is not optional.

· `settrace` IS NEVER ACTUALLY INSTALLED. `pytest_configure` calls `sys.settrace` and
  `threading.settrace` for real, and `sys.settrace` is exactly how coverage.py traces this
  tier. Installing the module's tracer for real would REPLACE coverage's own tracer mid-run
  and silently destroy the measurement of everything that ran after it — including this file's.
  Both are patched at the module's own lookup site, and the patches record the argument, which
  is the whole contract of those two hooks.
· THE `atexit` HANDLER IS DISARMED AT TEARDOWN. Importing the module registers `_dump` with
  `atexit`, so at the end of the unit tier it would fire and write `/tmp/thread-attrib.json`
  with whatever this suite left in `_hits`. The autouse fixture sets `_done = True` after every
  test, which is the module's own idempotence guard, so the handler is inert by the time the
  process exits. Nothing outside `tmp_path` is written by any test here.
· MODULE STATE IS RESET BOTH WAYS. `_hits` and `_done` are module globals that persist between
  tests. The fixture clears them before each test and disarms after, so no test depends on
  another's ordering.
· `OUT` AND `PREFIX` ARE READ AT IMPORT TIME into module constants, so a test that changed the
  environment would change nothing. Both are patched as module attributes instead.

WHY `_dump` IS ASSERTED ON THE FILE CONTENTS rather than on `_hits`: the JSON on disk is the
only output that survives the process, and `detect_thread_credited_coverage.py` is a separate
program that reads it. The in-memory dict is an implementation detail; the file is the interface.
"""

import importlib
import json
import os
import sys
import threading

import pytest


_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
for _p in ( os.path.join( _ROOT, "src", "scripts" ), os.path.join( _ROOT, "src" ) ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

mod = importlib.import_module( "thread_attribution_plugin" )


# A first-party path the tracer should accept, and three it must reject. Built from the
# module's own PREFIX default so a change to that default fails these loudly rather than
# quietly reclassifying every path.
FIRST_PARTY = "/src/cosa/rest/queue_protocol.py"
IN_TESTS    = "/src/tests/unit/scripts/test_thread_attribution_plugin.py"
THIRD_PARTY = "/usr/lib/python3.13/site-packages/pytest/__init__.py"
OUTSIDE     = "/etc/hosts"


class _Frame:
    """
    Minimal stand-in for a CPython frame — the two attributes the tracer reads, and nothing else.

    Ensures:
        - an access to any attribute the tracer does not use raises AttributeError, so the
          test proves which fields the tracer depends on rather than assuming them
    """
    def __init__( self, filename, lineno ):
        self.f_code   = type( "Code", (), { "co_filename": filename } )()
        self.f_lineno = lineno


@pytest.fixture( autouse=True )
def clean_module_state():
    """
    Give every test an empty recorder, and disarm the atexit handler afterwards.

    Requires:
        - the module has already been imported (its atexit registration is therefore live)

    Ensures:
        - `_hits` is empty and `_done` is False at the start of each test
        - `_done` is True at teardown, so the registered atexit `_dump` writes nothing when
          the tier's process finally exits
    """
    mod._hits.clear()
    mod._done = False
    yield
    mod._hits.clear()
    mod._done = True


@pytest.fixture
def traced( monkeypatch ):
    """
    Capture what the module installs, without installing it.

    Ensures:
        - returns a dict with "sys" and "threading" lists recording every settrace argument
        - the real `sys.settrace` is never called, so coverage's own tracer survives this file
    """
    seen = { "sys": [ ], "threading": [ ] }
    monkeypatch.setattr( sys,       "settrace", lambda fn: seen[ "sys"       ].append( fn ) )
    monkeypatch.setattr( threading, "settrace", lambda fn: seen[ "threading" ].append( fn ) )
    return seen


# ── the tracer's filter ──────────────────────────────────────────────────────

def test_first_party_line_is_recorded_under_the_running_thread():
    """A line in a first-party, non-test file is recorded against the current thread's name."""
    mod._tracer( _Frame( FIRST_PARTY, 42 ), "line", None )

    name = threading.current_thread().name
    assert mod._hits[ name ][ FIRST_PARTY ] == { 42 }


def test_repeated_lines_collapse_into_a_set():
    """
    The same line hit twice is stored once. Asserted because the container is a set and the
    consumer counts LINES covered, not executions — a list would inflate every hot loop.
    """
    for _ in range( 3 ):
        mod._tracer( _Frame( FIRST_PARTY, 7 ), "line", None )
    mod._tracer( _Frame( FIRST_PARTY, 8 ), "line", None )

    name = threading.current_thread().name
    assert mod._hits[ name ][ FIRST_PARTY ] == { 7, 8 }


@pytest.mark.parametrize( "event", [ "call", "return", "exception", "opcode" ] )
def test_non_line_events_record_nothing( event ):
    """
    Only "line" events are recorded. Every other event returns the tracer so tracing continues,
    but leaves `_hits` untouched — a call event carries no line to attribute.
    """
    assert mod._tracer( _Frame( FIRST_PARTY, 1 ), event, None ) is mod._tracer
    assert mod._hits == { }


@pytest.mark.parametrize( "path,why", [
    ( IN_TESTS,    "a test file — attributing test lines would credit the harness"    ),
    ( THIRD_PARTY, "site-packages — third-party frames are out of scope"              ),
    ( OUTSIDE,     "outside the first-party prefix entirely"                          ),
] )
def test_rejected_paths_record_nothing( path, why ):
    """Each of the three rejection reasons drops the frame before anything is recorded."""
    mod._tracer( _Frame( path, 99 ), "line", None )

    assert mod._hits == { }, why


def test_rejected_frame_still_returns_the_tracer():
    """
    A rejected frame must keep tracing installed for that scope. Returning None instead would
    switch tracing OFF for the rest of the frame, so a first-party callee below a third-party
    caller would go unrecorded — which is most of them.
    """
    assert mod._tracer( _Frame( THIRD_PARTY, 1 ), "line", None ) is mod._tracer


def test_accepted_frame_returns_the_tracer():
    """The accepted path returns the tracer too, so tracing continues into the next line."""
    assert mod._tracer( _Frame( FIRST_PARTY, 1 ), "line", None ) is mod._tracer


def test_prefix_is_honoured_as_a_substring_not_a_stem( monkeypatch ):
    """
    PREFIX is matched with `in`, not `startswith` — which is what lets it work against absolute
    paths from any checkout root. Proven by moving the prefix and watching the classification
    of the SAME path flip.
    """
    monkeypatch.setattr( mod, "PREFIX", "/nowhere/" )
    mod._tracer( _Frame( FIRST_PARTY, 5 ), "line", None )
    assert mod._hits == { }

    monkeypatch.setattr( mod, "PREFIX", "/cosa/" )
    mod._tracer( _Frame( FIRST_PARTY, 5 ), "line", None )
    assert mod._hits[ threading.current_thread().name ][ FIRST_PARTY ] == { 5 }


def test_lines_from_two_threads_are_kept_apart():
    """
    Separating threads is the module's entire reason to exist — its consumer subtracts the
    background thread's lines from the test thread's. A recorder that merged them would report
    a clean run on exactly the defect it was built to find.
    """
    def worker():
        mod._tracer( _Frame( FIRST_PARTY, 100 ), "line", None )

    t = threading.Thread( target=worker, name="probe-worker" )
    t.start()
    t.join()
    mod._tracer( _Frame( FIRST_PARTY, 200 ), "line", None )

    assert mod._hits[ "probe-worker" ][ FIRST_PARTY ]                    == { 100 }
    assert mod._hits[ threading.current_thread().name ][ FIRST_PARTY ]   == { 200 }


# ── the pytest hooks ─────────────────────────────────────────────────────────

def test_configure_installs_the_tracer_on_both_surfaces( traced ):
    """
    Both installs are needed and they cover different threads: `threading.settrace` applies to
    threads started AFTER it is set, and `sys.settrace` covers the thread already running.
    """
    mod.pytest_configure( config=object() )

    assert traced[ "threading" ] == [ mod._tracer ]
    assert traced[ "sys"       ] == [ mod._tracer ]


def test_unconfigure_removes_both_tracers_and_dumps( traced, tmp_path, monkeypatch ):
    """Teardown clears both hooks and writes the map — the file is the deliverable."""
    out = tmp_path / "attrib.json"
    monkeypatch.setattr( mod, "OUT", str( out ) )
    mod._tracer( _Frame( FIRST_PARTY, 3 ), "line", None )

    mod.pytest_unconfigure( config=object() )

    assert traced[ "sys"       ] == [ None ]
    assert traced[ "threading" ] == [ None ]
    assert out.exists()


def test_unconfigure_clears_sys_before_threading( traced, tmp_path, monkeypatch ):
    """
    Order is asserted because the reverse would leave `sys.settrace` live while the dump runs,
    tracing the dump's own lines into the map it is writing.
    """
    monkeypatch.setattr( mod, "OUT", str( tmp_path / "attrib.json" ) )
    order = [ ]
    monkeypatch.setattr( sys,       "settrace", lambda fn: order.append( "sys"       ) )
    monkeypatch.setattr( threading, "settrace", lambda fn: order.append( "threading" ) )

    mod.pytest_unconfigure( config=object() )

    assert order == [ "sys", "threading" ]


# ── the dump ─────────────────────────────────────────────────────────────────

def test_dump_writes_sorted_lines_keyed_by_thread_then_file( tmp_path, monkeypatch ):
    """
    The on-disk shape is `{ thread: { file: [line, ...] } }` with lines SORTED — a set has no
    order, and the consumer diffs two of these files, so an unstable order would produce a
    diff on every run regardless of what changed.

    🔴 THE LINE NUMBERS ARE NOT ARBITRARY, AND THE OBVIOUS ONES DO NOT WORK. This test first
    used 30 / 10 / 20, and a mutation replacing `sorted( ls )` with `list( ls )` SURVIVED it.
    A CPython set of small ints iterates in ascending order by hash-table placement, so for
    those three values the unsorted answer and the sorted answer are the same list — the test
    was named for sorting and could not see sorting. `set( ( 156, 208, 249 ) )` iterates
    `[ 208, 249, 156 ]`, which is why these values are here. The fix is the FIXTURE, not the
    assertion: the assertion was already correct and an audit of it would have found nothing.
    """
    out = tmp_path / "attrib.json"
    monkeypatch.setattr( mod, "OUT", str( out ) )
    for lineno in ( 249, 156, 208 ):
        mod._tracer( _Frame( FIRST_PARTY, lineno ), "line", None )

    # The guard on the guard: if a future CPython makes these iterate in ascending order, this
    # test silently stops testing anything, so the premise is asserted rather than assumed.
    assert list( { 249, 156, 208 } ) != [ 156, 208, 249 ], "pick new line numbers — see docstring"

    mod._dump()

    payload = json.loads( out.read_text() )
    assert payload == { threading.current_thread().name: { FIRST_PARTY: [ 156, 208, 249 ] } }


def test_dump_writes_an_empty_map_when_nothing_was_traced( tmp_path, monkeypatch ):
    """
    A run that recorded nothing still produces a file. The consumer must be able to tell "no
    lines were attributed" from "the run died before writing", and only a present-but-empty
    file says the first.
    """
    out = tmp_path / "attrib.json"
    monkeypatch.setattr( mod, "OUT", str( out ) )

    mod._dump()

    assert json.loads( out.read_text() ) == { }


def test_second_dump_is_a_no_op( tmp_path, monkeypatch ):
    """
    `_done` makes the write happen at most once, whichever of `pytest_unconfigure` or `atexit`
    calls first. Proven by pointing OUT at a NEW path for the second call: if the guard failed,
    that second file would exist.
    """
    first  = tmp_path / "first.json"
    second = tmp_path / "second.json"
    monkeypatch.setattr( mod, "OUT", str( first ) )
    mod._dump()

    monkeypatch.setattr( mod, "OUT", str( second ) )
    mod._dump()

    assert first.exists()
    assert not second.exists()


def test_unconfigure_after_a_dump_does_not_write_again( traced, tmp_path, monkeypatch ):
    """
    The atexit-then-unconfigure ordering, which is the pair the guard exists for. The hooks
    still clear, but no second file appears.
    """
    monkeypatch.setattr( mod, "OUT", str( tmp_path / "first.json" ) )
    mod._dump()
    monkeypatch.setattr( mod, "OUT", str( tmp_path / "second.json" ) )

    mod.pytest_unconfigure( config=object() )

    assert traced[ "sys" ] == [ None ]
    assert not ( tmp_path / "second.json" ).exists()
