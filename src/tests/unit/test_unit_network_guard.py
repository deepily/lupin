"""
Row 7c84b8b8 — the unit tier's guard against tests that dial OUT.

WHY THE GUARD EXISTS. A unit test that opens a network connection does not pass or fail on
the code; it passes or fails on whether a server happened to be up. Five tests in
test_v2_eval.py dialled :8000 for a git sha, and their red set MOVED between runs of
identical code — two seats independently read that movement as a branch-versus-base
difference. The unit tier is a merge gate.

PROVED BY CONSTRUCTION. Every arm here runs a REAL pytest subprocess with a REAL test file
and a REAL socket, in each of the guard's three modes. Asserting on the guard's internals
would prove the module's shape, not that a run is protected.

⚠️ THE ARM THAT MATTERS is `test_block_mode_names_the_frames_not_just_the_test`. The first
instrument built for this row recorded only which test was in flight and blamed a file that
contains no networking code at all — the dial came from production the test reached. A guard
that names the victim sends the next reader to the wrong file.
"""

import os
import subprocess
import sys
import textwrap

import pytest

import cosa.utils.util as cu


PROJECT_ROOT = cu.get_project_root()


def _install_real_guard( directory ):
    """
    Put the REAL guard into a sandbox directory, by loading `src/conftest.py` itself.

    ⚠️ WHY NOT JUST RUN THE SANDBOX TEST DIRECTLY: pytest loads a conftest only for tests
    UNDER it, so a throwaway file in /tmp gets no guard at all and every arm below would
    pass for the wrong reason. Copying the guard's logic here would be worse — it would
    prove a copy works. This loads the shipped file, so the arms exercise what actually
    ships, including the import-time socket patch.

    Writing the throwaway tests inside the repo instead was rejected: a concurrent tier on
    this box would collect a deliberately-dialing test and go red for no reason.
    """
    ( directory / "conftest.py" ).write_text( textwrap.dedent( f"""
        import importlib.util, os
        _path = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "conftest.py" )
        _spec = importlib.util.spec_from_file_location( "lupin_root_conftest_under_test", _path )
        _mod  = importlib.util.module_from_spec( _spec )
        _spec.loader.exec_module( _mod )

        pytest_runtest_setup    = _mod.pytest_runtest_setup
        pytest_terminal_summary = _mod.pytest_terminal_summary
    """ ).lstrip() )


def _run_pytest( target, mode, extra_env=None ):
    """Run a real pytest subprocess with the guard in `mode`; return (exit code, output)."""
    env = dict( os.environ )
    env[ "LUPIN_UNIT_NETWORK" ] = mode
    env[ "PYTHONPATH" ]         = os.path.join( PROJECT_ROOT, "src" ) + os.pathsep + env.get( "PYTHONPATH", "" )
    env[ "LUPIN_ROOT" ]         = PROJECT_ROOT
    if extra_env: env.update( extra_env )
    proc = subprocess.run(
        [ sys.executable, "-m", "pytest", str( target ), "-q", "-p", "no:cacheprovider" ],
        capture_output=True, text=True, timeout=180, env=env, cwd=PROJECT_ROOT,
    )
    return proc.returncode, proc.stdout + proc.stderr


@pytest.fixture
def dialing_test( tmp_path ):
    """A test that reaches a routed address — through a helper, so the frames have depth."""
    _install_real_guard( tmp_path )
    path = tmp_path / "test_dials_out.py"
    path.write_text( textwrap.dedent( """
        import socket

        def _the_actual_culprit():
            s = socket.socket()
            s.settimeout( 2 )
            try:
                s.connect( ( "192.0.2.1", 9 ) )     # TEST-NET-1, reserved and unroutable
            finally:
                s.close()

        def test_innocent_looking_name():
            _the_actual_culprit()
    """ ).lstrip() )
    return path


@pytest.fixture
def swallowing_dialer( tmp_path ):
    """
    A dialer whose caller catches broadly — the shape production actually has.

    ⚠️ THIS IS THE GUARD'S HONEST LIMIT. `dm.py`'s inline grader wraps its model call in a
    broad `except`, so raising into it changes nothing the test can see: the test still
    passes. That is precisely why the summary line exists and why the zero case is printed
    — the count is the only signal that survives code which swallows.
    """
    _install_real_guard( tmp_path )
    path = tmp_path / "test_swallows.py"
    path.write_text( textwrap.dedent( """
        import socket

        def _grader_that_never_raises():
            s = socket.socket()
            s.settimeout( 2 )
            try:
                s.connect( ( "192.0.2.1", 9 ) )
            except Exception:
                pass                      # exactly what production does
            finally:
                s.close()

        def test_looks_completely_local():
            _grader_that_never_raises()
    """ ).lstrip() )
    return path


@pytest.fixture
def loopback_test( tmp_path ):
    """A test that binds and connects to 127.0.0.1 — legitimate, and must never be touched."""
    _install_real_guard( tmp_path )
    path = tmp_path / "test_loopback.py"
    path.write_text( textwrap.dedent( """
        import socket

        def test_loopback_round_trip():
            server = socket.socket()
            server.bind( ( "127.0.0.1", 0 ) )
            server.listen( 1 )
            client = socket.socket()
            client.connect( server.getsockname() )
            client.close()
            server.close()
    """ ).lstrip() )
    return path


# ── 1. BLOCK MODE — the guard fires, and blames the right code ──────────────
def test_block_mode_fails_the_test_that_dials_out( dialing_test ):
    code, output = _run_pytest( dialing_test, "block" )

    assert code != 0, "a dialing test must not pass in block mode"
    assert "OUTBOUND NETWORK BLOCKED" in output
    assert "192.0.2.1" in output, "the refusal must name the address"


def test_block_mode_names_the_frames_not_just_the_test( dialing_test ):
    """
    THE LESSON THIS ROW WAS TAUGHT THE HARD WAY. Naming the test in flight is not enough:
    the dial often comes from production code the test merely reaches, and the file that
    gets blamed then contains no networking at all.
    """
    _code, output = _run_pytest( dialing_test, "block" )

    assert "_the_actual_culprit" in output, "the guard must name the frame that dialled"
    assert "test_dials_out.py" in output


def test_block_mode_says_how_to_fix_it( dialing_test ):
    """A refusal that does not name its own escape hatch gets worked around, not obeyed."""
    _code, output = _run_pytest( dialing_test, "block" )

    assert "allows_outbound_network" in output
    assert "Inject the seam" in output


# ── 2. THE EXEMPTION — explicit, per-test, in the file that needs it ────────
def test_a_marked_test_is_allowed_through( tmp_path ):
    """
    Deliberate live tests exist (TestLiveMistralRegression). They need a NAMED exemption,
    not an environment switch that quietly exempts everything.
    """
    _install_real_guard( tmp_path )
    path = tmp_path / "test_marked_live.py"
    path.write_text( textwrap.dedent( """
        import socket
        import pytest

        @pytest.mark.allows_outbound_network
        def test_deliberately_live():
            s = socket.socket()
            s.settimeout( 1 )
            try:
                s.connect( ( "192.0.2.1", 9 ) )
            except Exception:
                pass
            finally:
                s.close()
    """ ).lstrip() )

    code, output = _run_pytest( path, "block" )

    assert code == 0, "a marked test must run untouched"
    assert "OUTBOUND NETWORK BLOCKED" not in output


# ── 3. COUNT MODE — the census that does not stop at its first finding ─────
def test_count_mode_records_without_failing_the_test( swallowing_dialer ):
    """
    MEASURED 2026-08-17: in block mode the FIRST offender in the real tier was at collection
    time, and a collection error takes the rest of the run with it — one offender hid every
    other one. Count mode is what makes a census a census.
    """
    code, output = _run_pytest( swallowing_dialer, "count" )

    assert code == 0, "count mode must not fail the run — it is measuring, not enforcing"
    assert "[unit-network:count] outbound connections: 1" in output
    assert "192.0.2.1" in output


def test_count_mode_reports_zero_out_loud( loopback_test ):
    """
    THE ZERO CASE IS PRINTED ON PURPOSE. A guard silent on a clean run is indistinguishable
    from a guard that was never armed — the exact confusion this row exists to end.
    """
    code, output = _run_pytest( loopback_test, "count" )

    assert code == 0
    assert "[unit-network:count] outbound connections: 0" in output


def test_a_swallowed_block_is_still_reported( swallowing_dialer ):
    """
    THE CASE THAT WOULD OTHERWISE GO SILENT. Code that catches broadly eats the guard's
    refusal, so the test passes — and the run must still SAY the connection happened, or
    the guard is defeated by the very pattern that made the original bug invisible.
    """
    code, output = _run_pytest( swallowing_dialer, "block" )

    assert code == 0, "the test swallows the refusal — this arm is about the REPORT, not the verdict"
    assert "[unit-network:block] outbound connections: 1" in output
    assert "_grader_that_never_raises" in output


# ── 4. THE CONTROLS — loopback and the default must be untouched ───────────
def test_loopback_is_never_blocked( loopback_test ):
    """
    TestClient and the real-socket probe tests bind 127.0.0.1 deliberately. A guard that
    breaks legitimate tests gets switched off, and a control that is switched off is worse
    than no control at all.
    """
    code, output = _run_pytest( loopback_test, "block" )

    assert code == 0, "loopback must pass even in block mode"
    assert "OUTBOUND NETWORK BLOCKED" not in output


def test_off_is_the_default_and_is_completely_inert( swallowing_dialer ):
    """
    Integration and E2E runs use the network legitimately and never set the variable, so
    the guard must be invisible to them — no block, and no summary line either.
    """
    code, output = _run_pytest( swallowing_dialer, "off" )

    assert code == 0
    assert "OUTBOUND NETWORK BLOCKED" not in output
    assert "unit-network" not in output


def test_an_unknown_mode_does_not_arm_the_guard( swallowing_dialer ):
    """A typo in the variable must fail SAFE (inert), not fail closed on every test."""
    code, output = _run_pytest( swallowing_dialer, "blokc" )

    assert code == 0
    assert "OUTBOUND NETWORK BLOCKED" not in output


# ── 5. THE WIRING — the unit runners must actually arm it ──────────────────
@pytest.mark.parametrize( "script_rel", (
    "src/tests/run-unit-tests.sh",
    "src/tests/run-cosa-tests.sh",
) )
def test_the_unit_runners_arm_the_guard( script_rel ):
    """
    A guard nothing sets is a guard nothing runs — the shape of row d97b024e. If someone
    drops the export, this goes red instead of the tier quietly losing its protection.
    """
    text = open( os.path.join( PROJECT_ROOT, script_rel ) ).read()

    assert "LUPIN_UNIT_NETWORK" in text, f"{script_rel} no longer arms the network guard"


@pytest.mark.parametrize( "script_rel", (
    "src/tests/run-integration-tests.sh",
    "src/scripts/run-e2e-ui-tests.sh",
) )
def test_the_network_using_runners_do_not_arm_it( script_rel ):
    """
    Integration and E2E legitimately use the network. Arming the guard there would be a
    guard that fires on correct behaviour, which is how guards get deleted.
    """
    text = open( os.path.join( PROJECT_ROOT, script_rel ) ).read()

    assert "LUPIN_UNIT_NETWORK" not in text, f"{script_rel} must not arm the unit network guard"
