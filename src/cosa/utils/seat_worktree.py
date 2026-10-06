"""
Give a spawned seat its own private worktree, so two seats are never mid-edit in one tree.

The defect this closes: `git commit -- <path>` commits that path's working-tree content. A seat
that legitimately claims a file still commits whatever a peer left uncommitted inside it. Every
control the fleet has is per file, and the risk is per hunk. The manifest says the file is
yours and it is. The commit scope guard checks the path and it passes. A pathspec cannot help,
because you named the file you meant. It has fired three times. Once it landed: 57 of one seat's
uncommitted lines went into a peer's commit under his name, with every control saying yes.

Why this is provisioning and not a louder alarm: `session_spawner` already detects the condition
and returns `placement_alarm`. An alarm tells a seat it is standing somewhere unsafe and then
leaves it there. A rule that depends on someone acting on a message is not a control. The
default placement is what is wrong, so the detection becomes the fix.

Why it delegates rather than reimplementing: `src/scripts/provision-seat-worktree.sh` owns the
predicate. It resolves the main checkout from git rather than from a path shape. It reuses a
registered worktree instead of recreating it. It refuses a path that exists and is not one. It
verifies the tree before claiming success. A second implementation would be a second thing to
keep in sync, so there is no "is it already provisioned" fast path here either.

It never raises. This has the same fail-open shape as `provision_worktree_venv`. A seat in the
shared checkout is worse off, but a spawn that dies because provisioning failed is worse still.
Every non-recoverable outcome is logged at `WARNING` with the target and exit code. The failure
to prevent is the one that looks like success.

It never removes a worktree. `cosa.agents.shared.seat_teardown` does that when the seat is reaped
or exits. The arbiter's worktree janitor is the backstop once the seat is gone. Seat trees live in
`<main>/.claude/worktrees/` and stay locked while the seat lives.

A test run must not provision into the real checkout. Spawn tests that call `spawn_sessions` with
a fake runner would otherwise create one permanent tree per seat name in the box's own repo. The
guard refuses any main checkout named in `LUPIN_SEAT_WORKTREE_REFUSE_ROOT`, which the unit
conftest sets to the real checkout. It is an environment check, not a stub in the conftest. A
local fixture can override a module attribute, but it cannot unset a variable the provisioner
reads for itself.
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

REFUSE_ROOT_ENV = "LUPIN_SEAT_WORKTREE_REFUSE_ROOT"


def _main_checkout_of( path ):
    """
    The main checkout that owns `path` (itself, or the main tree of a linked worktree).

    Ensures:
        - returns the realpath of the parent of `git rev-parse --git-common-dir`
        - falls back to realpath( path ) when git cannot answer, so the comparison
          still refuses the refused root handed in directly
        - never raises
    """
    try:
        out = subprocess.run( [ "git", "-C", str( path ), "rev-parse", "--path-format=absolute", "--git-common-dir" ],
                              capture_output=True, text=True, timeout=10 )
        if out.returncode == 0 and out.stdout.strip():
            return os.path.realpath( os.path.dirname( out.stdout.strip().rstrip( "/" ) ) )
    except ( OSError, subprocess.SubprocessError ):
        pass
    return os.path.realpath( str( path ) )


def _parse_keys( stdout ):
    """
    Parse the provisioning script's machine-readable upper-case `NAME=value` lines.

    Ensures:
        - returns those lines as a dict
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
        - `work_dir` is the directory the seat should be placed in. It is the new
          worktree on success, and None on every failure. The caller keeps whatever
          it had, so a failure degrades to the old behaviour rather than to a guess.
        - a falsy main_root or seat_name is a no-op reported as status "no_target",
          never an error: an explicit project=None inherits the caller's own cwd and
          this code does not know where that seat will land, so it must not guess
        - a missing script is a no-op reported as status "script_absent" — an older
          checkout must still be able to spawn
        - a main_root whose main checkout is the one named in
          LUPIN_SEAT_WORKTREE_REFUSE_ROOT is a no-op reported as status "refused_root"
          (the unit tier's guard against creating trees in the real repo)
        - status is "created" for a new tree, "reused" for one that was already there
          (a re-spun seat comes back to its own tree with its work still in it), and
          "already_seat_tree" when the path handed in is this seat's own tree
        - provisioned is True only for "created" and "reused"
        - status is "occupied" when the seat's existing tree has a live process with its
          cwd inside it, or uncommitted changes no memento claims: work_dir is None,
          provisioned is False, and `occupied_tree` / `occupied_reason` say which tree
          and why. The caller picks another slot; it never falls back to that tree
        - drift_behind is how many commits the tree is behind the main checkout's HEAD:
          0 at creation, non-zero for a reused tree. It is disclosed because computing it
          costs nothing (`git rev-list --count` is instant at any depth)
        - every other non-zero exit is reported as status "failed" and logged at
          `WARNING`, never silently swallowed
        - never raises, and never blocks a spawn
    """
    if not main_root or not seat_name:
        return { "provisioned": False, "status": "no_target", "work_dir": None,
                 "drift_behind": None, "exit_code": None,
                 "message": "no main_root or seat_name given — nothing to provision" }

    refused_root = os.environ.get( REFUSE_ROOT_ENV, "" ).strip()
    if refused_root and _main_checkout_of( main_root ) == os.path.realpath( refused_root ):
        return { "provisioned": False, "status": "refused_root", "work_dir": None,
                 "drift_behind": None, "exit_code": None,
                 "message": f"{REFUSE_ROOT_ENV} forbids provisioning into {refused_root}" }

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

    # "occupied" (row 81714af0): the seat's tree has a live process in it or holds
    # unclaimed uncommitted work, so the script declined to reuse it. Nothing is
    # provisioned and no work_dir is handed back — the caller must pick another slot,
    # never fall back to the tree it was refused.
    if status == "occupied":
        return { "provisioned": False, "status": "occupied", "work_dir": None,
                 "drift_behind": None, "exit_code": _EXIT_OK,
                 "occupied_tree": work_dir, "occupied_reason": keys.get( "OCCUPIED_REASON" ),
                 "message": ( result.stdout or "" ).strip() }

    return { "provisioned": status in ( "created", "reused" ), "status": status,
             "work_dir": work_dir, "drift_behind": drift_behind,
             "exit_code": _EXIT_OK, "message": ( result.stdout or "" ).strip() }


def drift_disclosure( provisioning ):
    """
    Render the tree's drift as one sentence, for a caller that reads the top of a result.

    Why it is a disclosure and not a gate: the case against per-session worktrees was drift, a seat
    working a stale tree. The real problem was unstated drift. The tree furthest behind was the
    harmless one, because its pin was declared. So this prints a number and forbids nothing.

    Requires:
        - provisioning is the dict returned by provision_seat_worktree, or None

    Ensures:
        - returns None when there is nothing to disclose: no provisioning, an
          unknown drift, or a tree that is level with the main checkout. None means
          the line does not appear at all, so when it does appear it means something.
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
