"""
The capped JS-test lane — row `282d4c19`, following row `32c58572`.

WHAT THIS PINS, and why each one is here rather than trusted:

· The lane REFUSES rather than silently running uncapped. An uncapped fallback is
  the worst outcome available: the run LOOKS lane-protected, is not, and the
  operator learns the difference from systemd-oomd picking a victim that need not
  be the offender.
· It sets MemoryMax and NOT MemoryHigh. MemoryHigh throttles instead of killing,
  so a runaway stalls and drives slice PSI up — the exact 2026-08-23 mechanism.
  A future edit "helpfully" adding MemoryHigh must go red.
· ALL FOUR DOORS funnel into the lane. Doors 3 and 4 reach it by invoking
  run-typescript-tests.sh, so this pins the FUNNEL: a future door that invokes
  node directly fails here instead of quietly escaping.
· The wall clock is NOT 300s. A single-file probe dies in ~5s so 300 looks
  generous, but the full suite is observed at 8m19s and budgeted 1500s; a 300s
  ceiling would kill it mid-run every time and report it as a cap hit.

⚠️ NOTHING HERE RUNS THE TYPESCRIPT TIER. The behavioural tests drive `true` and
`cat`. The tier is under a standing ban and this file does not lift it.
"""
import json
import os
import sys
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT     = Path( os.environ[ "LUPIN_ROOT" ] )
LIB      = ROOT / "src" / "scripts" / "lib" / "jstest-slice.sh"
DOOR1    = ROOT / "src" / "scripts" / "run-js-tests-capped.sh"
DOOR2    = ROOT / "src" / "tests"   / "run-typescript-tests.sh"
DOOR3    = ROOT / "src" / "tests"   / "run-all-tests.sh"
DOOR4    = ROOT / "src" / "cosa" / "agents" / "test_suite" / "job.py"
PKG_JSON = ROOT / "package.json"


# The synthetic runaway. Deliberately stops at 1 GB — small enough that the
# falsifier can raise the cap ABOVE it without letting a real multi-GB
# allocation loose on a shared box.
_HOG_SRC = (
    "import sys\n"
    "chunks = []\n"
    "while True:\n"
    "    chunks.append( bytearray( 8 * 1024 * 1024 ) )\n"
    "    if len( chunks ) > 128: sys.exit( 99 )\n"
)


def _run_snippet( body, env=None, path=None ):
    """Source the lane and run `body`, returning the CompletedProcess."""
    script = 'source "%s"\n%s' % ( LIB, textwrap.dedent( body ) )
    e = dict( os.environ )
    if path is not None: e[ "PATH" ] = path
    if env:              e.update( env )
    return subprocess.run( [ "bash", "-c", script ], capture_output=True, text=True, env=e, timeout=60 )


def _bin_without_systemd_run( tmp_path, extra=() ):
    """A PATH carrying a shell and the named tools but NO systemd-run."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ( "bash", "true", "cat", "echo" ) + tuple( extra ):
        for root in ( "/usr/bin", "/bin" ):
            src = os.path.join( root, tool )
            if os.path.exists( src ) and not ( bin_dir / tool ).exists():
                os.symlink( src, bin_dir / tool )
    return bin_dir


# ══════════════════════════════════════════════════════════════════════════════
# 1. It refuses rather than running uncapped
# ══════════════════════════════════════════════════════════════════════════════

class TestItRefusesRatherThanRunningUncapped:

    def test_no_systemd_run_means_REFUSE_not_a_silent_uncapped_run( self, tmp_path ):
        bin_dir = _bin_without_systemd_run( tmp_path )
        r = _run_snippet( 'jstest_slice_exec true; echo "RC=$?"', path=str( bin_dir ) )
        assert "RC=70" in r.stdout, (
            "The lane must REFUSE (rc 70) when it cannot cap. Falling through to an uncapped "
            "run is the false-green shape this lane exists to prevent.\n"
            "stdout=%s\nstderr=%s" % ( r.stdout, r.stderr )
        )
        assert "refusing" in r.stderr.lower()

    def test_the_refusal_explains_the_BLAST_RADIUS_not_just_the_missing_binary( self, tmp_path ):
        # A refusal that says only "systemd-run not found" invites the reader to
        # shrug and run the command by hand instead, which is the hazard.
        bin_dir = _bin_without_systemd_run( tmp_path )
        r = _run_snippet( 'jstest_slice_exec true', path=str( bin_dir ) )
        assert "fleet pressure" in r.stderr, r.stderr

    def test_the_uncapped_ESCAPE_HATCH_exists_and_announces_what_it_gives_up( self, tmp_path ):
        # NOTE: the hatch path ends in `exec`, which REPLACES the shell — so a
        # trailing `echo "RC=$?"` never runs and the exit code of the snippet IS
        # the exit code of the target. Asserting on a trailing echo here passed
        # for the refuse path (a `return`) and silently could not for this one.
        bin_dir = _bin_without_systemd_run( tmp_path )
        r = _run_snippet( 'jstest_slice_exec true',
                          env={ "JSTEST_ALLOW_UNCAPPED": "1" }, path=str( bin_dir ) )
        assert r.returncode == 0, ( r.returncode, r.stdout, r.stderr )
        assert "UNCAPPED" in r.stderr

    def test_the_hatch_really_RUNS_the_command_rather_than_only_announcing( self, tmp_path ):
        # An escape hatch that prints its warning and then does nothing would
        # pass the test above. Prove the target actually executed.
        bin_dir = _bin_without_systemd_run( tmp_path )
        r = _run_snippet( 'jstest_slice_exec cat /proc/self/cgroup',
                          env={ "JSTEST_ALLOW_UNCAPPED": "1" }, path=str( bin_dir ) )
        assert r.returncode == 0, ( r.returncode, r.stderr )
        assert ":/" in r.stdout, "cat produced no cgroup output — the hatch announced but did not exec"
        assert "jstest.slice" not in r.stdout, "uncapped hatch must NOT be inside the lane's slice"


# ══════════════════════════════════════════════════════════════════════════════
# 2. The ceiling it actually asks for
# ══════════════════════════════════════════════════════════════════════════════

class TestTheCeiling:

    def test_it_sets_MemoryMax_and_MemorySwapMax_zero( self ):
        text = LIB.read_text( encoding="utf-8" )
        assert "-p MemoryMax=" in text
        assert "-p MemorySwapMax=0" in text

    def test_it_does_NOT_set_MemoryHigh( self ):
        # MemoryHigh THROTTLES rather than kills: the cgroup stalls in reclaim,
        # slice PSI climbs, and systemd-oomd picks a victim that need not be the
        # offender. That is how 2026-08-23 took seats. This must stay absent.
        text = LIB.read_text( encoding="utf-8" )
        directives = [ ln.strip() for ln in text.splitlines() if "-p MemoryHigh" in ln ]
        assert directives == [], (
            "MemoryHigh converts a fast LOCAL kill into a slow SLICE-WIDE stall.\nFound: %r" % directives
        )

    def test_the_wall_clock_default_is_not_the_300s_that_would_kill_the_full_suite( self ):
        r = _run_snippet( 'echo "MAX=$JSTEST_RUNTIME_MAX"' )
        val = int( r.stdout.split( "MAX=" )[ 1 ].strip() )
        assert val >= 1400, (
            "Default RuntimeMaxSec is %d. The full suite is observed at 8m19s (499s) without c8 "
            "and budgeted 1500s with it, so a 300s ceiling kills it mid-run every time." % val
        )

    @pytest.mark.skipif( not os.path.exists( "/usr/bin/systemd-run" ), reason="systemd-run absent" )
    def test_it_REALLY_places_the_process_in_the_named_slice( self ):
        # The behavioural half: not "the script contains the flag" but "the child
        # actually lands in the cgroup".
        r = _run_snippet( 'jstest_slice_exec cat /proc/self/cgroup',
                          env={ "JSTEST_SLICE": "jstest.slice" } )
        assert "jstest.slice" in r.stdout, (
            "The child did not land in jstest.slice.\nstdout=%s\nstderr=%s" % ( r.stdout, r.stderr )
        )


# ══════════════════════════════════════════════════════════════════════════════
# 3. All four doors funnel into the lane
# ══════════════════════════════════════════════════════════════════════════════

class TestAllFourDoorsFunnelIntoTheLane:

    def test_door1_npm_test_goes_through_the_capped_script_not_bare_node( self ):
        scripts = json.loads( PKG_JSON.read_text( encoding="utf-8" ) )[ "scripts" ]
        assert "run-js-tests-capped.sh" in scripts[ "test" ], scripts[ "test" ]
        assert "node --test" not in scripts[ "test" ], (
            "package.json's test script invokes node directly, bypassing the lane."
        )

    def test_door1_script_sources_the_lane_AND_calls_it( self ):
        text = DOOR1.read_text( encoding="utf-8" )
        assert "jstest-slice.sh" in text
        assert "jstest_slice_exec" in text, "sourced but never called is a no-op cap"

    def test_door2_the_typescript_runner_sources_the_lane_AND_calls_it( self ):
        text = DOOR2.read_text( encoding="utf-8" )
        assert "jstest-slice.sh" in text
        assert "jstest_slice_exec" in text, "sourced but never called is a no-op cap"

    def test_door3_run_all_tests_reaches_the_lane_via_the_typescript_runner( self ):
        # Door 3 does not invoke node itself; it delegates. Pin the delegation,
        # because an edit that inlined the command would escape the lane silently.
        text = DOOR3.read_text( encoding="utf-8" )
        assert "run-typescript-tests.sh" in text
        assert "--import tsx" not in text, (
            "run-all-tests.sh inlines a node/tsx invocation instead of delegating — a door "
            "outside the lane."
        )

    def test_door4_the_submit_api_maps_typescript_to_the_same_runner( self ):
        text = DOOR4.read_text( encoding="utf-8" )
        assert "src/tests/run-typescript-tests.sh" in text, (
            "job.py's SUITE_SCRIPTS no longer maps typescript to the lane-wrapped runner."
        )

    def test_the_all_expansion_still_contains_typescript_so_this_funnel_matters( self ):
        # If "all" ever stops expanding to typescript, the door-4 test above is
        # vacuous and should be re-read rather than left passing for a stale reason.
        text = DOOR4.read_text( encoding="utf-8" )
        assert "ALL_SUITE_COMPONENTS" in text
        assert '"typescript"' in text


# ══════════════════════════════════════════════════════════════════════════════
# 4. It actually CONTAINS a runaway — the acceptance test
# ══════════════════════════════════════════════════════════════════════════════

class TestItActuallyContainsARunaway:
    """
    Everything above checks that the lane ASKS for a ceiling. This checks that the
    ceiling HOLDS, which is a different claim and the only one that matters.

    ⚠️ The subject is a synthetic allocator, NOT the TypeScript tier. The tier's
    real failure mode is already characterised in
    src/rnd/v0.2.0/2026.08.24-oom-allocator-named-happy-dom-assertion-diff.md and
    is under a standing ban; reproducing it here to prove a cgroup works would be
    running the banned tier to test systemd.
    """

    @pytest.mark.skipif( not os.path.exists( "/usr/bin/systemd-run" ), reason="systemd-run absent" )
    def test_a_runaway_dies_at_the_cap_instead_of_growing_without_bound( self, tmp_path ):
        hog = tmp_path / "hog.py"
        hog.write_text( _HOG_SRC, encoding="utf-8" )
        r = _run_snippet(
            'jstest_slice_exec %s %s' % ( sys.executable, hog ),
            env={ "JSTEST_MEM_MAX": "512M", "JSTEST_RUNTIME_MAX": "60", "JSTEST_SLICE": "jstest.slice" },
        )
        # falsifier below can raise the cap above it WITHOUT letting a real
        # 32 GB allocation loose on a shared box.
        assert r.returncode != 99, (
            "The runaway reached its 1 GB mark under a 512M cap — the cap did not hold. "
            "That is the whole point of the lane."
        )
        assert r.returncode != 0, "A runaway that exits 0 was not contained, it was lucky."


    @pytest.mark.skipif( not os.path.exists( "/usr/bin/systemd-run" ), reason="systemd-run absent" )
    def test_the_containment_test_CAN_fail_raise_the_cap_and_the_hog_gets_through( self, tmp_path ):
        """
        The falsifier for the test above. A containment assertion that cannot be made
        to fail proves nothing — it would pass just as happily against a lane that
        silently did nothing. Raising the ceiling above the hog's own 1 GB stop must
        let it reach exit 99.

        (This method was briefly orphaned OUTSIDE the class by a bad append: present
        in the file, indented, and collected by nothing. The count is what caught it —
        15 tests before and 15 after. A test that is not collected is not a test.)
        """
        hog = tmp_path / "hog.py"
        hog.write_text( _HOG_SRC, encoding="utf-8" )
        r = _run_snippet(
            'jstest_slice_exec %s %s' % ( sys.executable, hog ),
            env={ "JSTEST_MEM_MAX": "4G", "JSTEST_RUNTIME_MAX": "60", "JSTEST_SLICE": "jstest.slice" },
        )
        assert r.returncode == 99, (
            "With a 4G ceiling the 1 GB hog should run to completion. It returned %r instead, so "
            "the containment test above is not measuring the cap." % r.returncode
        )
