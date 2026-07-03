#!/usr/bin/env python3
"""
Unit tests: hook-spawned background children must never inherit the hook's
stdout/stderr pipe (bug 73d2b589 — the CC Stop-phase pipe-hold wedge).

MECHANISM UNDER GUARD (proven live on CC v2.1.199, 2026-07-03): Claude Code's
hook phase waits for hook-STDOUT EOF, not process exit. The default per-hook
timeout binds the hook PROCESS — a backgrounded grandchild that inherits the
hook's stdout keeps the pipe open after the hook exits, holding the Stop phase
indefinitely. Messages injected during that phase enqueue ("Press up to edit
queued messages") and the queue drains only at phase end; bare Enter no-ops on
an empty composer. Full triage record: store bug 73d2b589 + R&D doc
src/rnd/v0.1.9/2026.07.03-cc-stop-phase-pipe-hold-guard-and-runbook.md.

Three guard layers:
  1. AST sweep — EVERY `subprocess.Popen(...)` call in the hook tree must pass
     explicit `stdout=` AND `stderr=` keywords (DEVNULL or a file object —
     anything except pipe inheritance). Turns today's compliance into a pinned
     invariant; any future un-redirected background spawn fails this test.
  2. Seam pins — the FOUR real background-spawn sites pass non-inheriting
     stdout/stderr + start_new_session=True on their actual Popen calls:
       hook_common.inject_qualifier_via_tmux (Stop-path self-poke),
       stop._arm_idle_waiter (deferred-ask waiter),
       idle_waiter._spawn_successor (waiter backoff chain),
       register_session._spawn_listener_locked (notification listener).
  3. Live demonstration — the `sleep N & exit 0` pipe-hold shape: with an
     inherited pipe the read blocks until the grandchild dies; with DEVNULL
     the phase releases at process exit. Executable documentation of WHY the
     invariant exists.

Venue: :7999-eligible / local — no server, no DB, tmp-dir only, ~2s (one
bounded sleep in the demonstration pair).
"""
import ast
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

HOOKS_ROOT = Path( _src_path ) / "lupin_cli" / "claude_code" / "hooks"


# ---------------------------------------------------------------------------
# Shared seam scaffolding
# ---------------------------------------------------------------------------

class _FakeProc:
    pid = 424242


def _capture_popen( captured ):
    """Popen stand-in that records (cmd, kwargs) and returns a fake process."""
    def fake_popen( cmd, **kwargs ):
        captured[ "cmd" ]    = cmd
        captured[ "kwargs" ] = kwargs
        return _FakeProc()
    return fake_popen


def _assert_detached_kwargs( kwargs ):
    """
    The invariant at a spawn seam: stdout and stderr are BOTH explicitly
    non-inheriting (DEVNULL or an open file — never absent, never PIPE),
    and the child is detached into its own session.
    """
    for stream in ( "stdout", "stderr" ):
        assert stream in kwargs, f"{stream} not passed — child would inherit the hook's pipe"
        value = kwargs[ stream ]
        ok    = value is subprocess.DEVNULL or hasattr( value, "write" )
        assert ok, f"{stream}={value!r} is neither DEVNULL nor a file object"
        assert value is not subprocess.PIPE, f"{stream}=PIPE would hand the hook a pipe to hold"
    assert kwargs.get( "start_new_session" ) is True, "child not detached (start_new_session)"


# ---------------------------------------------------------------------------
# Layer 1 — AST sweep: no un-redirected Popen anywhere in the hook tree
# ---------------------------------------------------------------------------

SPAWN_ATTRS = { "Popen", "create_subprocess_exec", "create_subprocess_shell" }


def _popen_aliases( tree ):
    """
    Names bound to a spawn callable via `from subprocess import Popen [as x]`
    (or the asyncio create_subprocess_* twins) — so aliasing cannot evade the
    sweep.
    """
    aliases = set()
    for node in ast.walk( tree ):
        if isinstance( node, ast.ImportFrom ) and node.module in ( "subprocess", "asyncio" ):
            for name in node.names:
                if name.name in SPAWN_ATTRS:
                    aliases.add( name.asname or name.name )
    return aliases


def _is_spawn_call( node, aliases ):
    """True iff the AST Call node is a subprocess/asyncio spawn (any alias)."""
    func = node.func
    if isinstance( func, ast.Attribute ) and func.attr in SPAWN_ATTRS:
        return True
    if isinstance( func, ast.Name ) and ( func.id in SPAWN_ATTRS or func.id in aliases ):
        return True
    return False


def _is_os_system_call( node ):
    """True iff the AST Call node is os.system(...) — banned outright: it
    always inherits stdout, and a shell-backgrounded `cmd &` grandchild is the
    exact pipe-hold shape with no way to redirect per-child."""
    func = node.func
    return isinstance( func, ast.Attribute ) and func.attr == "system" \
        and isinstance( func.value, ast.Name ) and func.value.id == "os"


def _popen_violations( tree, path ):
    """
    Yield "path:lineno ..." for every spawn call missing an explicit stdout=
    or stderr= keyword, and for every os.system call. AST-based, so docstring/
    comment examples never false-positive (they are not Call nodes).
    """
    aliases = _popen_aliases( tree )
    for node in ast.walk( tree ):
        if not isinstance( node, ast.Call ):
            continue
        if _is_os_system_call( node ):
            yield f"{path}:{node.lineno} os.system is banned in hook code (inherits stdout; '&' backgrounding = pipe-hold)"
            continue
        if not _is_spawn_call( node, aliases ):
            continue
        keywords = { kw.arg for kw in node.keywords if kw.arg is not None }
        missing  = { "stdout", "stderr" } - keywords
        if missing:
            yield f"{path}:{node.lineno} missing {sorted( missing )}"


def test_hook_tree_has_no_unredirected_popen():
    """
    THE INVARIANT (73d2b589): every subprocess.Popen in the hook tree names
    stdout AND stderr explicitly. An inherited-pipe Popen is exactly the
    grandchild shape that holds the CC Stop phase open past hook exit.
    """
    assert HOOKS_ROOT.is_dir(), f"hook tree not found at {HOOKS_ROOT}"
    violations = [ ]
    py_files   = sorted( HOOKS_ROOT.rglob( "*.py" ) )
    assert py_files, "hook tree unexpectedly empty — sweep would be vacuous"
    for py in py_files:
        tree = ast.parse( py.read_text( encoding="utf-8" ), filename=str( py ) )
        violations.extend( _popen_violations( tree, py.relative_to( HOOKS_ROOT ) ) )
    assert violations == [ ], (
        "Un-redirected subprocess.Popen in hook tree — a backgrounded child "
        "inheriting the hook's stdout holds the CC Stop phase open after the "
        "hook exits (bug 73d2b589). Pass stdout=/stderr= (DEVNULL or a file) "
        "explicitly:\n" + "\n".join( violations )
    )


def test_sweep_detects_a_violation():
    """
    Negative control: the sweep itself must FLAG an un-redirected Popen —
    guards against the guard silently going vacuous (e.g. an AST refactor
    that stops matching Call nodes).
    """
    bad_src = (
        "import subprocess\n"
        "def spawn():\n"
        "    subprocess.Popen( [ 'sleep', '300' ], start_new_session=True )\n"
    )
    tree       = ast.parse( bad_src, filename="synthetic.py" )
    violations = list( _popen_violations( tree, "synthetic.py" ) )
    assert len( violations ) == 1
    assert "synthetic.py:3" in violations[ 0 ]
    assert "stdout" in violations[ 0 ] and "stderr" in violations[ 0 ]


def test_sweep_detects_partial_redirect():
    """stdout redirected but stderr forgotten is still a violation."""
    src = (
        "from subprocess import Popen, DEVNULL\n"
        "Popen( [ 'sleep', '300' ], stdout=DEVNULL )\n"
    )
    tree       = ast.parse( src, filename="synthetic.py" )
    violations = list( _popen_violations( tree, "synthetic.py" ) )
    assert len( violations ) == 1
    assert "stderr" in violations[ 0 ] and "stdout" not in violations[ 0 ].split( "missing" )[ 1 ]


def test_sweep_detects_aliased_popen():
    """Evasion guard: `from subprocess import Popen as P` is still swept."""
    src = (
        "from subprocess import Popen as P\n"
        "P( [ 'sleep', '300' ] )\n"
    )
    tree       = ast.parse( src, filename="synthetic.py" )
    violations = list( _popen_violations( tree, "synthetic.py" ) )
    assert len( violations ) == 1 and "synthetic.py:2" in violations[ 0 ]


def test_sweep_bans_os_system():
    """Evasion guard: os.system always inherits stdout; '&' backgrounding is
    the pipe-hold shape with no per-child redirect — banned outright."""
    src = (
        "import os\n"
        "os.system( 'sleep 300 &' )\n"
    )
    tree       = ast.parse( src, filename="synthetic.py" )
    violations = list( _popen_violations( tree, "synthetic.py" ) )
    assert len( violations ) == 1 and "os.system is banned" in violations[ 0 ]


def test_sweep_detects_asyncio_subprocess():
    """Evasion guard: asyncio.create_subprocess_shell without redirects is swept."""
    src = (
        "import asyncio\n"
        "async def go():\n"
        "    await asyncio.create_subprocess_shell( 'sleep 300 &' )\n"
    )
    tree       = ast.parse( src, filename="synthetic.py" )
    violations = list( _popen_violations( tree, "synthetic.py" ) )
    assert len( violations ) == 1 and "synthetic.py:3" in violations[ 0 ]


def test_sweep_accepts_redirected_popen():
    """Negative control twin: a fully-redirected Popen produces no violation."""
    good_src = (
        "import subprocess\n"
        "def spawn():\n"
        "    subprocess.Popen( [ 'sleep', '300' ],\n"
        "                      stdout=subprocess.DEVNULL,\n"
        "                      stderr=subprocess.DEVNULL,\n"
        "                      start_new_session=True )\n"
    )
    tree = ast.parse( good_src, filename="synthetic.py" )
    assert list( _popen_violations( tree, "synthetic.py" ) ) == [ ]


# ---------------------------------------------------------------------------
# Layer 2 — seam pins: the four real background-spawn sites
# ---------------------------------------------------------------------------

def test_inject_qualifier_via_tmux_spawns_fully_detached( monkeypatch ):
    """Pin site 1: hook_common.inject_qualifier_via_tmux (Stop-path self-poke)."""
    from lupin_cli.claude_code.hooks.lib import hook_common

    captured = { }
    monkeypatch.setattr( hook_common.subprocess, "Popen", _capture_popen( captured ) )
    monkeypatch.setattr(
        "lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id",
        lambda sid: { "tmux_session": "fake-tmux-session" }
    )

    hook_common.inject_qualifier_via_tmux( "deadbeef", "hello", wrap=False )

    assert captured, "Popen was never invoked — injection path did not spawn"
    _assert_detached_kwargs( captured[ "kwargs" ] )


def test_inject_qualifier_via_tmux_no_session_no_spawn( monkeypatch ):
    """Site 1 branch guard: no bridge match → returns silently, zero Popen."""
    from lupin_cli.claude_code.hooks.lib import hook_common

    spawned = [ ]
    monkeypatch.setattr( hook_common.subprocess, "Popen",
                         lambda *a, **k: spawned.append( a ) )
    monkeypatch.setattr(
        "lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id",
        lambda sid: None
    )

    hook_common.inject_qualifier_via_tmux( "deadbeef", "hello", wrap=False )
    assert spawned == [ ]


def test_arm_idle_waiter_spawns_fully_detached( monkeypatch, tmp_path ):
    """Pin site 2: stop._arm_idle_waiter (deferred-ask waiter spawn)."""
    from lupin_cli.claude_code.hooks import stop

    captured = { }
    # _arm_idle_waiter does `import subprocess` locally → patch the global module attr
    monkeypatch.setattr( subprocess, "Popen", _capture_popen( captured ) )
    monkeypatch.setattr( stop, "_shared_summarize_task", lambda msg: "gist" )
    monkeypatch.setattr( stop, "get_idle_detection", lambda sid: { "backoff_index": 1 } )
    monkeypatch.setattr( stop, "get_session_metadata", lambda: { "cc_pid": 12345 } )
    monkeypatch.setattr( stop, "kill_idle_waiter", lambda sid: None )
    monkeypatch.setattr( stop, "set_idle_detection_field", lambda sid, **kw: None )
    monkeypatch.setattr( stop, "log_to_stream", lambda *a, **kw: None )
    monkeypatch.setattr( os.path, "expanduser",
                         lambda p: str( tmp_path / Path( p ).name ) )

    pid = stop._arm_idle_waiter( "deadbeef-session", "last message", str( tmp_path ) )

    assert pid == _FakeProc.pid
    assert captured, "Popen was never invoked — waiter was not spawned"
    _assert_detached_kwargs( captured[ "kwargs" ] )


def test_spawn_successor_spawns_fully_detached( monkeypatch, tmp_path ):
    """Pin site 3: idle_waiter._spawn_successor (waiter backoff chain)."""
    from lupin_cli.claude_code.hooks.lib import idle_waiter

    captured = { }
    monkeypatch.setattr( idle_waiter.subprocess, "Popen", _capture_popen( captured ) )
    monkeypatch.setattr( idle_waiter, "_LOG_DIR", tmp_path )

    pid = idle_waiter._spawn_successor( "deadbeef-session", 12345, 2 )

    assert pid == _FakeProc.pid
    assert captured, "Popen was never invoked — successor waiter was not spawned"
    _assert_detached_kwargs( captured[ "kwargs" ] )


def test_spawn_listener_locked_spawns_fully_detached( monkeypatch, tmp_path ):
    """Pin site 4: register_session._spawn_listener_locked (notification listener)."""
    sys.path.insert( 0, str( HOOKS_ROOT ) )  # register_session.py is a script, not a package module
    try:
        import register_session
    finally:
        sys.path.pop( 0 )

    captured = { }
    monkeypatch.setattr( register_session.subprocess, "Popen", _capture_popen( captured ) )
    monkeypatch.setattr( register_session.os.path, "expanduser",
                         lambda p: str( tmp_path ) )
    monkeypatch.setattr( register_session.time, "sleep", lambda s: None )
    monkeypatch.setattr( register_session.os, "kill", lambda pid, sig: None )
    monkeypatch.setattr( register_session, "_record_listener_pid",
                         lambda *a, **kw: None )

    pid = register_session._spawn_listener_locked(
        "deadbeef-session", { }, str( tmp_path / "bridge.json" ), None
    )

    assert pid == _FakeProc.pid
    assert captured, "Popen was never invoked — listener was not spawned"
    _assert_detached_kwargs( captured[ "kwargs" ] )


# ---------------------------------------------------------------------------
# Layer 3 — live demonstration of the pipe-hold mechanism (executable "why")
# ---------------------------------------------------------------------------

GRANDCHILD_SLEEP = 1.5   # seconds the backgrounded grandchild outlives its parent


@pytest.mark.skipif( not Path( "/bin/bash" ).exists(), reason="bash required" )
def test_inherited_pipe_holds_eof_past_process_exit():
    """
    The wedge shape: `sleep N & exit 0` with an inherited (PIPE) stdout. The
    hook PROCESS exits immediately, but reading its stdout to EOF blocks until
    the grandchild dies — this is what holds the CC Stop phase (bug 73d2b589).
    """
    start = time.monotonic()
    proc  = subprocess.Popen(
        [ "bash", "-c", f"sleep {GRANDCHILD_SLEEP} & exit 0" ],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    proc.wait( timeout=5 )
    exited_at = time.monotonic() - start

    proc.stdout.read()   # blocks until the grandchild releases the pipe
    eof_at = time.monotonic() - start
    proc.stdout.close()

    assert exited_at < 1.0, f"parent should exit ~instantly, took {exited_at:.2f}s"
    assert eof_at >= GRANDCHILD_SLEEP - 0.2, (
        f"EOF arrived at {eof_at:.2f}s — expected the grandchild's inherited "
        f"pipe to hold it ~{GRANDCHILD_SLEEP}s (the 73d2b589 wedge mechanism)"
    )


@pytest.mark.skipif( not Path( "/bin/bash" ).exists(), reason="bash required" )
def test_devnull_releases_at_process_exit():
    """
    The fix shape: same grandchild, stdout=DEVNULL — nothing holds a pipe, the
    phase releases the moment the hook process exits.
    """
    start = time.monotonic()
    proc  = subprocess.Popen(
        [ "bash", "-c", f"sleep {GRANDCHILD_SLEEP} & exit 0" ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    proc.wait( timeout=5 )
    done_at = time.monotonic() - start

    assert done_at < 1.0, (
        f"with DEVNULL the wait must return at process exit (~0s), took {done_at:.2f}s"
    )
