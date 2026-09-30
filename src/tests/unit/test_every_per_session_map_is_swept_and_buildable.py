#!/usr/bin/env python3
"""
Two enumerations about `WebSocketManager`'s per-session maps, replaced by predicates.

Why this file exists
--------------------
`WebSocketManager` holds a growing family of maps keyed by `session_id`, and TWO separate
hand-maintained lists have to stay in step with it:

  1. `disconnect()` deletes from each one in its own statement.
  2. Four test files build a manager via `WebSocketManager.__new__`, bypassing the
     config-heavy `__init__`, and hand-set each map.

Both lists were short by one on 2026-09-27, when the CC transcript console added
`cc_transcript_watchers`. The first hole is the leak the plan predicted (P3) — a watcher
surviving a disconnect, with the tailer polling forever and no error anywhere. The SECOND hole
was not predicted by anyone: three of those factories raised `AttributeError` from inside
`disconnect()`, which is a failure in a test that is not about the new map at all, reported
against a line the new feature's author never wrote.

CLAUDE.md § "Writing a rule or a guard": *"Write the predicate the enumeration is
approximating… When the fix for an enumeration defect is itself an enumeration, you have moved
the defect."* Patching the four factories by hand is exactly that move. So this file derives
the map list from `__init__` and fails when either consumer falls behind.

⚠️ WHAT THIS DOES NOT DO. It cannot check that `disconnect()` deletes the RIGHT key or in the
right way — it checks that each map is NAMED in the function's source. A statement that
mentions a map without removing the session's entry would pass. That is a real limit and it is
stated rather than papered over: the behavioural arms live in
`test_cc_transcript_watch_verbs.py` and `test_websocket_manager_client_type.py`.

Venue: :7999-eligible — pure source and attribute inspection, no server, no IO.
"""

import ast
import inspect
import os
import re
import sys
import textwrap

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.websocket_manager import WebSocketManager

LUPIN_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )

# Maps that are deliberately NOT per-session and so are not swept on disconnect. Each needs a
# reason, because an unexplained exemption is how a real map gets excused.
NOT_PER_SESSION = {
    "user_sessions" : "keyed by user_id, and disconnect prunes it through the user association",
    "user_to_email" : "keyed by user_id; cleared when a user's LAST session goes",
    "session_to_user": "swept, but through the user-association block rather than a bare del",
}


def _per_session_map_names():
    """
    The names `__init__` assigns a session-keyed dict to, derived rather than listed.

    Requires:
        - WebSocketManager.__init__ is readable source

    Ensures:
        - returns the `self.<name>` attributes annotated `Dict[str, ...]` or assigned `{}`
          whose name begins with `session_` or ends with `_watchers`
        - the predicate is a NAMING convention, which is weaker than reading the key's type —
          stated here rather than left implied
    """
    # textwrap.dedent, NOT inspect.cleandoc: cleandoc is for DOCSTRINGS and leaves the first
    # line's indentation alone, so parsing a method's source through it raises
    # IndentationError. Found by running this file, not by reading the docs.
    source = textwrap.dedent( inspect.getsource( WebSocketManager.__init__ ) )
    tree   = ast.parse( source )

    names = set()
    for node in ast.walk( tree ):
        target = None
        if isinstance( node, ast.AnnAssign ):
            target = node.target
        elif isinstance( node, ast.Assign ) and len( node.targets ) == 1:
            target = node.targets[ 0 ]
        if not isinstance( target, ast.Attribute ): continue
        if not isinstance( target.value, ast.Name ) or target.value.id != "self": continue

        name = target.attr
        if name.startswith( "session_" ) or name.endswith( "_watchers" ):
            names.add( name )
    return names


def test_the_predicate_finds_a_real_population():
    """
    The instrument can find something.

    A negative result is worth nothing until the same search has returned a positive one — and
    a predicate that matched nothing would make every assertion below vacuous.
    """
    names = _per_session_map_names()
    assert len( names ) >= 4, f"the predicate found only {sorted( names )}"
    for expected in ( "session_subscriptions", "session_is_admin", "session_client_types" ):
        assert expected in names, f"the predicate missed the known map {expected}"


def _disconnect_reach():
    """
    `disconnect()`'s source, PLUS the source of the `self.` methods it calls.

    One level of indirection, deliberately, because a sweep is allowed to go through a helper:
    `cc_transcript_watchers` is swept by `drop_all_cc_transcript_watches( session_id )`, so a
    literal-name search over `disconnect()` alone reports a hole that is not there. Found by
    running this guard against a sweep it had just been written to describe.

    ⚠️ ONE level, not transitive. A map swept two helpers deep would be reported as missing —
    which is the safe direction for a guard to be wrong in, and is why the bound is stated.

    Ensures:
        - returns the concatenated source text to search
    """
    source = inspect.getsource( WebSocketManager.disconnect )
    reach  = [ source ]

    for node in ast.walk( ast.parse( textwrap.dedent( source ) ) ):
        if not isinstance( node, ast.Call ): continue
        func = node.func
        if not isinstance( func, ast.Attribute ): continue
        if not isinstance( func.value, ast.Name ) or func.value.id != "self": continue

        helper = getattr( WebSocketManager, func.attr, None )
        if helper is None or not callable( helper ): continue
        try:
            reach.append( inspect.getsource( helper ) )
        except ( OSError, TypeError ):                  # pragma: no cover - builtins have no source
            continue

    return "\n".join( reach )


def test_the_reach_helper_sees_past_one_call():
    """
    The instrument can follow the indirection it claims to.

    Without this, a `_disconnect_reach()` that silently returned only `disconnect()` would make
    the sweep test below pass for the wrong reason — every map name being found because the
    predicate had quietly narrowed to the maps swept inline.
    """
    reach = _disconnect_reach()
    assert "drop_all_cc_transcript_watches" in reach, "disconnect does not call the sweep helper"
    assert "cc_transcript_watchers" in reach, "the helper's body was not reached"


def test_disconnect_names_every_per_session_map():
    """
    The sweep is hand-maintained, so derive its obligation instead of trusting it.

    This is the leak P3 predicted: a map left out means a closed tab's entry survives, the
    tailer polls forever, and `emit_to_session` early-returns into a session already gone — a
    silent burn with no error anywhere.
    """
    disconnect_source = _disconnect_reach()

    missing = [ name for name in sorted( _per_session_map_names() )
                if name not in NOT_PER_SESSION and name not in disconnect_source ]

    assert not missing, (
        f"disconnect() never mentions {missing}. Every per-session map must be swept there — a "
        f"survivor is a silent leak, not an error. If one of these is genuinely not "
        f"per-session, add it to NOT_PER_SESSION with its reason."
    )


def _hand_rolled_factory_files():
    """
    The test files that build a manager via `__new__`, found by predicate.

    Ensures:
        - returns the paths under src/tests that contain `WebSocketManager.__new__`
        - a file list derived from the tree, so a NEW factory is covered the day it lands
    """
    found = [ ]
    tests_root = os.path.join( LUPIN_ROOT, "src", "tests" )
    for dirpath, _dirnames, filenames in os.walk( tests_root ):
        for filename in filenames:
            if not filename.endswith( ".py" ): continue
            path = os.path.join( dirpath, filename )
            with open( path, "r" ) as handle:
                if "WebSocketManager.__new__" in handle.read():
                    found.append( path )
    return found


def test_the_factory_predicate_finds_a_real_population():
    """Same instrument check, for the second enumeration."""
    files = _hand_rolled_factory_files()
    assert files, "no hand-rolled WebSocketManager factory found — this file's premise is gone"


@pytest.mark.parametrize( "factory_file", _hand_rolled_factory_files(),
                          ids=lambda path: os.path.basename( path ) )
def test_every_per_session_map_is_built_by_the_hand_rolled_test_factories( factory_file ):
    """
    A factory that bypasses `__init__` must still build every map `disconnect()` will touch.

    Parametrised per file so a failure names WHICH factory fell behind.

    ⚠️ Only files whose factory actually reaches `disconnect()` can break this way, so a
    factory that never disconnects is exempt — checked by looking for the call rather than
    assumed, because exempting by name is the enumeration this file exists to avoid.
    """
    with open( factory_file, "r" ) as handle:
        source = handle.read()

    if not re.search( r"\.disconnect\s*\(", source ):
        pytest.skip( f"{os.path.basename( factory_file )} never calls disconnect(), so an "
                     f"unbuilt map cannot raise from it" )

    disconnect_source = _disconnect_reach()
    required = [ name for name in sorted( _per_session_map_names() )
                 if name not in NOT_PER_SESSION and name in disconnect_source ]

    missing = [ name for name in required if f"mgr.{name}" not in source and f".{name} " not in source ]

    assert not missing, (
        f"{os.path.basename( factory_file )} builds a manager with __new__ and calls "
        f"disconnect(), but never sets {missing}. disconnect() touches them, so it raises "
        f"AttributeError from inside a test that is not about those maps at all — which is how "
        f"three factories broke on 2026-09-27 when cc_transcript_watchers was added."
    )
