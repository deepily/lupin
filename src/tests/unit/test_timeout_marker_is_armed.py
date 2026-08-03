"""
`@pytest.mark.timeout` is ARMED, not decoration — row `61ef0e0d`.

THE STATE THIS GUARDS AGAINST
-----------------------------
Six files decorated tests with `@pytest.mark.timeout(n)` while `pytest-timeout` was
NOT installed. An unrecognised marker is **silently ignored**, so all 18 caps were
inert — and four of the six files are subprocess / two-session shapes, precisely the
shape that hangs.

The near-miss that surfaced it (Krishna 🦚, 2026-07-27): arming `--strict-markers`
turned the unregistered marker into a hard collection error and took the unit tier
down fleet-wide for ~10 minutes.

⚠️ AND THE OBVIOUS FIX WAS THE WRONG ONE. Registering `timeout` in `pytest.ini`
clears the error instantly — and makes six uncapped files LOOK capped, which is
strictly worse than the red, because the marker then reads as a guard to every future
reader. It shipped as REGISTERED-NOT-PROVIDED with that stated plainly, until this.

WHY THIS FILE EXISTS RATHER THAN A LINE IN THE DOCS
---------------------------------------------------
If `pytest-timeout` is ever uninstalled — a dependency-group edit, a fresh venv, a
container image built without the dev group — **every cap in the tree silently
becomes decoration again, with no error anywhere.** The failure mode is a return to
the exact prior state, and it is invisible by construction: nothing goes red, tests
just stop being capped.

⇒ A pinned dependency is not enough on its own, because the thing that breaks is not
  the pin but the ENVIRONMENT the suite runs in. This asserts the property where it
  matters: in the running interpreter.

⚠️ WHY THE SECOND TEST SPAWNS A SUBPROCESS
An "is the plugin importable" check answers a weaker question than "does a cap
actually kill an over-running test". Those came apart today at a different layer —
the marker was registered (so collection worked) while the cap did not exist. This
file refuses to repeat that: it proves the ENFORCEMENT, not the registration.

Venue: :7999-eligible. No server, no docker, no network. ~1.5s (one subprocess).
"""
import subprocess
import sys
import textwrap

import pytest


def test_pytest_timeout_is_installed_and_loaded():
    """
    The cheap half. Necessary, not sufficient — see the enforcement test below.
    """
    import importlib.util

    assert importlib.util.find_spec( "pytest_timeout" ) is not None, (
        "pytest-timeout is NOT installed, so every @pytest.mark.timeout(n) in the tree "
        "is silently ignored and every cap is decoration. Reinstall it: it is pinned in "
        "pyproject [dependency-groups] dev."
    )


def _run_pytest_on( tmp_path, body ):
    """
    Run pytest in a SUBPROCESS against one generated test file.

    Requires:
        - body is the source of a test module

    Ensures:
        - returns ( returncode, combined_output )
        - the subprocess inherits this interpreter, so it exercises the SAME
          environment the caller is running in — a check against a different
          interpreter would answer about a venv nobody uses
    """
    f = tmp_path / "test_generated_cap_probe.py"
    f.write_text( textwrap.dedent( body ) )
    p = subprocess.run(
        [ sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
          "-p", "no:warnings", "-q", "--tb=line", str( f ) ],
        capture_output=True, text=True, timeout=120
    )
    return p.returncode, ( p.stdout + p.stderr )


def test_a_cap_ACTUALLY_KILLS_an_overrunning_test( tmp_path ):
    """
    ⚠️ THE LOAD-BEARING TEST. Proves ENFORCEMENT, not registration.

    Without this, "the whole suite still passes after installing pytest-timeout"
    is indistinguishable from "pytest-timeout still isn't active" — because every
    marked test in the tree finishes far under its cap (max measured 2.17s against a
    15s minimum), so arming the plugin changed no observable outcome. A green that
    cannot distinguish the fix from its absence is not evidence of the fix.
    """
    rc, out = _run_pytest_on( tmp_path, """
        import time, pytest

        @pytest.mark.timeout( 1 )
        def test_sleeps_past_its_cap():
            time.sleep( 5 )
    """ )
    assert rc != 0, f"a test sleeping 5s under a 1s cap PASSED — the cap is not enforced:\n{out}"
    assert "Timeout" in out, f"it failed, but not from the timeout — wrong reason:\n{out}"


def test_the_probe_harness_can_also_report_a_PASS( tmp_path ):
    """
    CONTROL for the test above. Its assertion is `rc != 0`, which a harness that
    ALWAYS fails would satisfy — a broken generator, an unwritable tmp_path, a
    collection error would each produce a non-zero exit and read as proof.

    Same generator, same runner, a test that fits its cap: it must come back GREEN.
    """
    rc, out = _run_pytest_on( tmp_path, """
        import time, pytest

        @pytest.mark.timeout( 5 )
        def test_finishes_well_within_its_cap():
            time.sleep( 0.05 )
    """ )
    assert rc == 0, f"the harness cannot produce a PASS, so the failure above proves nothing:\n{out}"


def test_no_global_timeout_is_set_in_addopts():
    """
    Pins the BLAST RADIUS. Arming the plugin was safe to do mid-session precisely
    because `addopts` sets no `--timeout`, so caps apply to MARKED tests only — 18 of
    them. A global cap added later would silently put every test in the repo under a
    wall-clock limit nobody chose per-test, which is a much larger change than this
    row authorised and should not arrive as a side effect of this one.
    """
    import configparser
    import os

    import cosa.utils.util as cu

    cfg = configparser.ConfigParser()
    cfg.read( os.path.join( cu.get_project_root(), "pytest.ini" ) )
    addopts = cfg.get( "pytest", "addopts", fallback="" )
    assert "--timeout" not in addopts, (
        f"a GLOBAL --timeout appeared in addopts ({addopts!r}). That caps every test in "
        "the repo, not the 18 that opted in. If it is deliberate, update row 61ef0e0d "
        "and this test together."
    )
