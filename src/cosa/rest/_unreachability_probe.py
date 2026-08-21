"""
A temporary tripwire on two branches the plan says nothing reaches. DELETE WITH THE
BRANCHES — this module exists to answer one question and then go away (step B0(iii)).

WHY IT EXISTS. Steps 7a and 7c delete code on the strength of a STATIC search: grep found
no production caller of `RunningFifoQueue._process_fast_lane` (deleted by 7a on
2026-08-21, on this probe's evidence), and nothing that arms a blocking object, so
`is_accepting_jobs()` is said never to go false. A static search cannot
see a caller assembled at runtime — a getattr by name, a registry lookup, a string in a
config. Pocholo's order, and the reason for this file: arm the probe, watch the positive
control go RED so the wiring is proven, run a live-traffic window, and only then delete.

WHY THE POSITIVE CONTROL IS THE WHOLE POINT. "The probe never fired" and "the probe was
never wired" produce EXACTLY the same silence. A probe that has never been seen to fire is
not evidence of anything — it is an untested assertion about an untested assertion. So the
suite must make each trip fire at least once, visibly, before the quiet run means anything.

WHAT IT MUST NOT DO. Change behaviour. It records and returns; it never raises, never
swallows, never reorders. If the recording itself fails, it stays silent rather than
turning a probe into an outage — the one exception to fail-loud in this repo, because a
tripwire that can take down the thing it watches is worse than no tripwire.

READING IT. The trips go to a FILE and nowhere else — deliberately not stdout. A live
window on :7999 has to be readable after the fact, from outside the process that was
serving, and a marker printed into a server log that rolls or gets truncated is evidence
that can disappear before anyone reads it. The file lives beside the fleet's other
durable state, in projects-data/<repo>/, which is outside the git tree and so cannot be
committed by accident. `LUPIN_UNREACHABILITY_PROBE_PATH` overrides it for tests.
"""

import os
import time

import cosa.utils.util as du


# The branches under test, named once so a typo cannot invent another.
#
# FAST_LANE ("running_fifo_queue._process_fast_lane") was RETIRED with step 7a on
# 2026-08-21: the method it watched is deleted, and a probe name with no call site is a
# name whose control cannot be kept honest. Its window did what it was built for — zero
# trips against 65 spoken requests, with the positive control proving it was armed.
BLOCKING_GATE   = "todo_fifo_queue.is_accepting_jobs() returned False"
BLOCKING_BRANCH = "todo_fifo_queue.push_job: run_previous_best_snapshot branch"

PROBE_NAMES = ( BLOCKING_GATE, BLOCKING_BRANCH )


def probe_path():
    """
    Where trips are written.

    Ensures:
        - returns the LUPIN_UNREACHABILITY_PROBE_PATH override when set
        - otherwise <project root>/io/unreachability-probe.log
    """
    override = os.environ.get( "LUPIN_UNREACHABILITY_PROBE_PATH" )
    if override: return override

    # 🔴 io/, NOT projects-data/ — and the reason is the whole point of this probe.
    #
    # The first version resolved projects-data/<repo>/ the way the heartbeat holds do:
    # walk up from the project root and across to the sibling data dir. On the HOST that
    # is right. Inside the dev container it is not: `get_project_root()` returns
    # /var/lupin, so the same arithmetic produced /projects-data/lupin/, which nothing
    # mounts. Every trip would have been written into the container's throwaway layer and
    # lost at the next restart — and I would have read an empty file on the host and
    # reported "no trips," which is the EXACT failure this probe exists to rule out.
    # Caught by asking the running container where it would write, instead of assuming
    # the host answer travelled.
    #
    # /var/lupin/io is bind-mounted to the repo's io/ directory, so a trip written by the
    # server is readable on the host immediately, and io/ is git-ignored so nothing here
    # can be committed by accident.
    return du.get_project_root().rstrip( "/" ) + "/io/unreachability-probe.log"


def trip( name, detail="" ):
    """
    Record that a supposedly-unreachable branch just executed.

    Requires:
        - name is one of PROBE_NAMES

    Ensures:
        - appends one timestamped line to probe_path(), creating the directory if needed
        - writes nowhere else: no stdout, no server log
        - returns None and NEVER raises — a tripwire must not be able to break the
          code it is watching

    Raises:
        - nothing, deliberately. See the module docstring.
    """
    line = f"[UNREACHABLE-BRANCH-REACHED] {time.strftime( '%Y-%m-%dT%H:%M:%S' )} {name} {detail}".rstrip()
    try:
        target = probe_path()
        os.makedirs( os.path.dirname( target ), exist_ok=True )
        with open( target, "a" ) as fh:
            fh.write( line + "\n" )
    except Exception:
        pass


def trips( path=None ):
    """
    Read back every trip recorded so far.

    Ensures:
        - returns a list of recorded lines, oldest first
        - returns [] when the file does not exist — an unarmed run and a quiet run
          look the same on disk, which is exactly why the positive control matters
    """
    target = path or probe_path()
    if not os.path.exists( target ): return []
    with open( target ) as fh:
        return [ line.rstrip( "\n" ) for line in fh if line.strip() ]


def reset( path=None ):
    """
    Clear the log so a window measures only itself.

    Ensures:
        - the file is absent afterwards
    """
    target = path or probe_path()
    if os.path.exists( target ): os.remove( target )
