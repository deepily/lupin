"""
Row 73c6819d — a collection error must reach a HUMAN AT A TERMINAL, not just the suite job.

WHAT WAS ALREADY COVERED, and is not re-proved here: row bc83f2df wired the diagnosis into
the scheduled suite job (`job.py` reads the exit code) and into the in-process pytest hook
(`src/conftest.py`, which catches the test-module shape only). Its 17 tests live in
test_pytest_collection_diagnosis.py and still pass unchanged.

WHAT WAS NOT, and is what these tests are about: somebody running one of the sanctioned
runner scripts got pytest's bare traceback and nothing else. The conftest shape fires NO
pytest hook — not even in the outermost conftest — and writes no junit, so nothing inside
the process can report it. The exit code, read by the shell after pytest returns, is the
only signal that survives, and every runner reached it with `exec` — which replaces the
shell, leaving nothing alive to read the code.

PROVED BY CONSTRUCTION, in Sam's shape: every test here writes a real cause shape on disk
and runs a REAL runner script against it as a subprocess. Nothing is stubbed, so nothing
here can pass because of a string this file wrote.

MEASURED BEFORE THE FIX (2026-08-17, run-pytest-direct.sh against a broken conftest):
    exit 4, pytest's own ImportError traceback, and NO diagnosis block. The
    `test_raw_pytest_*` control below preserves that "before" — it asserts that plain
    pytest still says nothing, which is what makes the wrapper's output evidence.
"""

import os
import signal
import subprocess
import sys
import textwrap
import time

import pytest

import cosa.utils.util as cu


PROJECT_ROOT = cu.get_project_root()
RUN_DIRECT   = os.path.join( PROJECT_ROOT, "src", "tests", "run-pytest-direct.sh" )
HELPER       = os.path.join( PROJECT_ROOT, "src", "scripts", "lib", "pytest-with-diagnosis.sh" )
DIAG_MODULE  = os.path.join( PROJECT_ROOT, "src", "cosa", "utils", "pytest_collection_diagnosis.py" )

BLOCK_HEADLINE = "COLLECTION ERROR — the suite did not run"


# ── Builders: real cause shapes on disk ─────────────────────────────────────
def _write( path, text ):
    path.write_text( textwrap.dedent( text ).lstrip() )


@pytest.fixture
def broken_conftest( tmp_path ):
    """
    THE SHAPE THAT COST THE TIME: a required parameter added ahead of its callers, failing
    inside a conftest. Exit 4, no junit, no hook — invisible to anything inside pytest.
    """
    d = tmp_path / "conftest_shape"
    d.mkdir()
    _write( d / "provenance.py", """
        def make_provenance( source, run_id ):
            return { "source": source, "run_id": run_id }
    """ )
    _write( d / "conftest.py", """
        from provenance import make_provenance
        DEFAULT_PROV = make_provenance( "test" )
    """ )
    _write( d / "test_paired_eval.py", """
        def test_x(): assert True
        def test_y(): assert True
    """ )
    return d


@pytest.fixture
def broken_test_module( tmp_path ):
    """The other shape: an orphaned import in a test module. Exit 2, hooks DO fire."""
    d = tmp_path / "module_shape"
    d.mkdir()
    _write( d / "test_orphan.py", """
        from cosa.memory.credential_watcher_retired import CredentialWatcher
        def test_it(): assert CredentialWatcher
    """ )
    _write( d / "test_innocent_bystander.py", """
        def test_a(): assert True
    """ )
    return d


def _run_runner( target, extra_env=None ):
    """Run the real runner script against `target`; return (exit code, combined output)."""
    env = dict( os.environ )
    if extra_env: env.update( extra_env )
    proc = subprocess.run(
        [ "bash", RUN_DIRECT, str( target ), "-p", "no:cacheprovider" ],
        capture_output=True, text=True, timeout=180, env=env,
    )
    return proc.returncode, proc.stdout + proc.stderr


# ── 1. THE "BEFORE", kept alive as a control ────────────────────────────────
def test_raw_pytest_still_says_nothing_about_a_broken_conftest( broken_conftest ):
    """
    THE CONTROL THAT MAKES THE REST EVIDENCE. Bare pytest — no wrapper — reports the
    traceback and no cause class, which is exactly the silence this row is about. If this
    ever starts printing a diagnosis on its own, the wrapper's output stops being proof
    that the wrapper did anything, and this test failing is how we would find out.
    """
    proc = subprocess.run(
        [ sys.executable, "-m", "pytest", str( broken_conftest ), "-p", "no:cacheprovider" ],
        capture_output=True, text=True, timeout=180,
    )
    output = proc.stdout + proc.stderr

    assert proc.returncode == 4, "a conftest import failure is a pytest usage error"
    assert "ImportError while loading conftest" in output
    assert BLOCK_HEADLINE not in output, "plain pytest cannot report this — that is the defect"


# ── 2. THE "AFTER": the runner script reports both shapes ───────────────────
def test_runner_diagnoses_the_conftest_shape( broken_conftest ):
    """The half no hook can reach. This is the whole point of the row."""
    code, output = _run_runner( broken_conftest )

    assert code == 4, "the runner must re-raise pytest's status verbatim"
    assert BLOCK_HEADLINE in output
    assert "Where        : conftest" in output
    assert "signature change ahead of its callers" in output
    assert "make_provenance" in output


def test_runner_diagnoses_the_test_module_shape( broken_test_module ):
    """The loud half, which the in-process hook also catches — the wrapper must not lose it."""
    code, output = _run_runner( broken_test_module )

    assert code == 2
    assert BLOCK_HEADLINE in output
    assert "orphaned import" in output
    assert "credential_watcher_retired" in output


def test_runner_flags_an_empty_selection_rather_than_reading_it_as_a_pass( tmp_path ):
    """Exit 5 — nothing collected — is the adjacent silence, and is not a pass either."""
    d = tmp_path / "empty"; d.mkdir()
    ( d / "test_nothing.py" ).write_text( "# no tests here\n" )

    code, output = _run_runner( d )

    assert code == 5
    assert BLOCK_HEADLINE in output
    assert "no tests matched" in output


# ── 3. THE CONTROLS: runs that DID execute must be untouched ────────────────
def test_a_passing_run_is_unchanged_and_silent( tmp_path ):
    """
    THE CONTROL THAT MATTERS MOST. A wrapper that printed the block on every run would
    satisfy every test above while making the block meaningless.
    """
    d = tmp_path / "green"; d.mkdir()
    ( d / "test_green.py" ).write_text( "def test_ok(): assert True\n" )

    code, output = _run_runner( d )

    assert code == 0, "a pass must still exit 0 — the wrapper adds nothing to a run that ran"
    assert BLOCK_HEADLINE not in output
    assert "1 passed" in output


def test_a_failing_run_keeps_its_own_verdict( tmp_path ):
    """
    A genuine red ran and produced a verdict. Dressing it as a collection error would
    suppress a real defect — the mirror image of the bug being fixed.
    """
    d = tmp_path / "red"; d.mkdir()
    ( d / "test_red.py" ).write_text( "def test_bad(): assert False\n" )

    code, output = _run_runner( d )

    assert code == 1, "a failure must still exit 1 — a swallowed status is the same silence"
    assert BLOCK_HEADLINE not in output
    assert "1 failed" in output


# ── 4. DROPPING `exec` CHANGED PROCESS SHAPE — measure what it changed ──────
def test_ctrl_c_still_ends_the_run_with_130( tmp_path ):
    """
    `exec` handed the terminal's signal straight to pytest. Now a shell sits in between,
    so this asserts the observable a human cares about: one SIGINT to the process group
    (what Ctrl-C sends) ends the run with 130, and no diagnosis block is invented for it.
    """
    d = tmp_path / "slow"; d.mkdir()
    ( d / "test_slow.py" ).write_text( "import time\ndef test_slow(): time.sleep( 60 )\n" )

    proc = subprocess.Popen(
        [ "bash", RUN_DIRECT, str( d ), "-p", "no:cacheprovider" ],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True,
    )
    # Wait for pytest to actually be running before interrupting, so the signal lands on a
    # started run rather than on process startup.
    time.sleep( 8 )
    os.killpg( os.getpgid( proc.pid ), signal.SIGINT )
    output = proc.communicate( timeout=60 )[ 0 ]

    assert proc.returncode == 130, f"expected 130 for an interrupted run, got {proc.returncode}"
    assert BLOCK_HEADLINE not in output, "an interrupt is not a collection error"


def test_a_timeout_kill_keeps_its_own_status( tmp_path ):
    """A killed run reports 124 through the wrapper, and is not re-labelled."""
    d = tmp_path / "slow2"; d.mkdir()
    ( d / "test_slow.py" ).write_text( "import time\ndef test_slow(): time.sleep( 60 )\n" )

    proc = subprocess.run(
        [ "timeout", "-s", "TERM", "5", "bash", RUN_DIRECT, str( d ), "-p", "no:cacheprovider" ],
        capture_output=True, text=True, timeout=90,
    )

    assert proc.returncode == 124
    assert BLOCK_HEADLINE not in ( proc.stdout + proc.stderr )


def test_a_pid_file_guard_still_records_the_shell_that_owns_the_run( tmp_path ):
    """
    THE `exec` FALLOUT, MEASURED. The overlap guards in run-integration-tests.sh and
    run-e2e-ui-tests.sh record `$$` — the runner shell's own PID, never pytest's — and
    check it with `kill -0`. Neither script ever used `exec`, so the wrapper cannot have
    changed them; this asserts the pattern they rely on holds while the wrapper is running
    a real pytest: the recorded PID is the wrapper shell, and it is alive mid-run.
    """
    d = tmp_path / "slow3"; d.mkdir()
    ( d / "test_slow.py" ).write_text( "import time\ndef test_slow(): time.sleep( 20 )\n" )
    pid_file = tmp_path / "guarded.pid"

    guarded = tmp_path / "guarded_runner.sh"
    _write( guarded, f"""
        #!/bin/bash
        set -e
        export LUPIN_ROOT="{PROJECT_ROOT}"
        echo "$$" > "{pid_file}"
        source "{HELPER}"
        run_pytest_with_diagnosis "{sys.executable}" -m pytest "{d}" -p no:cacheprovider
        exit $?
    """ )

    proc = subprocess.Popen( [ "bash", str( guarded ) ],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True )
    # Give the script time to write the PID file and start pytest.
    time.sleep( 5 )
    recorded = int( pid_file.read_text().strip() )
    alive    = subprocess.run( [ "kill", "-0", str( recorded ) ] ).returncode == 0
    proc.communicate( timeout=90 )

    assert recorded == proc.pid, "the guard must record the runner shell, which is what it kills"
    assert alive, "the recorded PID must be live mid-run, or the guard reads a running suite as stale"


# ── 5. FAIL-SAFE: the diagnostic may never become the failure ───────────────
def test_exit_code_survives_a_missing_diagnosis_module( broken_conftest, tmp_path ):
    """
    The thing being diagnosed is often a broken import in this very tree. If the diagnoser
    cannot be found or cannot run, the run's own status must still come through untouched —
    a diagnostic that can change a verdict is worse than the silence it removes.

    Driven through the helper directly rather than through a runner script: every runner
    exports its OWN LUPIN_ROOT (that is how it finds the repo at all), so a runner cannot
    be pointed at an empty tree from outside.
    """
    empty_root = tmp_path / "no_lupin_here"; empty_root.mkdir()
    harness    = tmp_path / "no_module_runner.sh"
    _write( harness, f"""
        #!/bin/bash
        export LUPIN_ROOT="{empty_root}"
        source "{HELPER}"
        run_pytest_with_diagnosis "{sys.executable}" -m pytest "{broken_conftest}" -p no:cacheprovider
        exit $?
    """ )

    proc   = subprocess.run( [ "bash", str( harness ) ], capture_output=True, text=True, timeout=180 )
    output = proc.stdout + proc.stderr

    assert proc.returncode == 4, "the pytest status is the product; nothing may swallow it"
    assert "ImportError while loading conftest" in output, "pytest's own report must still arrive"
    assert BLOCK_HEADLINE not in output, "no module, no block — and no invented one either"


def test_colourised_output_is_still_diagnosed( broken_test_module ):
    """
    REGRESSION GUARD FOR THE WRAPPER'S OWN SIDE EFFECT. `tee` makes stdout a pipe, which
    makes pytest drop colour, so the wrapper asks for colour back with PY_COLORS. That puts
    escape codes inside the text the cause-classifier matches against — and a coloured
    "E   ModuleNotFoundError" does not match a pattern written for the plain string.
    """
    code, output = _run_runner( broken_test_module, extra_env={ "PY_COLORS": "1" } )

    assert code == 2
    assert BLOCK_HEADLINE in output
    assert "orphaned import" in output, "the escape codes must be stripped before matching"


# ── 6. THE CENSUS: a runner that loses the wrapper must go red ──────────────
# Every runner script whose backing command is pytest. Losing the wrapper in one of these
# restores the original silence for that suite and nothing else would notice — the same
# shape as the gate-reachability census (row d97b024e).
_PYTEST_RUNNERS = (
    "src/tests/run-unit-tests.sh",
    "src/tests/run-cosa-tests.sh",
    "src/tests/run-smoke-tests.sh",
    "src/tests/run-pytest-direct.sh",
    "src/tests/run-integration-tests.sh",
    "src/scripts/run-e2e-ui-tests.sh",
    "src/scripts/run-serial-bridge-guard.sh",
)


@pytest.mark.parametrize( "script_rel", _PYTEST_RUNNERS )
def test_every_pytest_runner_calls_the_diagnosis_wrapper( script_rel ):
    text = open( os.path.join( PROJECT_ROOT, script_rel ) ).read()

    assert "pytest-with-diagnosis.sh" in text, f"{script_rel} no longer sources the wrapper"
    assert "run_pytest_with_diagnosis" in text, f"{script_rel} no longer calls the wrapper"


@pytest.mark.parametrize( "script_rel", _PYTEST_RUNNERS )
def test_no_pytest_runner_execs_pytest_away( script_rel ):
    """
    `exec` replaces the shell, so there is no shell left to read the exit code — which is
    the only signal a conftest collection error produces. A re-introduced `exec pytest`
    would silently undo this row.
    """
    text = open( os.path.join( PROJECT_ROOT, script_rel ) ).read()
    offenders = [ line.strip() for line in text.splitlines()
                  if line.strip().startswith( "exec " ) and "pytest" in line ]

    assert offenders == [], f"{script_rel} exec's pytest again: {offenders}"


def test_the_presentation_orchestrator_diagnoses_its_own_not_executed_tiers():
    """
    Its tiers are classified 3-way already, so a collection error lands in NOT EXECUTED
    with the raw code named and no cause. It calls the module directly rather than through
    the wrapper, because it runs each tier under `timeout … | tee` itself.
    """
    text = open( os.path.join( PROJECT_ROOT, "src/tests/run-presentation-regression.sh" ) ).read()

    assert "pytest_collection_diagnosis.py" in text
    assert "--exit-code" in text


# ── 7. THE RUNNERS MUST FIND THEIR OWN REPO ────────────────────────────────
# Section 6 reads each runner's TEXT, so it passes whether or not the script can run at
# all. run-serial-bridge-guard.sh computed its project root as SCRIPT_DIR/.. — one level
# short, because the script lives at src/scripts/ — and so sourced
# <root>/src/src/scripts/lib/pytest-with-diagnosis.sh, exited 1, and ran ZERO tests. The
# text census stayed green through every bit of it. This runs the script.
def test_the_serial_bridge_guard_runner_finds_its_own_repo():
    """
    Requires:
        - src/scripts/run-serial-bridge-guard.sh exists and is executable.

    Ensures:
        - the runner exits 0 collecting its two guard tests, which is only possible if
          PROJECT_ROOT resolved to the repo root.
        - a root resolved one level short goes RED here: the source fails and the exit
          code is 1 with no tests collected.

    Collection only — nothing is executed, so no bridge is written and the box does not
    need to be quiescent for this test.
    """
    script = os.path.join( PROJECT_ROOT, "src", "scripts", "run-serial-bridge-guard.sh" )
    result = subprocess.run(
        [ script, "--collect-only", "-q", "-p", "no:cacheprovider" ],
        capture_output=True, text=True, timeout=180,
    )
    combined = result.stdout + result.stderr

    assert "No such file or directory" not in combined, f"the runner could not resolve its own tree:\n{combined}"
    assert result.returncode == 0, f"runner exited {result.returncode}:\n{combined}"
    assert "test_the_real_bridge_dir_is_untouched_SERIAL_GATE" in combined, f"the two guard tests were not collected:\n{combined}"
