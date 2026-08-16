"""Guard: run-unit-tests.sh must FAIL LOUD when no venv pytest is found (row c98bce3f).

WHY THIS IS A COMMITTED GATE, not a one-off check. The runner used to silently fall back
to a bare `python3 -m pytest` when its expected venv pytest was absent. On 2026-08-16 that
silent interpreter switch ran the container's under-provisioned /opt/venv, aborted collection
of ~3000 tests, and the runner reported the REDUCED count as a pass — a false green on the
:8000 merge gate. The fix removed the fallback; this test pins that the fallback stays gone,
because an ungated fix to a runner can silently regress into the exact defect it removed.

The test drives the SHIPPED script with both venv candidates pointed at nonexistent paths and
asserts it exits non-zero, names what it looked for, and never mentions the bare-python fallback.
"""

import os
import subprocess

_PROJECT_ROOT = os.environ[ "LUPIN_ROOT" ]
_SCRIPT       = os.path.join( _PROJECT_ROOT, "src", "tests", "run-unit-tests.sh" )

# The two candidate paths the shipped script probes, in order.
_HOST_CANDIDATE      = '"$PROJECT_ROOT/.venv/bin/pytest"'
_CONTAINER_CANDIDATE = '"/opt/venv/bin/pytest"'


def _patched_script_with_absent_venvs( tmp_path ):
    """A copy of the shipped runner whose BOTH venv candidates point at nonexistent paths."""
    text    = open( _SCRIPT ).read()
    patched = ( text
                .replace( _HOST_CANDIDATE,      '"/nonexistent/host/pytest"' )
                .replace( _CONTAINER_CANDIDATE, '"/nonexistent/container/pytest"' ) )
    # Guard the guard: if the candidate literals ever change, this test must fail loudly
    # rather than silently exercise the unpatched script (which would find the real .venv).
    assert "/nonexistent/host/pytest" in patched and "/nonexistent/container/pytest" in patched, \
        "candidate literals in run-unit-tests.sh changed — update this test's replacements"
    script = tmp_path / "run-unit-tests.sh"
    script.write_text( patched )
    return str( script )


def test_fails_loud_when_no_venv_pytest_is_found( tmp_path ):
    script = _patched_script_with_absent_venvs( tmp_path )
    result = subprocess.run( [ "bash", script ], capture_output=True, text=True, timeout=30 )

    combined = result.stdout + result.stderr
    assert result.returncode != 0, f"runner did NOT fail loud (exit {result.returncode}):\n{combined}"
    assert "no runnable venv pytest found" in result.stderr, result.stderr
    # It names BOTH paths it looked for, in the message.
    assert "/nonexistent/host/pytest" in result.stderr, result.stderr
    assert "/nonexistent/container/pytest" in result.stderr, result.stderr
    # And it did NOT quietly execute a bare python3 fallback (the removed defect).
    assert "using pytest at" not in combined, "runner selected a pytest despite both candidates being absent"


def test_names_the_merge_gate_risk_in_its_refusal( tmp_path ):
    # The refusal explains WHY the fallback is refused — so the next reader does not
    # re-add it as a convenience. Pins the rationale, not just the exit code.
    script = _patched_script_with_absent_venvs( tmp_path )
    result = subprocess.run( [ "bash", script ], capture_output=True, text=True, timeout=30 )
    assert "python3 -m pytest" in result.stderr, "refusal should name the fallback it declines"
    assert "false green" in result.stderr.lower(), result.stderr
