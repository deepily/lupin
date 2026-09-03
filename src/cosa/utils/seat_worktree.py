"""
Give a spawned seat its own private worktree, so two seats are never mid-edit in one
working tree (row 9d654899 — Rick ruled "Adopt, with drift disclosure", 2026-09-03).

THE DEFECT THIS CLOSES. `git commit -- <path>` commits that path's WORKING-TREE
CONTENT, so a seat that legitimately claims a file still commits whatever a peer left
uncommitted inside it. Every control the fleet has is per-FILE and the hazard is
per-HUNK: the manifest says the file is yours and it IS yours; the commit scope guard
checks the PATH and it passes; a pathspec cannot help because you named exactly the
file you meant. It has fired three times, once as a completed hit — 57 of one seat's
uncommitted lines landed in a peer's commit, under his name, with every control saying
yes and the author sincerely reporting it clean.

WHY THIS IS PROVISIONING AND NOT A LOUDER ALARM. `session_spawner` already DETECTS the
condition and returns `placement_alarm`. An alarm tells a seat it is standing somewhere
unsafe and then leaves it there — and this repo's own doctrine is that a rule which
depends on someone acting on a message is not a control. Under the ruling the DEFAULT
is what is wrong, so the detection becomes the fix.

WHY IT DELEGATES RATHER THAN REIMPLEMENTING. `src/scripts/provision-seat-worktree.sh`
owns the predicate: it resolves the main checkout from git rather than from a path
shape, reuses a registered worktree instead of recreating it, refuses a path that
exists and is not one, and verifies the tree before claiming success. A second
implementation of that predicate is a second thing to keep in sync. Deliberately no
"is it already provisioned" fast path here, for the same reason.

⚠️ IT NEVER RAISES, DELIBERATELY. Same fail-open shape as `provision_worktree_venv`: a
seat in the shared checkout is worse off, a spawn that DIES because provisioning failed
is worse still. Every non-recoverable outcome is logged at WARNING naming the target
and the exit code, because the failure this row exists to kill is the one that looks
like success.

⚠️ IT NEVER REMOVES A WORKTREE. Reaping is a separate policy (seat death is the
trigger, emptiness is the permission — designed on row 9d654899, unbuilt). Measured
2026-09-03 before this was written: 129 worktrees, 123 with no uncommitted work, 21G
total against 1.1T free — so disk is not the argument for reaping, and nothing here
pretends to settle it.
"""

import logging
import os
import subprocess

logger = logging.getLogger( __name__ )

# The script, resolved from the TARGET repo rather than from LUPIN_ROOT. A script
# shipped inside the tree it acts on can only be disagreed with by the environment,
# never informed by it — resolving from LUPIN_ROOT is the wrong-tree family that has
# bitten the pyc verifier, the purge script and the unit tier in turn.
_SCRIPT_REL_PATH = os.path.join( "src", "scripts", "provision-seat-worktree.sh" )

_EXIT_OK      = 0
_TIMEOUT_SECS = 60          # a `git worktree add` on a 21G repo, with headroom


def _parse_keys( stdout ):
    """
    Ensures:
        - returns the script's machine-readable KEY=value lines as a dict
        - prose lines (no '=') are ignored, so the human text can change freely
        - never raises
    """
    keys = {}
    for line in ( stdout or "" ).splitlines():
        if "=" in line:
            name, _, value = line.partition( "=" )
            name = name.strip()
            if name.isupper():
                keys[ name ] = value.strip()
    return keys


def provision_seat_worktree( main_root, seat_name, debug=False ):
    """
    Ensure the seat named `seat_name` has a private worktree of `main_root`.

    Requires:
        - main_root is a repository path, or falsy
        - seat_name is the spawn's session name, or falsy

    Ensures:
        - returns a dict with keys: provisioned (bool), status (str), work_dir (str or
          None), drift_behind (int or None), exit_code (int or None), message (str)
        - `work_dir` is the directory the seat should be placed in. It is the NEW
          worktree on success, and None on every failure — the caller keeps whatever
          it had, so a failure degrades to today's behaviour rather than to a guess.
        - a falsy main_root or seat_name is a no-op reported as status "no_target",
          never an error: an explicit project=None inherits the caller's own cwd and
          this code does not know where that seat will land, so it must not guess
        - a missing script is a no-op reported as status "script_absent" — an older
          checkout must still be able to spawn
        - status is "created" for a new tree, "reused" for one that was already there
          (a re-spun seat comes back to its own tree with its work still in it), and
          "already_seat_tree" when the path handed in IS this seat's own tree
        - drift_behind is the DISCLOSURE half of Rick's ruling: how many commits the
          tree is behind the main checkout's HEAD. 0 at creation; non-zero for a reused
          tree. The row's own precondition was that this costs nothing to compute
          (`git rev-list --count` is 0.00s at any depth) and that nothing prints it.
        - every other non-zero exit is reported as status "failed" AND logged at
          WARNING — never silently swallowed
        - NEVER raises, and never blocks a spawn
    """
    if not main_root or not seat_name:
        return { "provisioned": False, "status": "no_target", "work_dir": None,
                 "drift_behind": None, "exit_code": None,
                 "message": "no main_root or seat_name given — nothing to provision" }

    script = os.path.join( main_root, _SCRIPT_REL_PATH )
    if not os.path.isfile( script ):
        return { "provisioned": False, "status": "script_absent", "work_dir": None,
                 "drift_behind": None, "exit_code": None,
                 "message": f"no provisioning script at {script}" }

    try:
        result = subprocess.run( [ "bash", script, str( main_root ), str( seat_name ) ],
                                 capture_output=True, text=True, timeout=_TIMEOUT_SECS )
    except ( OSError, subprocess.SubprocessError ) as e:
        logger.warning( "seat worktree provisioning could not run for %s (seat %s): %r",
                        main_root, seat_name, e )
        return { "provisioned": False, "status": "failed", "work_dir": None,
                 "drift_behind": None, "exit_code": None,
                 "message": f"could not run {script}: {e!r}" }

    if debug: print( f"provision-seat-worktree.sh rc={result.returncode}\n{result.stdout}" )

    if result.returncode != _EXIT_OK:
        logger.warning( "seat worktree provisioning failed for %s (seat %s), exit %s: %s",
                        main_root, seat_name, result.returncode,
                        ( result.stderr or "" ).strip() )
        return { "provisioned": False, "status": "failed", "work_dir": None,
                 "drift_behind": None, "exit_code": result.returncode,
                 "message": ( result.stderr or result.stdout or "" ).strip() }

    keys      = _parse_keys( result.stdout )
    work_dir  = keys.get( "WORKTREE" ) or None
    status    = keys.get( "STATUS" ) or "unknown"

    # A zero exit with no WORKTREE line is a clean-looking result that says nothing —
    # exactly the shape this repo names as "a clean exit is not evidence the work
    # happened". Treat it as a failure rather than handing the caller a None cwd.
    if work_dir is None:
        logger.warning( "seat worktree provisioning exited 0 but named no worktree for %s (seat %s)",
                        main_root, seat_name )
        return { "provisioned": False, "status": "failed", "work_dir": None,
                 "drift_behind": None, "exit_code": _EXIT_OK,
                 "message": "script exited 0 without a WORKTREE line" }

    drift = keys.get( "DRIFT_BEHIND" )
    try:
        drift_behind = int( drift ) if drift is not None else None
    except ValueError:
        drift_behind = None

    return { "provisioned": status in ( "created", "reused" ), "status": status,
             "work_dir": work_dir, "drift_behind": drift_behind,
             "exit_code": _EXIT_OK, "message": ( result.stdout or "" ).strip() }


def drift_disclosure( provisioning ):
    """
    The second half of Rick's ruling, rendered for a caller that reads the TOP of a
    result rather than a nested dict.

    WHY IT IS A DISCLOSURE AND NOT A GATE (row 9d654899). The case against per-session
    worktrees was drift — a seat working a stale tree. The row's own re-diagnosis is
    that the problem was never drift but UNSTATED drift: the tree furthest behind was
    the harmless one, because its pin was declared. So this prints a number and
    forbids nothing.

    Requires:
        - provisioning is the dict returned by provision_seat_worktree, or None

    Ensures:
        - returns None when there is nothing to disclose — no provisioning, an
          unknown drift, or a tree that is level with the main checkout. None means
          the line does not appear at all, so when it DOES appear it means something.
        - otherwise returns one sentence naming the tree and how far behind it is
    """
    if not provisioning:                                    return None
    behind = provisioning.get( "drift_behind" )
    if not isinstance( behind, int ) or behind <= 0:        return None
    return ( f"this seat's worktree is {behind} commit(s) behind the main checkout at "
             f"{provisioning.get( 'work_dir' )} — declared, not a problem; rebase or "
             f"re-provision if the work needs newer code" )


def quick_smoke_test():
    """Non-destructive: exercises the no-op and parsing paths only, never git."""
    import cosa.utils.util as du
    du.print_banner( "seat_worktree quick smoke test", prepend_nl=True )

    cases = [
        ( "falsy main_root",  provision_seat_worktree( "", "seat-1" ),          "no_target" ),
        ( "falsy seat_name",  provision_seat_worktree( "/tmp", "" ),            "no_target" ),
        ( "absent script",    provision_seat_worktree( "/nonexistent", "s-1" ), "script_absent" ),
    ]
    for label, got, expected in cases:
        ok = got[ "status" ] == expected and got[ "work_dir" ] is None
        print( f"  {'✓' if ok else '✗'} {label:<18} status={got[ 'status' ]}" )

    parsed = _parse_keys( "STATUS=created\nWORKTREE=/x/y\nDRIFT_BEHIND=3\nprose line\n" )
    print( f"  {'✓' if parsed == { 'STATUS': 'created', 'WORKTREE': '/x/y', 'DRIFT_BEHIND': '3' } else '✗'} key parsing ignores prose" )

    d = drift_disclosure( { "drift_behind": 3, "work_dir": "/x/y" } )
    print( f"  {'✓' if d and '3 commit' in d else '✗'} drift disclosure renders" )
    print( f"  {'✓' if drift_disclosure( { 'drift_behind': 0 } ) is None else '✗'} level tree discloses nothing" )


if __name__ == "__main__":
    quick_smoke_test()
