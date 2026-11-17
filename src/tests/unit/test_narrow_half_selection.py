"""
A test path given to a --half run must narrow it or be refused.

The runner used to append the caller's path to the half's file list. A path already in the half
adds nothing, so the whole half ran with no refusal: 544 passed, 1151 s, for a one-file request.

Each case sources the real src/scripts/lib/narrow-half-selection.sh in bash over files in
tmp_path and reads back the arrays it leaves. It runs on :7999: no server, no network.
"""

import os
import subprocess

import cosa.utils.util as cu


PROJECT_ROOT = cu.get_project_root()
LIB          = os.path.join( PROJECT_ROOT, "src", "scripts", "lib", "narrow-half-selection.sh" )
RUNNER       = os.path.join( PROJECT_ROOT, "src", "scripts", "run-e2e-ui-tests.sh" )


def _run( tmp_path, selected, args ):
    """
    Run narrow_half_selection over files named in `selected` (all created under tmp_path).

    Returns ( returncode, stdout lines ) where stdout is the message, then SEL: and REM: lines.
    """
    for rel in selected + [ "other/test_outside.py" ]:
        full = tmp_path / rel
        full.parent.mkdir( parents=True, exist_ok=True )
        full.write_text( "" )
    script = (
        f'source "{LIB}"\n'
        f'SELECTED_TESTS=( {" ".join( selected )} )\n'
        'REMAINING_ARGS=( "$@" )\n'
        f'narrow_half_selection "{tmp_path}"; rc=$?\n'
        'for x in "${SELECTED_TESTS[@]}"; do echo "SEL:$x"; done\n'
        'for x in "${REMAINING_ARGS[@]}"; do echo "REM:$x"; done\n'
        'exit $rc\n'
    )
    done = subprocess.run( [ "bash", "-c", script, "bash", *args ], capture_output=True, text=True )
    return done.returncode, done.stdout.splitlines()


HALF = [ "e2e/test_a.py", "e2e/test_b.py", "e2e/test_c.py" ]


def test_a_path_in_the_half_replaces_the_half_list( tmp_path ):
    rc, out = _run( tmp_path, HALF, [ "e2e/test_b.py", "-x" ] )
    assert rc == 0
    assert [ l for l in out if l.startswith( "SEL:" ) ] == [ "SEL:e2e/test_b.py" ]
    assert [ l for l in out if l.startswith( "REM:" ) ] == [ "REM:-x" ]


def test_a_node_id_and_dot_slash_prefix_are_honoured( tmp_path ):
    rc, out = _run( tmp_path, HALF, [ "./e2e/test_a.py::test_one" ] )
    assert rc == 0
    assert [ l for l in out if l.startswith( "SEL:" ) ] == [ "SEL:e2e/test_a.py::test_one" ]


def test_a_path_outside_the_half_is_refused_and_named( tmp_path ):
    rc, out = _run( tmp_path, HALF, [ "other/test_outside.py" ] )
    assert rc == 2
    assert any( "not in this half's manifest: other/test_outside.py" in l for l in out )


def test_a_missing_path_is_refused_and_named( tmp_path ):
    rc, out = _run( tmp_path, HALF, [ "e2e/test_gone.py" ] )
    assert rc == 2
    assert any( "does not exist: e2e/test_gone.py" in l for l in out )


def test_one_bad_path_refuses_even_when_another_is_good( tmp_path ):
    rc, out = _run( tmp_path, HALF, [ "e2e/test_a.py", "other/test_outside.py" ] )
    assert rc == 2


def test_option_values_without_a_path_leave_the_half_whole( tmp_path ):
    rc, out = _run( tmp_path, HALF, [ "-k", "some_expr", "-m", "visual" ] )
    assert rc == 0
    assert len( [ l for l in out if l.startswith( "SEL:" ) ] ) == 3
    assert [ l for l in out if l.startswith( "REM:" ) ] == [ "REM:-k", "REM:some_expr", "REM:-m", "REM:visual" ]


def test_the_runner_sources_the_lib_and_exits_2_on_refusal():
    text = open( RUNNER ).read()
    assert text.count( "lib/narrow-half-selection.sh" ) == 1
    assert "NARROW_RC" in text and "exit 2" in text.split( "NARROW_RC" )[ 2 ][ :300 ]
