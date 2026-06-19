#!/usr/bin/env python3
"""
STANDING REDLINE TEST (María #1, Round 2b) — the arbiter NEVER DESTRUCTIVELY
actuates the fleet.

A PERMANENT structural invariant re-run at every 2b gate: the arbiter modules
contain/call NO destructive primitive — no `reap` / `kill` / `dismiss` / `spawn`
/ `terminate` / `replace`-a-session call. The arbiter is a SENSOR + RECOMMENDER:
it observes (who/read), recommends (send_to/post), and escalates — a human or a
manager does the reaping. 2b narrows the original "never actuate" redline to
"never DESTRUCTIVELY actuate" (a non-destructive poke is allowed in 2b-3), but
the DESTRUCTIVE redline is absolute and this test enforces it structurally so a
future edit can't silently re-cross it.

Allowed exceptions (verified, design Appendix):
  • `os.kill( pid, 0 )` — a LIVENESS probe (signal 0 checks process existence,
    kills nothing); lives in the pure `context_pressure` leaf.
  • method `.replace()` calls — datetime/str VALUE operations, never a
    session-replacement primitive (no such primitive exists in the codebase).

The scan is AST-based (CALL nodes only) so comments, docstrings, and string
literals that merely MENTION these words (e.g. "spawn-lineage", "must not kill
the loop") never trip it — only an actual destructive CALL would.

Venue: :7999-eligible / local — pure source-AST scan, no IO, sub-second.
"""
import ast
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )


# The arbiter surface under the redline: the consumer job + its leaves
# (heartbeat_arbiter package) AND the standalone :8001 loop files (lupin_arbiter_app).
_HEARTBEAT_ARBITER_DIR = os.path.join( _src_path, "cosa", "agents", "heartbeat_arbiter" )
_ARBITER_APP_FILES = [
    os.path.join( _src_path, "lupin_arbiter_app", "fleet_arbiter_loop.py" ),
    os.path.join( _src_path, "lupin_arbiter_app", "arbiter_live_notify.py" ),
    os.path.join( _src_path, "lupin_arbiter_app", "health_watcher.py" ),
    os.path.join( _src_path, "lupin_arbiter_app", "app.py" ),
    os.path.join( _src_path, "lupin_arbiter_app", "local_snapshot_store.py" ),
]

# Destructive fleet-actuation verbs the arbiter must NEVER call.
_DESTRUCTIVE_CALL_NAMES = { "reap", "kill", "dismiss", "spawn", "terminate", "replace" }


def _arbiter_source_files():
    """Every arbiter source file under the redline (heartbeat_arbiter pkg + app loops)."""
    files = [ ]
    for name in sorted( os.listdir( _HEARTBEAT_ARBITER_DIR ) ):
        if name.endswith( ".py" ):
            files.append( os.path.join( _HEARTBEAT_ARBITER_DIR, name ) )
    files.extend( f for f in _ARBITER_APP_FILES if os.path.exists( f ) )
    return files


def _call_name( node ):
    """The called function's bare name (attr for `x.f()`, id for `f()`), or None."""
    func = node.func
    if isinstance( func, ast.Attribute ):
        return func.attr
    if isinstance( func, ast.Name ):
        return func.id
    return None


def _is_allowed( node, name ):
    """
    Is this destructive-named CALL one of the verified allowed exceptions?

      • os.kill( pid, 0 )  — liveness probe (signal-0 literal 2nd arg, receiver `os`)
      • <expr>.replace(…)  — datetime/str value op (an Attribute call, never a
                             bare `replace(...)` free function)
    """
    if name == "kill":
        func = node.func
        is_os_kill = ( isinstance( func, ast.Attribute )
                       and isinstance( func.value, ast.Name ) and func.value.id == "os" )
        sig_zero = ( len( node.args ) >= 2
                     and isinstance( node.args[ 1 ], ast.Constant ) and node.args[ 1 ].value == 0 )
        return is_os_kill and sig_zero
    if name == "replace":
        return isinstance( node.func, ast.Attribute )   # method value-op, not session-replace
    return False


def _destructive_calls_in( path ):
    """Return [ (call_name, lineno) ] for every DISALLOWED destructive call in `path`."""
    with open( path, "r", encoding="utf-8" ) as f:
        tree = ast.parse( f.read(), filename=path )
    violations = [ ]
    for node in ast.walk( tree ):
        if not isinstance( node, ast.Call ):
            continue
        name = _call_name( node )
        if name in _DESTRUCTIVE_CALL_NAMES and not _is_allowed( node, name ):
            violations.append( ( name, node.lineno ) )
    return violations


def test_arbiter_modules_make_no_destructive_call():
    """REDLINE: no reap/kill/dismiss/spawn/terminate/replace CALL across any
    arbiter module (only os.kill(pid,0) liveness + method .replace() value ops)."""
    offenders = { }
    for path in _arbiter_source_files():
        hits = _destructive_calls_in( path )
        if hits:
            offenders[ os.path.relpath( path, _src_path ) ] = hits
    assert offenders == { }, f"arbiter destructive-actuation calls found (redline crossed): {offenders}"


def test_only_kill_is_os_kill_signal_zero_liveness():
    """The ONLY `kill` anywhere in the arbiter surface is `os.kill(pid, 0)` — a
    liveness probe. Proves the allowed-exception is the single kill in scope."""
    kill_sites = [ ]
    for path in _arbiter_source_files():
        with open( path, "r", encoding="utf-8" ) as f:
            tree = ast.parse( f.read(), filename=path )
        for node in ast.walk( tree ):
            if isinstance( node, ast.Call ) and _call_name( node ) == "kill":
                kill_sites.append( ( os.path.relpath( path, _src_path ), node.lineno,
                                     _is_allowed( node, "kill" ) ) )
    # exactly one kill call, and it is the allowed os.kill(pid, 0) liveness probe
    assert len( kill_sites ) == 1, f"expected exactly one kill site, got {kill_sites}"
    assert kill_sites[ 0 ][ 2 ] is True, f"the lone kill is not the allowed liveness probe: {kill_sites}"
    assert kill_sites[ 0 ][ 0 ].endswith( "context_pressure.py" )


def test_redline_helper_flags_a_synthetic_destructive_call():
    """Guard the guard: the AST scanner actually CATCHES a destructive call (so a
    green redline means 'none present', not 'scanner is blind')."""
    import tempfile
    src = "def f( s ):\n    s.reap()\n    os.kill( pid, 9 )\n    dt.replace( year=2 )\n    os.kill( pid, 0 )\n"
    with tempfile.NamedTemporaryFile( "w", suffix=".py", delete=False ) as tf:
        tf.write( src )
        tmp = tf.name
    try:
        hits = { n for n, _ in _destructive_calls_in( tmp ) }
        assert "reap" in hits                         # bare destructive call → caught
        assert "kill" in hits                         # os.kill(pid, 9) → NOT signal-0 → caught
        assert "replace" not in hits                  # dt.replace(...) method value-op → allowed
    finally:
        os.unlink( tmp )


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
