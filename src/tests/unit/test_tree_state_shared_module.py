"""
Guard — the `[tree-state]` line has ONE implementation, and the non-pytest runners use it.

Store row `11253df9` gap 3: the root conftest's hook reaches every pytest tier and nothing
else, so the node/c8 runners produced greens carrying no tree at all — the larger half of
the original ask by surface area.

The shortcut would have been a shell function re-deriving the line with its own `git`
calls. That is two implementations of one contract, and two implementations drift — the
exact failure row `e2099400` keeps finding. These tests assert the single-implementation
property directly, because it is the thing that decays silently.

Venue: :7999-eligible — no network, no mutation.
"""
import os
import re
import subprocess
import sys

import pytest

from cosa.utils.tree_state import _coarse_age, _git_reader, tree_state_line

ROOT      = os.environ[ "LUPIN_ROOT" ]
HELPER    = os.path.join( ROOT, "src", "scripts", "lib", "tree-state.sh" )
TS_RUNNER = os.path.join( ROOT, "src", "tests", "run-typescript-tests.sh" )
JS_RUNNER = os.path.join( ROOT, "src", "scripts", "run-js-tests-capped.sh" )


def test_the_conftest_imports_the_line_rather_than_defining_its_own():
    """
    THE SINGLE-IMPLEMENTATION PROPERTY, asserted on the source. If someone re-adds a local
    `def tree_state_line` to the conftest, the two callers start rendering from different
    code and drift with nobody noticing — the line would still look right in both places.
    """
    source = open( os.path.join( ROOT, "src", "conftest.py" ) ).read()
    assert "from cosa.utils.tree_state import" in source, (
        "the conftest no longer imports the canonical line — a second implementation has appeared"
    )
    assert not re.search( r"^def tree_state_line\(", source, re.MULTILINE ), (
        "the conftest defines its own tree_state_line again; there must be exactly one"
    )


def test_the_module_prints_one_line_and_exits_zero():
    """
    The node runners call this as a subprocess. A diagnostic that can fail a runner is
    worse than no diagnostic: a runner that dies while reporting which tree it ran on has
    destroyed the result it was describing.
    """
    done = subprocess.run( [ sys.executable, "-m", "cosa.utils.tree_state" ],
                           cwd=ROOT, capture_output=True, text=True, timeout=60,
                           env={ **os.environ, "PYTHONPATH": os.path.join( ROOT, "src" ) } )
    assert done.returncode == 0, f"module exited {done.returncode}: {done.stderr[ :400 ]}"
    lines = [ l for l in done.stdout.splitlines() if l.strip() ]
    assert len( lines ) == 1, f"expected exactly one line, got {lines!r}"
    assert lines[ 0 ].startswith( "[tree-state]" )


def test_the_shell_helper_renders_the_same_line_as_the_python_caller():
    """
    The property that makes one implementation worth the indirection: both paths produce
    the SAME line. Compared field by field rather than whole, because `fetched=` moves when
    a peer fetches between the two calls — a whole-string compare would be flaky for a
    reason that says nothing about the code.
    """
    done = subprocess.run( [ "bash", "-c", f'source "{HELPER}"; emit_tree_state' ],
                           cwd=ROOT, capture_output=True, text=True, timeout=60,
                           env={ **os.environ, "LUPIN_ROOT": ROOT } )
    shell_line = done.stdout.strip()
    assert shell_line.startswith( "[tree-state]" ), f"helper produced: {done.stdout!r} / {done.stderr[ :300 ]!r}"

    direct = tree_state_line( _git_reader( os.path.join( ROOT, "src" ) ) )
    stable = lambda line: [ f for f in line.split() if not f.startswith( "fetched=" ) ]
    assert stable( shell_line ) == stable( direct ), (
        f"the shell path and the python path rendered different lines:\n  shell: {shell_line}\n  py   : {direct}"
    )


def test_the_helper_never_fails_its_caller_even_with_no_python():
    """
    `emit_tree_state` must be safe to call unconditionally from a runner. With python
    unreachable it prints nothing and still returns success.
    """
    done = subprocess.run(
        [ "bash", "-c", f'source "{HELPER}"; PATH=/nonexistent emit_tree_state; echo "rc=$?"' ],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
        env={ **os.environ, "LUPIN_ROOT": ROOT } )
    assert "rc=0" in done.stdout, f"the helper failed its caller: {done.stdout!r}"


@pytest.mark.parametrize( "runner", [ TS_RUNNER, JS_RUNNER ],
                          ids=[ "run-typescript-tests.sh", "run-js-tests-capped.sh" ] )
def test_each_node_runner_emits_the_line_BEFORE_its_run( runner ):
    """
    Placement, not presence. After the run the line would be the LAST line, which the
    output contract forbids for every diagnostic; and in the capped runner
    `jstest_slice_exec` REPLACES the shell, so anything after it would never run at all.
    """
    source = open( runner ).read()
    assert "emit_tree_state" in source, f"{os.path.basename( runner )} does not state its tree"

    # Compare LINE NUMBERS over non-comment lines only. Matching raw offsets found
    # "node --test" inside a header comment and reported the emit as too late — the test
    # failed for a reason that had nothing to do with placement.
    code = [ ( n, l ) for n, l in enumerate( source.splitlines() )
                      if l.strip() and not l.lstrip().startswith( "#" ) ]
    emit    = next( n for n, l in code if l.strip() == "emit_tree_state" )
    exec_at = next( n for n, l in code
                      if l.lstrip().startswith( ( "jstest_slice_exec", "node --test", "npx c8" ) ) )
    assert emit < exec_at, (
        f"{os.path.basename( runner )} emits the tree-state line after the run starts; it must "
        f"come first"
    )


def test_coarse_age_moved_with_its_three_callers():
    """
    `_coarse_age` has three call sites, not one (Rio ⚡): the fetch age, the coverage-file
    age, and the module. Leaving it in the conftest would have split a shared helper away
    from two of its callers.
    """
    assert _coarse_age( 30 )      == "0m"
    assert _coarse_age( 3600 )    == "1h"
    assert _coarse_age( 86400 )   == "1d"
