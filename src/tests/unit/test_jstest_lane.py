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
import signal
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.collected_count_guard import assert_every_declared_test_is_collected

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


# ══════════════════════════════════════════════════════════════════════════════
# 5. This file's own tests are actually collected
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# 6. The container path — where systemd-run does not exist
# ══════════════════════════════════════════════════════════════════════════════

class TestTheContainerPath:
    """
    Measured on lupin-rest-test, 2026-08-24: `command -v systemd-run` is ABSENT,
    the container runs as 1001:1001, and /sys/fs/cgroup/memory.max is root-owned
    0644 — the process can READ its ceiling and cannot create or write one.

    So door 4 cannot cap itself. The ceiling must come from docker-compose.yml,
    and the lane's job in a container is to CHECK that it arrived. Refusing when
    it did not is what makes the compose limit load-bearing instead of
    decorative: without these tests, a container with no limit would run the
    suite uncapped while reporting itself as the capped lane.
    """

    def _fake_container( self, tmp_path, ceiling ):
        """A tiny shim tree: a /.dockerenv marker and a memory.max to read."""
        cg = tmp_path / "cgroup"
        cg.mkdir()
        ( cg / "memory.max" ).write_text( ceiling, encoding="utf-8" )
        return cg

    def _run_as_container( self, tmp_path, ceiling, extra_env=None ):
        # Override the two probes rather than pretending to be in Docker: the
        # shell functions are the seam, and overriding them keeps the test
        # honest about WHICH branch it is exercising.
        cg = self._fake_container( tmp_path, ceiling )
        body = (
            '_jstest_in_container() { return 0; }\n'
            '_jstest_container_ceiling() { cat "%s/memory.max"; }\n'
            'jstest_slice_exec true\n'
        ) % cg
        return _run_snippet( body, env=extra_env )

    def test_a_container_WITHOUT_a_ceiling_is_REFUSED( self, tmp_path ):
        r = self._run_as_container( tmp_path, "max" )
        assert r.returncode == 70, ( r.returncode, r.stdout, r.stderr )
        assert "NO MEMORY CEILING" in r.stderr

    def test_the_refusal_names_the_COMPOSE_KEY_that_fixes_it( self, tmp_path ):
        # A refusal that does not say where the ceiling comes from sends the
        # reader to systemd-run, which does not exist in a container.
        r = self._run_as_container( tmp_path, "max" )
        assert "deploy:" in r.stderr and "limits:" in r.stderr and "memory:" in r.stderr

    def test_the_refusal_warns_that_a_RESTART_does_not_apply_it( self, tmp_path ):
        # Mount and resource specs resolve at container CREATE. A plain restart
        # reuses the old values and the change silently does not land.
        r = self._run_as_container( tmp_path, "max" )
        assert "recreate" in r.stderr.lower()

    def test_a_container_WITH_a_ceiling_RUNS_and_names_the_number( self, tmp_path ):
        r = self._run_as_container( tmp_path, "12884901888" )
        assert r.returncode == 0, ( r.returncode, r.stderr )
        assert "12884901888" in r.stderr, "the lane must state the ceiling it is trusting"

    def test_an_unreadable_ceiling_is_treated_as_ABSENT_not_as_permission( self, tmp_path ):
        # Fail closed: if the ceiling cannot be read, we do not know there is one.
        cg = tmp_path / "cgroup"; cg.mkdir()
        body = (
            '_jstest_in_container() { return 0; }\n'
            '_jstest_container_ceiling() { echo ""; }\n'
            'jstest_slice_exec true\n'
        )
        r = _run_snippet( body )
        assert r.returncode == 70, ( r.returncode, r.stderr )

    def test_the_container_escape_hatch_still_exists_and_announces_itself( self, tmp_path ):
        r = self._run_as_container( tmp_path, "max", extra_env={ "JSTEST_ALLOW_UNCAPPED": "1" } )
        assert r.returncode == 0, ( r.returncode, r.stderr )
        assert "UNCAPPED" in r.stderr


# ══════════════════════════════════════════════════════════════════════════════
# 7. The per-process watchdog — bound NODE, not the container
# ══════════════════════════════════════════════════════════════════════════════

class TestTheWatchdog:
    """
    🔴 WHY NOT `--max-old-space-size`, which is the obvious answer and is wrong.
    This allocator is OFF-HEAP, so the V8 heap ceiling is not in its path.
    Measured twice: the original kill ran at 2048 MB and reached 6 GB with no
    heap abort and no heapsnapshot despite asking for one; re-run at 512 MB it
    still reached the 4 GB cgroup limit and was SIGKILLed in 3.4 seconds.

    The ceiling therefore has to be enforced from OUTSIDE the process, by
    something that works where systemd-run does not exist and the process cannot
    write its own cgroup — which is the container. Polling RSS needs no
    privileges and behaves identically in both venues.
    """

    HOG = ( "import sys\n"
            "c = []\n"
            "while True:\n"
            "    c.append( bytearray( 8 * 1024 * 1024 ) )\n"
            "    if len( c ) > 256: sys.exit( 99 )\n" )


    # ── THE CLEANUP THAT WAS NEVER HERE (added 2026-08-24) ───────────────────
    # 🔴 THE HAZARD IS IN THE GREEN PATH'S BLIND SPOT: these tests spawn a hog
    # with persist=True, which by design NEVER exits on its own — that is what
    # killed the race the docstring below describes. Nothing ever reaped it.
    #
    # So on a GREEN run the watchdog's kill cleans up and nothing leaks. On a
    # RED run — the watchdog regressing, or a deliberate mutation proving this
    # suite still bites — the survivors the test just DETECTED stay resident
    # FOREVER, at ~2.1 GB each.
    #
    # MEASURED 2026-08-24: sixteen processes from three separate pytest runs
    # (pytest-470 / -474 / -477) were alive for over an hour holding 6.3 GB —
    # three complete chains, reparented to `systemd --user` once their pytest
    # exited. They were NOT evidence of a broken kill: a green run leaves
    # nothing, verified. They were the debris of red runs that had no cleanup.
    #
    # ⇒ A test that leaks 2 GB every time it correctly fails punishes the suite
    #   for working. Mutation testing is the practice this fleet runs ON PURPOSE,
    #   so the failing path is a path we deliberately visit.
    #
    # Reaps by EXPLICIT PID, deepest-first, matched on this pytest process's own
    # marker — never a pattern sweep of the box. The marker embeds os.getpid(),
    # so it cannot match a peer session's processes even by accident (row
    # cd332d2b: a hand-rolled pattern kill took three seats on 2026-08-21).
    @pytest.fixture( autouse=True )
    def _reap_my_own_strays( self ):
        yield
        marker = "jstest_survivor_%d" % os.getpid()
        listing = subprocess.run(
            [ "ps", "-eo", "pid=,ppid=,args=" ], capture_output=True, text=True ).stdout
        mine = {}
        for line in listing.splitlines():
            if marker not in line: continue
            parts = line.split( None, 2 )
            if len( parts ) < 3: continue
            mine[ int( parts[ 0 ] ) ] = int( parts[ 1 ] )
        if not mine: return
        # Deepest-first: a pid whose parent is also ours is deeper. Sorting by
        # how many of its ancestors are in the set orders the kill safely.
        def depth( pid ):
            d, seen = 0, set()
            while pid in mine and pid not in seen:
                seen.add( pid ); pid = mine[ pid ]; d += 1
            return d
        for pid in sorted( mine, key=depth, reverse=True ):
            try: os.kill( pid, signal.SIGKILL )
            except ProcessLookupError: pass

    def _watch( self, tmp_path, script_src, ceiling_mb, poll="0.05" ):
        f = tmp_path / "subject.py"
        f.write_text( script_src, encoding="utf-8" )
        return _run_snippet(
            'jstest_watchdog_exec %s %s' % ( sys.executable, f ),
            env={ "JSTEST_RSS_MAX_MB": str( ceiling_mb ), "JSTEST_POLL_SECS": poll },
        )

    def test_a_runaway_is_KILLED_at_the_ceiling( self, tmp_path ):
        r = self._watch( tmp_path, self.HOG, ceiling_mb=300 )
        assert r.returncode == 137, ( r.returncode, r.stderr )
        assert r.returncode != 99, "the hog reached its own exit — the ceiling did not hold"

    def test_the_CALLER_SURVIVES_the_kill( self, tmp_path ):
        # The entire design goal: kill node, leave the server serving. If the
        # watchdog took its own shell down this would print nothing.
        f = tmp_path / "subject.py"
        f.write_text( self.HOG, encoding="utf-8" )
        r = _run_snippet(
            'jstest_watchdog_exec %s %s\necho "CALLER_ALIVE rc=$?"' % ( sys.executable, f ),
            env={ "JSTEST_RSS_MAX_MB": "300", "JSTEST_POLL_SECS": "0.05" },
        )
        assert "CALLER_ALIVE rc=137" in r.stdout, ( r.stdout, r.stderr )

    def test_it_watches_the_whole_PROCESS_TREE_not_just_the_parent( self, tmp_path ):
        """
        🔴 THE PRODUCTION SHAPE, and the one a single-process hog cannot test.
        `node --test` spawns a WORKER PER FILE, so the memory lives in a CHILD
        while the parent stays small. A watchdog reading only the parent's RSS
        sees ~10 MB forever and never fires.

        This test exists because a mutation proved the gap: changing
        `ps -o rss= -p "$root" --ppid "$root"` to drop `--ppid` left every other
        watchdog test green. The suite could not tell parent-only from tree.
        """
        child = tmp_path / "child.py"
        child.write_text( self.HOG, encoding="utf-8" )
        parent = tmp_path / "parent.py"
        parent.write_text(
            "import subprocess, sys\n"
            "# The parent stays tiny and just waits — all the memory is the child's.\n"
            "p = subprocess.Popen( [ sys.executable, %r ] )\n"
            "p.wait()\n" % str( child ),
            encoding="utf-8",
        )
        r = _run_snippet(
            'jstest_watchdog_exec %s %s' % ( sys.executable, parent ),
            env={ "JSTEST_RSS_MAX_MB": "300", "JSTEST_POLL_SECS": "0.05" },
        )
        assert r.returncode == 137, (
            "The watchdog did not fire on memory held by a CHILD process. That is the "
            "shape node --test actually produces.\nrc=%r\nstderr=%s" % ( r.returncode, r.stderr )
        )

    def _chain( self, tmp_path, marker, persist=False ):
        """A parent→…→hog chain of arbitrary depth. Returns the chain script path."""
        hog = tmp_path / ( marker + "_hog.py" )
        hog.write_text(
            ( "import sys, time\n"
              "c = []\n"
              "while len( c ) <= 256:\n"
              "    c.append( bytearray( 8 * 1024 * 1024 ) )\n"
              "while True: time.sleep( 0.2 )\n" ) if persist else self.HOG,
            encoding="utf-8" )
        chain = tmp_path / ( marker + "_chain.py" )
        chain.write_text(
            "import subprocess, sys\n"
            "n = int( sys.argv[1] )\n"
            "nxt = [ sys.executable, %r ] if n <= 0 else [ sys.executable, __file__, str( n - 1 ) ]\n"
            "subprocess.Popen( nxt ).wait()\n" % str( hog ),
            encoding="utf-8" )
        return chain

    @pytest.mark.parametrize( "depth", [ 0, 1, 2, 4 ] )
    def test_DETECTION_reaches_the_hog_at_any_depth( self, tmp_path, depth ):
        """
        🔴 PARAMETRISED BY DEPTH ON PURPOSE. Two earlier versions of this guard
        walked a FIXED number of levels — first the parent only, then the parent
        plus direct children — and each looked correct against a test written at
        exactly the depth it happened to handle.

        A single-depth test cannot tell "walks every level" from "walks enough
        levels for this test". Depth 4 is here so that capping the walk at two
        goes red, which a depth-2 test would not catch.

        depth 0 = the hog is the direct child; depth 4 = four hops below it.
        """
        marker = "jstest_depth_%d_%d" % ( depth, os.getpid() )
        chain  = self._chain( tmp_path, marker )
        r = _run_snippet(
            'jstest_watchdog_exec %s %s %d' % ( sys.executable, chain, depth ),
            env={ "JSTEST_RSS_MAX_MB": "300", "JSTEST_POLL_SECS": "0.05" },
        )
        assert r.returncode == 137, (
            "The watchdog did not fire on memory held %d level(s) down.\nrc=%r\nstderr=%s"
            % ( depth + 1, r.returncode, r.stderr )
        )

    def test_the_kill_LEAVES_NO_SURVIVORS_anywhere_in_the_tree( self, tmp_path ):
        """
        🔴 THE THIRD LEVEL OF THE SAME BUG, and the worst of the three.

        Detection was fixed to walk every depth while the KILL still reached only
        the root and its direct children. Measured on a depth-4 chain: the
        watchdog fired, ANNOUNCED the kill, returned 137 — and three processes
        were still alive afterwards, including the one allocating.

        That is worse than never firing. A watchdog that half-kills reports the
        runaway as handled, so nobody looks again while it keeps growing.

        Every other test in this class passed throughout, because they all
        asserted on the RETURN CODE and none looked at what was still running.
        """
        marker = "jstest_survivor_%d" % os.getpid()
        # persist=True: the hog must NOT exit on its own. With a self-exiting hog
        # this very test passed against a DELIBERATELY BROKEN one-level kill — the
        # survivors had simply finished before the check looked. "No survivors" was
        # a race the test kept winning, not a kill.
        chain = self._chain( tmp_path, marker, persist=True )

        r = _run_snippet(
            'jstest_watchdog_exec %s %s 4' % ( sys.executable, chain ),
            env={ "JSTEST_RSS_MAX_MB": "300", "JSTEST_POLL_SECS": "0.05" },
        )
        assert r.returncode == 137, ( r.returncode, r.stderr )

        # The assertion the other tests could not make: is anything left?
        import subprocess, time
        time.sleep( 0.5 )
        listing = subprocess.run( [ "ps", "-eo", "cmd" ], capture_output=True, text=True ).stdout
        survivors = [ ln for ln in listing.splitlines() if marker in ln ]
        assert not survivors, (
            "The watchdog returned 137 and %d process(es) are STILL RUNNING — it reported "
            "the runaway as handled while it kept allocating:\n  %s"
            % ( len( survivors ), "\n  ".join( survivors[ :5 ] ) )
        )

    def test_a_well_behaved_process_runs_to_completion( self, tmp_path ):
        r = self._watch( tmp_path, "print( 'work done' )\n", ceiling_mb=2048 )
        assert r.returncode == 0, ( r.returncode, r.stderr )
        assert "work done" in r.stdout

    def test_a_FAILING_process_keeps_its_own_exit_code( self, tmp_path ):
        # A watchdog that swallowed the exit code would turn every red tier green.
        r = self._watch( tmp_path, "import sys; sys.exit( 3 )\n", ceiling_mb=2048 )
        assert r.returncode == 3, ( r.returncode, r.stderr )

    def test_it_does_NOT_report_a_fabricated_zero_peak( self, tmp_path ):
        # A process finishing inside one poll is never sampled. Printing
        # "peak 0MB" would be a measurement nobody took, and a number a tool
        # prints is a number someone later quotes.
        r = self._watch( tmp_path, "print( 'fast' )\n", ceiling_mb=2048, poll="5" )
        assert "peak RSS 0MB" not in r.stderr
        assert "no RSS sample" in r.stderr


# ══════════════════════════════════════════════════════════════════════════════
# 8. The host path must ENFORCE the ceiling it ANNOUNCES
# ══════════════════════════════════════════════════════════════════════════════

class TestTheHostPathEnforcesWhatItAnnounces:
    """
    🔴 THE HOST PATH ANNOUNCED A CEILING IT DID NOT ENFORCE. Its log line already
    read `rss_ceiling=2048MB` while it exec'd systemd-run directly — the watchdog
    ran only on the container path. The scope's MemoryMax did contain a runaway,
    so nothing escaped, but it killed the WHOLE SCOPE rather than the one process
    that grew, and the per-process ceiling in the message was decorative.

    A tool that prints a number it does not act on is worse than one that prints
    nothing: the number gets quoted.
    """

    @pytest.mark.skipif( not os.path.exists( "/usr/bin/systemd-run" ), reason="systemd-run absent" )
    def test_the_host_path_kills_at_the_RSS_ceiling_not_only_at_the_scope_limit( self, tmp_path ):
        # RSS ceiling far BELOW the scope's MemoryMax, so only the watchdog can
        # be what fires. If the scope were doing the work, this would need to
        # reach 6G first and the message would not name the RSS number.
        hog = tmp_path / "hog.py"
        hog.write_text( self.HOG_PERSIST, encoding="utf-8" )
        r = _run_snippet(
            'jstest_slice_exec %s %s' % ( sys.executable, hog ),
            env={ "JSTEST_RSS_MAX_MB": "300", "JSTEST_POLL_SECS": "0.05",
                  "JSTEST_MEM_MAX": "6G", "JSTEST_RUNTIME_MAX": "60" },
        )
        assert "exceeded the 300MB ceiling" in r.stderr, (
            "The host path did not enforce its own announced RSS ceiling — only the "
            "scope limit would have fired.\nstderr=%s" % r.stderr
        )

    HOG_PERSIST = ( "import sys, time\n"
                    "c = []\n"
                    "while len( c ) <= 256:\n"
                    "    c.append( bytearray( 8 * 1024 * 1024 ) )\n"
                    "while True: time.sleep( 0.2 )\n" )


def test_every_test_this_file_declares_is_actually_collected( request ):
    """
    The guard that would have caught this file's own defect (row 282d4c19).

    A method of TestItActuallyContainsARunaway briefly landed OUTSIDE the class:
    present, indented, syntactically valid, collected by nothing, suite green.
    Only the collected count moving 15 -> 15 instead of 15 -> 16 revealed it, and
    only because someone happened to be reading the number.
    """
    assert_every_declared_test_is_collected( request, __file__ )
