"""
preflight-vm.sh check C8 — the CALLER for `check_schema_parity.py` (row 3eb6dc41).

THE DEFECT THIS FILE EXISTS TO KEEP CLOSED
------------------------------------------
`src/scripts/check_schema_parity.py` landed 2026-05-29 with a green unit suite
and NO CALLER. Its own docstring said it existed to "gate a deploy / CI step";
nothing ever invoked it, for ~2 months. **A check that exists and never runs is
the same defect as a check that runs and cannot fail** — worse, because the green
unit suite is precisely what made it read as live in an audit.

⇒ So the remedy is a CALLER **plus proof the caller can go RED**. Asserting that
  the string `check_schema_parity.py` appears somewhere in the shell script would
  reproduce the original defect one layer up: a green assertion about a check that
  has never been observed to fail.

WHAT THIS FILE RUNS
-------------------
The real `preflight-vm.sh`, from a tmp copy (script + its lib, so `SCRIPT_DIR/lib`
resolves), with a STUB `docker` on PATH whose exit code and stdout for the parity
probe are driven by env vars. No VM, no container, no network, no database.

⚠️ THE CONTROL THAT MUST FAIL. A harness that only ever observes the wired script
is unaudited: it cannot tell "C8 fired" from "my grep matches something else".
`test_the_harness_ITSELF_can_tell_wired_from_unwired` runs the identical stub
against a copy with the C8 block DELETED and asserts the drift line is ABSENT
while C7's line is still PRESENT — proving the stub reached the script and the
assertion tracks C8 specifically.

⚠️ WHAT A GREEN HERE DOES NOT MEAN: that the probe works against a real database.
That is `src/cosa/tests/unit/scripts_tests/test_check_schema_parity.py`, whose
live layer creates a throwaway DB, drops `users.is_protected` and observes the
drift end to end (run 2026-07-27: 15 passed, live layer NOT skipped).

Venue: :7999-eligible. Subprocess `bash`, stubbed PATH, no state touched, <5s.
`PREFLIGHT_VM_APP_URL` is pointed at a dead port so layer D can never reach
Rick's live :7999 — a dead port is a connection REFUSED, i.e. immediate.
"""
import os
import pathlib
import re
import shutil
import subprocess

import pytest


LUPIN_ROOT = pathlib.Path( os.environ[ "LUPIN_ROOT" ] )
SCRIPT     = LUPIN_ROOT / "src/scripts/preflight-vm.sh"
LIB        = LUPIN_ROOT / "src/scripts/lib/preflight-vm-lib.sh"

# The stub answers `docker exec … check_schema_parity.py` with these.
PARITY_DRIFT_OUT = (
    "✗ Schema DRIFT detected (model is the source of truth):\n"
    "VERDICT=DRIFT\n"
    "DETAIL=tables with drift: users\n"
)
PARITY_OK_OUT     = "✓ Schema parity: every model table matches the live database.\nVERDICT=PARITY\n"
PARITY_UNKNOWN_OUT = (
    "VERDICT=CANNOT_DETERMINE\n"
    "DETAIL=cannot read the live schema: OperationalError: connection refused\n"
)

# `docker` stub. Only the calls layer C actually makes are answered; the parity
# probe's rc/stdout come from the environment so one stub drives every arm.
DOCKER_STUB = r"""#!/bin/bash
case "$1 $2" in
    "ps --filter"|"ps -a")
        printf '%s\n' "$PFV_STUB_CONTAINER"; exit 0 ;;
esac
if [ "$1" = "ps" ]; then printf '%s\n' "$PFV_STUB_CONTAINER"; exit 0; fi
if [ "$1" = "inspect" ]; then printf '/var/lupin\n/home/rruiz/.claude\n/home/rruiz/.claude/sessions\n'; exit 0; fi
if [ "$1" = "exec" ]; then
    shift
    case "$*" in
        *check_schema_parity.py*)
            printf '%s' "$PFV_STUB_PARITY_OUT"; exit "$PFV_STUB_PARITY_RC" ;;
        *check_schema_at_head.py*)
            printf 'HEAD_IN_TREE=abc123\nCURRENT_IN_DB=abc123\nVERDICT=AT_HEAD\n'; exit 0 ;;
    esac
    exit 0
fi
exit 0
"""

# `sudo` stub — layer B shells out to `sudo -n git`. Deterministic refusal, so no
# arm of this test can ever block on a password prompt.
SUDO_STUB = "#!/bin/bash\nexit 1\n"


@pytest.fixture( scope="module" )
def stub_bin( tmp_path_factory ):
    """
    A PATH directory holding the `docker` and `sudo` stubs.

    Ensures:
        - returns a directory to PREPEND to PATH
        - the real docker/sudo are never invoked by this file
    """
    d = tmp_path_factory.mktemp( "stub-bin" )
    for name, body in ( ( "docker", DOCKER_STUB ), ( "sudo", SUDO_STUB ) ):
        p = d / name
        p.write_text( body )
        p.chmod( 0o755 )
    return d


def _install_script( dest_dir, strip_c8=False ):
    """
    Copy preflight-vm.sh (+ its lib) into dest_dir, optionally deleting C8.

    Requires:
        - dest_dir exists and is writable

    Ensures:
        - returns the path to the runnable copy
        - with strip_c8, the `# C8 —` block up to the `# C5 —` marker is removed,
          and the removal is ASSERTED rather than assumed: a no-op strip would
          make the control pass vacuously, which is the exact failure this
          control exists to detect

    Returns:
        pathlib.Path
    """
    ( dest_dir / "lib" ).mkdir( exist_ok=True )
    shutil.copy( LIB, dest_dir / "lib" / LIB.name )
    text = SCRIPT.read_text()

    if strip_c8:
        stripped = re.sub( r"\n    # C8 —.*?(?=\n    # C5 —)", "\n", text, flags=re.S )
        assert stripped != text, "C8 strip was a NO-OP — the control would pass vacuously"
        assert "check_schema_parity.py" not in stripped, "strip left a parity reference behind"
        assert "check_schema_at_head.py" in stripped, "strip removed C7 too — the control is not isolating C8"
        text = stripped

    dest = dest_dir / "preflight-vm.sh"
    dest.write_text( text )
    dest.chmod( 0o755 )
    return dest


def _run( script, stub_bin, phase, parity_rc, parity_out ):
    """
    Run a preflight copy with the stubbed docker and a controlled parity result.

    Ensures:
        - returns the CompletedProcess; stdout carries the probe lines
        - layer D is pointed at a DEAD port, never Rick's live :7999
    """
    env = dict( os.environ )
    env.update( {
        "PATH"                     : f"{stub_bin}:{env['PATH']}",
        "LUPIN_ROOT"               : str( LUPIN_ROOT ),
        "PREFLIGHT_VM_CONTAINER"   : "pfv-stub-container",
        "PFV_STUB_CONTAINER"       : "pfv-stub-container",
        "PFV_STUB_PARITY_RC"       : str( parity_rc ),
        "PFV_STUB_PARITY_OUT"      : parity_out,
        # A dead port: ConnectionRefused, immediate — NOT a timeout.
        "PREFLIGHT_VM_APP_URL"     : "http://127.0.0.1:1",
        "PREFLIGHT_VM_ARBITER_URL" : "http://127.0.0.1:1",
    } )
    return subprocess.run(
        [ "bash", str( script ), "--phase", phase ],
        capture_output=True, text=True, timeout=180, env=env,
    )


def _c8_line( out ):
    """The single C8 output line, or None. Anchored on C8's own wording."""
    for line in out.splitlines():
        if "schema parity" in line.lower():
            return line
    return None


@pytest.fixture( scope="module" )
def wired( tmp_path_factory ):
    return _install_script( tmp_path_factory.mktemp( "wired" ) )


@pytest.fixture( scope="module" )
def unwired( tmp_path_factory ):
    return _install_script( tmp_path_factory.mktemp( "unwired" ), strip_c8=True )


# ── THE RED PROOF ────────────────────────────────────────────────────────────

def test_DRIFT_goes_RED_and_BLOCKS_in_post( wired, stub_bin ):
    """
    Break the thing C8 guards and watch it fail. THIS is the proof the wiring is
    real: a probe exiting 1 must surface as a BLOCKING failure naming the drifted
    table, not as a pass and not as a warning.
    """
    r    = _run( wired, stub_bin, "post", parity_rc=1, parity_out=PARITY_DRIFT_OUT )
    line = _c8_line( r.stdout )
    assert line is not None, f"C8 produced no line at all:\n{r.stdout}"
    assert "[FAIL]" in line, f"drift did not BLOCK in post — got: {line}"
    assert "SCHEMA PARITY DRIFT" in line
    assert "tables with drift: users" in line, "the DETAIL= key was not carried into the report"
    assert "needs a MIGRATION, not a restart" in r.stdout, "drift's remedy is missing or wrong"
    assert r.returncode == 1, "a blocking C8 failure must make preflight exit 1"


def test_DRIFT_is_a_WARN_in_pre_because_the_deploy_that_follows_migrates( wired, stub_bin ):
    """
    The phase-aware tier is deliberate, and mirrors C7: blocking in `pre` would
    abort the very deploy whose startup migrate fixes the condition.
    """
    r    = _run( wired, stub_bin, "pre", parity_rc=1, parity_out=PARITY_DRIFT_OUT )
    line = _c8_line( r.stdout )
    assert line is not None and "[WARN]" in line, f"pre-phase drift should WARN, got: {line}"
    assert "[FAIL]" not in line


def test_PARITY_passes( wired, stub_bin ):
    r    = _run( wired, stub_bin, "post", parity_rc=0, parity_out=PARITY_OK_OUT )
    line = _c8_line( r.stdout )
    assert line is not None and "[OK]" in line, f"a clean parity probe did not pass: {line}"


def test_CANNOT_DETERMINE_is_NOT_reported_as_drift( wired, stub_bin ):
    """
    The distinction the probe was fixed to make must survive the caller. An
    unreachable database used to exit 1 — identical to DRIFT — which would have
    printed "run a migration" at an operator with a connectivity problem.
    """
    r    = _run( wired, stub_bin, "post", parity_rc=2, parity_out=PARITY_UNKNOWN_OUT )
    line = _c8_line( r.stdout )
    assert line is not None, f"C8 produced no line at all:\n{r.stdout}"
    assert "cannot determine schema parity" in line, f"outcome 2 was not surfaced as unknown: {line}"
    assert "SCHEMA PARITY DRIFT" not in line, "cannot-determine was folded into DRIFT"
    assert "this is NOT drift and does not take drift's remedy" in r.stdout
    assert "needs a MIGRATION, not a restart" not in r.stdout, "drift's remedy was printed for a non-drift outcome"


def test_the_three_outcomes_are_pairwise_DISTINCT( wired, stub_bin ):
    """Three codes that render identically are two codes wearing three names."""
    lines = {
        rc: _c8_line( _run( wired, stub_bin, "post", parity_rc=rc, parity_out=out ).stdout )
        for rc, out in ( ( 0, PARITY_OK_OUT ), ( 1, PARITY_DRIFT_OUT ), ( 2, PARITY_UNKNOWN_OUT ) )
    }
    assert all( v is not None for v in lines.values() ), lines
    assert len( set( lines.values() ) ) == 3, f"outcomes are not distinguishable: {lines}"


# ── THE CONTROL THAT MUST FAIL ───────────────────────────────────────────────

def test_the_harness_ITSELF_can_tell_wired_from_unwired( unwired, wired, stub_bin ):
    """
    Run the identical stub, at the identical exit code, against a copy with C8
    DELETED. If this still reported drift, every assertion above would be
    measuring something other than C8.

    C7's line must remain PRESENT in the same run — that is what proves the stub
    reached the script at all, rather than the script dying early and taking C8's
    line with it for an unrelated reason.
    """
    r = _run( unwired, stub_bin, "post", parity_rc=1, parity_out=PARITY_DRIFT_OUT )
    assert _c8_line( r.stdout ) is None, "the C8-stripped script still emitted a parity line"
    assert "SCHEMA PARITY DRIFT" not in r.stdout
    assert "at the tree's head revision" in r.stdout, (
        "C7 did not report either — the run failed before layer C's schema checks, "
        "so this control proves nothing about C8"
    )
